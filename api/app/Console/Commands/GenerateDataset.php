<?php

namespace App\Console\Commands;

use App\Enums\InboundMessageStatus;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;

class GenerateDataset extends Command
{
    protected $signature = 'dataset:generate
        {--patients=500000 : Number of patients}
        {--orders-per-patient=4 : Average orders per patient}
        {--results-per-order=4 : Results per order}
        {--chunk=250000 : Rows per INSERT statement}
        {--force : Run outside local/testing and truncate existing data}';

    protected $description = 'Generate a dataset';

    private const TABLES = ['patients', 'inbound_messages', 'orders', 'results'];

    /** test => [service name, [code, name, unit, low, high]...] */
    private const TESTS = [
        'CBC' => ['Complete Blood Count', [
            ['HB', 'Hemoglobin', 'g/dL', 12, 16],
            ['WBC', 'White Blood Cell Count', 'cells/uL', 4000, 11000],
            ['PLT', 'Platelet Count', '10^3/uL', 150, 450],
            ['RBC', 'Red Blood Cell Count', '10^6/uL', 4.2, 5.9],
            ['HCT', 'Hematocrit', '%', 36, 48],
            ['MCV', 'Mean Corpuscular Volume', 'fL', 80, 100],
        ]],
        'BMP' => ['Basic Metabolic Panel', [
            ['NA', 'Sodium', 'mmol/L', 135, 145],
            ['K', 'Potassium', 'mmol/L', 3.5, 5.1],
            ['CL', 'Chloride', 'mmol/L', 98, 107],
            ['CO2', 'Carbon Dioxide', 'mmol/L', 22, 29],
            ['GLU', 'Glucose', 'mg/dL', 70, 99],
            ['BUN', 'Blood Urea Nitrogen', 'mg/dL', 7, 20],
            ['CREAT', 'Creatinine', 'mg/dL', 0.6, 1.2],
        ]],
        'LIPID' => ['Lipid Panel', [
            ['CHOL', 'Total Cholesterol', 'mg/dL', 125, 200],
            ['TRIG', 'Triglycerides', 'mg/dL', 40, 150],
            ['HDL', 'HDL Cholesterol', 'mg/dL', 40, 60],
            ['LDL', 'LDL Cholesterol', 'mg/dL', 50, 130],
        ]],
        'TFT' => ['Thyroid Function Tests', [
            ['TSH', 'Thyroid Stimulating Hormone', 'mIU/L', 0.4, 4.0],
            ['FT4', 'Free T4', 'ng/dL', 0.8, 1.8],
            ['FT3', 'Free T3', 'pg/mL', 2.3, 4.2],
            ['T4', 'Total T4', 'ug/dL', 5.0, 12.0],
        ]],
    ];

    /* @formatter:off */
    private const FIRST_NAMES = ['JOHN', 'JANE', 'MICHAEL', 'SARAH', 'DAVID', 'EMMA', 'JAMES', 'OLIVIA', 'ROBERT', 'AMELIA', 'WILLIAM', 'SOFIA', 'AHMAD', 'NUR', 'WEI', 'MEI', 'RAJ', 'PRIYA', 'CARLOS', 'MARIA'];

    private const LAST_NAMES = ['SMITH', 'JOHNSON', 'BROWN', 'TAYLOR', 'LEE', 'WONG', 'TAN', 'LIM', 'KUMAR', 'SINGH', 'GARCIA', 'MARTINEZ', 'NGUYEN', 'KIM', 'ABDULLAH', 'RAHMAN', 'MULLER', 'ROSSI', 'SILVA', 'DOE'];
    /* @formatter:on */


