from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple, Any, Literal, TypedDict
import zlib

from .rules import avoid_consecutive_repeats, main_food_label

# Import nutrition calculation utilities
try:
    from ..utils.food_matcher import get_food_nutrition
    from ..utils import convert_to_grams, calculate_food_nutrition
except ImportError:
    # Fallback for direct imports
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from utils.food_matcher import get_food_nutrition
    from utils import convert_to_grams, calculate_food_nutrition

try:
    # Optional: use the app's workflow gap analysis + recommendations when available
    from services.nutrition_gap_service import GapItem
    from services.recommendation_service import build_grocery_recommendations_from_gaps
except Exception:  # pragma: no cover (planner should still work standalone)
    GapItem = Any  # type: ignore
    build_grocery_recommendations_from_gaps = None  # type: ignore


MealName = Literal["breakfast", "lunch", "dinner"]
FoodCategory = Literal["grain", "fruit", "vegetable", "dairy", "protein", "fat", "unknown"]


class MealPlanWhy(TypedDict):
    food: str
    nutrition_benefit: str


class MealPlanPortion(TypedDict, total=False):
    quantity: float
    unit: str
    grams: float


class MealPlanMacros(TypedDict):
    calories: float
    protein: float
    carbs: float
    fats: float


class MealPlanItemV3(TypedDict, total=False):
    name: str
    category: FoodCategory
    portion: MealPlanPortion
    macros: MealPlanMacros
    why: MealPlanWhy
    source: Literal["purchased", "recommended"]


class WeeklyDayPlanV3(TypedDict, total=False):
    day: str
    breakfast: List[MealPlanItemV3]
    lunch: List[MealPlanItemV3]
    dinner: List[MealPlanItemV3]
    total_calories: float
    total_macros: MealPlanMacros
    status: str
    calorie_target: int
    decision_rules: List[str]


class WeeklyAddSuggestion(TypedDict):
    food: str
    nutrition_benefit: str

def _clean_list(values: Optional[Sequence[str]]) -> List[str]:
    if not values:
        return []
    out: List[str] = []
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            out.append(s)
    return out


def _rotate_pick(items: List[str], day_index: int) -> Optional[str]:
    """Pick an item by cycling through the list with day_index."""
    if not items:
        return None
    return items[day_index % len(items)]


def _stable_int(s: str) -> int:
    """
    Stable hash for deterministic ordering.
    Python's built-in hash() is salted per-process; do NOT use it in planners.
    """
    return int(zlib.crc32(str(s or "").encode("utf-8")) & 0xFFFFFFFF)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _keyword_score(text: str, keywords: Sequence[str]) -> int:
    t = text.lower()
    return sum(1 for kw in keywords if kw in t)


def _is_light_food(food: str) -> bool:
    # Used for "Breakfast: light foods" and "Dinner: lighter than lunch".
    light_keywords = [
        "salad",
        "soup",
        "fruit",
        "yogurt",
        "oat",
        "oats",
        "oatmeal",
        "porridge",
        "tea",
        "coffee",
        "milk",
        "grilled",
        "roasted",
        "steam",
        "steamed",
    ]
    heavy_keywords = [
        "pizza",
        "burger",
        "fried",
        "fries",
        "biryani",
        "bbq",
        "barbecue",
        "cream",
        "butter",
        "cheese",
    ]
    # Light if it contains more "light" signals than "heavy" signals.
    return _keyword_score(food, light_keywords) >= _keyword_score(food, heavy_keywords)


def estimate_item_calories(food: str, meal_type: str) -> int:
    """
    Beginner-friendly calorie estimate when quantities are unknown.

    This is a heuristic:
    - Start with a base per-meal value
    - Nudge up/down based on a few keywords
    """
    base_by_meal = {
        "breakfast": 300,
        "lunch": 650,
        "dinner": 500,
        "snack": 200,
    }
    base = int(base_by_meal.get(meal_type, 400))

    t = food.lower()

    # Bigger / heavier items
    if any(k in t for k in ["pizza", "burger", "biryani", "fried", "fries", "bbq", "barbecue"]):
        base += 150
    if any(k in t for k in ["cheese", "cream", "butter"]):
        base += 80

    # Lighter items
    if any(k in t for k in ["salad", "soup", "fruit", "yogurt"]):
        base -= 120

    # Keep within a reasonable range
    return max(120, min(base, 1100))


def split_daily_calories(total_daily_calories: int) -> Dict[str, int]:
    """
    Split a daily calorie total into meal targets using:
    - Breakfast: 30%
    - Lunch: 40%
    - Dinner: 30%

    Values are rounded to whole calories and are approximate.
    Lunch is computed as the remainder so the split sums exactly to the total.
    """
    total = int(round(total_daily_calories))
    breakfast = int(round(total * 0.30))
    dinner = int(round(total * 0.30))
    lunch = total - breakfast - dinner
    return {"breakfast": breakfast, "lunch": lunch, "dinner": dinner}


def _pick_best(
    candidates: List[str],
    day_index: int,
    prefer_light: bool = False,
) -> Optional[str]:
    """
    Pick a "best" candidate in a simple way:
    - Cycle order by day_index
    - If prefer_light=True, pick the first item (in rotated order) that looks light.
    """
    if not candidates:
        return None

    rotated = candidates[day_index % len(candidates) :] + candidates[: day_index % len(candidates)]
    if not prefer_light:
        return rotated[0]

    for item in rotated:
        if _is_light_food(item):
            return item
    return rotated[0]


