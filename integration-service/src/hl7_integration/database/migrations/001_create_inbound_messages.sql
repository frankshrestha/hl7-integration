CREATE TABLE inbound_messages (
    id uuid PRIMARY KEY,
    correlation_id uuid NOT NULL,
    message_control_id text,
    sending_application text NOT NULL DEFAULT '',
    sending_facility text NOT NULL DEFAULT '',
    message_type text,
    hl7_version text,
    order_no text,
    patient_external_id text,
    raw_payload text NOT NULL,
    payload_sha256 char(64) NOT NULL,
    normalized_payload jsonb,
    STATUS text NOT NULL,
    ack_code char(2) NOT NULL,
    validation_errors jsonb,
    attempt_count integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL,
    next_attempt_at timestamptz,
    locked_until timestamptz,
    last_error text,
    last_http_status integer,
    received_at timestamptz NOT NULL,
    queued_at timestamptz,
    processed_at timestamptz,
    dead_lettered_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT NOW(),
    CONSTRAINT inbound_messages_status_check CHECK (
        STATUS IN (
            -- Failed parsing or validation
            'rejected',
            -- Valid and queued; Set again when a dead-lettered message is replayed.
            'pending',
            -- Currently being sent; processed again if locked_until expires.
            'in_flight',
            -- API failure with attempts left.
            'retrying',
            'delivered',
            -- API failure or max_attempts reached.
            'dead_lettered'
        )
    ),
    CONSTRAINT inbound_messages_ack_code_check CHECK (ack_code IN ('AA', 'AE', 'AR')),
    CONSTRAINT inbound_messages_attempt_count_check CHECK (attempt_count >= 0)
);


CREATE UNIQUE INDEX inbound_messages_sender_control_id_unique ON inbound_messages (
    sending_application,
    sending_facility,
    message_control_id
)
WHERE
    STATUS <> 'rejected';


CREATE INDEX inbound_messages_deliverable_index ON inbound_messages (next_attempt_at)
WHERE
    STATUS IN ('pending', 'retrying');


CREATE INDEX inbound_messages_in_flight_lease_index ON inbound_messages (locked_until)
WHERE
    STATUS = 'in_flight';


CREATE INDEX inbound_messages_status_index ON inbound_messages (STATUS, received_at);
CREATE INDEX inbound_messages_order_no_index ON inbound_messages (order_no);
CREATE INDEX inbound_messages_control_id_index ON inbound_messages (message_control_id);
CREATE INDEX inbound_messages_correlation_id_index ON inbound_messages (correlation_id);


CREATE TABLE message_events (
    id bigserial PRIMARY KEY,
    inbound_message_id uuid NOT NULL REFERENCES inbound_messages (id),
    correlation_id uuid NOT NULL,
    event_type text NOT NULL,
    attempt_number integer,
    detail jsonb NOT NULL DEFAULT '{}' :: jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);


CREATE INDEX message_events_inbound_message_index ON message_events (inbound_message_id, created_at);


CREATE INDEX message_events_correlation_id_index ON message_events (correlation_id);