    public function handle(): int
    {
        $total_patients = (int) $this->option('patients');
        $total_orders = $total_patients * (int) $this->option('orders-per-patient');
        $resultsPerOrder = (int) $this->option('results-per-order');
        $chunk_size = (int) $this->option('chunk');
        $smallestTest = min(array_map(fn(array $test) => count($test[1]), self::TESTS));

        if (
            $total_patients < 1
            || $total_orders < 1
            || $chunk_size < 1
            || $resultsPerOrder < 1
            || $resultsPerOrder > $smallestTest
        ) {
            $this->error("Options must be positive and --results-per-order at most {$smallestTest}.");

            return self::INVALID;
        }

        if (! $this->option('force')) {
            if (! $this->laravel->environment(['local', 'testing'])) {
                $this->error('Use --force option to run outside local/testing.');

                return self::FAILURE;
            }
        }

        $this->info(sprintf(
            'Generating %s patients, %s orders, %s inbound messages, %s results.',
            number_format($total_patients),
            number_format($total_orders),
            number_format($total_orders),
            number_format($total_orders * $resultsPerOrder),
        ));

        $now = now()->toIso8601String();

        DB::statement('TRUNCATE audit_logs, results, orders, inbound_messages, patients RESTART IDENTITY');

        $indexes = $this->secondaryIndexes();

        $this->line('Dropping secondary indexes...');
        foreach ($indexes as $index) {
            $this->line("  {$index->definition};");
            DB::statement('DROP INDEX IF EXISTS ' . $this->quoteIdent($index->name));
        }

        try {
            $this->insertChunked(
                'patients',
                $total_patients,
                $chunk_size,
                fn(int $from, int $to) => DB::statement($this->patientsSql(), [$from, $to])
            );

            $this->insertChunked(
                'inbound_messages',
                $total_orders,
                $chunk_size,
                fn(int $from, int $to) => DB::statement($this->inboundMessagesSql(), [$now, $total_orders, $from, $to])
            );

            $this->insertChunked(
                'orders',
                $total_orders,
                $chunk_size,
                fn(int $from, int $to) => DB::statement($this->ordersSql(), [$total_patients, $now, $total_orders, $from, $to])
            );

            $ordersPerChunk = max(1, intdiv($chunk_size, $resultsPerOrder));
            $this->insertChunked(
                'results',
                $total_orders,
                $ordersPerChunk,
                fn(int $from, int $to) => DB::statement($this->resultsSql($resultsPerOrder), [$from, $to]),
                $resultsPerOrder
            );
        } finally {
            DB::statement("SET maintenance_work_mem = '1GB'");
            foreach ($indexes as $index) {
                DB::statement(preg_replace('/^CREATE INDEX /', 'CREATE INDEX IF NOT EXISTS ', $index->definition));
            }
            DB::statement('RESET maintenance_work_mem');
        }

        foreach (self::TABLES as $table) {
            DB::statement("SELECT setval(pg_get_serial_sequence('{$table}', 'id'), (SELECT max(id) FROM {$table}))");
            DB::statement("ANALYZE {$table}");
        }

        return self::SUCCESS;
    }

    /**
     * Non-unique, non-primary indexes on the generated tables.
     */
    private function secondaryIndexes(): array
    {
        return DB::select(
            <<<'SQL'
            SELECT i.relname AS name, pg_get_indexdef(i.oid) AS definition
            FROM pg_index x
            JOIN pg_class i ON i.oid = x.indexrelid
            JOIN pg_class t ON t.oid = x.indrelid
            WHERE t.relnamespace = current_schema()::regnamespace
              AND t.relname IN ('patients', 'inbound_messages', 'orders', 'results')
              AND NOT x.indisunique
              AND NOT x.indisprimary
            ORDER BY t.relname, i.relname
            SQL
        );
    }

    private function insertChunked(string $label, int $total, int $chunk, callable $insert, int $rowsPerId = 1): void
    {
        $this->newLine();
        $this->line($label);
        $bar = $this->output->createProgressBar($total * $rowsPerId);

        for ($from = 1; $from <= $total; $from += $chunk) {
            $to = min($from + $chunk - 1, $total);
            $insert($from, $to);
            $bar->advance(($to - $from + 1) * $rowsPerId);
        }

        $bar->finish();
        $this->newLine();
    }

    private function patientsSql(): string
    {
        $firstNames = $this->arrayLiteral(self::FIRST_NAMES);
        $lastNames = $this->arrayLiteral(self::LAST_NAMES);

        return <<<SQL
            INSERT INTO patients (id, external_id, first_name, last_name, dob, gender, created_at, updated_at)
            SELECT
                i,
                'PAT' || lpad(i::text, 9, '0'),
                ({$firstNames})[1 + floor(random() * cardinality({$firstNames}))::int],
                ({$lastNames})[1 + floor(random() * cardinality({$lastNames}))::int],
                current_date - (365 + floor(random() * 365 * 89))::int,
                CASE WHEN random() < 0.5 THEN 'M' ELSE 'F' END,
                now(),
                now()
            FROM generate_series(?::bigint, ?::bigint) AS i
            SQL;
    }

    private function inboundMessagesSql(): string
    {
        $status = InboundMessageStatus::Processed->value;

        return <<<SQL
            INSERT INTO inbound_messages (id, message_id, message_type, correlation_id, client_id, payload_hash, payload,
                                          status, attempts, received_at, processed_at, created_at, updated_at)
            SELECT
                i,
                'GEN' || lpad(i::text, 10, '0'),
                'ORU^R01',
                gen_random_uuid(),
                'hl7-service',
                encode(sha256(i::text::bytea), 'hex'),
                '{}'::jsonb,
                '{$status}',
                1,
                ts + interval '5 minutes',
                ts + interval '5 minutes',
                ts + interval '5 minutes',
                ts + interval '5 minutes'
            FROM ({$this->timestampedSeries()}) AS s
            SQL;
    }

