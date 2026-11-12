
import csv
import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

from solution.config import (
    DB_PATH,
    SCHEMA_DIR,
    get_encryption_key,
    get_phone_hmac_key,
)
from solution.core.validator import validate_row
from solution.database.db import get_connection


def _now_utc():
    return datetime.now(timezone.utc).isoformat()


def _load_schema(workflow_id):
    schema_path = SCHEMA_DIR / f"{workflow_id}.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")

    with schema_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _phone_hash(phone, hmac_key):
    return hmac.new(
        hmac_key,
        phone.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _encrypt_json(data, cipher):
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return cipher.encrypt(raw).decode("utf-8")


def _decrypt_json(token, cipher):
    raw = cipher.decrypt(token.encode("utf-8"))
    return json.loads(raw.decode("utf-8"))


def _is_blank_row(row):
    return not any(
        value is not None and str(value).strip()
        for value in row.values()
    )


def ingest_leads(drop_path, db_path=DB_PATH):
    """
    Ingest all workflow CSV files from one drop.

    Re-ingesting the same resolved drop path is a no-op.
    """
    drop_path = Path(drop_path).resolve()

    if not drop_path.is_dir():
        raise NotADirectoryError(f"Drop directory does not exist: {drop_path}")

    leads_root = drop_path / "leads"
    if not leads_root.exists():
        raise FileNotFoundError(f"Missing leads directory: {leads_root}")

    cipher = get_encryption_key()
    hmac_key = get_phone_hmac_key()

    summary = {
        "drop": str(drop_path),
        "already_ingested": False,
        "rows_total": 0,
        "rows_rejected": 0,
        "duplicates_merged": 0,
        "warnings": 0,
    }

    with get_connection(db_path) as connection:
        existing_drop = connection.execute(
            "SELECT 1 FROM ingested_drops WHERE drop_path = ?",
            (str(drop_path),),
        ).fetchone()

        if existing_drop:
            summary["already_ingested"] = True
            return summary

        for workflow_dir in sorted(leads_root.iterdir(), key=lambda p: p.name):
            if not workflow_dir.is_dir():
                continue

            workflow_id = workflow_dir.name
            schema = _load_schema(workflow_id)
            fields = schema["fields"]

            pii_field_names = {
                field["name"]
                for field in fields
                if field.get("pii", False)
            }
            reference_field = next(
                (
                    field["name"]
                    for field in fields
                    if field.get("reference", False)
                ),
                None,
            )

            for csv_path in sorted(
                workflow_dir.glob("*.csv"),
                key=lambda p: p.name,
            ):
                batch_id = csv_path.stem

                with csv_path.open(
                    "r",
                    encoding="utf-8-sig",
                    newline="",
                ) as csv_file:
                    reader = csv.DictReader(csv_file)
                    row_number = 0

                    for raw_row in reader:
                        if _is_blank_row(raw_row):
                            continue

                        row_number += 1
                        summary["rows_total"] += 1

                        normalized, reason, warnings = validate_row(
                            raw_row,
                            schema,
                        )

                        if reason:
                            connection.execute(
                                """
                                INSERT INTO lead_row_audit
                                (drop_path, workflow_id, batch_id,
                                 row_number, status, reason)
                                VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    str(drop_path),
                                    workflow_id,
                                    batch_id,
                                    row_number,
                                    "rejected",
                                    reason,
                                ),
                            )
                            summary["rows_rejected"] += 1
                            continue
                        for field_name in warnings:
                            connection.execute(
                                """
                                INSERT INTO field_warnings
                                (drop_path, workflow_id, batch_id,
                                 row_number, field_name)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    str(drop_path),
                                    workflow_id,
                                    batch_id,
                                    row_number,
                                    field_name,
                                ),
                            )
                            summary["warnings"] += 1

                        phone = normalized["phone"]
                        hashed_phone = _phone_hash(phone, hmac_key)

                        pii_values = {
                            name: normalized.get(name)
                            for name in pii_field_names
                        }
                        non_pii_values = {
                            field["name"]: normalized.get(field["name"])
                            for field in fields
                            if field["name"] not in pii_field_names
                        }

                        existing_lead = connection.execute(
                            """
                            SELECT id, pii_encrypted, fields_json,
                                   external_ref
                            FROM leads
                            WHERE workflow_id = ? AND phone_hash = ?
                            """,
                            (workflow_id, hashed_phone),
                        ).fetchone()

                        if existing_lead:
                            old_pii = _decrypt_json(
                                existing_lead["pii_encrypted"],
                                cipher,
                            )
                            old_fields = json.loads(
                                existing_lead["fields_json"]
                            )

                            for name, value in pii_values.items():
                                if value is not None:
                                    old_pii[name] = value

                            for name, value in non_pii_values.items():
                                if value is not None:
                                    old_fields[name] = value

                            external_ref = (
                                old_fields.get(reference_field)
                                if reference_field
                                else existing_lead["external_ref"]
                            )

                            connection.execute(
                                """
                                UPDATE leads
                                SET pii_encrypted = ?,
                                    fields_json = ?,
                                    external_ref = ?,
                                    updated_at = ?
                                WHERE id = ?
                                """,
                                (
                                    _encrypt_json(old_pii, cipher),
                                    json.dumps(old_fields, ensure_ascii=False),
                                    external_ref or "",
                                    _now_utc(),
                                    existing_lead["id"],
                                ),
                            )

                            audit_status = "duplicate_merged"
                            summary["duplicates_merged"] += 1

                        else:
                            encrypted_last4 = cipher.encrypt(
                                phone[-4:].encode("utf-8")
                            ).decode("utf-8")

                            external_ref = (
                                non_pii_values.get(reference_field)
                                if reference_field
                                else ""
                            )

                            connection.execute(
                                """
                                INSERT INTO leads (
                                    workflow_id, phone_hash, phone_last4,
                                    batch_id, external_ref, pii_encrypted,
                                    fields_json, created_at, updated_at
                                )
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    workflow_id,
                                    hashed_phone,
                                    encrypted_last4,
                                    batch_id,
                                    external_ref or "",
                                    _encrypt_json(pii_values, cipher),
                                    json.dumps(
                                        non_pii_values,
                                        ensure_ascii=False,
                                    ),
                                    _now_utc(),
                                    _now_utc(),
                                ),
                            )

                            audit_status = "accepted"

                        connection.execute(
                            """
                            INSERT INTO lead_row_audit
                            (drop_path, workflow_id, batch_id,
                             row_number, status, reason)
                            VALUES (?, ?, ?, ?, ?, NULL)
                            """,
                            (
                                str(drop_path),
                                workflow_id,
                                batch_id,
                                row_number,
                                audit_status,
                            ),
                        )


        connection.execute(
            """
            INSERT INTO ingested_drops (drop_path, ingested_at)
            VALUES (?, ?)
            """,
            (str(drop_path), _now_utc()),
        )

    return summary
