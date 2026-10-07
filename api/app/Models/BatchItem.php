<?php

namespace App\Models;

use App\Enums\BatchItemStatus;
use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;

class BatchItem extends Model
{
    use HasFactory;

    protected function casts(): array
    {
        return [
            'status' => BatchItemStatus::class,
            'attempts' => 'integer',
            'available_at' => 'datetime',
        ];
    }
}
