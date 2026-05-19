from __future__ import annotations

"""
User-scoped data models.

All stored data (weight, nutrition, confirmed items, meal plans) is isolated per user
via user_id. Records are never shared between users; all queries must filter by
user_id from the authenticated user.
"""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class User(Base):
    """
    User account model. Passwords must be hashed (e.g. via bcrypt or passlib)
    before assignment to hashed_password; never store plain text passwords.
    """
    __tablename__ = "users"

    # Primary key.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Unique login identifier.
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # Unique email; used for auth and notifications.
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    # Store only the hash (e.g. bcrypt). Never assign plain text passwords.
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    # When the account was created (UTC).
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class WeightEntry(Base):
    """Weight logs. User-based isolation: always filter by user_id; never shared between users."""

    __tablename__ = "weight_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_weight_entries_user_date"),)


class WeightLog(Base):
    """
    Timestamped weight logs (multiple entries over time).
    User-based isolation: always filter by user_id; never shared between users.
    """

    __tablename__ = "weight_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    body_fat_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Date-only key used to prevent multiple entries for the same day per user.
    recorded_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, default=lambda: datetime.now(timezone.utc).date())
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    __table_args__ = (UniqueConstraint("user_id", "recorded_date", name="uq_weight_logs_user_recorded_date"),)


class NutritionSummaryEntry(Base):
    """Nutrition summaries per day. User-based isolation: always filter by user_id; never shared between users."""

    __tablename__ = "nutrition_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    calories: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    protein: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    carbs: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fats: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_nutrition_summaries_user_date"),)


class ConfirmedItemEntry(Base):
    """
    Stores confirmed food items that have been analyzed for nutrition.
    These items are automatically used for meal plan generation.
    User-based isolation: always filter by user_id; never shared between users.
    """
    __tablename__ = "confirmed_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String, nullable=True)


class MealPlanEntry(Base):
    """
    Stores generated weekly meal plans.
    Only one meal plan is stored per date (the latest generated plan) per user.
    User-based isolation: always filter by user_id; never shared between users.
    """
    __tablename__ = "meal_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    plan_data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string of the meal plan
    created_at: Mapped[date] = mapped_column(Date, nullable=False, default=lambda: date.today())

    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_meal_plans_user_date"),)


class ReceiptEntry(Base):
    """
    Stores uploaded receipt metadata.

    User-based isolation: always filter by user_id; never shared between users.
    Linking strategy (lightweight): receipt_date = upload_time.date(), which is used
    to associate confirmed items / nutrition summaries / meal plans for that day.
    """

    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    upload_time: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)


class UserProfile(Base):
    """
    Personal profile data for personalization.

    One-to-one with users (enforced via unique user_id).
    """

    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)

    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)

    activity_level: Mapped[str | None] = mapped_column(String(16), nullable=True)  # low/moderate/high
    diet_preference: Mapped[str | None] = mapped_column(String(16), nullable=True)  # veg/non-veg/vegan
    fitness_goal: Mapped[str | None] = mapped_column(String(24), nullable=True)  # lose_weight/maintain_weight/gain_weight

