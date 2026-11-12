
import sqlite3
from pathlib import Path

from solution.config import DB_PATH


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Create a SQLite connection with useful safety settings."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")

    return connection


def initialize_database(db_path: Path = DB_PATH) -> None:
    """Create all database tables if they do not already exist."""

    with get_connection(db_path) as connection:

        connection.executescript("""
        CREATE TABLE IF NOT EXISTS ingested_drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drop_path TEXT NOT NULL UNIQUE,
            ingested_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            phone_hash TEXT NOT NULL,
            phone_last4 TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            external_ref TEXT NOT NULL,
            pii_encrypted TEXT NOT NULL,
            fields_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            UNIQUE(workflow_id, phone_hash)
        );

        CREATE TABLE IF NOT EXISTS lead_row_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drop_path TEXT NOT NULL,
            workflow_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            status TEXT NOT NULL,
            reason TEXT,

            UNIQUE(drop_path, workflow_id, batch_id, row_number)
        );

        CREATE TABLE IF NOT EXISTS field_warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drop_path TEXT NOT NULL,
            workflow_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            field_name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            workflow_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            call_id TEXT,
            occurred_at_utc TEXT,
            occurred_at_ist TEXT,
            phone_hash TEXT,
            disposition_code TEXT,
            payload_json TEXT NOT NULL,
            ignored_reason TEXT,
            source_drop TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS event_links (
            event_id TEXT PRIMARY KEY,
            lead_id INTEGER,
            status TEXT NOT NULL,

            FOREIGN KEY(event_id)
                REFERENCES events(event_id),

            FOREIGN KEY(lead_id)
                REFERENCES leads(id)
        );

        CREATE TABLE IF NOT EXISTS event_line_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drop_path TEXT NOT NULL,
            file_path TEXT NOT NULL,
            line_number INTEGER NOT NULL,
            status TEXT NOT NULL,

            UNIQUE(drop_path, file_path, line_number)
        );

        CREATE INDEX IF NOT EXISTS idx_leads_workflow_phone
            ON leads(workflow_id, phone_hash);

        CREATE INDEX IF NOT EXISTS idx_events_call
            ON events(workflow_id, call_id);

        CREATE INDEX IF NOT EXISTS idx_events_phone
            ON events(workflow_id, phone_hash);

        CREATE INDEX IF NOT EXISTS idx_events_type
            ON events(event_type);

        CREATE INDEX IF NOT EXISTS idx_event_links_lead
            ON event_links(lead_id);
        """)
