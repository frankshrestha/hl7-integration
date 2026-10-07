<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('batch_items', function (Blueprint $table) {
            $table->id();
            $table->string('message_id', 64)->unique();
            $table->string('status', 20);
            $table->unsignedInteger('attempts')->default(0);

            // status pending -> available_at is next due
            // status processing -> available_at is when the claim's lease expires
            $table->timestampTz('available_at', 6);
            $table->text('last_error')->nullable();
            $table->timestampsTz();

            $table->index(['status', 'available_at']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('batch_items');
    }
};
