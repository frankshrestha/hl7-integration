<?php

use App\Enums\InboundMessageStatus;
use App\Models\AuditLog;
use App\Models\InboundMessage;
use App\Models\Order;
use App\Models\Patient;
use App\Models\Result;
use Illuminate\Foundation\Testing\LazilyRefreshDatabase;

uses(LazilyRefreshDatabase::class);

const LAB_RESULTS_URI = '/api/integrations/lab-results';

it('records the incoming message', function () {
    $correlationId = '7d1c2b8e-6d1f-4a51-9f8e-2a5f0c6b9e11';

    $response = signedPostJson(LAB_RESULTS_URI, labResultMessage(), ['X-Correlation-ID' => $correlationId]);

    $response->assertCreated()
        ->assertHeader('X-Correlation-ID', $correlationId)
        ->assertJson([
            'outcome' => 'processed',
            'message_id' => 'MSG00001',
            'status' => 'processed',
            'correlation_id' => $correlationId,
        ]);

    $patient = Patient::sole();
    expect($patient->only(['external_id', 'first_name', 'last_name', 'gender']))
        ->toBe([
            'external_id' => 'PAT00001',
            'first_name' => 'JOHN',
            'last_name' => 'DOE',
            'gender' => 'M'
        ]);

    $order = Order::sole();
    expect($order->only(['patient_id', 'order_no', 'service_code', 'service_name']))
        ->toBe([
            'patient_id' => $patient->id,
            'order_no' => 'ORD00001',
            'service_code' => 'CBC',
            'service_name' => 'Complete Blood Count'
        ]);

    $inboundMessage = InboundMessage::sole();
    expect($inboundMessage->status)->toBe(InboundMessageStatus::Processed)
        ->and($inboundMessage->attempts)->toBe(1)
        ->and($inboundMessage->client_id)->toBe('hl7-service')
        ->and($inboundMessage->processed_at)->not->toBeNull();

    $results = Result::query()->orderBy('set_id')->get();
    expect($results->pluck('code')->all())->toBe(['HB', 'WBC'])
        ->and($results->pluck('value')->all())->toBe(['13.5', '7500'])
        ->and($results->pluck('order_id')->unique()->all())->toBe([$order->id])
        ->and($results->pluck('patient_id')->unique()->all())->toBe([$patient->id])
        ->and($results->pluck('inbound_message_id')->unique()->all())->toBe([$inboundMessage->id]);

    expect(AuditLog::query()->orderBy('id')->pluck('event')->all())
        ->toBe(['patient.created', 'order.created', 'result.created', 'result.created', 'message.processed'])
        ->and(AuditLog::query()->distinct()->pluck('correlation_id')->all())->toBe([$correlationId])
        ->and(AuditLog::query()->distinct()->pluck('message_id')->all())->toBe(['MSG00001']);
});

it('generates a correlation ID when the caller does not send one', function () {
    $response = signedPostJson(LAB_RESULTS_URI, labResultMessage());

    $correlationId = $response->headers->get('X-Correlation-ID');

    expect($correlationId)->toBeUuid()
        ->and(InboundMessage::sole()->correlation_id)->toBe($correlationId);
});

it('rejects an invalid message and writes nothing', function (array $overrides, string $invalidField) {
    signedPostJson(LAB_RESULTS_URI, labResultMessage($overrides))
        ->assertUnprocessable()
        ->assertJsonValidationErrors($invalidField);

    expect(InboundMessage::count())->toBe(0)
        ->and(Patient::count())->toBe(0)
        ->and(Result::count())->toBe(0);
})->with([
    'missing message id' => [['message_id' => null], 'message_id'],
    'missing patient id' => [['patient.external_id' => null], 'patient.external_id'],
    'missing order number' => [['order.order_no' => null], 'order.order_no'],
    'no results' => [['results' => []], 'results'],
    'duplicate result codes' => [['results.1.code' => 'HB'], 'results.0.code'],
    'dob in the future' => [['patient.dob' => '2999-01-01'], 'patient.dob'],
    'dob not Y-m-d' => [['patient.dob' => '19900101'], 'patient.dob'],
    'unknown gender' => [['patient.gender' => 'X'], 'patient.gender'],
]);

it('stores the same message only once', function () {
    signedPostJson(LAB_RESULTS_URI, labResultMessage())->assertCreated();
    signedPostJson(LAB_RESULTS_URI, labResultMessage())->assertOk()->assertJson([
        'outcome' => 'duplicate',
        'status' => 'processed'
    ]);
    signedPostJson(LAB_RESULTS_URI, labResultMessage())->assertOk()->assertJson(['outcome' => 'duplicate']);

    expect(Patient::count())->toBe(1)
        ->and(Order::count())->toBe(1)
        ->and(Result::count())->toBe(2)
        ->and(InboundMessage::sole()->attempts)->toBe(1)
        ->and(AuditLog::where('event', 'message.processed')->count())->toBe(1);
});

