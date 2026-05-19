from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def _sqlite_url() -> str:
    # Default to a local SQLite file in the backend folder.
    # Can be overridden by setting DATABASE_URL, e.g.:
    # DATABASE_URL=sqlite:///./mealsnap.db
    return os.getenv("DATABASE_URL", "sqlite:///./mealsnap.db")


engine = create_engine(
    _sqlite_url(),
    connect_args={"check_same_thread": False},  # needed for SQLite + FastAPI threads
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)

# User-scoped tables. In SQLite we may drop/recreate these to keep schema in sync.
_USER_SCOPED_TABLES = ("weight_entries", "weight_logs", "nutrition_summaries", "confirmed_items", "meal_plans", "receipts")


def _migrate_sqlite_user_scoped_schema() -> None:
    """
    If user-scoped tables exist without user_id, drop them so create_all recreates
    them with the new schema. Preserves users table and auth data.
    """
    url = _sqlite_url()
    if "sqlite" not in url.lower():
        return
    with engine.connect() as conn:
        # 1) Legacy migration: tables existed without user_id -> drop/recreate.
        try:
            r = conn.execute(text("PRAGMA table_info(weight_entries)"))
            rows = r.fetchall()
            # SQLite PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
            has_user_id = any(str(row[1]) == "user_id" for row in rows)
            if not has_user_id:
                for table in _USER_SCOPED_TABLES:
                    conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
                conn.commit()
                return
        except Exception:
            # weight_entries missing; create_all will create it (and others).
            return

        # 2) Schema sync for weight_logs: ensure columns exist for the redesigned module.
        # If the table exists but is missing required columns, drop/recreate. This keeps
        # the app reliable without introducing a complex migration framework.
        try:
            r2 = conn.execute(text("PRAGMA table_info(weight_logs)"))
            rows2 = r2.fetchall()
            if rows2:
                cols = {str(row[1]) for row in rows2}
                required = {"user_id", "weight_kg", "recorded_at", "recorded_date", "body_fat_percentage", "note"}
                if not required.issubset(cols):
                    conn.execute(text("DROP TABLE IF EXISTS weight_logs"))
                    conn.commit()
        except Exception:
            return


def init_db() -> None:
    # Import models so they register with SQLAlchemy before create_all.
    from . import models  # noqa: F401

    _migrate_sqlite_user_scoped_schema()
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

