from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def get_database_url() -> str:
    """
    Read DATABASE_URL from environment.

    Local development:
        sqlite:///./mealsnap.db

    Production (Render PostgreSQL):
        postgresql://user:password@host:5432/dbname
    """

    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite:///./mealsnap.db"
    )

    # Render sometimes provides postgres://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://",
            "postgresql://",
            1,
        )

    return database_url


DATABASE_URL = get_database_url()

# SQLite requires special connection arguments.
engine_kwargs = {}

if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {
        "check_same_thread": False
    }

engine = create_engine(
    DATABASE_URL,
    **engine_kwargs
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    class_=Session
)

# User-scoped tables. In SQLite we may drop/recreate these
# to keep schema in sync.
_USER_SCOPED_TABLES = (
    "weight_entries",
    "weight_logs",
    "nutrition_summaries",
    "confirmed_items",
    "meal_plans",
    "receipts",
)


def _migrate_sqlite_user_scoped_schema() -> None:
    """
    SQLite-only migration helper.

    If user-scoped tables exist without user_id,
    drop them and recreate with the current schema.

    This migration is skipped entirely for PostgreSQL.
    """

    if not DATABASE_URL.startswith("sqlite"):
        return

    with engine.connect() as conn:

        try:
            result = conn.execute(
                text("PRAGMA table_info(weight_entries)")
            )

            rows = result.fetchall()

            has_user_id = any(
                str(row[1]) == "user_id"
                for row in rows
            )

            if not has_user_id:

                for table in _USER_SCOPED_TABLES:
                    conn.execute(
                        text(f"DROP TABLE IF EXISTS {table}")
                    )

                conn.commit()
                return

        except Exception:
            return

        try:
            result = conn.execute(
                text("PRAGMA table_info(weight_logs)")
            )

            rows = result.fetchall()

            if rows:

                cols = {
                    str(row[1])
                    for row in rows
                }

                required = {
                    "user_id",
                    "weight_kg",
                    "recorded_at",
                    "recorded_date",
                    "body_fat_percentage",
                    "note",
                }

                if not required.issubset(cols):
                    conn.execute(
                        text("DROP TABLE IF EXISTS weight_logs")
                    )
                    conn.commit()

        except Exception:
            return


def init_db() -> None:
    """
    Create all database tables.
    """

    from . import models  # noqa: F401

    _migrate_sqlite_user_scoped_schema()

    Base.metadata.create_all(
        bind=engine
    )


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI database dependency.
    """

    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()