def generate_weekly_meal_plan(
    categorized_foods: Dict[str, List[str]],
    *,
    include_snacks: bool = False,
    calorie_estimator: Optional[Callable[[str, str], int]] = None,
) -> Dict[str, object]:
    """
    Generate a 7-day meal plan from categorized foods.

    Inputs:
    - categorized_foods: dict with keys like "breakfast", "lunch", "dinner", "snack"
      and values as lists of food strings.

    What this does (simple rules):
    - Assigns breakfast, lunch, dinner for 7 days
    - Rotates through available foods to reduce repetition
    - Avoids repeating the same "main food" on consecutive days (using keyword labels)
    - Estimates daily calories with a simple heuristic (customizable)

    Returns:
        {
          "days": [
            {
              "day": 1,
              "breakfast": "oats",
              "lunch": "rice bowl",
              "dinner": "soup",
              "estimated_calories": 1450,
              "main_food_label": "rice",
            },
            ...
          ],
          "notes": {...}
        }
    """
    breakfast_items = _clean_list(categorized_foods.get("breakfast"))
    lunch_items = _clean_list(categorized_foods.get("lunch"))
    dinner_items = _clean_list(categorized_foods.get("dinner"))
    snack_items = _clean_list(categorized_foods.get("snack"))

    # Fallback pools if some categories are empty
    if not breakfast_items:
        breakfast_items = snack_items[:]
    if not dinner_items:
        # If no dinner list, reuse lunch foods but prefer lighter picks
        dinner_items = lunch_items[:]

    if calorie_estimator is None:
        calorie_estimator = estimate_item_calories

    plan_days: List[Dict[str, object]] = []
    prev_main: Optional[str] = None

    for day_index in range(7):
        # Breakfast: rotate, prefer light
        breakfast = _pick_best(breakfast_items, day_index, prefer_light=True)

        # Lunch: reorder to avoid repeating yesterday's main label, then rotate pick
        lunch_candidates = avoid_consecutive_repeats(lunch_items, prev_main)
        lunch = _pick_best(lunch_candidates, day_index, prefer_light=False)

        # Dinner: lighter than lunch where possible
        # Also apply the "no consecutive main repeat" against the previous day's main.
        dinner_candidates = avoid_consecutive_repeats(dinner_items, prev_main)
        dinner = _pick_best(dinner_candidates, day_index, prefer_light=True)

        # If dinner looks heavier than lunch, try to find a lighter dinner alternative.
        if dinner and lunch and (not _is_light_food(dinner)) and _is_light_food(lunch):
            dinner_alt = _pick_best(dinner_candidates, day_index + 1, prefer_light=True)
            if dinner_alt:
                dinner = dinner_alt

        # Optional snack: rotate through snacks
        snack = _rotate_pick(snack_items, day_index) if include_snacks else None

        # Compute main label using lunch as the "main meal" anchor
        day_main = main_food_label(lunch or "") or main_food_label(dinner or "") or None

        total = 0
        if breakfast:
            total += int(calorie_estimator(breakfast, "breakfast"))
        if lunch:
            total += int(calorie_estimator(lunch, "lunch"))
        if dinner:
            total += int(calorie_estimator(dinner, "dinner"))
        if include_snacks and snack:
            total += int(calorie_estimator(snack, "snack"))

        # Approximate: daily calories ≈ sum of meal calories (rounded)
        total = int(round(total))
        meal_calories = split_daily_calories(total)

        day_entry: Dict[str, object] = {
            "day": day_index + 1,
            "breakfast": breakfast,
            "lunch": lunch,
            "dinner": dinner,
            "estimated_calories": total,
            "estimated_meal_calories": meal_calories,
            "main_food_label": day_main,
        }
        if include_snacks:
            day_entry["snack"] = snack

        plan_days.append(day_entry)
        prev_main = day_main or prev_main

    return {
        "days": plan_days,
        "notes": {
            "rule_breakfast": "Prefer light foods.",
            "rule_lunch": "Main carbs + vegetables (most substantial meal).",
            "rule_dinner": "Lighter than lunch where possible.",
            "rule_variety": "Avoid repeating the same main food label on consecutive days.",
            "calorie_estimation": (
                "Approximate heuristic estimates (no quantities). Daily calories are calculated "
                "as the sum of meal estimates, then split into breakfast/lunch/dinner using "
                "30%/40%/30% and rounded."
            ),
        },
    }


def estimate_item_nutrition(food: str, default_quantity_grams: float = 150.0) -> Dict[str, float]:
    """
    Estimate nutrition values (calories, protein, carbs, fats) for a food item.
    
    Uses the nutrition database to get per-100g values, then estimates based on
    a default quantity. If food is not found in database, uses heuristic estimates.
    
    Args:
        food: Food item name
        default_quantity_grams: Default quantity in grams to use for estimation (default: 150g)
    
    Returns:
        Dictionary with nutrition values:
        {
            'calories': float,
            'protein': float,
            'carbs': float,
            'fats': float
        }
    """
    # Try to get nutrition data from database
    nutrition_data = get_food_nutrition(food, similarity_threshold=80.0)
    
    if nutrition_data:
        # Calculate nutrition based on default quantity
        multiplier = default_quantity_grams / 100.0
        return {
            'calories': round(nutrition_data['calories_per_100g'] * multiplier, 1),
            'protein': round(nutrition_data['protein_per_100g'] * multiplier, 1),
            'carbs': round(nutrition_data['carbs_per_100g'] * multiplier, 1),
            'fats': round(nutrition_data['fats_per_100g'] * multiplier, 1),
        }
    
    # Fallback: use heuristic calorie estimate and rough macro estimates
    # Estimate calories using the existing function
    base_calories = estimate_item_calories(food, "lunch")  # Use lunch as default
    
    # Rough macro estimates based on food type
    food_lower = food.lower()
    
    # Protein-rich foods
    if any(k in food_lower for k in ["chicken", "beef", "fish", "salmon", "tuna", "egg", "paneer", "tofu", "dal", "beans", "lentil"]):
        protein = base_calories * 0.25  # ~25% of calories from protein
        carbs = base_calories * 0.15   # ~15% from carbs
        fats = base_calories * 0.10    # ~10% from fats
    # Carb-rich foods
    elif any(k in food_lower for k in ["rice", "bread", "pasta", "noodle", "potato", "oats", "cereal"]):
        protein = base_calories * 0.10  # ~10% from protein
        carbs = base_calories * 0.60    # ~60% from carbs
        fats = base_calories * 0.10     # ~10% from fats
    # Dairy
    elif any(k in food_lower for k in ["milk", "yogurt", "cheese"]):
        protein = base_calories * 0.20  # ~20% from protein
        carbs = base_calories * 0.30    # ~30% from carbs
        fats = base_calories * 0.20     # ~20% from fats
    # Vegetables/Fruits
    elif any(k in food_lower for k in ["salad", "vegetable", "fruit", "apple", "banana", "orange", "broccoli", "carrot"]):
        protein = base_calories * 0.10  # ~10% from protein
        carbs = base_calories * 0.70    # ~70% from carbs
        fats = base_calories * 0.05     # ~5% from fats
    # Default (mixed)
    else:
        protein = base_calories * 0.15  # ~15% from protein
        carbs = base_calories * 0.50    # ~50% from carbs
        fats = base_calories * 0.15     # ~15% from fats
    
    # Convert to grams (protein/carbs: ~4 cal/g, fats: ~9 cal/g)
    protein_g = round(protein / 4.0, 1)
    carbs_g = round(carbs / 4.0, 1)
    fats_g = round(fats / 9.0, 1)
    
    return {
        'calories': round(base_calories, 1),
        'protein': protein_g,
        'carbs': carbs_g,
        'fats': fats_g,
    }


