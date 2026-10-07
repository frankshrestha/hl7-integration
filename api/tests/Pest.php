<?php

use App\Http\Middleware\VerifyHmacSignature;
use Tests\TestCase;

const TEST_SIGNING_KEY = 'test-signing-key';

/*
|--------------------------------------------------------------------------
| Test Case
|--------------------------------------------------------------------------
|
| The closure you provide to your test functions is always bound to a specific PHPUnit test
| case class. By default, that class is "PHPUnit\Framework\TestCase". Of course, you may
| need to change it using the "pest()" function to bind different classes or traits.
|
*/

pest()->extend(TestCase::class)
    ->beforeEach(function () {
        config([
            'integration.clients' => ['hl7-service' => TEST_SIGNING_KEY],
            'integration.allow_failure_simulation' => true,
        ]);
    })
    ->in('Feature');

/*
|--------------------------------------------------------------------------
| Expectations
|--------------------------------------------------------------------------
|
| When you're writing tests, you often need to check that values meet certain conditions. The
| "expect()" function gives you access to a set of "expectations" methods that you can use
| to assert different things. Of course, you may extend the Expectation API at any time.
|
*/

expect()->extend('toBeOne', function () {
    return $this->toBe(1);
});

/*
|--------------------------------------------------------------------------
| Functions
|--------------------------------------------------------------------------
|
| While Pest is very powerful out-of-the-box, you may have some testing code specific to your
| project that you don't want to repeat in every file. Here you can also expose helpers as
| global functions to help you to reduce the number of lines of code in your test files.
|
*/

function something()
{
    // ..
}

/**
 * Load the sample normalized lab-result message
 */
function labResultMessage(array $overrides = []): array
{
    $message = json_decode(
        file_get_contents(__DIR__.'/Fixtures/lab-result-message.json'),
        true,
        flags: JSON_THROW_ON_ERROR
    );

    foreach ($overrides as $key => $value) {
        data_set($message, $key, $value);
    }

    return $message;
}

/**
 * POST an HMAC-signed JSON as the hl7-service client.
 */
function signedPostJson(string $uri, array $payload, array $headers = [])
{
    return test()->postJson($uri, $payload, [
        'X-Client-Id' => 'hl7-service',
        'X-Signature' => VerifyHmacSignature::sign(TEST_SIGNING_KEY, 'POST', $uri, json_encode($payload)),
        ...$headers,
    ]);
}

/**
 * Send an HMAC-signed GET as the hl7-service client.
 */
function signedGetJson(string $path, array $query = [])
{
    $uri = $query === [] ? $path : $path.'?'.http_build_query($query);

    return test()->get($uri, [
        'Accept' => 'application/json',
        'X-Client-Id' => 'hl7-service',
        'X-Signature' => VerifyHmacSignature::sign(TEST_SIGNING_KEY, 'GET', $uri, ''),
    ]);
}
