<?php

namespace App\Models;

use App\Enums\InboundMessageStatus;
use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;

class InboundMessage extends Model
{
    use HasFactory;

    public function results(): HasMany
    {
        return $this->hasMany(Result::class);
    }

    protected function casts(): array
    {
        return [
            'payload' => 'array',
            'status' => InboundMessageStatus::class,
            'attempts' => 'integer',
            'received_at' => 'datetime',
            'processed_at' => 'datetime',
        ];
    }
}
