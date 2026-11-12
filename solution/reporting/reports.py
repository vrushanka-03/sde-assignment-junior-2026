
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet

from solution.config import (
    DB_PATH,
    REPORT_DIR,
    SCHEMA_DIR,
    DISPOSITIONS_FILE,
    get_encryption_key,
)
from solution.database.db import get_connection


REPORT_COLUMNS = {
    "batch_summary.csv": [
        "workflow_id", "batch_id", "total_leads",
        "yet_to_reach_out", "in_progress_telephony_failed",
        "in_progress_dialed", "completed",
    ],
    "daily_overview.csv": [
        "workflow_id", "date", "total_calls",
        "connected_calls", "connectivity_rate", "success_leads",
    ],
    "lead_report.csv": [
        "workflow_id", "external_ref", "batch_id", "phone_masked",
        "bucket", "total_calls", "connected_calls", "last_call_at",
        "current_disposition", "ever_success",
    ],
    "rejections.csv": [
        "workflow_id", "batch_id", "row_number", "reason",
    ],
}


def _parse_time(value):
    if not value:
        return None
    return datetime.fromisoformat(value)


def _load_dispositions():
    result = {}

    with DISPOSITIONS_FILE.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        for row in csv.DictReader(file):
            workflow = row["workflow_id"].strip()
            code = row["code"].strip()
            result[(workflow, code)] = {
                "terminal": row["is_terminal"].strip().lower() == "true",
                "success": row["is_success"].strip().lower() == "true",
            }

    return result


def _load_schemas():
    schemas = {}
    for path in SCHEMA_DIR.glob("*.json"):
        with path.open("r", encoding="utf-8") as file:
            schemas[path.stem] = json.load(file)
    return schemas


def _reconcile_all_events(connection):
    # Recalculate links globally. This also picks up leads added in later drops.
    connection.execute("""
        UPDATE event_links
        SET lead_id = NULL, status = 'orphan'
        WHERE event_id IN (
            SELECT event_id FROM events
            WHERE ignored_reason IS NULL
        )
    """)

    # First link events that have a phone hash.
    connection.execute("""
        UPDATE event_links
        SET lead_id = (
            SELECT l.id
            FROM events e
            JOIN leads l
              ON l.workflow_id = e.workflow_id
             AND l.phone_hash = e.phone_hash
            WHERE e.event_id = event_links.event_id
            LIMIT 1
        ),
        status = CASE
            WHEN EXISTS (
                SELECT 1
                FROM events e
                JOIN leads l
                  ON l.workflow_id = e.workflow_id
                 AND l.phone_hash = e.phone_hash
                WHERE e.event_id = event_links.event_id
            ) THEN 'linked'
            ELSE 'orphan'
        END
        WHERE event_id IN (
            SELECT event_id FROM events
            WHERE ignored_reason IS NULL
              AND phone_hash IS NOT NULL
              AND event_type != 'disposition.override'
        )
    """)

    # Overrides have no phone; link them through another event in the call.
    overrides = connection.execute("""
        SELECT event_id, workflow_id, call_id
        FROM events
        WHERE event_type = 'disposition.override'
          AND ignored_reason IS NULL
    """).fetchall()

    for event in overrides:
        if not event["call_id"]:
            continue

        linked = connection.execute("""
            SELECT el.lead_id
            FROM events e
            JOIN event_links el ON el.event_id = e.event_id
            WHERE e.workflow_id = ?
              AND e.call_id = ?
              AND e.event_id != ?
              AND el.lead_id IS NOT NULL
            ORDER BY
              CASE WHEN e.event_type = 'call.initiated' THEN 0 ELSE 1 END,
              e.occurred_at_utc
            LIMIT 1
        """, (
            event["workflow_id"],
            event["call_id"],
            event["event_id"],
        )).fetchone()

        if linked:
            connection.execute("""
                UPDATE event_links
                SET lead_id = ?, status = 'linked'
                WHERE event_id = ?
            """, (linked["lead_id"], event["event_id"]))


def _effective_disposition(call_events):
    overrides = [
        event for event in call_events
        if event["event_type"] == "disposition.override"
        and event["disposition_code"]
    ]

    if overrides:
        chosen = max(
            overrides,
            key=lambda event: event["occurred_at_utc"] or "",
        )
        return chosen["disposition_code"]

    sets = [
        event for event in call_events
        if event["event_type"] == "disposition.set"
        and event["disposition_code"]
    ]

    if not sets:
        return None

    chosen = max(
        sets,
        key=lambda event: event["occurred_at_utc"] or "",
    )
    return chosen["disposition_code"]


