<?php

namespace Database\Factories;

use App\Enums\InboundMessageStatus;
use Illuminate\Database\Eloquent\Factories\Factory;
use Illuminate\Support\Str;

class InboundMessageFactory extends Factory
{
    public function definition(): array
    {
        return [
            'message_id' => 'MSG' . fake()->unique()->numerify('########'),
            'message_type' => 'ORU^R01',
            'correlation_id' => (string) Str::uuid(),
            'client_id' => 'hl7-service',
            'payload_hash' => hash('sha256', Str::random()),
            'payload' => [],
            'status' => InboundMessageStatus::Processed,
            'attempts' => 1,
            'received_at' => now(),
            'processed_at' => now(),
        ];
    }
}
