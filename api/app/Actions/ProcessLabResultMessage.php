<?php

namespace App\Actions;

use App\Enums\InboundMessageStatus;
use App\Enums\ProcessingOutcome;
use App\Exceptions\OrderPatientMismatch;
use App\Exceptions\SimulatedProcessingFailure;
use App\Models\AuditLog;
use App\Models\InboundMessage;
use App\Models\Order;
use App\Models\Patient;
use App\Models\Result;
use Illuminate\Support\Arr;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Log;
use Throwable;

class ProcessLabResultMessage
{
    public function handle(array $message, string $correlationId, string $clientId, bool $simulateFailure = false): ProcessingOutcome
    {
        $payloadHash = $this->payloadHash($message);

        try {
            return DB::transaction(
                function () use ($message, $correlationId, $clientId, $payloadHash, $simulateFailure): ProcessingOutcome {
                    $inboundMessageId = $this->claim($message, $correlationId, $clientId, $payloadHash);

                    if ($inboundMessageId === null) {
                        return $this->resolveAlreadyProcessed($message['message_id'], $payloadHash);
                    }

                    $audit = fn(
                        string $event,
                        ?string $type = null,
                        ?int $id = null,
                        ?array $old = null,
                        ?array $new = null
                    ) => $this->audit(
                        $message['message_id'],
                        $correlationId,
                        $clientId,
                        $event,
                        $type,
                        $id,
                        $old,
                        $new,
                    );

                    $patientId = $this->upsertPatient($message['patient'], $audit);
                    $orderId = $this->upsertOrder($message['order'], $patientId, $audit);
                    $this->upsertResults($message, $orderId, $patientId, $inboundMessageId, $audit);

                    if ($simulateFailure) {
                        throw new SimulatedProcessingFailure;
                    }

                    InboundMessage::query()->whereKey($inboundMessageId)->update([
                        'status' => InboundMessageStatus::Processed,
                        'processed_at' => now(),
                    ]);

                    $audit('message.processed', InboundMessage::class, $inboundMessageId);

                    Log::info('Lab result message processed.', [
                        'message_id' => $message['message_id'],
                        'order_no' => $message['order']['order_no'],
                    ]);

                    return ProcessingOutcome::Processed;
                }
            );
        } catch (Throwable $exception) {
            $this->recordFailure($message, $correlationId, $clientId, $payloadHash, $exception);

            throw $exception;
        }
    }

    private function claim(array $message, string $correlationId, string $clientId, string $payloadHash): ?int
    {
        $row = DB::selectOne(
            <<<'SQL'
            INSERT INTO inbound_messages
                (message_id, message_type, correlation_id, client_id, payload_hash, payload, status, attempts, received_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?::jsonb, ?, 1, now(), now(), now())
            ON CONFLICT (message_id) DO UPDATE SET
                message_type = EXCLUDED.message_type,
                correlation_id = EXCLUDED.correlation_id,
                client_id = EXCLUDED.client_id,
                payload_hash = EXCLUDED.payload_hash,
                payload = EXCLUDED.payload,
                status = EXCLUDED.status,
                attempts = inbound_messages.attempts + 1,
                last_error = NULL,
                updated_at = now()
            WHERE inbound_messages.status <> ?
            RETURNING id
            SQL,
            [
                $message['message_id'],
                $message['message_type'] ?? null,
                $correlationId,
                $clientId,
                $payloadHash,
                json_encode($message, JSON_THROW_ON_ERROR),
                InboundMessageStatus::Processing->value,
                InboundMessageStatus::Processed->value,
            ]
        );

        return $row?->id;
    }


    private function resolveAlreadyProcessed(string $messageId, string $payloadHash): ProcessingOutcome
    {
        $storedHash = InboundMessage::query()->where('message_id', $messageId)->value('payload_hash');

        if (hash_equals($storedHash, $payloadHash)) {
            return ProcessingOutcome::Duplicate;
        }

        Log::warning('Message ID reused with a different payload.', ['message_id' => $messageId]);

        return ProcessingOutcome::Conflict;
    }