def _write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=columns,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def generate_reports(output_dir=REPORT_DIR, db_path=DB_PATH):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    dispositions = _load_dispositions()
    schemas = _load_schemas()
    cipher = get_encryption_key()

    with get_connection(db_path) as connection:
        _reconcile_all_events(connection)

        leads = connection.execute("""
            SELECT * FROM leads
            ORDER BY workflow_id, external_ref
        """).fetchall()

        events = connection.execute("""
            SELECT e.*, el.lead_id, el.status AS link_status
            FROM events e
            JOIN event_links el ON el.event_id = e.event_id
            WHERE el.lead_id IS NOT NULL
              AND el.status = 'linked'
              AND e.ignored_reason IS NULL
            ORDER BY e.occurred_at_utc
        """).fetchall()

        # Build calls only from events linked to a lead.
        events_by_call = defaultdict(list)
        for event in events:
            if event["call_id"]:
                key = (event["lead_id"], event["workflow_id"], event["call_id"])
                events_by_call[key].append(dict(event))

        calls_by_lead = defaultdict(list)
        daily_calls = defaultdict(list)

        for (lead_id, workflow_id, call_id), call_events in events_by_call.items():
            initiated = [
                event for event in call_events
                if event["event_type"] == "call.initiated"
                and event["occurred_at_utc"]
            ]

            # A call counts only when call.initiated exists.
            if not initiated:
                continue

            start_event = min(
                initiated,
                key=lambda event: event["occurred_at_utc"],
            )

            connected = any(
                event["event_type"] == "call.connected"
                for event in call_events
            )

            telephony_failed = any(
                event["event_type"] == "call.telephony_failed"
                for event in call_events
            )

            disposition = _effective_disposition(call_events)
            disposition_info = dispositions.get(
                (workflow_id, disposition),
                {"terminal": False, "success": False},
            )

            call = {
                "lead_id": lead_id,
                "workflow_id": workflow_id,
                "call_id": call_id,
                "started_utc": start_event["occurred_at_utc"],
                "started_ist": start_event["occurred_at_ist"],
                "date": (
                    start_event["occurred_at_ist"][:10]
                    if start_event["occurred_at_ist"]
                    else ""
                ),
                "connected": connected,
                "telephony_failed": telephony_failed,
                "disposition": disposition,
                "terminal": disposition_info["terminal"],
                "success": disposition_info["success"],
            }

            calls_by_lead[lead_id].append(call)
            daily_calls[(workflow_id, call["date"])].append(call)

        # ---------------- Batch summary ----------------
        batch_counts = defaultdict(lambda: {
            "total_leads": 0,
            "yet_to_reach_out": 0,
            "in_progress_telephony_failed": 0,
            "in_progress_dialed": 0,
            "completed": 0,
        })

        lead_bucket = {}

        for lead in leads:
            lead_id = lead["id"]
            lead_calls = calls_by_lead[lead_id]

            if not lead_calls:
                bucket = "yet_to_reach_out"
            elif any(call["terminal"] for call in lead_calls):
                bucket = "completed"
            elif all(call["telephony_failed"] for call in lead_calls):
                bucket = "in_progress_telephony_failed"
            else:
                bucket = "in_progress_dialed"

            lead_bucket[lead_id] = bucket
            key = (lead["workflow_id"], lead["batch_id"])
            batch_counts[key]["total_leads"] += 1
            batch_counts[key][bucket] += 1

        batch_rows = []
        for (workflow_id, batch_id), counts in sorted(batch_counts.items()):
            batch_rows.append({
                "workflow_id": workflow_id,
                "batch_id": batch_id,
                **counts,
            })

        _write_csv(
            output_dir / "batch_summary.csv",
            REPORT_COLUMNS["batch_summary.csv"],
            batch_rows,
        )

        # ---------------- Daily overview ----------------
        daily_rows = []

        for (workflow_id, date), calls in sorted(daily_calls.items()):
            if not date:
                continue

            total = len(calls)
            connected = sum(1 for call in calls if call["connected"])
            successful_leads = {
                call["lead_id"] for call in calls if call["success"]
            }

            daily_rows.append({
                "workflow_id": workflow_id,
                "date": date,
                "total_calls": total,
                "connected_calls": connected,
                "connectivity_rate": f"{connected / total:.4f}",
                "success_leads": len(successful_leads),
            })

        _write_csv(
            output_dir / "daily_overview.csv",
            REPORT_COLUMNS["daily_overview.csv"],
            daily_rows,
        )

        # ---------------- Lead report ----------------
        lead_rows = []

        for lead in leads:
            lead_id = lead["id"]
            lead_calls = calls_by_lead[lead_id]

            lead_calls.sort(key=lambda call: call["started_utc"])

            latest_call = lead_calls[-1] if lead_calls else None
            disposition_call = next(
                (
                    call for call in reversed(lead_calls)
                    if call["disposition"]
                ),
                None,
            )

            last4 = cipher.decrypt(
                lead["phone_last4"].encode("utf-8")
            ).decode("utf-8")

            pii = json.loads(
                cipher.decrypt(
                    lead["pii_encrypted"].encode("utf-8")
                ).decode("utf-8")
            )

            workflow_schema = schemas.get(lead["workflow_id"], {})
            defaults = {
                field["name"]: field.get("default")
                for field in workflow_schema.get("fields", [])
                if "default" in field
            }

            # Defaults are presentation-time fallbacks; they do not overwrite
            # stored values or affect duplicate merging.
            current_disposition = (
                disposition_call["disposition"]
                if disposition_call else ""
            )

            lead_rows.append({
                "workflow_id": lead["workflow_id"],
                "external_ref": lead["external_ref"],
                "batch_id": lead["batch_id"],
                "phone_masked": "+91******" + last4,
                "bucket": lead_bucket[lead_id],
                "total_calls": len(lead_calls),
                "connected_calls": sum(
                    1 for call in lead_calls if call["connected"]
                ),
                "last_call_at": (
                    latest_call["started_ist"] if latest_call else ""
                ),
                "current_disposition": current_disposition,
                "ever_success": str(
                    any(call["success"] for call in lead_calls)
                ).lower(),
            })

        lead_rows.sort(
            key=lambda row: (
                row["workflow_id"],
                row["external_ref"],
            )
        )

        _write_csv(
            output_dir / "lead_report.csv",
            REPORT_COLUMNS["lead_report.csv"],
            lead_rows,
        )

        # ---------------- Rejections ----------------
        rejection_records = connection.execute("""
            SELECT workflow_id, batch_id, row_number, reason
            FROM lead_row_audit
            WHERE status = 'rejected'
            ORDER BY workflow_id, batch_id, row_number
        """).fetchall()

        rejection_rows = [
            {
                "workflow_id": row["workflow_id"],
                "batch_id": row["batch_id"],
                "row_number": row["row_number"],
                "reason": row["reason"],
            }
            for row in rejection_records
        ]

        _write_csv(
            output_dir / "rejections.csv",
            REPORT_COLUMNS["rejections.csv"],
            rejection_rows,
        )

        # ---------------- Data quality ----------------
        lead_audit = connection.execute("""
            SELECT status, COUNT(*) AS count
            FROM lead_row_audit
            GROUP BY status
        """).fetchall()

        lead_status_counts = {
            row["status"]: row["count"] for row in lead_audit
        }

        rejection_reasons = connection.execute("""
            SELECT reason, COUNT(*) AS count
            FROM lead_row_audit
            WHERE status = 'rejected'
            GROUP BY reason
            ORDER BY reason
        """).fetchall()

        warning_count = connection.execute("""
            SELECT COUNT(*) FROM field_warnings
        """).fetchone()[0]

        event_status = connection.execute("""
            SELECT status, COUNT(*) AS count
            FROM event_line_audit
            GROUP BY status
        """).fetchall()

        event_status_counts = {
            row["status"]: row["count"] for row in event_status
        }

        event_total = connection.execute("""
            SELECT COUNT(*) FROM event_line_audit
        """).fetchone()[0]

        orphan_count = connection.execute("""
            SELECT COUNT(*)
            FROM event_links
            WHERE status = 'orphan'
        """).fetchone()[0]

        unknown_count = connection.execute("""
            SELECT COUNT(*)
            FROM events
            WHERE ignored_reason = 'unknown_disposition'
        """).fetchone()[0]

        data_quality = {
            "lead_rows_total": sum(lead_status_counts.values()),
            "lead_rows_rejected": lead_status_counts.get("rejected", 0),
            "rejections_by_reason": {
                row["reason"]: row["count"]
                for row in rejection_reasons
            },
            "duplicate_lead_rows_merged": lead_status_counts.get(
                "duplicate_merged", 0
            ),
            "field_warnings": warning_count,
            "events_total": event_total,
            "malformed_events": event_status_counts.get("malformed", 0),
            "duplicate_events_dropped": event_status_counts.get(
                "duplicate", 0
            ),
            "orphan_events": orphan_count,
            "unknown_disposition_events": unknown_count,
        }

        with (output_dir / "data_quality.json").open(
            "w", encoding="utf-8"
        ) as file:
            json.dump(data_quality, file, indent=2)

    return {
        "output_directory": str(output_dir),
        "files": [
            "batch_summary.csv",
            "daily_overview.csv",
            "lead_report.csv",
            "rejections.csv",
            "data_quality.json",
        ],
        "data_quality": data_quality,
    }
