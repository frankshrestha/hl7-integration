<?php

namespace App\Actions;

use App\Enums\BatchItemStatus;
use App\Enums\ProcessingOutcome;
use App\Exceptions\BatchRequestFailed;
use App\Exceptions\OrderPatientMismatch;
use App\Http\Requests\StoreLabResultRequest;
use App\Services\IntegrationServiceClient;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Facades\Validator;
use Illuminate\Support\Str;
use Throwable;

/**
 * Claim the next due batch items, fetch their payloads from the integration service and store them.
 */
class ProcessBatch
{
    public function __construct(
        private IntegrationServiceClient $integrationServiceClient,
        private ProcessLabResultMessage $processLabResultMessage,
    ) {}

    public function handle(): void
    {
        $items = $this->claim(config('integration.batch.size'));

        if ($items === []) {
            return;
        }

        $batchId = (string) Str::uuid();

        try {
            $results = $this->integrationServiceClient->fetchBatch(
                $batchId,
                array_map(fn(object $item) => [
                    'item_id' => $item->id,
                    'message_id' => $item->message_id,
                ], $items),
            );
        } catch (BatchRequestFailed $exception) {
            foreach ($items as $item) {
                $this->retryLater($item, $exception->getMessage());
            }

            Log::warning('Batch request failed.', [
                'batch_id' => $batchId,
                'claimed' => count($items),
                'error' => $exception->getMessage()
            ]);

            throw $exception;
        }

        $resultsByItemId = collect($results)->keyBy('item_id');

        foreach ($items as $item) {
            $this->applyResult($item, $resultsByItemId->get($item->id));
        }

        Log::info('Batch processed.', ['batch_id' => $batchId, 'claimed' => count($items)]);
    }

    /** Claim up to $limit due items */
    public function claim(int $limit): array
    {
        return DB::select(
            'WITH picked AS (
                SELECT id FROM batch_items
                WHERE status IN (?, ?) AND available_at <= now()
                ORDER BY id
                LIMIT ?
                FOR UPDATE SKIP LOCKED
            )
            UPDATE batch_items
            SET status = ?, attempts = batch_items.attempts + 1,
                available_at = now() + make_interval(secs => ?), updated_at = now()
            FROM picked
            WHERE batch_items.id = picked.id
            RETURNING batch_items.id, batch_items.message_id, batch_items.attempts',
            [
                BatchItemStatus::Pending->value,
                BatchItemStatus::Processing->value,
                $limit,
                BatchItemStatus::Processing->value,
                config('integration.batch.lease_seconds'),
            ],
        );
    }

    private function applyResult(object $item, ?array $result): void
    {
        match ($result['status'] ?? null) {
            null => $this->retryLater($item, 'Item missing from the integration service response.'),
            'found' => $this->store($item, $result),
            'not_found', 'ambiguous' => $this->markFailed($item, $result['error'] ?? $result['status']),
            default => $this->retryLater($item, $result['error'] ?? "Unexpected status [{$result['status']}]."),
        };
    }

    private function store(object $item, array $result): void
    {
        $validator = Validator::make($result['payload'] ?? [], (new StoreLabResultRequest)->rules());

        if ($validator->fails()) {
            $this->markFailed($item, 'Invalid payload: ' . $validator->errors()->toJson());
            return;
        }

        if ($validator->validated()['message_id'] !== $item->message_id) {
            $this->markFailed($item, 'Payload message_id does not match the requested message.');
            return;
        }

        try {
            $outcome = $this->processLabResultMessage->handle(
                $validator->validated(),
                $result['correlation_id'] ?? (string) Str::uuid(),
                config('integration.batch.client_id'),
            );
        } catch (OrderPatientMismatch $exception) {
            $this->markFailed($item, $exception->getMessage());
            return;
        } catch (Throwable $exception) {
            $this->retryLater($item, $exception->getMessage());
            return;
        }

        if ($outcome === ProcessingOutcome::Conflict) {
            $this->markFailed($item, 'Message ID already stored with a different payload.');
            return;
        }

        $this->update($item, ['status' => BatchItemStatus::Completed->value, 'last_error' => null]);
    }

    private function markFailed(object $item, string $error): void
    {
        $this->update($item, ['status' => BatchItemStatus::Failed->value, 'last_error' => $error]);
    }

    private function retryLater(object $item, string $error): void
    {
        if ($item->attempts >= config('integration.batch.max_attempts')) {
            $this->markFailed($item, $error);
            return;
        }

        $delay = config('integration.batch.backoff_seconds') * 2 ** ($item->attempts - 1);

        $this->update($item, [
            'status' => BatchItemStatus::Pending->value,
            'available_at' => DB::raw('now() + make_interval(secs => ' . (int) $delay . ')'),
            'last_error' => $error,
        ]);
    }

    private function update(object $item, array $values): void
    {
        DB::table('batch_items')
            ->where('id', $item->id)
            ->where('status', BatchItemStatus::Processing->value)
            ->where('attempts', $item->attempts)
            ->update([...$values, 'updated_at' => now()]);
    }
}
