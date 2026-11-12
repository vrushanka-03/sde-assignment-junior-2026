# Submission

## Candidate
- **Name:** Vrushanka Dasar
- **Assignment chosen:** A — Interaction Ledger & Reporting Pipeline
- **Time spent (honest estimate):** [Enter your actual total hours]

## How to run

**Requirements:** Python 3.11+

### 1. Setup

```bash
git clone <your-private-repository-url>
cd sde-assignment-junior-2026

python -m venv .venv
```

Activate the environment:

**Windows PowerShell**
```powershell
.\.venv\Scripts\Activate.ps1
```

**Linux/macOS**
```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### 2. Configure encryption keys

Create a local `.env` file containing:
- `APP_ENCRYPTION_KEY`
- `PHONE_HMAC_KEY`

Generate the keys using:

```bash
python -c "from cryptography.fernet import Fernet; import secrets; from pathlib import Path; Path('.env').write_text('APP_ENCRYPTION_KEY='+Fernet.generate_key().decode()+'\nPHONE_HMAC_KEY='+secrets.token_urlsafe(48)+'\n', encoding='utf-8')"
```

The `.env` file is excluded from Git.

### 3. Run the pipeline

Ingest the two supplied data drops:

```bash
python -m solution.main ingest data/drop_1
python -m solution.main ingest data/drop_2
```

Generate the five reports:

```bash
python -m solution.main report --out reports
```

### 4. Run tests

```bash
python -m pytest -v
```

## Design

### Architecture

The solution uses a modular Python architecture with SQLite as the persistent storage layer.

The pipeline is divided into the following components:

1. **Configuration:** Manages paths, environment variables, and encryption keys.
2. **Lead ingestion:** Reads workflow-specific CSV files, maps headers using schema names and aliases, normalizes values, validates required fields, records warnings and rejections, and merges duplicate leads.
3. **Event ingestion:** Reads JSONL event files, validates event records, handles duplicate event IDs, normalizes timestamps, and stores event information.
4. **Reconciliation:** Connects events to leads using workflow identity and HMAC-based phone matching. Events that cannot be matched are retained as orphans.
5. **Reporting:** Aggregates the stored data and generates the five required output files.

### Database design

SQLite is used because the assignment requires persistent storage and supports transactional processing without requiring an external database server.

The main tables are:

| Table | Purpose |
|---|---|
| `leads` | Stores normalized lead records and protected PII |
| `events` | Stores ingested event records |
| `event_links` | Tracks whether events are linked, orphaned, or ignored |
| `ingested_drops` | Prevents repeated lead-drop ingestion |
| `event_drop_ingestions` | Tracks processed event drops |
| `lead_row_audit` | Records accepted, merged, and rejected lead rows |
| `event_line_audit` | Tracks event-line processing outcomes |
| `field_warnings` | Records invalid optional fields |

Indexes are created on workflow and phone identity, call identifiers, event types, and lead-event relationships to support reconciliation and reporting.

### PII protection

Phone numbers are normalized and matched using HMAC-SHA256 hashes rather than plaintext values.

Sensitive lead information is encrypted using Fernet before being stored in SQLite. The encryption and HMAC keys are supplied through environment variables and are not committed to the repository.

### Processing flow

```text
CSV Lead Files       JSONL Event Files
      |                      |
      v                      v
Schema Validation      Event Validation
      |                      |
      v                      v
Normalization         Deduplication
      |                      |
      v                      v
Duplicate Merging      Event Storage
      |                      |
      +----------+-----------+
                 |
                 v
          Reconciliation
                 |
          +------+------+
          |             |
          v             v
       Linked        Orphaned
          |
          v
       Reporting
          |
          v
  Five Output Files
