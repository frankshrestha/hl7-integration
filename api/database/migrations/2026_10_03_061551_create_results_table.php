<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('results', function (Blueprint $table) {
            $table->id();
            $table->foreignId('order_id')->constrained()->restrictOnDelete();
            $table->foreignId('patient_id')->constrained()->restrictOnDelete();
            $table->foreignId('inbound_message_id')->index()->constrained()->restrictOnDelete();
            $table->unsignedSmallInteger('set_id')->nullable();
            $table->string('code', 50);
            $table->string('name')->nullable();
            $table->text('value')->nullable();
            $table->string('value_type', 10)->nullable();
            $table->string('unit', 50)->nullable();
            $table->string('reference_range', 100)->nullable();
            $table->string('flag', 5)->nullable();
            $table->char('result_status', 1)->nullable();
            $table->timestampTz('observed_at');
            $table->timestampsTz();

            $table->unique(['order_id', 'code']);
        });

        DB::statement('CREATE INDEX results_patient_id_observed_at_index ON results (patient_id, observed_at DESC, id DESC)');
        DB::statement('CREATE INDEX results_code_observed_at_index ON results (code, observed_at DESC, id DESC)');
        DB::statement('CREATE INDEX results_observed_at_index ON results (observed_at DESC, id DESC)');
    }

    public function down(): void
    {
        Schema::dropIfExists('results');
    }
};
