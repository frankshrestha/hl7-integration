<?php

return [

    /*
    |--------------------------------------------------------------------------
    | Integration Clients
    |--------------------------------------------------------------------------
    |
    | Services allowed to call the API, keyed by the value they must
    | send in the X-Client-Id header. Each value is the shared HMAC signing key.
    |
    */

    'clients' => array_filter([
        'hl7-service' => env('HL7_SERVICE_SIGNING_KEY'),
    ]),

    /*
    |--------------------------------------------------------------------------
    | Failure Simulation
    |--------------------------------------------------------------------------
    |
    | When enabled, a request carrying "X-Simulate-Failure: true" throws after
    | the data writes and before commit, demonstrating transaction rollback.
    |
    */

    'allow_failure_simulation' => (bool) env('ALLOW_FAILURE_SIMULATION', false),

    /*
    |--------------------------------------------------------------------------
    | Batch Processing
    |--------------------------------------------------------------------------
    |
    | Failed inbound messages are fetched again from the integration service
    | in batches.
    |
    */

    'batch' => [
        'size' => (int) env('INTEGRATION_BATCH_SIZE', 300),
        'service_url' => env('INTEGRATION_SERVICE_URL', 'http://127.0.0.1:8085'),
        'client_id' => 'hl7-service',
        'timeout' => (int) env('INTEGRATION_BATCH_TIMEOUT', 30),
        'lease_seconds' => (int) env('INTEGRATION_BATCH_LEASE_SECONDS', 120),
        'max_attempts' => (int) env('INTEGRATION_BATCH_MAX_ATTEMPTS', 8),
        'backoff_seconds' => (int) env('INTEGRATION_BATCH_BACKOFF_SECONDS', 10),
        'queue' => env('INTEGRATION_BATCH_QUEUE', 'batches'),
    ],

];