def _get_food_category(item: str) -> Optional[str]:
    """
    Get food category from nutrition database.
    Returns one of: 'grain', 'fruit', 'vegetable', 'dairy', 'protein', 'fat', or None.
    """
    nutrition_data = get_food_nutrition(item, similarity_threshold=80.0)
    if nutrition_data and 'category' in nutrition_data:
        return nutrition_data['category']
    return None


def _categorize_items_by_database(all_items: List[str]) -> Dict[str, List[str]]:
    """
    Categorize items using nutrition database categories.
    Returns dict with keys: 'grain', 'fruit', 'vegetable', 'dairy', 'protein', 'fat', 'unknown'
    """
    categories: Dict[str, List[str]] = {
        'grain': [],
        'fruit': [],
        'vegetable': [],
        'dairy': [],
        'protein': [],
        'fat': [],
        'unknown': []
    }
    
    for item in all_items:
        category = _get_food_category(item)
        if category and category in categories:
            categories[category].append(item)
        else:
            categories['unknown'].append(item)
    
    return categories


def _is_carb_item(item: str) -> bool:
    """Check if item is a carbohydrate-rich food (legacy function for backward compatibility)."""
    category = _get_food_category(item)
    return category == 'grain'


def _is_protein_item(item: str) -> bool:
    """Check if item is a protein-rich food (legacy function for backward compatibility)."""
    category = _get_food_category(item)
    return category == 'protein'


def _is_dairy_item(item: str) -> bool:
    """Check if item is a dairy product (legacy function for backward compatibility)."""
    category = _get_food_category(item)
    return category == 'dairy'


def _is_vegetable_item(item: str) -> bool:
    """Check if item is a vegetable (legacy function for backward compatibility)."""
    category = _get_food_category(item)
    return category == 'vegetable'


def _select_daily_items(
    all_items: List[str],
    day_index: int,
    items_per_day: int = 3,
    prev_items: Optional[List[str]] = None,
    category_counts: Optional[Dict[str, int]] = None
) -> List[str]:
    """
    Select items for a day with realistic combinations using food categories.
    Ensures at least one grain + one vegetable per day.
    Prioritizes categories that are low across the week.
    
    Args:
        all_items: List of all available food items
        day_index: Day index (0-6)
        items_per_day: Number of items to select per day (default: 2-3)
        prev_items: Items used in previous day (to avoid exact repetition)
        category_counts: Dict tracking category counts across days (for recommendations)
    
    Returns:
        List of selected item names for the day
    """
    if not all_items:
        return []
    
    # Categorize items using database categories
    categorized = _categorize_items_by_database(all_items)
    grains = categorized['grain']
    vegetables = categorized['vegetable']
    proteins = categorized['protein']
    dairy = categorized['dairy']
    fruits = categorized['fruit']
    fats = categorized['fat']
    others = categorized['unknown']
    
    # If prev_items provided, try to avoid exact repetition
    prev_set = set(prev_items) if prev_items else set()
    
    selected = []
    used_items = set()
    
    def _has_category_in_selected(category: str) -> bool:
        """Check if a category is already represented in selected items."""
        for item in selected:
            if _get_food_category(item) == category:
                return True
        return False
    
    # RULE 1: Ensure at least one grain + one vegetable per day
    # Priority: grain first, then vegetable
    
    # Step 1: Always include at least one grain
    if grains:
        item = _pick_rotated_item(grains, day_index, prev_set, used_items)
        if item:
            selected.append(item)
            used_items.add(item)
    
    # Step 2: Always include at least one vegetable
    if vegetables:
        item = _pick_rotated_item(vegetables, day_index, prev_set, used_items)
        if item:
            selected.append(item)
            used_items.add(item)
    
    # Step 3: Fill remaining slots based on category recommendations
    # If protein category is low, prioritize protein
    # If vegetable category is low, add more vegetables
    # Otherwise, rotate through protein/dairy/fruit
    
    if category_counts:
        # Find categories that are low (below average)
        total_days = 7
        avg_per_category = total_days * items_per_day / 6  # Rough average (6 main categories)
        
        low_categories = []
        for cat, count in category_counts.items():
            if cat in ['grain', 'vegetable', 'protein', 'dairy', 'fruit']:
                if count < avg_per_category * 0.7:  # 30% below average
                    low_categories.append((cat, count))
        
        # Sort by count (lowest first)
        low_categories.sort(key=lambda x: x[1])
        
        # Prioritize low categories
        for cat, _ in low_categories:
            if len(selected) >= items_per_day:
                break
            
            if cat == 'protein' and proteins and not _has_category_in_selected('protein'):
                item = _pick_rotated_item(proteins, day_index, prev_set, used_items)
                if item:
                    selected.append(item)
                    used_items.add(item)
            elif cat == 'vegetable' and vegetables and len([x for x in selected if _get_food_category(x) == 'vegetable']) < 2:
                item = _pick_rotated_item(vegetables, day_index, prev_set, used_items)
                if item:
                    selected.append(item)
                    used_items.add(item)
            elif cat == 'dairy' and dairy and not _has_category_in_selected('dairy'):
                item = _pick_rotated_item(dairy, day_index, prev_set, used_items)
                if item:
                    selected.append(item)
                    used_items.add(item)
            elif cat == 'fruit' and fruits and not _has_category_in_selected('fruit'):
                item = _pick_rotated_item(fruits, day_index, prev_set, used_items)
                if item:
                    selected.append(item)
                    used_items.add(item)
    
    # Step 4: Fill remaining slots with balanced rotation
    # Rotate through: protein, dairy, fruit, or others
    pattern = day_index % 4
    
    while len(selected) < items_per_day:
        candidates = None
        
        if pattern == 0 and proteins and not _has_category_in_selected('protein'):
            candidates = proteins
        elif pattern == 1 and dairy and not _has_category_in_selected('dairy'):
            candidates = dairy
        elif pattern == 2 and fruits and not _has_category_in_selected('fruit'):
            candidates = fruits
        elif pattern == 3 and proteins and not _has_category_in_selected('protein'):
            candidates = proteins
        else:
            # Fallback: use any available category
            if proteins and not _has_category_in_selected('protein'):
                candidates = proteins
            elif dairy and not _has_category_in_selected('dairy'):
                candidates = dairy
            elif fruits and not _has_category_in_selected('fruit'):
                candidates = fruits
            elif others:
                candidates = others
            else:
                # Use any remaining items
                remaining = [item for item in all_items if item not in used_items]
                if remaining:
                    candidates = remaining
                else:
                    break
        
        if candidates:
            item = _pick_rotated_item(candidates, day_index, prev_set, used_items)
            if item:
                selected.append(item)
                used_items.add(item)
            else:
                # If rotation fails, pick first available
                available = [x for x in candidates if x not in used_items]
                if available:
                    selected.append(available[0])
                    used_items.add(available[0])
                else:
                    break
        else:
            break
    
    return selected[:items_per_day]


