import csv
import os
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from rapidfuzz import fuzz, process
import re

# Handle both relative import (when used as module) and absolute import (when run directly)
try:
    from .food_normalizer import normalize_food_name
except ImportError:
    from food_normalizer import normalize_food_name


# Path to the nutrition database CSV file
# Using Path to handle cross-platform path resolution
NUTRITION_DB_PATH = Path(__file__).parent.parent.parent / "data" / "nutrition_database.csv"

# Confidence boost applied when an alias matches (increases match score)
ALIAS_CONFIDENCE_BOOST = 10.0


def load_nutrition_database_with_mapping() -> Tuple[List[str], Dict[str, str]]:
    """
    Load food names from the nutrition database CSV file with alias mapping.
    Includes both canonical names and aliases for improved matching.
    
    Returns:
        Tuple of:
        - List of normalized food names from the database (including aliases)
        - Dictionary mapping normalized aliases to their canonical food names
          Format: {normalized_alias: normalized_canonical_name}
    """
    food_names = []
    alias_to_canonical = {}  # Maps normalized alias -> normalized canonical name
    
    if not NUTRITION_DB_PATH.exists():
        raise FileNotFoundError(f"Nutrition database not found at: {NUTRITION_DB_PATH}")
    
    with open(NUTRITION_DB_PATH, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            food_name = row.get('food_name', '').strip()
            if food_name:
                # Normalize database food names for consistent matching
                normalized_canonical = normalize_food_name(food_name)
                if normalized_canonical:
                    food_names.append(normalized_canonical)
                    # Map canonical name to itself (for consistency)
                    alias_to_canonical[normalized_canonical] = normalized_canonical
            
            # Also include aliases for matching
            aliases_str = row.get('aliases', '').strip()
            if aliases_str:
                # Split aliases with common separators (comma/semicolon/pipe)
                aliases = [a.strip() for a in re.split(r"[;,|]+", aliases_str) if a and a.strip()]
                for alias in aliases:
                    normalized_alias = normalize_food_name(alias)
                    if normalized_alias:
                        # Add to food names list if not already present
                        if normalized_alias not in food_names:
                            food_names.append(normalized_alias)
                        # Map alias to its canonical name
                        if normalized_canonical:
                            alias_to_canonical[normalized_alias] = normalized_canonical
    
    return food_names, alias_to_canonical


def load_nutrition_database() -> list[str]:
    """
    Load food names from the nutrition database CSV file.
    Includes both canonical names and aliases for improved matching.
    
    Returns:
        List of normalized food names from the database (including aliases)
    """
    food_names, _ = load_nutrition_database_with_mapping()
    return food_names


def match_food_name(
    normalized_food_name: str,
    similarity_threshold: float = 80.0,
    database_foods: Optional[list[str]] = None,
    alias_mapping: Optional[Dict[str, str]] = None
) -> Optional[Tuple[str, float, bool]]:
    """
    Find the best matching food name from the nutrition database using fuzzy matching.
    Checks both canonical names and aliases, with increased confidence for alias matches.
    
    Uses RapidFuzz's ratio scoring algorithm to calculate similarity between the
    normalized input and database food names. Returns the best match if it exceeds
    the similarity threshold.
    
    Similarity Score Logic (RapidFuzz ratio):
    -----------------------------------------
    The ratio() function uses a normalized Levenshtein distance algorithm:
    
    1. Levenshtein Distance: Measures the minimum number of single-character
       edits (insertions, deletions, substitutions) needed to transform one
       string into another.
    
    2. Normalization: The distance is normalized to a 0-100 scale:
       similarity = (1 - (distance / max_length)) * 100
       where max_length is the length of the longer string.
    
    3. Alias Boost: When a match is found on an alias (not canonical name),
       the confidence score is boosted by ALIAS_CONFIDENCE_BOOST points.
       This helps prioritize alias matches which are often more specific
       (e.g., "curd" matching "dahi" is more confident than fuzzy matching).
    
    4. Examples:
       - "apple" vs "apple" = 100% (identical, canonical)
       - "dahi" vs "curd" (alias) = 100% + 10% boost = 110% (capped at 100%)
       - "appl" vs "apple" = ~83% (one deletion, canonical)
       - "chiken" vs "chicken" = ~86% (one substitution, canonical)
    
    Args:
        normalized_food_name: The normalized food name to match (should be pre-normalized
                             using normalize_food_name())
        similarity_threshold: Minimum similarity score (0-100) required for a match.
                             Default is 80.0 (80% similarity).
        database_foods: Optional pre-loaded list of database food names. If None,
                       the database will be loaded from CSV.
        alias_mapping: Optional pre-loaded alias mapping. If None, will be loaded from CSV.
    
    Returns:
        Tuple of (matched_canonical_name, confidence_score, is_alias_match) if match found,
        None if no match found above threshold.
        - matched_canonical_name: The canonical food name from database
        - confidence_score: Similarity score (0-100), boosted if alias match
        - is_alias_match: True if match was on an alias, False if on canonical name
    
    Examples:
        >>> match_food_name("apple")
        ('apple', 100.0, False)
        >>> match_food_name("dahi")  # Alias for curd
        ('curd', 100.0, True)  # Score boosted
        >>> match_food_name("appl")  # Typo
        ('apple', 83.3, False)
        >>> match_food_name("xyzabc")  # No match
        None
    """
    if not normalized_food_name or not normalized_food_name.strip():
        return None
    
    # Load database and mapping if not provided
    if database_foods is None or alias_mapping is None:
        db_foods, db_mapping = load_nutrition_database_with_mapping()
        if database_foods is None:
            database_foods = db_foods
        if alias_mapping is None:
            alias_mapping = db_mapping
    
    if not database_foods or not alias_mapping:
        return None
    
    # Fast path: exact match on normalized key (canonical or alias)
    key = normalized_food_name.strip()
    if key in alias_mapping:
        canonical_name = alias_mapping.get(key, key)
        is_alias_match = (key != canonical_name)
        score = 100.0 if not is_alias_match else 100.0  # exact match
        return (canonical_name, score, is_alias_match)

    def _squeeze_repeats(s: str) -> str:
        # Collapse 3+ repeated chars to 1 (helps OCR like "milkk" / "appple")
        # Keep double letters (e.g., "coffee") intact to reduce false changes.
        return re.sub(r"(.)\1{2,}", r"\1", s)

    # Generate a few variants to improve OCR-typo robustness
    variants = []
    variants.append(key)
    squeezed = _squeeze_repeats(key)
    if squeezed != key:
        variants.append(squeezed)
    no_space = key.replace(" ", "")
    if no_space != key:
        variants.append(no_space)
    no_space_squeezed = _squeeze_repeats(no_space)
    if no_space_squeezed not in variants:
        variants.append(no_space_squeezed)

    # Use multiple scorers; WRatio is generally stronger for typos + token differences.
    # We keep a single threshold API but evaluate best score across variants.
    best: Optional[Tuple[str, float]] = None  # (matched_name, score)
    best_variant_score = -1.0
    for v in variants:
        # Lower cutoff slightly for very short strings to avoid missing simple typos,
        # but never below 60 to keep false matches in check.
        cutoff = similarity_threshold - ALIAS_CONFIDENCE_BOOST
        if len(v) <= 4:
            cutoff = max(60.0, cutoff - 5.0)

        # Try WRatio first
        r1 = process.extractOne(v, database_foods, scorer=fuzz.WRatio, score_cutoff=cutoff)
        # Then token_set_ratio as a fallback for multi-word cases
        r2 = process.extractOne(v, database_foods, scorer=fuzz.token_set_ratio, score_cutoff=cutoff)

        for r in (r1, r2):
            if not r:
                continue
            matched_name, base_score, _ = r
            if base_score > best_variant_score:
                best_variant_score = float(base_score)
                best = (matched_name, float(base_score))

    if not best:
        return None

    matched_name, base_score = best
    
    # Check if the match was on an alias or canonical name
    canonical_name = alias_mapping.get(matched_name, matched_name)
    is_alias_match = (matched_name != canonical_name)
    
    # Apply confidence boost if it's an alias match
    if is_alias_match:
        boosted_score = min(100.0, base_score + ALIAS_CONFIDENCE_BOOST)
    else:
        boosted_score = base_score
    
    # Only return if boosted score meets threshold
    if boosted_score >= similarity_threshold:
        return (canonical_name, boosted_score, is_alias_match)
    
    return None


def get_food_nutrition(food_name: str, similarity_threshold: float = 80.0) -> Optional[dict]:
    """
    Get nutrition information for a food item by matching it against the database.
    Checks both canonical names and aliases, with increased confidence for alias matches.
    
    This is a convenience function that combines normalization, matching, and
    nutrition data retrieval.
    
    Args:
        food_name: Raw food name (will be normalized before matching)
        similarity_threshold: Minimum similarity score required for match
    
    Returns:
        Dictionary with nutrition data if match found, None otherwise.
        Format: {
            'food_name': str,
            'calories_per_100g': float,
            'protein_per_100g': float,
            'carbs_per_100g': float,
            'fats_per_100g': float,
            'category': str (optional),
            'aliases': list[str] (optional),
            'match_confidence': float (optional),
            'matched_via_alias': bool (optional)
        }
    """
    # Normalize the input food name
    normalized = normalize_food_name(food_name)
    if not normalized:
        return None
    
    # Load alias mapping for match_food_name
    _, alias_mapping = load_nutrition_database_with_mapping()
    
    # Find the best match (now returns tuple with confidence and alias flag)
    match_result = match_food_name(normalized, similarity_threshold, alias_mapping=alias_mapping)
    if not match_result:
        return None
    
    matched_canonical_name, match_confidence, is_alias_match = match_result
    
    # Load the database and find the nutrition data
    # Note: We need to match against the original database food_name, not normalized
    if not NUTRITION_DB_PATH.exists():
        return None
    
    with open(NUTRITION_DB_PATH, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            db_food_name = row.get('food_name', '').strip()
            # Normalize database name for comparison
            normalized_db_name = normalize_food_name(db_food_name)
            
            # Check if matched canonical name matches this row's canonical name
            if normalized_db_name == matched_canonical_name:
                result = {
                    'food_name': db_food_name,  # Return original name from DB
                    'calories_per_100g': float(row.get('calories_per_100g', 0)),
                    'protein_per_100g': float(row.get('protein_per_100g', 0)),
                    'carbs_per_100g': float(row.get('carbs_per_100g', 0)),
                    'fats_per_100g': float(row.get('fats_per_100g', 0)),
                    'match_confidence': match_confidence,
                    'matched_via_alias': is_alias_match
                }
                # Add category and aliases if available
                category = row.get('category', '').strip()
                if category:
                    result['category'] = category
                aliases_str = row.get('aliases', '').strip()
                if aliases_str:
                    result['aliases'] = [alias.strip() for alias in aliases_str.split(',') if alias.strip()]
                return result
    
    return None


# Example usage and test cases
if __name__ == "__main__":
    print("Food Matching Test:")
    print("=" * 70)
    
    test_cases = [
        ("apple", "Exact match"),
        ("appl", "Typo - missing 'e'"),
        ("appple", "Typo - extra 'p'"),
        ("chicken", "Exact match"),
        ("chiken", "Typo - missing 'c'"),
        ("chikn", "Multiple typos"),
        ("banana", "Exact match"),
        ("banan", "Typo - missing 'a'"),
        ("Fresh Organic Apples", "With adjectives - should normalize first"),
        ("xyzabc123", "No match - random string"),
        ("milk", "Exact match"),
        ("mil", "Typo - missing 'k'"),
    ]
    
    # Load database once for efficiency
    db_foods, alias_map = load_nutrition_database_with_mapping()
    print(f"Loaded {len(db_foods)} food items from database\n")
    
    for test_input, description in test_cases:
        # Normalize first
        normalized = normalize_food_name(test_input)
        # Then match
        result = match_food_name(normalized, similarity_threshold=80.0, database_foods=db_foods, alias_mapping=alias_map)
        
        if result:
            matched_name, confidence, is_alias = result
            alias_info = " (via alias)" if is_alias else ""
            status = f"Matched: '{matched_name}' (confidence: {confidence:.1f}%){alias_info}"
        else:
            status = "No match"
        print(f"{test_input:30} ({description:35}) -> {status}")
        if normalized != test_input:
            print(f"{'':30} Normalized: '{normalized}'")
    
    print("\n" + "=" * 70)
    print("\nNutrition Data Retrieval Test:")
    print("=" * 70)
    
    nutrition_tests = [
        "Fresh Organic Apples",
        "Whole Milk (Toned)",
        "Chicken Breast - 500g",
        "Bananas (1kg)",
        "dahi",  # Test alias matching
        "curd",  # Test alias matching
        "paneer",  # Test alias matching
    ]
    
    for test_input in nutrition_tests:
        nutrition = get_food_nutrition(test_input, similarity_threshold=80.0)
        if nutrition:
            print(f"\n{test_input}:")
            print(f"  Matched: {nutrition['food_name']}")
            print(f"  Confidence: {nutrition.get('match_confidence', 'N/A'):.1f}%")
            print(f"  Matched via alias: {nutrition.get('matched_via_alias', False)}")
            print(f"  Calories: {nutrition['calories_per_100g']} kcal/100g")
            print(f"  Protein: {nutrition['protein_per_100g']}g/100g")
            print(f"  Carbs: {nutrition['carbs_per_100g']}g/100g")
            print(f"  Fats: {nutrition['fats_per_100g']}g/100g")
        else:
            print(f"{test_input}: No match found")
