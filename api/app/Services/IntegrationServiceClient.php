<?php

namespace App\Services;

use App\Exceptions\BatchRequestFailed;
use App\Http\Middleware\VerifyHmacSignature;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Str;

class IntegrationServiceClient
{
    public const BATCH_PATH = '/batches';

    public function fetchBatch(string $batchId, array $items): array
    {
        $clientId = config('integration.batch.client_id');
        $body = json_encode(['batch_id' => $batchId, 'items' => $items], JSON_THROW_ON_ERROR);

        try {
            $response = Http::baseUrl(config('integration.batch.service_url'))
                ->timeout(config('integration.batch.timeout'))
                ->acceptJson()
                ->withHeaders([
                    'X-Correlation-ID' => (string) Str::uuid(),
                    'X-Client-Id' => $clientId,
                    'X-Signature' => VerifyHmacSignature::sign(
                        (string) config("integration.clients.{$clientId}"),
                        'POST',
                        self::BATCH_PATH,
                        $body
                    ),
                ])
                ->withBody($body, 'application/json')
                ->post(self::BATCH_PATH);
        } catch (ConnectionException $exception) {
            throw new BatchRequestFailed(
                "Integration service unreachable: {$exception->getMessage()}",
                previous: $exception
            );
        }

        if ($response->failed()) {
            throw new BatchRequestFailed(
                "Integration service returned HTTP {$response->status()}: " . Str::limit($response->body(), 500)
            );
        }

        $results = $response->json('results');

        if (! is_array($results)) {
            throw new BatchRequestFailed('Integration service returned a response without results.');
        }

        return $results;
    }
}
