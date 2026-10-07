<?php

namespace Database\Factories;

use App\Models\Patient;
use Illuminate\Database\Eloquent\Factories\Factory;

class OrderFactory extends Factory
{
    public function definition(): array
    {
        return [
            'patient_id' => Patient::factory(),
            'order_no' => 'ORD' . fake()->unique()->numerify('########'),
            'service_code' => 'CBC',
            'service_name' => 'Complete Blood Count',
        ];
    }
}
