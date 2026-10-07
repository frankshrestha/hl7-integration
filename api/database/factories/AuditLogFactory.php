<?php

namespace Database\Factories;

use Illuminate\Database\Eloquent\Factories\Factory;
use Illuminate\Support\Str;

class AuditLogFactory extends Factory
{
    public function definition(): array
    {
        return [
            'correlation_id' => (string) Str::uuid(),
            'message_id' => 'MSG' . fake()->numerify('########'),
            'client_id' => 'hl7-service',
            'event' => 'message.processed',
        ];
    }
}
