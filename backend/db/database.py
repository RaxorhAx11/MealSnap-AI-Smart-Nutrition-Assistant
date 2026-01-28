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

# User-scoped tables that were updated to include user_id. Dropped and recreated on migration.
_USER_SCOPED_TABLES = ("weight_entries", "nutrition_summaries", "confirmed_items", "meal_plans")


def _migrate_sqlite_user_scoped_schema() -> None:
    """
    If user-scoped tables exist without user_id, drop them so create_all recreates
    them with the new schema. Preserves users table and auth data.
    """
    url = _sqlite_url()
    if "sqlite" not in url.lower():
        return
    with engine.connect() as conn:
        try:
            r = conn.execute(text("PRAGMA table_info(weight_entries)"))
        except Exception:
            return  # table missing, create_all will create it
        rows = r.fetchall()
        # SQLite PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        has_user_id = any(str(row[1]) == "user_id" for row in rows)
        if has_user_id:
            return
        for table in _USER_SCOPED_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        conn.commit()


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

