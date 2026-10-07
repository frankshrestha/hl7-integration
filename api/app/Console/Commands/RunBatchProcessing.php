<?php

namespace App\Console\Commands;

use App\Enums\BatchItemStatus;
use App\Enums\InboundMessageStatus;
use App\Jobs\ProcessBatchChunkJob;
use App\Models\BatchItem;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\Bus;
use Illuminate\Support\Facades\DB;

class RunBatchProcessing extends Command
{
    protected $signature = 'batch:run';

    protected $description = 'Queue failed messages and dispatch jobs';

    public function handle(): int
    {
        $this->queueFailedMessages();

        $dueItems = BatchItem::query()
            ->whereIn('status', [BatchItemStatus::Pending, BatchItemStatus::Processing])
            ->whereRaw('available_at <= now()')
            ->count();

        if ($dueItems === 0) {
            $this->info('No batch items are due.');

            return self::SUCCESS;
        }

        // queue the jobs required to process those many messages
        $jobs = array_map(
            fn() => new ProcessBatchChunkJob,
            range(1, (int) ceil($dueItems / config('integration.batch.size'))),
        );

        $batch = Bus::batch($jobs)
            ->name('lab-result-batch')
            ->onQueue(config('integration.batch.queue'))
            ->allowFailures()
            ->dispatch();

        $this->info("{$dueItems} item(s) due: dispatched batch {$batch->id} with " . count($jobs) . ' job(s).');

        return self::SUCCESS;
    }

    private function queueFailedMessages(): void
    {
        DB::statement(
            'INSERT INTO batch_items (message_id, status, attempts, available_at, created_at, updated_at)
             SELECT message_id, ?, 0, now(), now(), now()
             FROM inbound_messages WHERE status = ?
             ON CONFLICT (message_id) DO UPDATE
                SET status = EXCLUDED.status, attempts = 0, available_at = now(), last_error = NULL, updated_at = now()
                WHERE batch_items.status = ?',
            [BatchItemStatus::Pending->value, InboundMessageStatus::Failed->value, BatchItemStatus::Completed->value],
        );
    }
}
