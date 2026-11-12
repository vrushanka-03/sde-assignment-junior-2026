
from solution.core.normalizers import (
    normalize_header,
    normalize_string,
    normalize_value,
)


def build_header_mapping(csv_headers, schema):
    """
    Map CSV column names and aliases to canonical schema field names.

    Unknown columns are ignored.
    """
    mapping = {}

    for field in schema["fields"]:
        accepted_names = {
            normalize_header(field["name"]),
            *[
                normalize_header(alias)
                for alias in field.get("aliases", [])
            ],
        }

        for csv_header in csv_headers:
            normalized_header = normalize_header(csv_header)

            if (
                normalized_header in accepted_names
                and field["name"] not in mapping
            ):
                mapping[field["name"]] = csv_header
                break

    return mapping


def validate_row(raw_row, schema):
    """
    Normalize and validate one CSV row.

    Returns:
        normalized_fields: normalized values
        rejection_reason: None if valid, otherwise first failure
        warnings: invalid optional fields
    """
    headers = list(raw_row.keys())
    header_mapping = build_header_mapping(headers, schema)

    normalized_fields = {}
    warnings = []

    # Walk through fields in schema order.
    for field in schema["fields"]:
        field_name = field["name"]
        raw_header = header_mapping.get(field_name)

        raw_value = raw_row.get(raw_header) if raw_header else None
        cleaned_value = normalize_string(raw_value)

        # Required field missing.
        if field.get("required", False) and cleaned_value is None:
            return (
                normalized_fields,
                f"missing_required:{field_name}",
                warnings,
            )

        # Optional missing fields are not warnings.
        if cleaned_value is None:
            normalized_fields[field_name] = None
            continue

        try:
            normalized_value = normalize_value(cleaned_value, field)
            normalized_fields[field_name] = normalized_value

        except ValueError as exc:
            # Invalid phone numbers reject the entire row.
            if field["type"] == "phone":
                return normalized_fields, "invalid_phone", warnings

            # Other invalid values in optional fields become NULL.
            if not field.get("required", False):
                normalized_fields[field_name] = None
                warnings.append(field_name)
                continue

            # Defensive handling for future required field types.
            return (
                normalized_fields,
                f"invalid_{field['type']}",
                warnings,
            )

    return normalized_fields, None, warnings
