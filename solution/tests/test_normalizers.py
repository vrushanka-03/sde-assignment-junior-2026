
import pytest

from solution.core.normalizers import (
    normalize_header,
    normalize_phone,
    normalize_date,
    normalize_decimal,
    normalize_enum,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("9876543210", "+919876543210"),
        ("(+91) 98765 43210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("09876543210", "+919876543210"),
    ],
)
def test_phone_normalization(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "1234567890",
        "987654321",
        "12345678901",
        "2026-13-01",
    ],
)
def test_invalid_values(raw):
    with pytest.raises(ValueError):
        if raw == "2026-13-01":
            normalize_date(raw)
        else:
            normalize_phone(raw)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-10-14", "2026-10-14"),
        ("14/10/2026", "2026-10-14"),
        ("14-10-2026", "2026-10-14"),
        ("14-Oct-2026", "2026-10-14"),
    ],
)
def test_date_normalization(raw, expected):
    assert normalize_date(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("₹18,500", "18500.00"),
        ("Rs. 24787", "24787.00"),
        ("INR 4737.14", "4737.14"),
        ("100.456", "100.46"),
    ],
)
def test_decimal_normalization(raw, expected):
    assert normalize_decimal(raw) == expected


def test_enum_normalization():
    assert normalize_enum(" HI ", ["en", "hi", "ta"]) == "hi"


def test_header_normalization():
    assert normalize_header("  Customer__Name  ") == "customer name"
