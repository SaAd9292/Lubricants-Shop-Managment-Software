"""Database bootstrap: create schema (if missing), migrate, seed defaults.

Call `init_database(db)` once at application startup, after the Database
object is constructed. Schema creation is idempotent (CREATE TABLE IF NOT
EXISTS), migrations are idempotent, and seeding is idempotent — so this is
safe to run on every launch.
"""
from __future__ import annotations

from pathlib import Path

from ..core.logging_config import get_logger
from .connection import Database
from .migrations import run_migrations
from .seed import seed_all

log = get_logger(__name__)

_SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def init_database(db: Database) -> None:
    schema_sql = _SCHEMA_FILE.read_text(encoding="utf-8")
    conn = db.connect()
    # executescript runs in its own transaction; pragmas already applied.
    conn.executescript(schema_sql)
    log.info("Schema ensured (%d statements)", schema_sql.count(";"))
    run_migrations(db)
    seed_all(db)
