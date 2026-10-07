<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('inbound_messages', function (Blueprint $table) {
            $table->id();
            $table->string('message_id', 64)->unique();
            $table->string('message_type', 20)->nullable(); // HL7 message type
            $table->uuid('correlation_id')->index();
            $table->string('client_id', 64); // Authenticated client.
            $table->char('payload_hash', 64);
            $table->jsonb('payload');
            $table->string('status', 20)->index();
            $table->unsignedInteger('attempts')->default(0);
            $table->text('last_error')->nullable();
            $table->timestampTz('received_at');
            $table->timestampTz('processed_at')->nullable();
            $table->timestampsTz();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('inbound_messages');
    }
};