def _pick_rotated_item(
    candidates: List[str],
    day_index: int,
    prev_set: set,
    used_items: set
) -> Optional[str]:
    """
    Pick an item from candidates, preferring items not in prev_set or used_items.
    Rotates through candidates based on day_index.
    """
    if not candidates:
        return None
    
    # Filter out already used items
    available = [item for item in candidates if item not in used_items]
    if not available:
        available = candidates  # Fallback to all candidates if all are used
    
    # Prefer items not used yesterday
    preferred = [item for item in available if item not in prev_set]
    if preferred:
        available = preferred
    
    # Rotate based on day_index
    start_idx = (day_index * 2) % len(available)
    return available[start_idx]


def generate_daily_meal_plan(
    available_items: List[str],
    *,
    daily_calorie_target: int = 2000,
    items_per_day: int = 3,
) -> List[Dict[str, object]]:
    """
    Generate a 7-day weekly meal plan using daily meal targets.
    
    Each day has ONE full-day meal plan (list of food items) instead of
    separate breakfast/lunch/dinner. Calculates total nutrition per day
    and compares against daily calorie target.
    
    Args:
        available_items: List of all available food item names
        daily_calorie_target: Daily calorie target in kcal (default: 2000)
        items_per_day: Number of items to include per day (default: 3)
    
    Returns:
        List of day objects with format:
        [
            {
                "day": "Monday",
                "daily_meal_plan": ["Milk", "Basmati Rice"],
                "total_nutrition_today": {
                    "calories": 1450,
                    "protein": 48,
                    "carbs": 210,
                    "fats": 32
                },
                "daily_target": {
                    "target_calories": 2000,
                    "status": "Deficit"
                }
            },
            ...
        ]
    """
    DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    # Clean and prepare items
    clean_items = _clean_list(available_items)
    
    if not clean_items:
        # Return empty plan for all days
        return [
            {
                "day": DAY_NAMES[i],
                "daily_meal_plan": [],
                "total_nutrition_today": {
                    "calories": 0,
                    "protein": 0,
                    "carbs": 0,
                    "fats": 0
                },
                "daily_target": {
                    "target_calories": daily_calorie_target,
                    "status": "N/A"
                }
            }
            for i in range(7)
        ]
    
    plan_days: List[Dict[str, object]] = []
    prev_day_items: Optional[List[str]] = None
    
    # Track category counts across all days for recommendations
    category_counts: Dict[str, int] = {
        'grain': 0,
        'fruit': 0,
        'vegetable': 0,
        'dairy': 0,
        'protein': 0,
        'fat': 0
    }
    
    # First pass: collect category counts from previous days
    # (This will be updated as we go, but helps with later days)
    
    for day_index in range(7):
        # Select items for this day
        day_items = _select_daily_items(
            clean_items,
            day_index,
            items_per_day=items_per_day,
            prev_items=prev_day_items,
            category_counts=category_counts if day_index > 0 else None  # Use counts after first day
        )
        
        # Update category counts
        for item in day_items:
            category = _get_food_category(item)
            if category and category in category_counts:
                category_counts[category] += 1
        
        # Calculate total nutrition for the day
        total_calories = 0.0
        total_protein = 0.0
        total_carbs = 0.0
        total_fats = 0.0
        
        for item in day_items:
            nutrition = estimate_item_nutrition(item)
            total_calories += nutrition['calories']
            total_protein += nutrition['protein']
            total_carbs += nutrition['carbs']
            total_fats += nutrition['fats']
        
        # Round totals
        total_calories = round(total_calories, 1)
        total_protein = round(total_protein, 1)
        total_carbs = round(total_carbs, 1)
        total_fats = round(total_fats, 1)
        
        # Determine status compared to target
        # Met: within ±10% of target
        # Deficit: below target - 10%
        # Excess: above target + 10%
        target_lower = daily_calorie_target * 0.9
        target_upper = daily_calorie_target * 1.1
        
        if total_calories < target_lower:
            status = "Deficit"
        elif total_calories > target_upper:
            status = "Excess"
        else:
            status = "Met"
        
        # Get categories for selected items
        day_categories = []
        for item in day_items:
            category = _get_food_category(item)
            if category:
                day_categories.append(category)
        
        # Generate recommendations based on category balance
        recommendations = []
        total_days = 7
        avg_per_category = total_days * items_per_day / 6  # Rough average
        
        # Check if vegetable category is low
        veg_count = category_counts.get('vegetable', 0)
        if veg_count < avg_per_category * 0.7:
            recommendations.append("Consider adding more vegetables for balanced nutrition")
        
        # Check if protein category is low
        protein_count = category_counts.get('protein', 0)
        if protein_count < avg_per_category * 0.7:
            recommendations.append("Consider adding more protein foods (chicken, dal, eggs, etc.)")
        
        # Check if grain category is low
        grain_count = category_counts.get('grain', 0)
        if grain_count < avg_per_category * 0.7:
            recommendations.append("Consider adding more grains (rice, bread, roti, etc.)")
        
        day_entry: Dict[str, object] = {
            "day": DAY_NAMES[day_index],
            "daily_meal_plan": day_items,
            "categories": day_categories,
            "total_nutrition_today": {
                "calories": total_calories,
                "protein": total_protein,
                "carbs": total_carbs,
                "fats": total_fats
            },
            "daily_target": {
                "target_calories": daily_calorie_target,
                "status": status
            }
        }
        
        # Add recommendations on the last day
        if day_index == 6 and recommendations:
            day_entry["recommendations"] = recommendations
        
        plan_days.append(day_entry)
        prev_day_items = day_items
    
    return plan_days


