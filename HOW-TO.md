# Running both projects

Requires PHP 8.3+ with Composer, Python 3.14 with [uv](https://docs.astral.sh/uv/), and PostgreSQL.

```sh
createdb hl7_api && createdb hl7_int && createdb hl7_int_test
```

## Laravel API (`api/`)

```sh
cd api
composer install
cp .env.example .env && php artisan key:generate
```

`.env` settings:

- `DB_DATABASE=hl7_api`
- `HL7_SERVICE_SIGNING_KEY=<shared secret>`
- `INTEGRATION_SERVICE_URL=http://127.0.0.1:8085`
- `ALLOW_FAILURE_SIMULATION=true`

```sh
php artisan migrate
PHP_CLI_SERVER_WORKERS=5 php artisan serve --no-reload
```

## Integration service (`integration-service/`)

```sh
cd integration-service
uv sync
cp .env.example .env
```

`.env` settings:

- `DATABASE_URL=postgresql://localhost:5432/hl7_int`
- `HL7_API_URL=http://127.0.0.1:8000/api/integrations/lab-results`
- `HL7_API_HMAC_SECRET=<same shared secret>`
- `HL7_INT_CLIENT_ID=hl7-service`

```sh
uv run hl7 migrate --fresh
uv run hl7 serve
```

## Send and inspect messages

```sh
cd integration-service
# send a message
uv run python -m tools.hl7_simulator samples/oru_r01_cbc.hl7

# send message concurrently
uv run python -m tools.hl7_simulator samples/oru_r01_cbc.hl7 --count 20 --concurrency 20

# send a message with curl
curl -X POST http://127.0.0.1:8085/hl7/messages -H 'Content-Type: application/hl7-v2' \
  --data-binary @samples/oru_r01_cbc.hl7
```

## Sending signed API requests

```sh
export HL7_API_HMAC_SECRET=<your-shared-secret>

# helper for signing requests
sign() { printf '%s\n%s\n%s' "$1" "$2" "$(printf %s "$3" | shasum -a 256 | cut -d' ' -f1)" \
  | openssl dgst -sha256 -hmac "$HL7_API_HMAC_SECRET" | awk '{print $NF}'; }
H=(-H 'Accept: application/json' -H 'Content-Type: application/json' -H 'X-Client-Id: hl7-service')

# API result search
# available filters: patient_id, patient_external_id, order_no, code, flag, from, to, per_page
Q='/api/results?code=HB&from=2026-09-01&to=2026-10-01'
curl "http://127.0.0.1:8000$Q" "${H[@]}" -H "X-Signature: $(sign GET "$Q" '')"
```

## Failure scenarios

1. **Invalid HL7 message:**

    ```sh
    uv run python -m tools.hl7_simulator samples/oru_r01_invalid_missing_pid.hl7
    ```

2. **Concurrent duplicates:**

    ```sh
    uv run python -m tools.hl7_simulator samples/oru_r01_cbc.hl7 --count 20 --concurrency 20

    psql -d hl7_int -c "SELECT status, attempt_count FROM inbound_messages WHERE message_control_id='MSG00001'"

    psql -d hl7_api -c "SELECT (SELECT count(*) FROM inbound_messages WHERE message_id='MSG00001') total_received,
      (SELECT count(*) FROM orders WHERE order_no='ORD00001') orders,
      (SELECT count(*) FROM results r JOIN orders o ON o.id=r.order_id WHERE o.order_no='ORD00001') results"
    ```

    Expected: 20 × `AA`, 1 `delivered` row and 19 `duplicate_received` events in the service, and `1 | 1 | 2` in Laravel.

3. **API down:**
    - Stop API serve process and send a message.
    - Serve again -> message `delivered` on the next attempt.
    - If all attempts fail -> message is `dead_lettered`. Redeliver with `uv run hl7 replay --all-dead-lettered`
4. **Rollback** (`ALLOW_FAILURE_SIMULATION=true`)

    ```sh
    export BODY='{"order": {"order_no": "ORD00001", "service_code": "CBC", "service_name": "Complete Blood Count"}, "patient": {"dob": "1990-01-01", "gender": "M", "last_name": "DOE", "first_name": "JOHN", "external_id": "PAT00001"}, "results": [{"code": "HB", "flag": "N", "name": "Hemoglobin", "unit": "g/dL", "value": "13.5", "set_id": 1, "value_type": "NM", "observed_at": null, "result_status": "F", "reference_range": "12-16"}, {"code": "WBC", "flag": "N", "name": "White Blood Cell Count", "unit": "cells/uL", "value": "7500", "set_id": 2, "value_type": "NM", "observed_at": null, "result_status": "F", "reference_range": "4000-11000"}], "message_id": "UNIQUE_MSG", "message_type": "ORU^R01", "message_datetime": "2026-10-01T10:30:00"}'
    ```

    - First call returns 503, no patient/order/result rows, status `failed`.
        ```sh
        curl -X POST http://127.0.0.1:8000/api/integrations/lab-results "${H[@]}" -H 'X-Simulate-Failure: true' \
            -H "X-Signature: $(sign POST /api/integrations/lab-results "$BODY")" -d "$BODY" -w "%{http_code}"
        ```
    - Without the header -> 201 -> create.

        ```sh
        curl -X POST http://127.0.0.1:8000/api/integrations/lab-results "${H[@]}" \
            -H "X-Signature: $(sign POST /api/integrations/lab-results "$BODY")" -d "$BODY" -w "%{http_code}"
        ```

    - Same request again -> 200 (duplicate).
        ```sh
        curl -X POST http://127.0.0.1:8000/api/integrations/lab-results "${H[@]}" \
            -H "X-Signature: $(sign POST /api/integrations/lab-results "$BODY")" -d "$BODY" -w "%{http_code}"
        ```

5. **Wrong secret.** API returns 401 and the message at integration service is `dead_lettered`.

# Batching failed messages

Messages that are `failed` in API can be synced by running `php artisan batch:run` or `php artisan schedule:work`.
This will queue failed messages and start multiple jobs (max 300 messages).

Found messages status will be `completed`. If the service is down status goes to `pending` with backoff, then `failed` after max attempts.

```
php artisan queue:work --queue=batches
php artisan schedule:work
```

# Dataset generation

```
php artisan dataset:generate
```

# Tests

```
cd api && php artisan test
cd integration-service && uv run pytest
```
