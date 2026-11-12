
import json
from pathlib import Path

import pytest

from solution.core.validator import (
    build_header_mapping,
    validate_row,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "assignment-a-data" / "schemas"


def load_schema(workflow):
    path = SCHEMA_DIR / f"{workflow}.json"

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def test_header_alias_mapping():
    schema = load_schema("motor_renewal")

    mapping = build_header_mapping(
        [
            "Language",
            "Insured Name",
            "Policy No",
            "Mobile No",
            "Expiry Date",
            "Premium",
            "agent_notes",
        ],
        schema,
    )

    assert mapping["customer_name"] == "Insured Name"
    assert mapping["phone"] == "Mobile No"
    assert mapping["policy_number"] == "Policy No"
    assert "agent_notes" not in mapping


def test_valid_motor_renewal_row():
    schema = load_schema("motor_renewal")

    raw = {
        "Insured Name": " Ananya Rao ",
        "Mobile No": "9876543210",
        "Policy No": "MOT/2026/100402",
        "Expiry Date": "05/11/2026",
        "Premium": "INR 18,678.3",
        "Language": "EN",
        "agent_notes": "Ignore this column",
    }

    fields, reason, warnings = validate_row(raw, schema)

    assert reason is None
    assert warnings == []

    assert fields["customer_name"] == "Ananya Rao"
    assert fields["phone"] == "+919876543210"
    assert fields["policy_number"] == "MOT/2026/100402"
    assert fields["policy_expiry"] == "2026-11-05"
    assert fields["premium_amount"] == "18678.30"
    assert fields["preferred_language"] == "en"


def test_missing_required_field():
    schema = load_schema("motor_renewal")

    raw = {
        "Insured Name": "",
        "Mobile No": "9876543210",
        "Policy No": "MOT/2026/100402",
    }

    fields, reason, warnings = validate_row(raw, schema)

    assert reason == "missing_required:customer_name"


def test_invalid_phone_rejects_row():
    schema = load_schema("motor_renewal")

    raw = {
        "Insured Name": "Ananya Rao",
        "Mobile No": "1234567890",
        "Policy No": "MOT/2026/100402",
    }

    fields, reason, warnings = validate_row(raw, schema)

    assert reason == "invalid_phone"


def test_invalid_optional_date_creates_warning():
    schema = load_schema("motor_renewal")

    raw = {
        "Insured Name": "Ananya Rao",
        "Mobile No": "9876543210",
        "Policy No": "MOT/2026/100402",
        "Expiry Date": "2026-13-01",
    }

    fields, reason, warnings = validate_row(raw, schema)

    assert reason is None
    assert fields["policy_expiry"] is None
    assert warnings == ["policy_expiry"]


def test_missing_optional_field_is_not_warning():
    schema = load_schema("motor_renewal")

    raw = {
        "Insured Name": "Ananya Rao",
        "Mobile No": "9876543210",
        "Policy No": "MOT/2026/100402",
    }

    fields, reason, warnings = validate_row(raw, schema)

    assert reason is None
    assert fields["policy_expiry"] is None
    assert fields["premium_amount"] is None
    assert warnings == []


def test_policy_feedback_schema():
    schema = load_schema("policy_feedback")

    raw = {
        "Order ID": "ORD-700107",
        "Name": "Ishaan Banerjee",
        "Contact": "91-72328-54142",
        "Product": "Laptop",
        "Order Date": "21/09/2026",
        "Language": " hi ",
        "agent_notes": "Ignore",
    }

    fields, reason, warnings = validate_row(raw, schema)

    assert reason is None
    assert warnings == []
    assert fields["order_id"] == "ORD-700107"
    assert fields["phone"] == "+917232854142"
    assert fields["order_date"] == "2026-09-21"
    assert fields["preferred_language"] == "hi"