def _estimate_calories_for_item_from_confirmed(
    *,
    name: str,
    quantity: Optional[float],
    unit: Optional[str],
) -> float:
    """
    Estimate calories for an item using confirmed receipt quantity/unit when available.
    Falls back to estimate_item_nutrition when quantity/unit can't be converted.
    """
    clean_name = str(name or "").strip()
    if not clean_name:
        return 0.0

    try:
        if quantity is None or unit is None:
            return float(estimate_item_nutrition(clean_name).get("calories", 0.0))
        q = float(quantity)
        u = str(unit).strip()
        if not u:
            return float(estimate_item_nutrition(clean_name).get("calories", 0.0))

        # Convert to grams using existing nutrition utility (handles pcs with food_name)
        if u.lower() in ["pc", "pcs", "piece", "pieces"]:
            qty_str = f"{q} {u}"
        else:
            qty_str = f"{q}{u}"
        grams = convert_to_grams(qty_str, food_name=clean_name)
        if grams is None:
            return float(estimate_item_nutrition(clean_name).get("calories", 0.0))

        # Use existing nutrition calculation logic to compute calories for the gram amount.
        calc = calculate_food_nutrition(
            food_name=clean_name,
            quantity_grams=float(grams),
            similarity_threshold=80.0,
            round_decimals=1,
        )
        if calc and "calories" in calc:
            return float(calc["calories"] or 0.0)
    except Exception:
        pass

    return float(estimate_item_nutrition(clean_name).get("calories", 0.0))


def generate_daily_meal_plan_v2(
    confirmed_items: List[Dict[str, object]],
    *,
    daily_calorie_target: int = 2000,
    items_per_day: int = 3,
    nutrition_gaps: Optional[List[GapItem]] = None,
) -> List[Dict[str, object]]:
    """
    Improved 7-day plan generator.

    Goals:
    - Prefer foods the user already purchased (confirmed_items)
    - Ensure variety across 7 days (avoid repeating same items day-to-day; balance usage counts)
    - Consider nutrition gaps when choosing foods (bias categories for "low" gaps)
    - Estimate daily calories and compare with target (2000 kcal)

    Output is compatible with existing UI shape, but also includes:
      - total_calories
      - target_status
    """
    DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    # Normalize confirmed items into a name->best-entry map (prefer entries with quantity+unit).
    by_name: Dict[str, Dict[str, object]] = {}
    for it in confirmed_items or []:
        raw_name = str(it.get("name") or "").strip()
        if not raw_name:
            continue
        q = it.get("quantity")
        u = it.get("unit")
        existing = by_name.get(raw_name)
        if existing is None:
            by_name[raw_name] = {"name": raw_name, "quantity": q, "unit": u}
        else:
            # Prefer the one that has both quantity and unit
            if (existing.get("quantity") is None or existing.get("unit") in [None, ""]) and (q is not None and u not in [None, ""]):
                by_name[raw_name] = {"name": raw_name, "quantity": q, "unit": u}

    purchased_names = list(by_name.keys())
    purchased_names = _clean_list(purchased_names)
    if not purchased_names:
        return [
            {
                "day": DAY_NAMES[i],
                "daily_meal_plan": [],
                "total_calories": 0,
                "target_status": "N/A",
                "total_nutrition_today": {"calories": 0, "protein": 0, "carbs": 0, "fats": 0},
                "daily_target": {"target_calories": daily_calorie_target, "status": "N/A"},
            }
            for i in range(7)
        ]

    # Determine "needed" categories from low gaps (simple mapping).
    needed_categories: List[str] = []
    for g in nutrition_gaps or []:
        if not isinstance(g, dict):
            continue
        if g.get("status") != "low":
            continue
        n = g.get("nutrient")
        if n == "protein":
            needed_categories.append("protein")
        elif n == "carbohydrates":
            needed_categories.append("grain")
        elif n == "fats":
            needed_categories.append("fat")

    # Optional non-purchased boosters from recommendation engine (used only when needed category is missing).
    booster_items: List[str] = []
    if needed_categories and build_grocery_recommendations_from_gaps:
        try:
            recs = build_grocery_recommendations_from_gaps(list(nutrition_gaps or []))
            booster_items = _clean_list([r.get("food") for r in recs if isinstance(r, dict)])
        except Exception:
            booster_items = []

    categorized = _categorize_items_by_database(purchased_names)
    usage: Dict[str, int] = {n: 0 for n in purchased_names}
    prev_day_set: set[str] = set()
    plan_days: List[Dict[str, object]] = []

    def pick_from(pool: List[str], day_index: int) -> Optional[str]:
        """Pick with variety bias: lowest usage first, avoid yesterday when possible."""
        pool = _clean_list(pool)
        if not pool:
            return None
        # Avoid yesterday if possible
        candidates = [x for x in pool if x not in prev_day_set] or pool
        # Sort by usage then rotate to spread (deterministic; do not use Python hash()).
        candidates.sort(key=lambda x: (usage.get(x, 0), (day_index + _stable_int(x)) % 97))
        for c in candidates:
            return c
        return candidates[0]

    for day_index in range(7):
        day_items: List[str] = []
        chosen_set: set[str] = set()

        # 1) Satisfy gap-driven categories if possible (from purchased foods first).
        for cat in needed_categories:
            if len(day_items) >= items_per_day:
                break
            pool = categorized.get(cat, [])
            choice = pick_from(pool, day_index)
            if choice and choice not in chosen_set:
                day_items.append(choice)
                chosen_set.add(choice)

        # 2) Ensure baseline balance: at least one grain + one vegetable when available.
        if len(day_items) < items_per_day and categorized.get("grain"):
            if not any(_get_food_category(x) == "grain" for x in day_items):
                choice = pick_from(categorized["grain"], day_index)
                if choice and choice not in chosen_set:
                    day_items.append(choice)
                    chosen_set.add(choice)
        if len(day_items) < items_per_day and categorized.get("vegetable"):
            if not any(_get_food_category(x) == "vegetable" for x in day_items):
                choice = pick_from(categorized["vegetable"], day_index)
                if choice and choice not in chosen_set:
                    day_items.append(choice)
                    chosen_set.add(choice)

        # 3) Fill remaining slots with least-used purchased items (variety).
        if len(day_items) < items_per_day:
            remaining = [x for x in purchased_names if x not in chosen_set]
            remaining.sort(key=lambda x: (usage.get(x, 0), (day_index + _stable_int(x)) % 97))
            for x in remaining:
                if len(day_items) >= items_per_day:
                    break
                # mild avoidance of exact repetition across consecutive days
                if x in prev_day_set and len(remaining) > items_per_day:
                    continue
                day_items.append(x)
                chosen_set.add(x)

        # 4) If we still can’t satisfy a needed category, add a booster suggestion (non-purchased) as last resort.
        if len(day_items) < items_per_day and booster_items:
            for b in booster_items:
                if len(day_items) >= items_per_day:
                    break
                if b not in chosen_set:
                    day_items.append(b)
                    chosen_set.add(b)

        # Update usage counts only for purchased items.
        for x in day_items:
            if x in usage:
                usage[x] += 1

        # Calories estimate: use confirmed quantities when possible.
        total_calories = 0.0
        for x in day_items:
            entry = by_name.get(x) or {"name": x, "quantity": None, "unit": None}
            total_calories += _estimate_calories_for_item_from_confirmed(
                name=str(entry.get("name") or x),
                quantity=entry.get("quantity") if isinstance(entry.get("quantity"), (int, float)) else None,
                unit=str(entry.get("unit")) if entry.get("unit") not in [None, ""] else None,
            )
        total_calories = float(round(total_calories, 1))

        # Target status (±10% band, matching existing behavior).
        target_lower = daily_calorie_target * 0.9
        target_upper = daily_calorie_target * 1.1
        if total_calories < target_lower:
            status = "Deficit"
        elif total_calories > target_upper:
            status = "Excess"
        else:
            status = "Met"

        plan_days.append(
            {
                "day": DAY_NAMES[day_index],
                "daily_meal_plan": day_items,
                "total_calories": total_calories,
                "target_status": status,
                # Backward compatible fields used by the current UI:
                "total_nutrition_today": {
                    "calories": total_calories,
                    "protein": 0,
                    "carbs": 0,
                    "fats": 0,
                },
                "daily_target": {"target_calories": daily_calorie_target, "status": status},
            }
        )

        prev_day_set = set(day_items)

    return plan_days


