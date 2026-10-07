# Architecture

- **Integration service** (`integration-service`) is a Python/FastAPI application that receives HL7 messages, validates, maps, ACKs, forwards JSON to the API.
- **API** (`api`) is a Laravel application that uses PostgreSQL and stores the forwarded information (messages, patients, results). It also has a search API, batch synchronization command.

```text
┌─────────────────┐
│                 │
│    HL7 Sender   │<─────────────┐
│   (Simulator)   │      ACK     │
│                 │              │
└────────┬────────┘              │
         │ POST /hl7/messages    │
         ▼                       │
┌─────────────────────────────────────────┐
│  Integration Service (Python/FastAPI)   │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │     parse -> validate -> map     │   │
│  └───────────────┬──────────────────┘   │
│                  ▼                      │              ┌──────────────────────────────────┐
│        ┌──────────────────┐             │              │     Laravel API                  │
│        │       Store      │             │              │ ┌──────────────────────────────┐ │
│        │                  │             │              │ │ verify request -> validate   │ │
│        └────────┬─────────┘             │              │ │                              │ │
│        ┌────────▼──────────────┐        │              │ └──────────────┬───────────────┘ │
│        │         Worker        │────────│─────JSON────>│                ▼                 │
│        │ claim -> sign -> send │        │              │   ┌────────────────────────┐     │
│        └───────────────────────┘        │              │   │  Store                 │     │
│                                         │              │   └────────────────────────┘     │
└─────────────────────────────────────────┘              └──────────────────────────────────┘
```

## Data flow

1. Sender posts HL7 message to `POST /hl7/messages`.
2. Service parses, validate, map to JSON.
3. Save raw HL7 + JSON then ACK.
4. A worker claims due rows, signs the JSON and posts it to the API.
5. API verifies request, validates and stores.
6. The service records the outcome: delivered, retry or dead letter.
7. Messages that failed in API are fetched again by `batch:run` in batches of 300.

# HL7 Messages Simulator

