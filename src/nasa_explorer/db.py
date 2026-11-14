import os
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]


def connect():
    return psycopg.connect(os.environ.get("DATABASE_URL", "postgresql://username:password@localhost:5439/postgis"))


def migrate():
    migration = ROOT / "migrations/001_project_catalog.sql"
    with connect() as conn:
        conn.execute(migration.read_text())
        conn.execute("INSERT INTO nasa_explorer.schema_migrations(version) VALUES ('001_project_catalog') ON CONFLICT DO NOTHING")
