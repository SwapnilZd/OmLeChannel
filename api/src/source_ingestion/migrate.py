"""Idempotent migration runner for source-ingestion tables."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, text

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def run_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS _source_schema_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            applied = connection.execute(
                text("SELECT 1 FROM _source_schema_migrations WHERE name = :name"),
                {"name": path.name},
            ).scalar()
            if applied:
                continue
            statements = [
                statement.strip()
                for statement in path.read_text(encoding="utf-8").split(";")
                if statement.strip()
            ]
            for statement in statements:
                connection.exec_driver_sql(statement)
            connection.execute(
                text(
                    "INSERT INTO _source_schema_migrations (name) VALUES (:name)"
                ),
                {"name": path.name},
            )
