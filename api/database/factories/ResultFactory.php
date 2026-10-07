<?php

namespace Database\Factories;

use App\Models\InboundMessage;
use App\Models\Order;
use Illuminate\Database\Eloquent\Factories\Factory;

class ResultFactory extends Factory
{
    public function definition(): array
    {
        return [
            'order_id' => Order::factory(),
            'patient_id' => fn(array $attributes) => Order::find($attributes['order_id'])->patient_id,
            'inbound_message_id' => InboundMessage::factory(),
            'set_id' => 1,
            'code' => fake()->unique()->bothify('??##'),
            'name' => fake()->words(2, true),
            'value' => (string) fake()->randomFloat(1, 1, 100),
            'value_type' => 'NM',
            'unit' => 'g/dL',
            'reference_range' => '12-16',
            'flag' => 'N',
            'result_status' => 'F',
            'observed_at' => fake()->dateTimeBetween('-1 year'),
        ];
    }
}
