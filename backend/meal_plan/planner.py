from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .rules import avoid_consecutive_repeats, main_food_label

# Import nutrition calculation utilities
try:
    from ..utils.food_matcher import get_food_nutrition
except ImportError:
    # Fallback for direct imports
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from utils.food_matcher import get_food_nutrition


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

