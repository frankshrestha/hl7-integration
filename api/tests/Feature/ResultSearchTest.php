<?php

use App\Models\Order;
use App\Models\Patient;
use App\Models\Result;
use Illuminate\Foundation\Testing\LazilyRefreshDatabase;

uses(LazilyRefreshDatabase::class);

it('returns 401 without a valid signature', function () {
    $this->getJson('/api/results')->assertUnauthorized();
});

it('returns results newest first with order and patient details', function () {
    $order = Order::factory()->create(['order_no' => 'ORD00001']);
    $older = Result::factory()->for($order)->create(['code' => 'HB', 'observed_at' => '2026-09-01 08:00:00']);
    $newer = Result::factory()->for($order)->create(['code' => 'WBC', 'observed_at' => '2026-09-02 08:00:00']);

    signedGetJson('/api/results')
        ->assertOk()
        ->assertJsonPath('data.*.id', [$newer->id, $older->id])
        ->assertJsonPath('data.0.order.order_no', 'ORD00001')
        ->assertJsonPath('data.0.patient.external_id', $order->patient->external_id);
});

it('filters by internal patient id', function () {
    $patient = Patient::factory()->create();
    $match = Result::factory()->for(Order::factory()->for($patient))->create();
    Result::factory()->create();

    signedGetJson('/api/results', ['patient_id' => $patient->id])
        ->assertOk()
        ->assertJsonPath('data.*.id', [$match->id]);
});

it('filters by patient external id', function () {
    $patient = Patient::factory()->create(['external_id' => 'PAT00001']);
    $match = Result::factory()->for(Order::factory()->for($patient))->create();
    Result::factory()->create();

    signedGetJson('/api/results', ['patient_external_id' => 'PAT00001'])
        ->assertOk()
        ->assertJsonPath('data.*.id', [$match->id]);
});

it('filters by order number', function () {
    $match = Result::factory()->for(Order::factory()->state(['order_no' => 'ORD00001']))->create();
    Result::factory()->create();

    signedGetJson('/api/results', ['order_no' => 'ORD00001'])
        ->assertOk()
        ->assertJsonPath('data.*.id', [$match->id]);
});

it('filters by code and flag', function () {
    $match = Result::factory()->create(['code' => 'HB', 'flag' => 'H']);
    Result::factory()->create(['code' => 'HB', 'flag' => 'N']);
    Result::factory()->create(['code' => 'WBC', 'flag' => 'H']);

    signedGetJson('/api/results', ['code' => 'HB', 'flag' => 'H'])
        ->assertOk()
        ->assertJsonPath('data.*.id', [$match->id]);
});

it('filters by an date range', function () {
    Result::factory()->create(['code' => 'HB', 'observed_at' => '2026-08-31 23:59:59']);
    $firstDay = Result::factory()->create(['code' => 'HB', 'observed_at' => '2026-09-01 00:00:00']);
    $lastDay = Result::factory()->create(['code' => 'HB', 'observed_at' => '2026-10-01 23:59:59']);
    Result::factory()->create(['code' => 'HB', 'observed_at' => '2026-10-02 00:00:00']);

    signedGetJson('/api/results', ['code' => 'HB', 'from' => '2026-09-01', 'to' => '2026-10-01'])
        ->assertOk()
        ->assertJsonPath('data.*.id', [$lastDay->id, $firstDay->id]);
});

it('pages through results with a cursor without repeating or skipping rows', function () {
    $order = Order::factory()->create();
    $results = Result::factory()->for($order)->count(5)
        ->sequence(fn($sequence) => ['observed_at' => '2026-09-01 08:00:00'])
        ->create();

    $firstPage = signedGetJson('/api/results', ['per_page' => 3])->assertOk()->assertJsonCount(3, 'data');
    $cursor = $firstPage->json('meta.next_cursor');

    $secondPage = signedGetJson('/api/results', ['per_page' => 3, 'cursor' => $cursor])
        ->assertOk()
        ->assertJsonCount(2, 'data')
        ->assertJsonPath('meta.next_cursor', null);

    expect([
        ...$firstPage->json('data.*.id'),
        ...$secondPage->json('data.*.id')
    ])
        ->toBe($results->pluck('id')->sortDesc()->values()->all());
});

it('rejects invalid search parameters', function (array $query, string $invalidField) {
    signedGetJson('/api/results', $query)
        ->assertUnprocessable()
        ->assertJsonValidationErrors($invalidField);
})->with([
    'per_page above 100' => [['per_page' => 101], 'per_page'],
    'per_page below 1' => [['per_page' => 0], 'per_page'],
    'to before from' => [['from' => '2026-10-01', 'to' => '2026-09-01'], 'to'],
    'invalid date' => [['from' => 'yesterday-ish'], 'from'],
    'non-numeric patient id' => [['patient_id' => 'abc'], 'patient_id'],
]);
