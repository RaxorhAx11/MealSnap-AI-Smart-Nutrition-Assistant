from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import delete

from db.database import Base, SessionLocal, init_db
from db.models import (
    ConfirmedItemEntry,
    MealPlanEntry,
    NutritionSummaryEntry,
    ReceiptEntry,
    User,
    UserProfile,
    WeightEntry,
    WeightLog,
)
from meal_plan.planner import generate_weekly_meal_plan_v3
from utils import hash_password


@dataclass(frozen=True)
class SeedUser:
    username: str
    email: str
    password: str
    profile: dict


def _repo_backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _remove_dirs(paths: Iterable[Path]) -> None:
    for p in paths:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)


def reset_database() -> None:
    """
    Delete ALL user-entered data, including accounts.

    This keeps the schema (tables) but removes rows from all ORM tables.
    """
    init_db()
    with SessionLocal() as db:
        # Delete children first (FKs), then parents.
        db.execute(delete(ReceiptEntry))
        db.execute(delete(MealPlanEntry))
        db.execute(delete(ConfirmedItemEntry))
        db.execute(delete(NutritionSummaryEntry))
        db.execute(delete(WeightLog))
        db.execute(delete(WeightEntry))
        db.execute(delete(UserProfile))
        db.execute(delete(User))
        db.commit()

        # For completeness, ensure any remaining rows in any mapped table are gone.
        # (This also protects against future tables being added without updating the list.)
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()


def reset_file_storage() -> None:
    """
    Remove any user-uploaded/processed receipt artifacts under backend working directory.
    """
    backend_dir = _repo_backend_dir()
    _remove_dirs(
        [
            backend_dir / "uploads",
            backend_dir / "processed",
        ]
    )


