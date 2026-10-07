<?php

namespace App\Enums;

enum ProcessingOutcome: string
{
    case Processed = 'processed';
    case Duplicate = 'duplicate';
    case Conflict = 'conflict';

    /**
     * HTTP status to return
     */
    public function httpStatus(): int
    {
        return match ($this) {
            self::Processed => 201,
            self::Duplicate => 200,
            self::Conflict => 409,
        };
    }
}
