<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;

class Patient extends Model
{
    use HasFactory;

    public function orders(): HasMany
    {
        return $this->hasMany(Order::class);
    }

    public function results(): HasMany
    {
        return $this->hasMany(Result::class);
    }

    protected function casts(): array
    {
        return [
            'dob' => 'date',
        ];
    }
}
