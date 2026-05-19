from __future__ import annotations

from typing import Dict, List, Literal, TypedDict

from services.nutrition_gap_service import GapItem


class SuggestionItem(TypedDict):
    food: str
    reason: str
    nutrition_benefit: str


GapKey = Literal["protein_low", "fiber_low", "healthy_fats_low"]


DEFAULT_GAP_FOOD_MAPPING: Dict[GapKey, List[SuggestionItem]] = {
    "protein_low": [
        {"food": "Eggs", "reason": "Low protein intake", "nutrition_benefit": "Provides high-quality protein"},
        {"food": "Lentils", "reason": "Low protein intake", "nutrition_benefit": "Rich in plant-based protein and fiber"},
        {"food": "Tofu", "reason": "Low protein intake", "nutrition_benefit": "Plant-based complete protein option"},
    ],
    "fiber_low": [
        {"food": "Oats", "reason": "Low fiber intake", "nutrition_benefit": "High in soluble fiber for gut health"},
        {"food": "Broccoli", "reason": "Low fiber intake", "nutrition_benefit": "Adds fiber and micronutrients"},
        {"food": "Spinach", "reason": "Low fiber intake", "nutrition_benefit": "Adds fiber, iron, and folate"},
    ],
    "healthy_fats_low": [
        {"food": "Almonds", "reason": "Low healthy fats intake", "nutrition_benefit": "Provides unsaturated fats and vitamin E"},
        {"food": "Avocado", "reason": "Low healthy fats intake", "nutrition_benefit": "Rich in monounsaturated fats and fiber"},
        {"food": "Olive Oil", "reason": "Low healthy fats intake", "nutrition_benefit": "Heart-healthy monounsaturated fats"},
    ],
}


def _dedupe_by_food(suggestions: List[SuggestionItem], limit: int = 8) -> List[SuggestionItem]:
    seen = set()
    out: List[SuggestionItem] = []
    for s in suggestions:
        key = str(s.get("food", "")).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def build_grocery_recommendations_from_gaps(
    gaps: List[GapItem],
    *,
    mapping: Dict[GapKey, List[SuggestionItem]] | None = None,
    limit: int = 8,
) -> List[SuggestionItem]:
    """
    Grocery Recommendation Engine.

    Input: nutrition gaps returned by nutrition_gap_service (nutrient + status).
    Output: structured purchase suggestions (food, reason, nutrition_benefit).

    Interpretation rules (kept simple and explainable):
    - protein == low -> protein_low mapping
    - carbohydrates == low -> treat as fiber_low (proxy for low complex carbs/fiber)
    - fats == low -> treat as healthy_fats_low
    """
    m = mapping or DEFAULT_GAP_FOOD_MAPPING

    wanted: List[GapKey] = []
    for g in gaps or []:
        if g.get("status") != "low":
            continue
        nutrient = g.get("nutrient")
        if nutrient == "protein":
            wanted.append("protein_low")
        elif nutrient == "carbohydrates":
            wanted.append("fiber_low")
        elif nutrient == "fats":
            wanted.append("healthy_fats_low")

    merged: List[SuggestionItem] = []
    for key in wanted:
        merged.extend(m.get(key, []))

    return _dedupe_by_food(merged, limit=limit)

