import os
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv



BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
SCHEMA_DIR = BASE_DIR / "assignment-a-data" / "schemas"
DISPOSITIONS_FILE = BASE_DIR / "assignment-a-data"/ "schemas" / "dispositions.csv"

SOLUTION_DIR = BASE_DIR / "solution"
DB_PATH = BASE_DIR / "data" / "interaction_ledger.db"
REPORT_DIR = BASE_DIR / "reports"

def get_encryption_key() -> Fernet:
    """Return the encryption object used to protect PII."""
    key = os.getenv("APP_ENCRYPTION_KEY")

    if not key:
        raise RuntimeError(
            "APP_ENCRYPTION_KEY is missing. "
            "Configure it in your local .env file."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise RuntimeError("APP_ENCRYPTION_KEY is invalid.") from exc

def get_phone_hmac_key() -> bytes:
    """Return the separate secret used to create phone lookup hashes."""
    key = os.getenv("PHONE_HMAC_KEY")

    if not key or len(key.encode("utf-8")) < 32:
        raise RuntimeError(
            "PHONE_HMAC_KEY must be configured and contain "
            "at least 32 bytes."
        )

    return key.encode("utf-8")