<?php

namespace App\Exceptions;

use RuntimeException;

/**
 * Thrown on demand mid-transaction to demonstrate that a failed message leaves no partial data.
 */
class SimulatedProcessingFailure extends RuntimeException
{
    public function __construct()
    {
        parent::__construct('Simulated processing failure before commit.');
    }
}
