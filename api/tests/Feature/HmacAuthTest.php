<?php

use App\Http\Middleware\VerifyHmacSignature;
use App\Models\InboundMessage;
use Illuminate\Foundation\Testing\LazilyRefreshDatabase;

uses(LazilyRefreshDatabase::class);

it('returns 401 when a header is missing', function (array $headers) {
    $payload = labResultMessage();
    $signature = VerifyHmacSignature::sign(
        TEST_SIGNING_KEY,
        'POST',
        '/api/integrations/lab-results',
        json_encode($payload)
    );

    $this->postJson(
        '/api/integrations/lab-results',
        $payload,
        array_intersect_key(['X-Client-Id' => 'hl7-service', 'X-Signature' => $signature], $headers)
    )
        ->assertUnauthorized()
        ->assertJson(['message' => 'Invalid service credentials.']);

    expect(InboundMessage::count())->toBe(0);
})->with([
    'no headers' => [[]],
    'no signature' => [['X-Client-Id' => true]],
    'no client id' => [['X-Signature' => true]],
]);

it('returns 401 for an unknown client id', function () {
    $payload = labResultMessage();

    $this->postJson(
        '/api/integrations/lab-results',
        $payload,
        [
            'X-Client-Id' => 'someone-else',
            'X-Signature' => VerifyHmacSignature::sign(TEST_SIGNING_KEY, 'POST', '/api/integrations/lab-results', json_encode($payload)),
        ]
    )->assertUnauthorized();
});

it('returns 401 for a signature made with the wrong key', function () {
    $payload = labResultMessage();

    $this->postJson(
        '/api/integrations/lab-results',
        $payload,
        [
            'X-Client-Id' => 'hl7-service',
            'X-Signature' => VerifyHmacSignature::sign('wrong-key', 'POST', '/api/integrations/lab-results', json_encode($payload)),
        ]
    )->assertUnauthorized();
});

it('returns 401 when the body was changed after signing', function () {
    $signature = VerifyHmacSignature::sign(
        TEST_SIGNING_KEY,
        'POST',
        '/api/integrations/lab-results',
        json_encode(labResultMessage())
    );

    $this->postJson(
        '/api/integrations/lab-results',
        labResultMessage(['results.0.value' => '99']),
        [
            'X-Client-Id' => 'hl7-service',
            'X-Signature' => $signature,
        ]
    )->assertUnauthorized();

    expect(InboundMessage::count())->toBe(0);
});

it('returns 401 for a signature of a different path', function () {
    $payload = labResultMessage();

    $this->postJson(
        '/api/integrations/lab-results',
        $payload,
        [
            'X-Client-Id' => 'hl7-service',
            'X-Signature' => VerifyHmacSignature::sign(TEST_SIGNING_KEY, 'POST', '/api/results', json_encode($payload)),
        ]
    )->assertUnauthorized();
});

it('returns 401 when no signing key is configured for the client', function () {
    config(['integration.clients' => []]);

    signedPostJson('/api/integrations/lab-results', labResultMessage())->assertUnauthorized();
});

it('accepts a correctly signed request and records the client id', function () {
    signedPostJson('/api/integrations/lab-results', labResultMessage())->assertCreated();

    expect(InboundMessage::sole()->client_id)->toBe('hl7-service');
});
