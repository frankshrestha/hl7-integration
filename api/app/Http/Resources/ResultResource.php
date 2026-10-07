<?php

namespace App\Http\Resources;

use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;

class ResultResource extends JsonResource
{
    public function toArray(Request $request): array
    {
        return [
            'id' => $this->id,
            'code' => $this->code,
            'name' => $this->name,
            'value' => $this->value,
            'value_type' => $this->value_type,
            'unit' => $this->unit,
            'reference_range' => $this->reference_range,
            'flag' => $this->flag,
            'result_status' => $this->result_status,
            'observed_at' => $this->observed_at->toIso8601String(),
            'order' => [
                'order_no' => $this->order->order_no,
                'service_code' => $this->order->service_code,
                'service_name' => $this->order->service_name,
            ],
            'patient' => [
                'id' => $this->patient->id,
                'external_id' => $this->patient->external_id,
                'first_name' => $this->patient->first_name,
                'last_name' => $this->patient->last_name,
            ],
        ];
    }
}
