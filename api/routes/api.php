<?php

use App\Http\Controllers\Api\LabResultController;
use App\Http\Controllers\Api\ResultSearchController;
use App\Http\Middleware\AssignCorrelationId;
use App\Http\Middleware\VerifyHmacSignature;
use Illuminate\Support\Facades\Route;

Route::middleware([AssignCorrelationId::class, VerifyHmacSignature::class])->group(function () {
    Route::post('integrations/lab-results', [LabResultController::class, 'store'])->name('integrations.lab-results.store');
    Route::get('results', ResultSearchController::class)->name('results.index');
});
