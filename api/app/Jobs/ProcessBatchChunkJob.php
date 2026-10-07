<?php

namespace App\Jobs;

use App\Actions\ProcessBatch;
use Illuminate\Bus\Batchable;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Queue\Queueable;

class ProcessBatchChunkJob implements ShouldQueue
{
    use Batchable, Queueable;

    // Failed items are rescheduled with backoff.
    public int $tries = 1;

    public function handle(ProcessBatch $processBatch): void
    {
        if ($this->batch()?->cancelled()) {
            return;
        }

        $processBatch->handle();
    }
}
