<?php

namespace Database\Factories;

use App\Enums\BatchItemStatus;
use Illuminate\Database\Eloquent\Factories\Factory;

class BatchItemFactory extends Factory
{
    public function definition(): array
    {
        return [
            'message_id' => 'MSG'.fake()->unique()->numerify('########'),
            'status' => BatchItemStatus::Pending,
            'attempts' => 0,
            'available_at' => now()->subMinute(),
        ];
    }
}