def seed_data() -> dict:
    """
    Seed realistic test data for exercising all modules.
    Returns a small summary describing what was created.
    """
    init_db()
    users: list[SeedUser] = [
        SeedUser(
            username="test_alex",
            email="alex.tester@example.com",
            password="TestPassword!123",
            profile={
                "age": 29,
                "gender": "male",
                "height_cm": 178.0,
                "current_weight_kg": 82.4,
                "target_weight_kg": 78.0,
                "activity_level": "moderate",
                "diet_preference": "non-veg",
                "fitness_goal": "lose_weight",
            },
        ),
        SeedUser(
            username="test_priya",
            email="priya.qa@example.com",
            password="TestPassword!123",
            profile={
                "age": 34,
                "gender": "female",
                "height_cm": 162.0,
                "current_weight_kg": 64.2,
                "target_weight_kg": 64.0,
                "activity_level": "low",
                "diet_preference": "veg",
                "fitness_goal": "maintain_weight",
            },
        ),
    ]

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=13)

    created = {"users": [], "days_seeded": 14}

    with SessionLocal() as db:
        for u in users:
            row = User(
                username=u.username,
                email=u.email,
                hashed_password=hash_password(u.password),
            )
            db.add(row)
            db.commit()
            db.refresh(row)

            profile = UserProfile(
                user_id=row.id,
                age=u.profile["age"],
                gender=u.profile["gender"],
                height_cm=u.profile["height_cm"],
                current_weight_kg=u.profile["current_weight_kg"],
                target_weight_kg=u.profile["target_weight_kg"],
                activity_level=u.profile["activity_level"],
                diet_preference=u.profile["diet_preference"],
                fitness_goal=u.profile["fitness_goal"],
            )
            db.add(profile)
            db.commit()

            # Seed weight logs (1 per day) with realistic trend.
            # Alex: gradual decrease; Priya: stable with small noise.
            base_w = float(u.profile["current_weight_kg"])
            for i in range(14):
                d = start + timedelta(days=i)
                if u.username == "test_alex":
                    w = base_w + (-(13 - i) * 0.1)  # ~1.3kg decrease over 2 weeks
                else:
                    w = base_w + (0.1 if i % 7 == 0 else 0.0) - (0.1 if i % 11 == 0 else 0.0)
                recorded_at = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc) + timedelta(
                    hours=8
                )
                db.add(
                    WeightLog(
                        user_id=row.id,
                        weight_kg=round(w, 1),
                        recorded_date=d,
                        recorded_at=recorded_at,
                        note="Seeded test data",
                        body_fat_percentage=22.0 if u.username == "test_alex" else 28.0,
                    )
                )
                # Legacy table also used by some charts/compat paths.
                db.add(
                    WeightEntry(
                        user_id=row.id,
                        date=d,
                        weight=round(w, 1),
                    )
                )

            # Seed nutrition summaries for 14 days.
            # Keep macros in plausible ranges and varied day-to-day.
            for i in range(14):
                d = start + timedelta(days=i)
                if u.username == "test_alex":
                    calories = 1950 + (50 if i % 5 == 0 else 0) - (75 if i % 6 == 0 else 0)
                    protein = 130 + (5 if i % 4 == 0 else 0)
                    carbs = 220 + (15 if i % 3 == 0 else -10)
                    fats = 60 + (5 if i % 7 == 0 else 0)
                else:
                    calories = 1750 + (60 if i % 4 == 0 else -30)
                    protein = 80 + (5 if i % 6 == 0 else 0)
                    carbs = 240 + (10 if i % 5 == 0 else -5)
                    fats = 55 + (3 if i % 7 == 0 else 0)
                db.add(
                    NutritionSummaryEntry(
                        user_id=row.id,
                        date=d,
                        calories=float(max(900, calories)),
                        protein=float(max(30, protein)),
                        carbs=float(max(50, carbs)),
                        fats=float(max(20, fats)),
                    )
                )

            # Seed a couple of receipt history events (metadata only).
            backend_dir = _repo_backend_dir()
            for offset_days in (0, 3, 9):
                dt = datetime.combine(today - timedelta(days=offset_days), datetime.min.time(), tzinfo=timezone.utc) + timedelta(
                    hours=18, minutes=22
                )
                file_path = str((backend_dir / "uploads" / str(row.id) / f"seed_receipt_{offset_days}.jpg").resolve())
                db.add(ReceiptEntry(user_id=row.id, upload_time=dt, file_path=file_path))

            # Seed confirmed items for today, so meal plan generation works without upload.
            confirmed_today = [
                {"name": "oats", "quantity": 80.0, "unit": "g"},
                {"name": "milk", "quantity": 250.0, "unit": "ml"},
                {"name": "eggs", "quantity": 2.0, "unit": "pcs"},
                {"name": "chicken breast", "quantity": 200.0, "unit": "g"},
                {"name": "spinach", "quantity": 150.0, "unit": "g"},
                {"name": "brown rice", "quantity": 180.0, "unit": "g"},
            ]
            if u.profile["diet_preference"] in ("veg", "vegan"):
                confirmed_today = [
                    {"name": "oats", "quantity": 80.0, "unit": "g"},
                    {"name": "milk", "quantity": 250.0, "unit": "ml"},
                    {"name": "lentils", "quantity": 200.0, "unit": "g"},
                    {"name": "tofu", "quantity": 180.0, "unit": "g"},
                    {"name": "spinach", "quantity": 150.0, "unit": "g"},
                    {"name": "brown rice", "quantity": 180.0, "unit": "g"},
                ]

            for it in confirmed_today:
                db.add(
                    ConfirmedItemEntry(
                        user_id=row.id,
                        date=today,
                        name=it["name"],
                        quantity=float(it["quantity"]),
                        unit=str(it["unit"]),
                    )
                )

            # Seed a stored meal plan for today (same structure as API returns).
            plan_days = generate_weekly_meal_plan_v3(
                confirmed_today,
                daily_calorie_target=2000,
                nutrition_gaps=[{"nutrient": "protein", "status": "low", "message": "low protein"}],
                days_count=3,
            )
            plan_dict = {"days": plan_days, "version": "v3-3days", "seeded": True}
            db.add(
                MealPlanEntry(
                    user_id=row.id,
                    date=today,
                    plan_data=json.dumps(plan_dict),
                    created_at=today,
                )
            )

            db.commit()
            created["users"].append(
                {
                    "id": row.id,
                    "username": u.username,
                    "email": u.email,
                    "password": u.password,
                }
            )

    # Create placeholder file structure (no binaries) so receipt-history file paths look sane.
    backend_dir = _repo_backend_dir()
    for info in created["users"]:
        (backend_dir / "uploads" / str(info["id"])).mkdir(parents=True, exist_ok=True)
        (backend_dir / "processed" / str(info["id"])).mkdir(parents=True, exist_ok=True)
        for offset_days in (0, 3, 9):
            placeholder = backend_dir / "uploads" / str(info["id"]) / f"seed_receipt_{offset_days}.jpg"
            if not placeholder.exists():
                placeholder.write_text("seed placeholder - replace with real receipt image if needed\n", encoding="utf-8")

    return created


def main() -> None:
    print("Resetting DB and file storage...")
    reset_database()
    reset_file_storage()
    print("Seeding data...")
    created = seed_data()
    print("Done.")
    print(json.dumps(created, indent=2))


if __name__ == "__main__":
    # Allow an opt-out for safety when running in other environments.
    if os.getenv("MEALSNAP_ALLOW_RESET", "1") != "1":
        raise SystemExit("Refusing to reset: set MEALSNAP_ALLOW_RESET=1 to proceed.")
    main()

