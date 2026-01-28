from __future__ import annotations

from typing import Dict, Iterable, List, Optional


"""
Meal planning rules (simple, explainable)
----------------------------------------

These rules are intentionally lightweight and rule-based (no ML). They are meant to
be easy to read, debug, and adjust.

- Breakfast: light foods
  - Examples: oats, yogurt, fruit, toast, tea/coffee.

- Lunch: main carbs + vegetables
  - Treat lunch as the most substantial meal.
  - Aim for a "main carb" (rice/bread/pasta/noodles/etc.) plus vegetables
    (salad/sabzi/veggies/etc.). Protein is optional but welcome.

- Dinner: lighter than lunch
  - Prefer smaller portions, fewer heavy carbs than lunch, and more vegetables
    and/or protein (soup, salad, light curry, grilled items).

- Variety rule: avoid repeating the same main food on consecutive days
  - If yesterday's main food was "rice", do not make today's main food "rice"
    again; pick the next best option available.
  - "Main food" here is a simplified label derived from keyword matching.
"""


def categorize_food_items(items: Iterable[str]) -> Dict[str, List[str]]:
    """
    Categorize food item strings into meal buckets using simple keyword matching.

    Rules:
    - Item text is lowercased and checked for keyword substrings.
    - First matching category wins in this priority order:
      breakfast -> lunch -> dinner -> snack
    - If nothing matches, the item is categorized as "snack".

    Args:
        items: Iterable of food item strings (e.g., ["egg sandwich", "pizza slice"])

    Returns:
        Dictionary mapping categories to lists of the original item strings.
        Keys are always: "breakfast", "lunch", "dinner", "snack".
    """
    categories: Dict[str, List[str]] = {
        "breakfast": [],
        "lunch": [],
        "dinner": [],
        "snack": [],
    }

    keyword_map = {
        "breakfast": [
            "breakfast",
            "cereal",
            "oat",
            "oats",
            "oatmeal",
            "porridge",
            "granola",
            "pancake",
            "waffle",
            "toast",
            "bagel",
            "muffin",
            "omelet",
            "omelette",
            "egg",
            "bacon",
            "sausage",
            "coffee",
            "tea",
            "milk",
            "yogurt",
        ],
        "lunch": [
            "lunch",
            "sandwich",
            "wrap",
            "burger",
            "bowl",
            "salad",
            "soup",
            "noodle",
            "noodles",
            "pasta",
            "rice",
            "burrito",
            "taco",
            "shawarma",
        ],
        "dinner": [
            "dinner",
            "steak",
            "chicken",
            "fish",
            "salmon",
            "curry",
            "biryani",
            "roti",
            "naan",
            "dal",
            "paneer",
            "sabzi",
            "stir fry",
            "stir-fry",
            "bbq",
            "barbecue",
            "pizza",
        ],
        "snack": [
            "snack",
            "chips",
            "cracker",
            "crackers",
            "cookie",
            "cookies",
            "biscuit",
            "biscuits",
            "chocolate",
            "candy",
            "sweet",
            "ice cream",
            "icecream",
            "nuts",
            "trail mix",
            "popcorn",
            "fruit",
            "banana",
            "apple",
            "orange",
            "bar",
            "protein bar",
        ],
    }

    def _match_category(text: str) -> str:
        t = text.lower()
        for category in ("breakfast", "lunch", "dinner", "snack"):
            for kw in keyword_map[category]:
                if kw in t:
                    return category
        return "snack"

    for item in items:
        if item is None:
            continue
        s = str(item).strip()
        if not s:
            continue
        categories[_match_category(s)].append(s)

    return categories


def main_food_label(food_name: str) -> Optional[str]:
    """
    Extract a simple "main food" label from a food name.

    This is used for the "avoid repeating same main food on consecutive days"
    rule. It is intentionally approximate and keyword-based.

    Examples:
        - "chicken biryani" -> "rice"
        - "whole wheat bread" -> "bread"
        - "pasta with veggies" -> "pasta"
    """
    if not food_name:
        return None
    t = food_name.strip().lower()
    if not t:
        return None

    label_keywords = {
        # Carbs / staples
        "rice": ["rice", "biryani", "fried rice"],
        "bread": ["bread", "toast", "bun", "roll", "roti", "naan", "wrap", "tortilla"],
        "pasta": ["pasta", "spaghetti", "macaroni"],
        "noodles": ["noodle", "noodles"],
        "potato": ["potato", "fries", "chips"],
        # Common mains
        "chicken": ["chicken"],
        "fish": ["fish", "salmon", "tuna"],
        "egg": ["egg", "omelet", "omelette"],
        "paneer": ["paneer"],
        "beans": ["bean", "beans", "dal", "lentil", "chickpea", "chana"],
        # Fast food / heavy mains
        "pizza": ["pizza"],
        "burger": ["burger"],
        "sandwich": ["sandwich"],
    }

    for label, kws in label_keywords.items():
        for kw in kws:
            if kw in t:
                return label
    return None


def avoid_consecutive_repeats(
    candidates: Iterable[str],
    previous_day_main: Optional[str],
) -> List[str]:
    """
    Filter/reorder candidate foods to avoid repeating the same main food label
    as the previous day.

    Strategy:
    - Keep the original order, but move foods that match the previous main label
      to the end (rather than deleting them).
    - If there is no previous label, return candidates as-is.

    Returns:
        A reordered list of candidate foods.
    """
    items = [str(x).strip() for x in candidates if x is not None and str(x).strip()]
    if not previous_day_main:
        return items

    prev = previous_day_main.strip().lower()
    non_repeating: List[str] = []
    repeating: List[str] = []
    for item in items:
        label = main_food_label(item)
        if label and label == prev:
            repeating.append(item)
        else:
            non_repeating.append(item)
    return non_repeating + repeating