- [BridgeLab](https://github.com/techemv-srl/BridgeLab/releases/tag/v2.0.0) for sending and generating HL7 messages
- [RokRage HL7 Toolkit](https://marketplace.visualstudio.com/items?itemName=RokRage.hl7-toolkit) VS Code extension for documentation, sending messages and research

# Supported HL7 message

`ORU^R01` (v2.5): one PID, one OBR, one or more OBX. Accepts `\r`/`\n`/`\r\n`.

# HL7 to JSON mapping

An HL7 message like:

```
MSH|^~\&|BRIDGELAB_GEN|TESTFAC|TESTAPP|TESTFAC|20260712084400||ORU^R01|GEN000001|P|2.5
PID|1||2802081^^^HOSPITAL^MR||COLOMBO^GRETA||20130603|F|||VIA GARIBALDI 195^^MILANO^^40621^IT
OBR|1|ORD281452||CBC^Complete Blood Count^L|||20260712084400|||||||||||||||20260712084400|F
OBX|1|NM|GLU^Glucose^L||84.8|mg/dL|65.0-110.0|N|||F|||20260712084400
OBX|2|NM|WBC^White Blood Cell Count^L||5.0|10*3/uL|4.0-11.0|N|||F|||20260712084400
OBX|3|NM|HGB^Hemoglobin^L||15.9|g/dL|12.0-17.5|N|||F|||20260712084400
OBX|4|NM|PLT^Platelet Count^L||296.4|10*3/uL|150.0-400.0|N|||F|||20260712084400
```

is mapped to:

```json
{
    "order": { "order_no": "ORD281452", "service_code": "CBC", "service_name": "Complete Blood Count" },
    "patient": {
        "dob": "2013-06-03",
        "gender": "F",
        "last_name": "COLOMBO",
        "first_name": "GRETA",
        "external_id": "2802081"
    },
    "results": [
        {
            "code": "GLU",
            "flag": "N",
            "name": "Glucose",
            "unit": "mg/dL",
            "value": "84.8",
            "set_id": 1,
            "value_type": "NM",
            "observed_at": "2026-07-12T08:44:00",
            "result_status": "F",
            "reference_range": "65.0-110.0"
        },
        {
            "code": "WBC",
            "flag": "N",
            "name": "White Blood Cell Count",
            "unit": "10*3/uL",
            "value": "5.0",
            "set_id": 2,
            "value_type": "NM",
            "observed_at": "2026-07-12T08:44:00",
            "result_status": "F",
            "reference_range": "4.0-11.0"
        },
        {
            "code": "HGB",
            "flag": "N",
            "name": "Hemoglobin",
            "unit": "g/dL",
            "value": "15.9",
            "set_id": 3,
            "value_type": "NM",
            "observed_at": "2026-07-12T08:44:00",
            "result_status": "F",
            "reference_range": "12.0-17.5"
        },
        {
            "code": "PLT",
            "flag": "N",
            "name": "Platelet Count",
            "unit": "10*3/uL",
            "value": "296.4",
            "set_id": 4,
            "value_type": "NM",
            "observed_at": "2026-07-12T08:44:00",
            "result_status": "F",
            "reference_range": "150.0-400.0"
        }
    ],
    "message_id": "GEN000001",
    "message_type": "ORU^R01",
    "message_datetime": "2026-07-12T08:44:00"
}
```

# Service-to-Service Authentication

The services use HMAC for authentication. Each service will send `X-Client-Id` and `X-Signature` (computed as `HMAC-SHA256(secret, METHOD\npath?query\nsha256(body))`)
headers with the request. Unlike an API key it protects the body and needs no token handling. The same key signs `POST /batches`. Secrets are configured in the .env file.

# Retry/failure handling

Messages flow through distinct states: `pending` -> `in_flight` -> (`delivered` | `retrying` | `dead_lettered`). ACK is sent after the message is stored and before the worker attempts delivery.

## State Machine & Retry Mechanism

**Integration Service (forwarding worker):**

- **Lease-based claiming:** `SKIP LOCKED + FOR UPDATE` claims one batch of due messages. Each claimed message is locked with `locked_until` timestamp for the lease duration.
- **Exponential backoff:** Failed deliveries are rescheduled with delay = `base_seconds * 2^(attempt_count-1)` and capped at `backoff_cap_seconds`.
- **Idempotent delivery:** The same normalized payload and correlation ID are sent on retry.
- **Dead-letter queue:** Messages that exceed `max_attempts` or encounter permanent errors (4xx response) are moved to `dead_lettered` status with the error recorded.
- **Message persistence:** Raw HL7 is always stored before ACK. The `raw_payload` and `normalized_payload` are kept so failed messages can be processed again.

**Laravel API (batch processing):**

- **Separate retry loop:** Batched items have their own `status` (pending -> processing -> completed/failed) and `attempts` counter.
- **Exponential backoff:** Failed batches schedule retry with delay = `backoff_seconds * 2^(attempts-1)`.
- **Partial failure handling:** A failed batch item does not block others. Integration service unavailability re-queues all items in the batch.
- **Validation outcomes:** Invalid data (bad payload, order/patient mismatch, conflict on message ID) are marked failed (not retried). Transient errors and missing items trigger retry.

# Tracing & Observability

- **Correlation ID:** Assigned on message arrival and sent with every outgoing request (header `X-Correlation-ID`) and logged by both services.
- **Search indexes:** Covering indexes on `(observed_at DESC, id DESC)` enable efficient range queries without table scans

# Idempotency Strategy

**HL7 sender -> Integration Service:**

- Unique index on `(sending_application, sending_facility, message_control_id)` prevents duplicate ingestion.
- `INSERT … ON CONFLICT DO NOTHING` silently drops exact duplicates.
- Rejected messages are tracked separately. So re-sending an invalid message updates it to pending if the error is fixed.

**Integration Service -> Laravel API:**

- Same normalized payload and correlation ID on every retry.
- Laravel stores a hash of the payload; duplicate payloads return `200 OK` without re-processing.
- `ON CONFLICT (message_id) DO UPDATE SET …` in a single transaction ensures no duplicates even if two workers race.

**Laravel -> Integration Service:**

- Each batch item has a unique `message_id`. Re-fetching returns stored results.
- The integration service is stateless and batch results are computed on demand and so replay is safe.

# Transaction Strategy

**Single message processing (Integration Service -> Laravel):**

- One `DB::transaction` covers: validate -> insert patient -> insert order -> insert results -> mark message processed.
- If any step fails, the entire transaction rolls back and the message status remains `in_flight`.
- Failure is recorded outside the transaction.

**Batch claiming (both services):**

- CTE with `FOR UPDATE SKIP LOCKED` atomically claims and locks rows in one query.
- Updates use `WHERE status = 'in_flight' AND attempt_count = %s` to protect against concurrent workers.
- All inserts use `ON CONFLICT` inside the transaction.

# Concurrency Strategy

- **Lease-based locking:** Each claimed message has `locked_until` timestamp. If a worker crashes, the lock expires and another worker claims it.
- **SKIP LOCKED:** Workers skip rows already held by others avoiding contention and deadlocks.
- **Attempt count:** Updates only succeed if `attempt_count` matches what the worker expects. If another worker won the lease, the update fails.

**Batch claiming (API):**

- `FOR UPDATE SKIP LOCKED LIMIT 300` claims without loading full dataset.
- Workers independently claim, process and update.
- Partial failure: only failed items are re-queued. Others move to completed.

# Audit & Tracing

**Correlation ID:**

- Assigned on message arrival as a UUID, sent in the `X-Correlation-ID` header to every outgoing request.
- Stored in `inbound_messages.correlation_id` and included in all logs and event records.
- Enables end-to-end tracing: HL7 sender request -> integration service -> API response.

**Message events:**

- `message_events` table records every state transition with:
    - `inbound_message_id`, `correlation_id`, `event_type` (e.g., received, delivery_attempted, delivery_succeeded, retry_scheduled, dead_lettered)
    - `attempt_number` for context
    - `details`: HTTP status, error message, retry delay

**Audit logs (Laravel):**

- Every data change (patient, order, result) is logged with: old values, new values, timestamp, correlation ID.

**Structured logs:**

- All log lines include `correlation_id`, `message_control_id`, `inbound_message_id`, and `attempt_number`.
- Logs carry HTTP status, error type.

# Database Indexing Decisions

**Unique indexes (idempotency & lookups):**

- `inbound_messages (sending_application, sending_facility, message_control_id)` - prevent duplicate records.
- `inbound_messages (message_id)` - fast lookup.
- `patients (external_id)` - unique patient per external system ID.
- `orders (order_no)` - unique order across all time.
- `results (order_id, code)` - unique result per order/test-code pair.
- `batch_items (message_id)` - prevent duplicate batch entries.

**Claim/queue indexes (worker claiming):**

- `inbound_messages (status, next_attempt_at)` - find due messages efficiently.
- `batch_items (status, available_at)` - find due batch items.

**Search indexes (API queries):**

- `results (observed_at DESC, id DESC)` - paginate by date, covering index for fast scans.
- `results (patient_id, observed_at DESC, id DESC)` - search by patient.
- `results (order_id, observed_at DESC, id DESC)` - search by order.
- `results (code, observed_at DESC, id DESC)` - search by test code.

**Foreign key indexes:**

- Automatic indexes on `results.patient_id`, `results.order_id`, `orders.patient_id`, and `audit_logs.inbound_message_id`.

**Event/audit indexes:**

- `message_events (inbound_message_id)` - fetch history for a message.
- `message_events (correlation_id)` - fetch history by request ID.

# Assumptions & Known Limitations

**Assumptions:**

- HL7 message IDs are unique within a sender (sending_application + sending_facility pair). If not enforced by the sender, collisions cause duplicates.
- API is reachable within the `hl7_api_timeout_seconds`. Network issues are transient and resolve within one retry cycle.

**Known limitations:**

- **Manual requeue:** Dead-lettered messages must be manually requeued.
- **No fast fail:** If API is persistently unavailable, workers retry indefinitely until max_attempts.

# Dataset Generation

```
php artisan dataset:generate
```

creates test data using `INSERT … SELECT generate_series` in chunks.

# EXPLAIN ANALYZE

Two queries analyzed with `EXPLAIN (ANALYZE, BUFFERS)` on 500k patients, 2M orders, 8M results.

## Query 1: Deep Pagination with Cursor

```sql
SELECT id, observed_at, patient_id, code, value, flag, reference_range
FROM results
WHERE (observed_at, id) < ('2024-10-07'::date, 9999999)
ORDER BY observed_at DESC, id DESC
LIMIT 51;
```

```
Limit  (cost=0.43..6.85 rows=51 width=41) (actual time=0.025..0.062 rows=51.00 loops=1)
  Buffers: shared hit=54
  ->  Index Scan using results_observed_at_index on results  (cost=0.43..345571.83 rows=2745889 width=41) (actual time=0.024..0.055 rows=51.00 loops=1)
        Index Cond: (ROW(observed_at, id) < ROW('2024-10-07'::date, 9999999))
        Index Searches: 1
        Buffers: shared hit=54
Planning:
  Buffers: shared hit=177
Planning Time: 1.388 ms
Execution Time: 0.105 ms
```

This query fetches the next page of results going 2 years back. The composite row comparison `(observed_at, id) < (?, ?)` positions the cursor and prevents re-scanning earlier rows.

The composite row condition must be an `index condition` (not `filter`). With it as index condition, PostgreSQL seeks directly to the cursor position using the index. Without it, sequential scan forces reading and discarding millions of rows.

## Query 2: Patient Search by External ID

```sql
SELECT r.id, r.observed_at, r.patient_id, r.code, r.value, r.flag, r.reference_range
FROM results r
WHERE r.patient_id = (SELECT id FROM patients WHERE external_id = 'PAT000499607' LIMIT 1)
ORDER BY r.observed_at DESC, r.id DESC
LIMIT 51;
```

```
Limit  (cost=9.00..169.68 rows=39 width=41) (actual time=0.114..0.140 rows=12.00 loops=1)
  Buffers: shared hit=20
  InitPlan 1
    ->  Limit  (cost=0.42..8.44 rows=1 width=8) (actual time=0.089..0.090 rows=1.00 loops=1)
          Buffers: shared hit=4
          ->  Index Scan using patients_external_id_unique on patients  (cost=0.42..8.44 rows=1 width=8) (actual time=0.089..0.089 rows=1.00 loops=1)
                Index Cond: ((external_id)::text = 'PAT000499607'::text)
                Index Searches: 1
                Buffers: shared hit=4
  ->  Index Scan using results_patient_id_observed_at_index on results r  (cost=0.56..161.24 rows=39 width=41) (actual time=0.113..0.137 rows=12.00 loops=1)
        Index Cond: (patient_id = (InitPlan 1).col1)
        Index Searches: 1
        Buffers: shared hit=20
Planning:
  Buffers: shared hit=206
Planning Time: 2.691 ms
Execution Time: 0.183 ms
```

The query looks up a patient by external system ID and returns 51 most recent results.

The subquery returns one value via `=`. It executes once before the main query. The patient_id value is then used as an `index condition` on the `(patient_id, observed_at DESC, id DESC)` index. Using `=` instead of `IN` avoids hash join overhead and unnecessary sorting.
