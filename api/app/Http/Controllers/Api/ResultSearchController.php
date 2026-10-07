<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Requests\SearchResultsRequest;
use App\Http\Resources\ResultResource;
use App\Models\Order;
use App\Models\Patient;
use App\Models\Result;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Pagination\Cursor;
use Illuminate\Pagination\CursorPaginator;
use Illuminate\Support\Carbon;

class ResultSearchController extends Controller
{
    public function __invoke(SearchResultsRequest $request)
    {
        $results = Result::query()
            ->when(
                $request->filled('patient_id'),
                fn($query) => $query->where('patient_id', $request->integer('patient_id'))
            )
            ->when(
                $request->filled('patient_external_id'),
                fn($query) => $query->where(
                    'patient_id',
                    Patient::query()->select('id')->where('external_id', $request->string('patient_external_id')),
                )
            )
            ->when(
                $request->filled('order_no'),
                fn($query) => $query->where(
                    'order_id',
                    Order::query()->select('id')->where('order_no', $request->string('order_no')),
                )
            )
            ->when(
                $request->filled('code'),
                fn($query) => $query->where('code', $request->string('code'))
            )
            ->when(
                $request->filled('flag'),
                fn($query) => $query->where('flag', $request->string('flag'))
            )
            ->when(
                $request->filled('from'),
                fn($query) => $query->where('observed_at', '>=', Carbon::parse($request->string('from')))
            )
            ->when(
                $request->filled('to'),
                fn($query) => $query->where('observed_at', '<=', Carbon::parse($request->string('to'))->endOfDay())
            )
            ->when(
                CursorPaginator::resolveCurrentCursor(),
                fn($query, Cursor $cursor) => $this->seekPastCursor($query, $cursor)
            )
            ->with([
                'order:id,order_no,service_code,service_name',
                'patient:id,external_id,first_name,last_name',
            ])
            ->orderByDesc('observed_at')
            ->orderByDesc('id')
            ->cursorPaginate($request->integer('per_page', 25))
            ->withQueryString();

        return ResultResource::collection($results);
    }

    /**
     * Cursor translates to `observed_at < ? OR (observed_at = ? AND id < ?)` which
     * does not use as an index.
     */
    private function seekPastCursor(Builder $query, Cursor $cursor): Builder
    {
        return $query->whereRaw(
            $cursor->pointsToNextItems() ? '(observed_at, id) < (?, ?)' : '(observed_at, id) > (?, ?)',
            [$cursor->parameter('observed_at'), $cursor->parameter('id')],
        );
    }
}