it('treats a redelivery with reordered JSON keys as a duplicate', function () {
    signedPostJson(LAB_RESULTS_URI, labResultMessage())->assertCreated();

    $reordered = array_reverse(labResultMessage(), preserve_keys: true);

    signedPostJson(LAB_RESULTS_URI, $reordered)->assertOk()->assertJson(['outcome' => 'duplicate']);
});

it('returns conflict when a processed message ID is reused with a different payload', function () {
    signedPostJson(LAB_RESULTS_URI, labResultMessage())->assertCreated();

    signedPostJson(LAB_RESULTS_URI, labResultMessage(['results.0.value' => '9.9']))
        ->assertConflict()
        ->assertJson(['outcome' => 'conflict']);

    expect(Result::where('code', 'HB')->value('value'))->toBe('13.5');
});

it('overwrites a corrected result and logs the old and new values', function () {
    signedPostJson(LAB_RESULTS_URI, labResultMessage())->assertCreated();

    signedPostJson(LAB_RESULTS_URI, labResultMessage([
        'message_id' => 'MSG00002',
        'results' => [[
            'set_id' => 1,
            'code' => 'HB',
            'name' => 'Hemoglobin',
            'value' => '11.2',
            'value_type' => 'NM',
            'unit' => 'g/dL',
            'reference_range' => '12-16',
            'flag' => 'L',
            'result_status' => 'C'
        ]],
    ]))->assertCreated();

    $result = Result::where('code', 'HB')->sole();
    expect($result->only(['value', 'flag', 'result_status']))
        ->toBe([
            'value' => '11.2',
            'flag' => 'L',
            'result_status' => 'C'
        ])
        ->and(Result::count())->toBe(2);

    $audit = AuditLog::where('event', 'result.updated')->sole();
    expect($audit->message_id)->toBe('MSG00002')
        ->and($audit->auditable_id)->toBe($result->id)
        ->and($audit->old_values)->toEqual(['value' => '13.5', 'flag' => 'N', 'result_status' => 'F'])
        ->and($audit->new_values)->toEqual(['value' => '11.2', 'flag' => 'L', 'result_status' => 'C']);

    expect(AuditLog::where('message_id', 'MSG00002')->whereIn('event', ['patient.updated', 'order.updated'])->exists())->toBeFalse();
});

it('rolls back everything when processing fails mid-transaction', function () {
    signedPostJson(LAB_RESULTS_URI, labResultMessage(), ['X-Simulate-Failure' => 'true'])
        ->assertServiceUnavailable();

    expect(Patient::count())->toBe(0)
        ->and(Order::count())->toBe(0)
        ->and(Result::count())->toBe(0)
        ->and(AuditLog::pluck('event')->all())->toBe(['message.failed']);

    $inboundMessage = InboundMessage::sole();
    expect($inboundMessage->status)->toBe(InboundMessageStatus::Failed)
        ->and($inboundMessage->attempts)->toBe(1)
        ->and($inboundMessage->last_error)->toBe('Simulated processing failure before commit.');
});

it('processes a previously failed message when it is retried', function () {
    signedPostJson(LAB_RESULTS_URI, labResultMessage(), ['X-Simulate-Failure' => 'true'])
        ->assertServiceUnavailable();

    signedPostJson(LAB_RESULTS_URI, labResultMessage())->assertCreated()->assertJson(['outcome' => 'processed']);

    $inboundMessage = InboundMessage::sole();
    expect($inboundMessage->status)
        ->toBe(InboundMessageStatus::Processed)
        ->and($inboundMessage->attempts)->toBe(2)
        ->and($inboundMessage->last_error)->toBeNull()
        ->and(Result::count())->toBe(2);
});

it('ignores the failure simulation header when simulation is disabled', function () {
    config(['integration.allow_failure_simulation' => false]);

    signedPostJson(LAB_RESULTS_URI, labResultMessage(), ['X-Simulate-Failure' => 'true'])->assertCreated();
});

it('rejects an order number that already belongs to another patient', function () {
    signedPostJson(LAB_RESULTS_URI, labResultMessage())->assertCreated();

    signedPostJson(LAB_RESULTS_URI, labResultMessage(['message_id' => 'MSG00002', 'patient.external_id' => 'PAT00002']))
        ->assertUnprocessable()
        ->assertJsonValidationErrors('order.order_no');

    expect(Patient::where('external_id', 'PAT00002')->exists())->toBeFalse()
        ->and(InboundMessage::where('message_id', 'MSG00002')->value('status'))->toBe(InboundMessageStatus::Failed);
});
