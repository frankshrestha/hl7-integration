<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

class StoreLabResultRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    public function rules(): array
    {
        return [
            'message_id' => ['required', 'string', 'max:64'],
            'message_type' => ['nullable', 'string', 'max:20'],
            'message_datetime' => ['required', 'date'],

            'patient' => ['required', 'array'],
            'patient.external_id' => ['required', 'string', 'max:64'],
            'patient.first_name' => ['nullable', 'string', 'max:255'],
            'patient.last_name' => ['nullable', 'string', 'max:255'],
            'patient.dob' => ['nullable', 'date_format:Y-m-d', 'before_or_equal:today'],
            'patient.gender' => ['nullable', 'string', 'in:M,F,O'],

            'order' => ['required', 'array'],
            'order.order_no' => ['required', 'string', 'max:64'],
            'order.service_code' => ['required', 'string', 'max:50'],
            'order.service_name' => ['nullable', 'string', 'max:255'],

            'results' => ['required', 'array', 'min:1', 'max:100'],
            'results.*.set_id' => ['nullable', 'integer', 'min:1', 'max:65535'],
            'results.*.code' => ['required', 'string', 'max:50', 'distinct'],
            'results.*.name' => ['nullable', 'string', 'max:255'],
            'results.*.value' => ['nullable', 'string', 'max:10000'],
            'results.*.value_type' => ['nullable', 'string', 'max:10'],
            'results.*.unit' => ['nullable', 'string', 'max:50'],
            'results.*.reference_range' => ['nullable', 'string', 'max:100'],
            'results.*.flag' => ['nullable', 'string', 'max:5'],
            'results.*.result_status' => ['nullable', 'string', 'size:1'],
            'results.*.observed_at' => ['nullable', 'date'],
        ];
    }
}