def _gap_status_by_nutrient(nutrition_gaps: Optional[List[GapItem]]) -> Dict[str, str]:
    """
    Normalize gap items to a simple nutrient->status mapping.
    Input shape: [{nutrient: "protein"|"carbohydrates"|"fats", status: "low"|"adequate"|"high", message: "..."}]
    """
    out: Dict[str, str] = {}
    for g in nutrition_gaps or []:
        if not isinstance(g, dict):
            continue
        nutrient = str(g.get("nutrient") or "").strip().lower()
        status = str(g.get("status") or "").strip().lower()
        if nutrient and status:
            out[nutrient] = status
    return out


def _portion_preset(item_name: str, category: FoodCategory, meal: MealName) -> Tuple[float, str]:
    """
    Deterministic portion presets (consumption), not purchase quantities.

    Decision rules:
    - Breakfast: lighter portions than lunch.
    - Lunch: largest meal; staple carbs are larger here.
    - Dinner: moderate; carbs smaller than lunch.
    - Units are chosen for readability: ml for common liquids, pcs for common "piece" foods, else g.
    """
    n = (item_name or "").strip().lower()

    # Units that humans typically track as pieces.
    if any(k in n for k in ["egg", "eggs"]):
        return (2.0 if meal == "breakfast" else 3.0 if meal == "lunch" else 2.0, "pcs")
    if any(k in n for k in ["bread", "toast"]):
        return (2.0, "pcs")
    if any(k in n for k in ["roti", "naan", "wrap", "tortilla"]):
        return (2.0 if meal == "lunch" else 1.0, "pcs")
    if category == "fruit" and any(k in n for k in ["banana", "apple", "orange"]):
        return (1.0, "pcs")

    # Liquids.
    if category == "dairy" and any(k in n for k in ["milk", "buttermilk", "lassi"]):
        return (250.0 if meal == "breakfast" else 200.0 if meal == "dinner" else 200.0, "ml")

    # Default gram-based presets by category + meal.
    if category == "grain":
        return (70.0 if meal == "breakfast" else 180.0 if meal == "lunch" else 120.0, "g")
    if category == "protein":
        return (100.0 if meal == "breakfast" else 150.0 if meal == "lunch" else 130.0, "g")
    if category == "vegetable":
        return (80.0 if meal == "breakfast" else 120.0 if meal == "lunch" else 150.0, "g")
    if category == "fat":
        return (15.0, "g")
    if category == "dairy":
        return (150.0, "g")
    if category == "fruit":
        return (120.0, "g")

    return (120.0 if meal == "lunch" else 80.0, "g")


def _portion_to_grams(*, name: str, quantity: float, unit: str) -> Optional[float]:
    """
    Convert a portion (quantity+unit) to grams, using existing converter.
    For ml, we assume 1ml≈1g (already implemented in convert_to_grams).
    """
    try:
        q = float(quantity)
        u = str(unit or "").strip()
        if not u:
            return None
        qty_str = f"{q} {u}" if u.lower() in ["pc", "pcs", "piece", "pieces"] else f"{q}{u}"
        grams = convert_to_grams(qty_str, food_name=str(name or "").strip())
        return float(grams) if grams is not None else None
    except Exception:
        return None


def _calc_macros_for_portion(*, name: str, grams: float) -> MealPlanMacros:
    calc = calculate_food_nutrition(
        food_name=str(name or "").strip(),
        quantity_grams=float(grams),
        similarity_threshold=80.0,
        round_decimals=1,
    )
    if isinstance(calc, dict) and calc.get("calories") is not None:
        return {
            "calories": float(calc.get("calories") or 0.0),
            "protein": float(calc.get("protein") or 0.0),
            "carbs": float(calc.get("carbs") or 0.0),
            "fats": float(calc.get("fats") or 0.0),
        }
    est = estimate_item_nutrition(str(name or "").strip(), default_quantity_grams=float(grams))
    return {
        "calories": float(est.get("calories") or 0.0),
        "protein": float(est.get("protein") or 0.0),
        "carbs": float(est.get("carbs") or 0.0),
        "fats": float(est.get("fats") or 0.0),
    }


def _why_for_item(*, name: str, category: FoodCategory, gap_status: Dict[str, str], source: str) -> MealPlanWhy:
    """
    Deterministic "why" messages (benefit only).
    """
    clean = str(name or "").strip()

    if gap_status.get("protein") == "low" and category == "protein":
        return {"food": clean, "nutrition_benefit": "Helps increase protein for better satiety and muscle support."}
    if gap_status.get("carbohydrates") == "low" and category in ("grain", "fruit"):
        return {"food": clean, "nutrition_benefit": "Adds energy and (often) fiber for steady fuel."}
    if gap_status.get("fats") == "low" and category == "fat":
        return {"food": clean, "nutrition_benefit": "Supports hormone health and absorption of fat‑soluble vitamins."}

    if category == "vegetable":
        return {"food": clean, "nutrition_benefit": "Adds fiber and micronutrients for better digestion and balance."}
    if category == "protein":
        return {"food": clean, "nutrition_benefit": "Adds protein to support satiety and muscle maintenance."}
    if category == "grain":
        return {"food": clean, "nutrition_benefit": "Provides carbohydrates for energy, especially around your main meals."}
    if category == "dairy":
        return {"food": clean, "nutrition_benefit": "Provides protein and calcium for daily nutrition."}
    if category == "fruit":
        return {"food": clean, "nutrition_benefit": "Adds vitamins and fiber for overall health."}
    if category == "fat":
        return {"food": clean, "nutrition_benefit": "Adds healthy fats to round out the meal."}
    return {"food": clean, "nutrition_benefit": "Included for variety and meal completeness."}


