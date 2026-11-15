import os
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]


def connect():
    return psycopg.connect(os.environ.get("DATABASE_URL", "postgresql://username:password@localhost:5439/postgis"))


def migrate():
    with connect() as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS nasa_explorer")
        conn.execute("CREATE TABLE IF NOT EXISTS nasa_explorer.schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        for migration in sorted((ROOT / "migrations").glob("*.sql")):
            version = migration.stem
            if conn.execute("SELECT 1 FROM nasa_explorer.schema_migrations WHERE version=%s", (version,)).fetchone():
                continue
            conn.execute(migration.read_text())
            conn.execute("INSERT INTO nasa_explorer.schema_migrations(version) VALUES (%s) ON CONFLICT DO NOTHING", (version,))
