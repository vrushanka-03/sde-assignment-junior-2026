
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def normalize_header(value: str) -> str:
    """Normalize CSV headers for schema and alias matching."""
    value = value.strip().lower()
    return re.sub(r"[_\s]+", " ", value)


def normalize_string(value):
    """Trim string values. Empty strings become None."""
    if value is None:
        return None

    value = str(value).strip()
    return value if value else None


def normalize_phone(value):
    """
    Convert an Indian phone number into +91XXXXXXXXXX.

    Accepted:
    - 10-digit mobile numbers
    - 11 digits beginning with 0
    - 12 digits beginning with 91
    """
    if value is None:
        return None

    digits = re.sub(r"\D", "", str(value))

    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 10:
        raise ValueError("invalid_phone")

    if digits[0] not in "6789":
        raise ValueError("invalid_phone")

    return "+91" + digits


def normalize_date(value):
    """Parse supported date formats and return YYYY-MM-DD."""
    value = normalize_string(value)

    if value is None:
        return None

    formats = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d-%b-%Y",
    )

    for date_format in formats:
        try:
            parsed = datetime.strptime(value, date_format)
            return parsed.date().isoformat()
        except ValueError:
            continue

    raise ValueError("invalid_date")


def normalize_decimal(value):
    """Normalize Indian currency-like values to two decimal places."""
    value = normalize_string(value)

    if value is None:
        return None

    cleaned = re.sub(
        r"^(?:₹|rs\.?|inr)\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    cleaned = cleaned.replace(",", "").strip()

    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("invalid_decimal") from exc

    if not amount.is_finite() or amount < 0:
        raise ValueError("invalid_decimal")

    amount = amount.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    return format(amount, ".2f")


def normalize_enum(value, allowed_values):
    """Match enum values case-insensitively."""
    value = normalize_string(value)

    if value is None:
        return None

    allowed = {item.lower() for item in allowed_values}
    normalized = value.lower()

    if normalized not in allowed:
        raise ValueError("invalid_enum")

    return normalized


def normalize_value(value, field_schema):
    """Normalize a value according to its schema type."""
    field_type = field_schema["type"]

    if field_type == "string":
        return normalize_string(value)

    if field_type == "phone":
        return normalize_phone(value)

    if field_type == "date":
        return normalize_date(value)

    if field_type == "decimal":
        return normalize_decimal(value)

    if field_type == "enum":
        return normalize_enum(value, field_schema["values"])

    raise ValueError(f"unsupported_type:{field_type}")