```

## Decisions & assumptions

| Decision | Why | Alternative considered |
|---|---|---|
| SQLite for persistence | Simple deployment and transactional support without external infrastructure | PostgreSQL |
| Lead identity uses `(workflow_id, phone_hash)` | A phone number identifies a lead within a workflow while avoiding plaintext phone matching | External reference as the primary identity |
| HMAC-SHA256 for phone matching | Supports deterministic matching without storing plaintext phone numbers | Plain SHA-256 hashing |
| Fernet encryption for sensitive lead data | Protects PII at rest using authenticated symmetric encryption | Plaintext storage |
| First accepted lead row determines `batch_id` | Preserves the original batch attribution when duplicate records are merged | Reassigning the batch to the latest duplicate |
| Non-null duplicate values overwrite existing values | Allows later records to enrich incomplete lead information without replacing values with null | First-record-wins merging |
| Invalid optional values become null with warnings | Preserves otherwise valid records while making data-quality issues visible | Rejecting the complete row |
| Timestamps without timezone information are interpreted as IST | The dataset uses Indian local time conventions | Treating naive timestamps as UTC |
| Unknown disposition codes are retained but excluded from derived disposition calculations | Prevents unrecognized codes from incorrectly affecting business reporting | Treating unknown codes as valid dispositions |
| Orphan events are retained rather than force-linked | Avoids associating an event with the wrong lead | Guessing a match using partial information |
| Override events take precedence over disposition-set events | Represents explicit disposition corrections | Using only the latest event timestamp |

## Failure modes considered

### Handled

- Missing required lead fields: the row is rejected with a specific reason.
- Invalid phone numbers: the row is rejected.
- Invalid optional fields: the value is set to null and a warning is recorded.
- Unknown CSV headers: ignored while supported schema aliases are mapped.
- Duplicate leads: merged using workflow and canonical phone identity.
- Duplicate event IDs: detected and dropped.
- Malformed JSON events: counted and skipped.
- Unknown disposition codes: counted and excluded from disposition calculations.
- Events without matching leads: retained as orphan events.
- Repeated data-drop ingestion: prevented through ingestion tracking.
- PII exposure in lead storage: mitigated through HMAC matching and encryption.

### Known limitations

- The automated test suite currently focuses on normalization and lead validation; broader integration tests for ingestion, reconciliation, and reporting are still needed.
- SQLite is suitable for this assignment but would need additional concurrency and operational considerations for a larger production workload.
- The implementation does not provide a full production monitoring or alerting system.
- Encryption-key rotation and recovery procedures are not implemented.
- More extensive testing of crash recovery and partially completed ingestion would improve reliability.

## Testing

The implementation was executed against both supplied data drops.

Automated tests were run using:

```bash
python -m pytest -v
```

**Result: 25 passed, 0 failed.**

The tests cover:
- Indian phone-number normalization.
- Date normalization across supported formats.
- Currency and decimal normalization.
- Enum and header normalization.
- Schema header alias mapping.
- Required-field validation.
- Invalid phone rejection.
- Optional-field warnings.
- Workflow-specific schema validation.

Additional manual verification included:
- Successful ingestion of both data drops.
- Report generation.
- Inspection of generated CSV and JSON files.
- Verification of event-link statuses.
- Investigation of orphan events using phone-hash and call-ID matching queries.
- Verification that local environment secrets, database files, and generated reports are excluded from Git.

## Results

The pipeline successfully generated exactly five report files.

### Data-quality results

| Metric | Result |
|---|---:|
| Lead rows processed | 2,057 |
| Rejected lead rows | 108 |
| Duplicate lead rows merged | 57 |
| Optional-field warnings | 122 |
| Events processed | 8,745 |
| Malformed events | 8 |
| Duplicate events dropped | 237 |
| Orphan events | 461 |
| Unknown disposition events | 19 |

### Event reconciliation

| Status | Events |
|---|---:|
| Linked | 8,020 |
| Orphaned | 461 |
| Ignored | 19 |

The orphan-event investigation found no orphan events whose phone hash matched an existing lead, and no orphan events sharing a call ID with another linked event.

### Generated reports

1. `batch_summary.csv`
2. `daily_overview.csv`
3. `lead_report.csv`
4. `rejections.csv`
5. `data_quality.json`

## If I had another day

1. Add integration tests for the complete ingestion and reconciliation pipeline.
2. Add tests for idempotency across repeated and incremental data drops.
3. Improve crash-recovery and transaction-boundary testing.
4. Add structured logging and more detailed operational diagnostics.
5. Introduce database migrations and evaluate PostgreSQL for larger workloads.
6. Add encryption-key rotation and recovery support.