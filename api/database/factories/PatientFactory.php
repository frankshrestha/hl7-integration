<?php

namespace Database\Factories;

use Illuminate\Database\Eloquent\Factories\Factory;

class PatientFactory extends Factory
{
    public function definition(): array
    {
        return [
            'external_id' => 'PAT' . fake()->unique()->numerify('########'),
            'first_name' => strtoupper(fake()->firstName()),
            'last_name' => strtoupper(fake()->lastName()),
            'dob' => fake()->date(max: '-1 year'),
            'gender' => fake()->randomElement(['M', 'F']),
        ];
    }
}
