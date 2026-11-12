
import csv
import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from solution.config import DB_PATH, DISPOSITIONS_FILE, get_phone_hmac_key
from solution.core.normalizers import normalize_phone
from solution.database.db import get_connection

IST = ZoneInfo("Asia/Kolkata")


def _parse_timestamp(value):
    if not value:
        return None, None

    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)

    # Naive timestamps in this dataset represent IST.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)

    utc_value = parsed.astimezone(timezone.utc)
    ist_value = parsed.astimezone(IST)

    return utc_value.isoformat(), ist_value.isoformat()



def _hash_phone(phone, key):
    if phone is None or not str(phone).strip():
        return None

    try:
        canonical = normalize_phone(phone)
    except (ValueError, TypeError):
        return None

    if canonical is None:
        return None

    return hmac.new(
        key,
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _safe_payload(payload):
    if not isinstance(payload, dict):
        return {}

    sensitive_terms = (
        "phone", "mobile", "customer",
        "name", "email", "address"
    )

    return {
        key: value
        for key, value in payload.items()
        if not any(
            term in key.lower()
            for term in sensitive_terms
        )
    }



def _load_dispositions():
    result = {}

    with DISPOSITIONS_FILE.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            normalized = {
                str(key).strip().lower().replace(" ", "_"): value
                for key, value in row.items()
                if key is not None
            }

            workflow = (
                normalized.get("workflow_id")
                or normalized.get("workflow")
            )
            code = (
                normalized.get("disposition_code")
                or normalized.get("code")
                or normalized.get("disposition")
            )

            if workflow and code:
                result.setdefault(workflow.strip(), set()).add(
                    code.strip()
                )

    return result


def ingest_events(drop_path, db_path=DB_PATH):
    drop_path = Path(drop_path).resolve()
    events_root = drop_path / "events"

    if not events_root.is_dir():
        raise FileNotFoundError(f"Events directory not found: {events_root}")

    phone_key = get_phone_hmac_key()
    known_dispositions = _load_dispositions()

    summary = {
        "events_total": 0,
        "malformed_events": 0,
        "duplicate_events_dropped": 0,
        "orphan_events": 0,
        "unknown_disposition_events": 0,
        "already_ingested": False,
    }

    with get_connection(db_path) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS event_drop_ingestions (
                drop_path TEXT PRIMARY KEY,
                ingested_at TEXT NOT NULL
            )
        """)

        if connection.execute(
            "SELECT 1 FROM event_drop_ingestions WHERE drop_path = ?",
            (str(drop_path),),
        ).fetchone():
            summary["already_ingested"] = True
            return summary

        for event_file in sorted(events_root.glob("*.jsonl")):
            with event_file.open("r", encoding="utf-8") as file:
                for line_number, line in enumerate(file, start=1):
                    if not line.strip():
                        continue

                    summary["events_total"] += 1
                    status = "accepted"

                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        summary["malformed_events"] += 1
                        status = "malformed"
                        _audit_line(
                            connection, drop_path, event_file,
                            line_number, status
                        )
                        continue

                    event_id = event.get("event_id")
                    event_type = event.get("event_type")
                    workflow_id = event.get("workflow_id")
                    call_id = event.get("call_id")
                    occurred_at = event.get("occurred_at")

                    if not event_id or not event_type or not workflow_id:
                        summary["malformed_events"] += 1
                        status = "malformed"
                        _audit_line(
                            connection, drop_path, event_file,
                            line_number, status
                        )
                        continue

                    if connection.execute(
                        "SELECT 1 FROM events WHERE event_id = ?",
                        (event_id,),
                    ).fetchone():
                        summary["duplicate_events_dropped"] += 1
                        status = "duplicate"
                        _audit_line(
                            connection, drop_path, event_file,
                            line_number, status
                        )
                        continue

                    payload = event.get("payload") or {}
                    if not isinstance(payload, dict):
                        payload = {}

                    disposition_code = payload.get("disposition_code")
                    ignored_reason = None

                    if (
                        event_type in ("disposition.set", "disposition.override")
                        and disposition_code
                        and disposition_code not in known_dispositions.get(
                            workflow_id, set()
                        )
                    ):
                        ignored_reason = "unknown_disposition"
                        summary["unknown_disposition_events"] += 1
                        status = "unknown_disposition"

                    try:
                        utc_time, ist_time = _parse_timestamp(occurred_at)
                    except (ValueError, TypeError):
                        summary["malformed_events"] += 1
                        status = "malformed"
                        _audit_line(
                            connection, drop_path, event_file,
                            line_number, status
                        )
                        continue

                    phone_hash = _hash_phone(event.get("phone"), phone_key)

                    # Store no raw phone number or unfiltered payload.
                    connection.execute(
                        """
                        INSERT INTO events (
                            event_id, workflow_id, event_type, call_id,
                            occurred_at_utc, occurred_at_ist, phone_hash,
                            disposition_code, payload_json, ignored_reason,
                            source_drop
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id,
                            workflow_id,
                            event_type,
                            call_id,
                            utc_time,
                            ist_time,
                            phone_hash,
                            disposition_code,
                            json.dumps(
                                _safe_payload(payload),
                                ensure_ascii=False,
                            ),
                            ignored_reason,
                            str(drop_path),
                        ),
                    )

                    connection.execute(
                        """
                        INSERT INTO event_links (event_id, lead_id, status)
                        VALUES (?, NULL, ?)
                        """,
                        (event_id, "ignored" if ignored_reason else "orphan"),
                    )

                    _audit_line(
                        connection, drop_path, event_file,
                        line_number, status
                    )

        # Reconcile regular events against all leads currently available.
        rows = connection.execute("""
            SELECT e.event_id, e.workflow_id, e.phone_hash, e.ignored_reason
            FROM events e
            WHERE e.source_drop = ?
        """, (str(drop_path),)).fetchall()

        for event in rows:
            if event["ignored_reason"]:
                continue

            if event["phone_hash"]:
                lead = connection.execute(
                    """
                    SELECT id FROM leads
                    WHERE workflow_id = ? AND phone_hash = ?
                    """,
                    (event["workflow_id"], event["phone_hash"]),
                ).fetchone()

                if lead:
                    connection.execute(
                        """
                        UPDATE event_links
                        SET lead_id = ?, status = 'linked'
                        WHERE event_id = ?
                        """,
                        (lead["id"], event["event_id"]),
                    )

        # Overrides have no phone. Link them through another event in
        # the same workflow and call.
        overrides = connection.execute("""
            SELECT event_id, workflow_id, call_id
            FROM events
            WHERE source_drop = ?
              AND event_type = 'disposition.override'
              AND ignored_reason IS NULL
        """, (str(drop_path),)).fetchall()

        for override in overrides:
            linked = connection.execute(
                """
                SELECT l.lead_id
                FROM events e
                JOIN event_links l ON l.event_id = e.event_id
                WHERE e.workflow_id = ?
                  AND e.call_id = ?
                  AND e.event_id != ?
                  AND l.lead_id IS NOT NULL
                LIMIT 1
                """,
                (
                    override["workflow_id"],
                    override["call_id"],
                    override["event_id"],
                ),
            ).fetchone()

            if linked:
                connection.execute(
                    """
                    UPDATE event_links
                    SET lead_id = ?, status = 'linked'
                    WHERE event_id = ?
                    """,
                    (linked["lead_id"], override["event_id"]),
                )

        # Count events still orphaned after reconciliation.
        summary["orphan_events"] = connection.execute(
            """
            SELECT COUNT(*)
            FROM event_links l
            JOIN events e ON e.event_id = l.event_id
            WHERE e.source_drop = ? AND l.status = 'orphan'
            """,
            (str(drop_path),),
        ).fetchone()[0]

        connection.execute(
            """
            INSERT INTO event_drop_ingestions (drop_path, ingested_at)
            VALUES (?, ?)
            """,
            (str(drop_path), datetime.now(timezone.utc).isoformat()),
        )

    return summary


def _audit_line(connection, drop_path, event_file, line_number, status):
    connection.execute(
        """
        INSERT INTO event_line_audit
        (drop_path, file_path, line_number, status)
        VALUES (?, ?, ?, ?)
        """,
        (
            str(drop_path),
            str(event_file.resolve()),
            line_number,
            status,
        ),
    )
