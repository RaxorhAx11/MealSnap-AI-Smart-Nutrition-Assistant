from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Literal, Optional


Trend = Literal["decreasing", "increasing", "stable"]


@dataclass(frozen=True)
class TrendAnalysis:
    trend: Trend
    change_7_days: float
    message: str


@dataclass(frozen=True)
class BmiResult:
    bmi: float
    category: Literal["Underweight", "Normal", "Overweight", "Obese"]


@dataclass(frozen=True)
class GoalProgress:
    current_weight: float
    target_weight: float
    remaining_difference: float
    progress_percentage: int


def _round1(x: float) -> float:
    return float(round(float(x), 1))


def _clamp_int(x: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, int(round(x)))))


def analyze_trend_from_weights(
    weights_by_date: Iterable[tuple[date, float]],
    *,
    reference_end: Optional[date] = None,
) -> Optional[TrendAnalysis]:
    """
    Analyze the past 7 days ending at reference_end (or latest date in series).

    weights_by_date must be chronological (ascending) and contain unique dates.
    Returns None if there is not enough data (needs >=2 points in the 7-day window).
    """
    series = [(d, float(w)) for (d, w) in weights_by_date]
    if not series:
        return None

    end = reference_end or series[-1][0]
    window_start = end.fromordinal(end.toordinal() - 7)

    window = [(d, w) for (d, w) in series if window_start <= d <= end]
    if len(window) < 2:
        return None

    start_w = float(window[0][1])
    end_w = float(window[-1][1])
    diff = _round1(end_w - start_w)

    eps = 0.2
    if diff <= -eps:
        trend: Trend = "decreasing"
        message = f"You lost {abs(diff):.1f} kg in the last 7 days"
    elif diff >= eps:
        trend = "increasing"
        message = f"You gained {diff:.1f} kg in the last 7 days"
    else:
        trend = "stable"
        message = "Your weight is stable over the last 7 days"

    return TrendAnalysis(trend=trend, change_7_days=diff, message=message)


def calculate_bmi(*, weight_kg: float, height_cm: float) -> BmiResult:
    """
    BMI = weight / (height_m^2)
    """
    h_m = float(height_cm) / 100.0
    bmi = float(weight_kg) / (h_m * h_m)
    bmi = float(round(bmi, 1))

    if bmi < 18.5:
        category: BmiResult.category = "Underweight"  # type: ignore[attr-defined]
    elif bmi < 25:
        category = "Normal"
    elif bmi < 30:
        category = "Overweight"
    else:
        category = "Obese"

    return BmiResult(bmi=bmi, category=category)


def compute_goal_progress(
    *,
    current_weight: float,
    target_weight: float,
    start_weight: Optional[float] = None,
) -> GoalProgress:
    """
    remaining_difference uses target - current (matches spec example: 68-72 = -4).
    progress_percentage is computed when start_weight is available; otherwise 0.
    """
    remaining = float(target_weight) - float(current_weight)

    pct = 0
    if start_weight is not None:
        denom = float(target_weight) - float(start_weight)
        if abs(denom) > 1e-9:
            pct = _clamp_int(((float(current_weight) - float(start_weight)) / denom) * 100.0, 0, 100)

    return GoalProgress(
        current_weight=float(current_weight),
        target_weight=float(target_weight),
        remaining_difference=_round1(remaining),
        progress_percentage=int(pct),
    )


def build_weight_insights(
    *,
    trend: Optional[Trend],
    fitness_goal: Optional[str],
    avg_calories_7d: Optional[float],
    estimated_calorie_target: Optional[int],
) -> list[str]:
    """
    Lightweight, deterministic "AI-style" insights.
    Uses stored nutrition summaries (avg_calories_7d) and profile goal when available.
    """
    recs: list[str] = []

    if trend == "decreasing":
        recs.append("Your weight is decreasing steadily. Keep maintaining balanced calorie intake.")
    elif trend == "increasing":
        recs.append("Your weight is increasing. Review portions and liquid calories, and aim for consistent tracking.")
    elif trend == "stable":
        recs.append("Your weight is stable. Stay consistent and review weekly averages rather than single-day changes.")
    else:
        recs.append("Add at least 2 weight entries across a week to unlock trend insights.")

    if estimated_calorie_target is None:
        recs.append("Complete your profile (age, gender, height, activity level) to estimate a personalized calorie target.")
    elif avg_calories_7d is None:
        recs.append("Log nutrition regularly so we can relate calorie intake to weight changes.")
    else:
        delta = float(avg_calories_7d) - float(estimated_calorie_target)
        if delta > 150:
            recs.append("Your recent calories look above your estimated needs. Try a small reduction (100–250 kcal/day) and reassess weekly.")
        elif delta < -150:
            recs.append("Your recent calories look below your estimated needs. Ensure you’re eating enough to support energy and recovery.")
        else:
            recs.append("Your recent calories are close to your estimated needs. Focus on protein, sleep, and consistency.")

    recs.append("Increase protein intake to preserve muscle mass.")
    recs.append("Consider light exercise 3–4 times per week.")

    if fitness_goal == "lose_weight":
        recs.append("For fat loss, prioritize high-satiety foods (lean protein, veggies, whole grains) and track weekly averages.")
    elif fitness_goal == "gain_weight":
        recs.append("For weight gain, add a small calorie surplus and include strength training to support lean mass.")
    elif fitness_goal == "maintain_weight":
        recs.append("For maintenance, keep calories consistent and focus on routine and activity.")

    # Dedupe, preserve order.
    seen: set[str] = set()
    out: list[str] = []
    for r in recs:
        k = r.strip().lower()
        if k and k not in seen:
            out.append(r)
            seen.add(k)

    return out[:6]