    private function upsertPatient(array $patient, callable $audit): int
    {
        $existing = Patient::query()->where('external_id', $patient['external_id'])->lockForUpdate()->first();

        $row = DB::selectOne(<<<'SQL'
            INSERT INTO patients (external_id, first_name, last_name, dob, gender, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, now(), now())
            ON CONFLICT (external_id) DO UPDATE SET
                first_name = COALESCE(EXCLUDED.first_name, patients.first_name),
                last_name = COALESCE(EXCLUDED.last_name, patients.last_name),
                dob = COALESCE(EXCLUDED.dob, patients.dob),
                gender = COALESCE(EXCLUDED.gender, patients.gender),
                updated_at = now()
            RETURNING id, external_id, first_name, last_name, dob, gender
            SQL, [
            $patient['external_id'],
            $patient['first_name'] ?? null,
            $patient['last_name'] ?? null,
            $patient['dob'] ?? null,
            $patient['gender'] ?? null,
        ]);

        $this->auditChange(
            $audit,
            'patient',
            Patient::class,
            $row,
            $existing?->only(['external_id', 'first_name', 'last_name', 'dob', 'gender']),
            fn(array $values) => [
                ...$values,
                'dob' => isset($values['dob']) ? Carbon::parse($values['dob'])->toDateString() : null,
            ]
        );

        return $row->id;
    }

    private function upsertOrder(array $order, int $patientId, callable $audit): int
    {
        $existing = Order::query()->where('order_no', $order['order_no'])->lockForUpdate()->first();

        if ($existing !== null && (int) $existing->patient_id !== $patientId) {
            throw new OrderPatientMismatch($order['order_no']);
        }

        $row = DB::selectOne(
            <<<'SQL'
            INSERT INTO orders (patient_id, order_no, service_code, service_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, now(), now())
            ON CONFLICT (order_no) DO UPDATE SET
                service_code = EXCLUDED.service_code,
                service_name = COALESCE(EXCLUDED.service_name, orders.service_name),
                updated_at = now()
            WHERE orders.patient_id = EXCLUDED.patient_id
            RETURNING id, patient_id, order_no, service_code, service_name
            SQL,
            [
                $patientId,
                $order['order_no'],
                $order['service_code'],
                $order['service_name'] ?? null,
            ]
        );

        if ($row === null) {
            throw new OrderPatientMismatch($order['order_no']);
        }

        $this->auditChange(
            $audit,
            'order',
            Order::class,
            $row,
            $existing?->only(['patient_id', 'order_no', 'service_code', 'service_name'])
        );

        return $row->id;
    }

    private function upsertResults(array $message, int $orderId, int $patientId, int $inboundMessageId, callable $audit): void
    {
        $columns = ['set_id', 'code', 'name', 'value', 'value_type', 'unit', 'reference_range', 'flag', 'result_status', 'observed_at'];

        $existing = Result::query()
            ->where('order_id', $orderId)
            ->get(['id', ...$columns])
            ->keyBy('code');

        foreach ($message['results'] as $result) {
            $observedAt = Carbon::parse($result['observed_at'] ?? $message['message_datetime'])->utc();

            $row = DB::selectOne(
                <<<'SQL'
                INSERT INTO results
                    (order_id, patient_id, inbound_message_id, set_id, code, name, value, value_type, unit,
                     reference_range, flag, result_status, observed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now(), now())
                ON CONFLICT (order_id, code) DO UPDATE SET
                    patient_id = EXCLUDED.patient_id,
                    inbound_message_id = EXCLUDED.inbound_message_id,
                    set_id = EXCLUDED.set_id,
                    name = EXCLUDED.name,
                    value = EXCLUDED.value,
                    value_type = EXCLUDED.value_type,
                    unit = EXCLUDED.unit,
                    reference_range = EXCLUDED.reference_range,
                    flag = EXCLUDED.flag,
                    result_status = EXCLUDED.result_status,
                    observed_at = EXCLUDED.observed_at,
                    updated_at = now()
                RETURNING id, set_id, code, name, value, value_type, unit, reference_range, flag, result_status, observed_at
                SQL,
                [
                    $orderId,
                    $patientId,
                    $inboundMessageId,
                    $result['set_id'] ?? null,
                    $result['code'],
                    $result['name'] ?? null,
                    $result['value'] ?? null,
                    $result['value_type'] ?? null,
                    $result['unit'] ?? null,
                    $result['reference_range'] ?? null,
                    $result['flag'] ?? null,
                    $result['result_status'] ?? null,
                    $observedAt,
                ]
            );

            $this->auditChange(
                $audit,
                'result',
                Result::class,
                $row,
                $existing->get($result['code'])?->only($columns),
                fn(array $values) => [
                    ...$values,
                    'observed_at' => isset($values['observed_at']) ? Carbon::parse($values['observed_at'])->toIso8601String() : null,
                ]
            );
        }
    }

