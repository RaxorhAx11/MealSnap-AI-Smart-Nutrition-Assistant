from __future__ import annotations

from typing import Dict, List, Literal, TypedDict


NutrientKey = Literal["protein", "carbohydrates", "fats"]
Status = Literal["low", "adequate", "high"]


class GapItem(TypedDict):
    nutrient: NutrientKey
    status: Status
    message: str


DEFAULT_TARGETS: Dict[NutrientKey, float] = {
    "protein": 75.0,
    "carbohydrates": 250.0,
    "fats": 70.0,
}


def _classify(value: float, target: float, tolerance: float = 0.15) -> Status:
    """
    Classify a nutrient value vs a daily target using a simple tolerance band.

    - low: value < target * (1 - tolerance)
    - high: value > target * (1 + tolerance)
    - adequate: otherwise
    """
    if value < target * (1.0 - tolerance):
        return "low"
    if value > target * (1.0 + tolerance):
        return "high"
    return "adequate"


def compute_nutrition_gaps_from_summary(
    *,
    protein_g: float,
    carbs_g: float,
    fats_g: float,
    targets: Dict[NutrientKey, float] | None = None,
    tolerance: float = 0.15,
) -> List[GapItem]:
    """
    Compute nutrition "gaps" from stored daily macro totals.

    Inputs are grams for protein/carbs/fats (calories is not used here).
    Returns structured items in the required format.
    """
    t = targets or DEFAULT_TARGETS

    items: List[GapItem] = []

    p_status = _classify(float(protein_g or 0.0), float(t["protein"]), tolerance=tolerance)
    c_status = _classify(float(carbs_g or 0.0), float(t["carbohydrates"]), tolerance=tolerance)
    f_status = _classify(float(fats_g or 0.0), float(t["fats"]), tolerance=tolerance)

    def msg(nutrient: NutrientKey, status: Status) -> str:
        pretty = "Protein" if nutrient == "protein" else "Carbohydrates" if nutrient == "carbohydrates" else "Fats"
        if status == "low":
            return f"{pretty} intake is below recommended level"
        if status == "high":
            return f"{pretty} intake is above recommended level"
        return f"{pretty} intake is within the recommended range"

    items.append({"nutrient": "protein", "status": p_status, "message": msg("protein", p_status)})
    items.append({"nutrient": "carbohydrates", "status": c_status, "message": msg("carbohydrates", c_status)})
    items.append({"nutrient": "fats", "status": f_status, "message": msg("fats", f_status)})

    return items