    private function ordersSql(): string
    {
        $tests = collect(['CBC', 'CBC', 'CBC', 'CBC', 'CBC', 'BMP', 'BMP', 'BMP', 'LIPID', 'TFT'])
            ->map(
                fn(string $test, int $slot) => sprintf(
                    '(%d, %s, %s)',
                    $slot,
                    $this->quote($test),
                    $this->quote(self::TESTS[$test][0])
                )
            )
            ->implode(', ');

        return <<<SQL
            WITH tests (slot, code, name) AS (VALUES {$tests})
            INSERT INTO orders (id, patient_id, order_no, service_code, service_name, created_at, updated_at)
            SELECT
                s.i,
                1 + floor(power(random(), 2) * ?::bigint)::bigint,
                'ORD' || lpad(s.i::text, 10, '0'),
                t.code,
                t.name,
                s.ts,
                s.ts
            FROM ({$this->timestampedSeries()}) AS s
            JOIN tests t ON t.slot = s.i % 10
            SQL;
    }

    private function resultsSql(int $resultsPerOrder): string
    {
        $analytes = collect(self::TESTS)
            ->flatMap(fn(array $test, string $code) => collect($test[1])->map(fn(array $a, int $pos) => sprintf(
                '(%s, %d, %d, %s, %s, %s, %s::numeric, %s::numeric)',
                $this->quote($code),
                $pos,
                count($test[1]),
                $this->quote($a[0]),
                $this->quote($a[1]),
                $this->quote($a[2]),
                $a[3],
                $a[4],
            )))
            ->implode(",\n                ");

        return <<<SQL
            WITH analytes (test, pos, test_size, code, name, unit, low, high) AS (VALUES
                {$analytes})
            INSERT INTO results (id, order_id, patient_id, inbound_message_id, set_id, code, name, value, value_type,
                                 unit, reference_range, flag, result_status, observed_at, created_at, updated_at)
            SELECT
                (r.order_id - 1) * {$resultsPerOrder} + r.k + 1,
                r.order_id,
                r.patient_id,
                r.order_id,
                r.k + 1,
                a.code,
                a.name,
                round(CASE
                    WHEN r.band < 0.85 THEN a.low + (a.high - a.low) * r.u
                    WHEN r.band < 0.92 THEN a.high + (a.high - a.low) * 0.25 * (0.05 + r.u)
                    WHEN r.band < 0.98 THEN a.low * (1 - 0.25 * (0.05 + r.u))
                    WHEN r.band < 0.99 THEN a.high * (1.5 + r.u)
                    ELSE a.low * 0.4 * (0.1 + r.u)
                END, 1)::text,
                'NM',
                a.unit,
                a.low || '-' || a.high,
                CASE
                    WHEN r.band < 0.85 THEN 'N'
                    WHEN r.band < 0.92 THEN 'H'
                    WHEN r.band < 0.98 THEN 'L'
                    WHEN r.band < 0.99 THEN 'HH'
                    ELSE 'LL'
                END,
                'F',
                r.observed_at,
                r.observed_at + interval '5 minutes',
                r.observed_at + interval '5 minutes'
            FROM (
                -- random() in this subquery's select list runs once per row (volatile, so not pulled up)
                SELECT o.id AS order_id, o.patient_id, o.service_code, o.created_at AS observed_at, k,
                       random()::numeric AS band, random()::numeric AS u
                FROM orders o
                CROSS JOIN generate_series(0, {$resultsPerOrder} - 1) AS k
                WHERE o.id BETWEEN ?::bigint AND ?::bigint
            ) AS r
            JOIN analytes a ON a.test = r.service_code AND a.pos = (r.order_id / 10 + r.k) % a.test_size
            SQL;
    }

    private function timestampedSeries(): string
    {
        return <<<SQL
            SELECT i, ?::timestamptz - interval '3 years' + interval '3 years' * ((i - 1)::float8 / ?::bigint) AS ts
            FROM generate_series(?::bigint, ?::bigint) AS i
            SQL;
    }

    private function arrayLiteral(array $values): string
    {
        return 'ARRAY[' . implode(', ', array_map($this->quote(...), $values)) . ']';
    }

    private function quote(string $value): string
    {
        return "'" . str_replace("'", "''", $value) . "'";
    }

    private function quoteIdent(string $name): string
    {
        return '"' . str_replace('"', '""', $name) . '"';
    }
}