    private function auditChange(callable $audit, string $entity, string $type, object $row, ?array $old, ?callable $normalize = null): void
    {
        $normalize ??= fn(array $values): array => $values;
        $new = $normalize(Arr::except((array) $row, ['id']));

        if ($old === null) {
            $audit(
                "{$entity}.created",
                $type,
                $row->id,
                null,
                $new
            );

            return;
        }

        $old = $normalize($old);
        $changedKeys = array_keys(
            array_filter(
                $new,
                fn(mixed $value, string $key) => $value != ($old[$key] ?? null),
                ARRAY_FILTER_USE_BOTH
            )
        );

        if ($changedKeys !== []) {
            $audit(
                "{$entity}.updated",
                $type,
                $row->id,
                Arr::only($old, $changedKeys),
                Arr::only($new, $changedKeys)
            );
        }
    }

    private function audit(
        string $messageId,
        string $correlationId,
        string $clientId,
        string $event,
        ?string $auditableType = null,
        ?int $auditableId = null,
        ?array $oldValues = null,
        ?array $newValues = null,
    ): void {
        AuditLog::query()->create([
            'correlation_id' => $correlationId,
            'message_id' => $messageId,
            'client_id' => $clientId,
            'event' => $event,
            'auditable_type' => $auditableType,
            'auditable_id' => $auditableId,
            'old_values' => $oldValues,
            'new_values' => $newValues,
        ]);
    }

    /**
     * Record the failed attempt
     */
    private function recordFailure(array $message, string $correlationId, string $clientId, string $payloadHash, Throwable $exception): void
    {
        try {
            DB::statement(
                <<<'SQL'
                INSERT INTO inbound_messages
                    (message_id, message_type, correlation_id, client_id, payload_hash, payload, status, attempts, last_error, received_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?::jsonb, ?, 1, ?, now(), now(), now())
                ON CONFLICT (message_id) DO UPDATE SET
                    correlation_id = EXCLUDED.correlation_id,
                    status = EXCLUDED.status,
                    attempts = inbound_messages.attempts + 1,
                    last_error = EXCLUDED.last_error,
                    updated_at = now()
                WHERE inbound_messages.status <> ?
                SQL,
                [
                    $message['message_id'],
                    $message['message_type'] ?? null,
                    $correlationId,
                    $clientId,
                    $payloadHash,
                    json_encode($message, JSON_THROW_ON_ERROR),
                    InboundMessageStatus::Failed->value,
                    $exception->getMessage(),
                    InboundMessageStatus::Processed->value,
                ]
            );

            $this->audit($message['message_id'], $correlationId, $clientId, 'message.failed', newValues: [
                'error' => $exception->getMessage(),
                'exception' => $exception::class,
            ]);
        } catch (Throwable $recordingException) {
            report($recordingException);
        }

        Log::warning('Lab result message failed.', [
            'message_id' => $message['message_id'],
            'order_no' => $message['order']['order_no'],
            'error' => $exception->getMessage(),
        ]);
    }

    private function payloadHash(array $message): string
    {
        return hash('sha256', json_encode($message, JSON_THROW_ON_ERROR));
    }
}
