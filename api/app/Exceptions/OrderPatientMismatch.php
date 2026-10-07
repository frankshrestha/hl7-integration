<?php

namespace App\Exceptions;

use RuntimeException;

class OrderPatientMismatch extends RuntimeException
{
    public function __construct(public readonly string $orderNo)
    {
        parent::__construct("Order [{$orderNo}] already belongs to a different patient.");
    }
}
