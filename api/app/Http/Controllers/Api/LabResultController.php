<?php

namespace App\Http\Controllers\Api;

use App\Actions\ProcessLabResultMessage;
use App\Http\Controllers\Controller;
use App\Http\Requests\StoreLabResultRequest;
use App\Models\InboundMessage;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\Context;

class LabResultController extends Controller
{
    public function store(StoreLabResultRequest $request, ProcessLabResultMessage $processLabResultMessage): JsonResponse
    {
        $result = $processLabResultMessage->handle(
            $request->validated(),
            Context::get('correlation_id'),
            Context::get('client_id'),
            simulateFailure: config('integration.allow_failure_simulation') && $request->header('X-Simulate-Failure') === 'true',
        );

        $inboundMessage = InboundMessage::query()
            ->where('message_id', $request->validated('message_id'))
            ->firstOrFail(['id', 'message_id', 'status', 'correlation_id', 'processed_at']);

        return response()->json([
            'outcome' => $result->value,
            'message_id' => $inboundMessage->message_id,
            'inbound_message_id' => $inboundMessage->id,
            'status' => $inboundMessage->status->value,
            'correlation_id' => $inboundMessage->correlation_id,
            'processed_at' => $inboundMessage->processed_at?->toIso8601String(),
        ], $result->httpStatus());
    }
}
