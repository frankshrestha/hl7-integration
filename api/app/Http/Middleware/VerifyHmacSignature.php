<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Context;
use Symfony\Component\HttpFoundation\Response;

/**
 * Authenticates service-to-service calls with a per-client shared key.
 */
class VerifyHmacSignature
{
    public function handle(Request $request, Closure $next): Response
    {
        $clientId = $request->header('X-Client-Id');
        $signature = $request->header('X-Signature');

        $key = is_string($clientId) ? config("integration.clients.{$clientId}") : null;

        if (
            ! is_string($key) || $key === '' || ! is_string($signature)
            || ! hash_equals(
                self::sign($key, $request->method(), $request->getRequestUri(), $request->getContent()),
                $signature
            )
        ) {
            return response()->json(['message' => 'Invalid service credentials.'], Response::HTTP_UNAUTHORIZED);
        }

        Context::add('client_id', $clientId);

        return $next($request);
    }

    /**
     * Compute the signature.
     */
    public static function sign(string $key, string $method, string $requestUri, string $body): string
    {
        return hash_hmac(
            'sha256',
            strtoupper($method) . "\n" . $requestUri . "\n" . hash('sha256', $body),
            $key
        );
    }
}