def _status_vs_target(total_calories: float, target: int) -> str:
    lo = float(target) * 0.9
    hi = float(target) * 1.1
    if total_calories < lo:
        return "Deficit"
    if total_calories > hi:
        return "Excess"
    return "Near Target"


def generate_weekly_meal_plan_v3(
    confirmed_items: List[Dict[str, object]],
    *,
    daily_calorie_target: int,
    nutrition_gaps: Optional[List[GapItem]] = None,
    days_count: int = 3,
) -> List[WeeklyDayPlanV3]:
    """
    Deterministic, rule-based weekly meal plan (Mon–Sun).

    Integrates:
    - confirmed receipt items (purchased-first)
    - nutrition gap analysis (bias selection)
    - user's daily calorie target (portion sizing)
    """
    DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    days_count = int(days_count or 3)
    days_count = max(1, min(days_count, len(DAY_NAMES)))
    # Use deterministic labels requested by UI: day-1, day-2, day-3 (etc).
    day_names = [f"day-{i + 1}" for i in range(days_count)]
    target = int(daily_calorie_target or 2000)
    meal_targets = split_daily_calories(target)
    gap_status = _gap_status_by_nutrient(nutrition_gaps)

    purchased_names: List[str] = []
    for it in confirmed_items or []:
        name = str(it.get("name") or "").strip()
        if name:
            purchased_names.append(name)

    purchased_names = _clean_list(purchased_names)
    purchased_names = list(dict.fromkeys(purchased_names))  # stable dedupe preserving order

    categorized = _categorize_items_by_database(purchased_names)

    booster: List[Dict[str, str]] = []
    if build_grocery_recommendations_from_gaps and nutrition_gaps:
        try:
            booster = [b for b in build_grocery_recommendations_from_gaps(list(nutrition_gaps)) if isinstance(b, dict)]
        except Exception:
            booster = []

    # Suggestions (what to add + what you get). Keep stable, simple, and de-duped.
    suggested_additions: List[WeeklyAddSuggestion] = []
    try:
        seen = set()
        for b in booster:
            food = str(b.get("food") or "").strip()
            benefit = str(b.get("nutrition_benefit") or "").strip()
            key = food.lower()
            if not food or not benefit or key in seen:
                continue
            suggested_additions.append({"food": food, "nutrition_benefit": benefit})
            seen.add(key)
            if len(suggested_additions) >= 6:
                break
    except Exception:
        suggested_additions = []

    def pool_for(cat: FoodCategory) -> List[str]:
        return _clean_list(categorized.get(cat, []))

    usage: Dict[str, int] = {n: 0 for n in purchased_names}
    last_main: Dict[MealName, Optional[str]] = {"breakfast": None, "lunch": None, "dinner": None}

    def pick_item(*, pool: List[str], day_index: int, meal: MealName, avoid_set: set[str]) -> Optional[str]:
        items = [x for x in _clean_list(pool) if x not in avoid_set] or _clean_list(pool)
        if not items:
            return None
        prev_label = last_main.get(meal)
        items = avoid_consecutive_repeats(items, prev_label) if prev_label else items
        items.sort(key=lambda x: (usage.get(x, 0), (_stable_int(x) + day_index * 17) % 997))
        return items[0] if items else None

    def add_booster(items: List[MealPlanItemV3], needed: FoodCategory, meal: MealName) -> None:
        if not booster:
            return
        for b in booster:
            food = str(b.get("food") or "").strip()
            if not food:
                continue
            cat = _get_food_category(food) or "unknown"
            if cat != needed:
                continue
            q, u = _portion_preset(food, cat, meal)
            grams = _portion_to_grams(name=food, quantity=q, unit=u) or 0.0
            macros = _calc_macros_for_portion(name=food, grams=grams) if grams else {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fats": 0.0}
            items.append(
                {
                    "name": food,
                    "category": cat,
                    "portion": {"quantity": float(q), "unit": str(u), "grams": float(round(grams, 1)) if grams else 0.0},
                    "macros": macros,
                    "why": {
                        "food": food,
                        "nutrition_benefit": str(b.get("nutrition_benefit") or "Helps improve overall balance."),
                    },
                    "source": "recommended",
                }
            )
            return

    def meal_total(items: List[MealPlanItemV3]) -> float:
        return float(round(sum(float(i.get("macros", {}).get("calories") or 0.0) for i in items), 1))

    def downscale_grains(meal_items: List[MealPlanItemV3], target_kcal: int) -> None:
        for _ in range(6):
            if meal_total(meal_items) <= float(target_kcal) * 1.05:
                return
            idx = next((i for i, it in enumerate(meal_items) if it.get("category") == "grain"), None)
            if idx is None:
                return
            it = meal_items[idx]
            portion = it.get("portion") or {}
            q = float(portion.get("quantity") or 0.0)
            u = str(portion.get("unit") or "g")
            new_q = _clamp(q * 0.85, 30.0 if u.lower().startswith("g") else 1.0, q)
            if abs(new_q - q) < 0.01:
                return
            grams = _portion_to_grams(name=str(it.get("name") or ""), quantity=new_q, unit=u) or 0.0
            it["portion"] = {"quantity": float(round(new_q, 1)), "unit": u, "grams": float(round(grams, 1)) if grams else 0.0}
            it["macros"] = _calc_macros_for_portion(name=str(it.get("name") or ""), grams=grams) if grams else {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fats": 0.0}

    def build_meal(meal: MealName, day_index: int, used_today: set[str]) -> List[MealPlanItemV3]:
        want_protein = gap_status.get("protein") == "low"
        want_carbs = gap_status.get("carbohydrates") == "low"
        want_fats = gap_status.get("fats") == "low"

        out: List[MealPlanItemV3] = []

        def _add(name: str, source: Literal["purchased", "recommended"] = "purchased") -> None:
            cat = _get_food_category(name) or "unknown"
            q, u = _portion_preset(name, cat, meal)
            grams = _portion_to_grams(name=name, quantity=q, unit=u) or 0.0
            macros = _calc_macros_for_portion(name=name, grams=grams) if grams else {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fats": 0.0}
            out.append(
                {
                    "name": name,
                    "category": cat,
                    "portion": {"quantity": float(q), "unit": str(u), "grams": float(round(grams, 1)) if grams else 0.0},
                    "macros": macros,
                    "why": _why_for_item(name=name, category=cat, gap_status=gap_status, source=source),
                    "source": source,
                }
            )
            used_today.add(name)
            if name in usage:
                usage[name] += 1

        if meal == "breakfast":
            first_pool = pool_for("protein") if want_protein and pool_for("protein") else pool_for("dairy")
            first = pick_item(pool=first_pool, day_index=day_index, meal=meal, avoid_set=used_today)
            grain = pick_item(pool=pool_for("grain"), day_index=day_index, meal=meal, avoid_set=used_today)
            fruit = pick_item(pool=pool_for("fruit"), day_index=day_index, meal=meal, avoid_set=used_today)
            for nm in [first, grain, fruit]:
                if nm:
                    _add(nm)
        elif meal == "lunch":
            grain = pick_item(pool=pool_for("grain"), day_index=day_index, meal=meal, avoid_set=used_today)
            protein = pick_item(pool=pool_for("protein"), day_index=day_index, meal=meal, avoid_set=used_today)
            veg = pick_item(pool=pool_for("vegetable"), day_index=day_index, meal=meal, avoid_set=used_today)
            fat = pick_item(pool=pool_for("fat"), day_index=day_index, meal=meal, avoid_set=used_today)
            if want_carbs and not grain:
                grain = pick_item(pool=pool_for("fruit"), day_index=day_index, meal=meal, avoid_set=used_today)
            for nm in [grain, protein, veg]:
                if nm:
                    _add(nm)
            if fat and (want_fats or len(out) < 4):
                _add(fat)
        else:  # dinner
            protein = pick_item(pool=pool_for("protein"), day_index=day_index, meal=meal, avoid_set=used_today)
            veg = pick_item(pool=pool_for("vegetable"), day_index=day_index, meal=meal, avoid_set=used_today)
            grain = pick_item(pool=pool_for("grain"), day_index=day_index, meal=meal, avoid_set=used_today)
            fat = pick_item(pool=pool_for("fat"), day_index=day_index, meal=meal, avoid_set=used_today)
            for nm in [protein, veg]:
                if nm:
                    _add(nm)
            if grain and (want_carbs or len(out) < 2):
                _add(grain)
            if fat and (want_fats or len(out) < 3):
                _add(fat)

        present = {str(i.get("category") or "unknown") for i in out}
        if meal in ("lunch", "dinner") and "vegetable" not in present:
            add_booster(out, "vegetable", meal)
        if meal in ("lunch", "dinner") and "protein" not in present:
            add_booster(out, "protein", meal)
        if "fat" not in present and want_fats:
            add_booster(out, "fat", meal)

        main = None
        for it in out:
            main = main_food_label(str(it.get("name") or ""))
            if main:
                break
        last_main[meal] = main or last_main.get(meal)
        return out

    plan: List[WeeklyDayPlanV3] = []
    for day_index, day_name in enumerate(day_names):
        used_today: set[str] = set()
        breakfast = build_meal("breakfast", day_index, used_today)
        lunch = build_meal("lunch", day_index, used_today)
        dinner = build_meal("dinner", day_index, used_today)

        downscale_grains(breakfast, meal_targets["breakfast"])
        downscale_grains(lunch, meal_targets["lunch"])
        downscale_grains(dinner, meal_targets["dinner"])

        # Hard cap: do not exceed daily calorie target.
        # Rule: reduce grain portions first (lunch -> dinner -> breakfast), then reduce added fats.
        def _reduce_category(meal_items: List[MealPlanItemV3], category: FoodCategory, factor: float, min_g: float) -> bool:
            idx = next((i for i, it in enumerate(meal_items) if it.get("category") == category), None)
            if idx is None:
                return False
            it = meal_items[idx]
            portion = it.get("portion") or {}
            q = float(portion.get("quantity") or 0.0)
            u = str(portion.get("unit") or "g")
            if q <= 0:
                return False
            new_q = q * float(factor)
            if u.lower() in ["pcs", "pc", "piece", "pieces"]:
                # Reduce pieces but keep at least 1.
                new_q = max(1.0, round(new_q))
            else:
                new_q = _clamp(new_q, float(min_g), q)
            if abs(new_q - q) < 0.01:
                return False
            grams = _portion_to_grams(name=str(it.get("name") or ""), quantity=new_q, unit=u) or 0.0
            it["portion"] = {"quantity": float(round(new_q, 1)), "unit": u, "grams": float(round(grams, 1)) if grams else 0.0}
            it["macros"] = _calc_macros_for_portion(name=str(it.get("name") or ""), grams=grams) if grams else {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fats": 0.0}
            return True

        for _ in range(10):
            total_now = meal_total(breakfast) + meal_total(lunch) + meal_total(dinner)
            if total_now <= float(target):
                break
            changed = (
                _reduce_category(lunch, "grain", 0.85, 30.0)
                or _reduce_category(dinner, "grain", 0.85, 30.0)
                or _reduce_category(breakfast, "grain", 0.85, 30.0)
                or _reduce_category(lunch, "fat", 0.80, 5.0)
                or _reduce_category(dinner, "fat", 0.80, 5.0)
                or _reduce_category(breakfast, "fat", 0.80, 5.0)
            )
            if not changed:
                break

        total_cal = float(round(meal_total(breakfast) + meal_total(lunch) + meal_total(dinner), 1))
        total_macros: MealPlanMacros = {
            "calories": total_cal,
            "protein": float(round(sum(float(i.get("macros", {}).get("protein") or 0.0) for i in breakfast + lunch + dinner), 1)),
            "carbs": float(round(sum(float(i.get("macros", {}).get("carbs") or 0.0) for i in breakfast + lunch + dinner), 1)),
            "fats": float(round(sum(float(i.get("macros", {}).get("fats") or 0.0) for i in breakfast + lunch + dinner), 1)),
        }
        plan.append(
            {
                "day": day_name,
                "breakfast": breakfast,
                "lunch": lunch,
                "dinner": dinner,
                "total_calories": total_cal,
                "total_macros": total_macros,
                "calorie_target": target,
                "status": _status_vs_target(total_cal, target),
                "suggested_additions": suggested_additions,
                "decision_rules": [
                    "Prefer purchased items first.",
                    "Each meal aims for carbs + protein + vegetables/fiber + healthy fats.",
                    "Avoid repeating the same main item on consecutive days (per meal).",
                    "Keep calories near the daily target by reducing grain portions first when needed.",
                    "Bias selections toward low nutrients (protein/carbs/fats) when gaps are detected.",
                ],
            }
        )

    return plan

