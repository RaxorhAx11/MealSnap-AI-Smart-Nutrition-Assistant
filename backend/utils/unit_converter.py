import re
from typing import Optional, Dict, Union


# Default average weights for common food items (in grams per piece)
# These can be overridden when calling the conversion function
DEFAULT_PIECE_WEIGHTS: Dict[str, float] = {
    'apple': 182,          # Medium apple
    'banana': 118,         # Medium banana
    'egg': 50,             # Large egg
    'potato': 150,         # Medium potato
    'tomato': 150,         # Medium tomato
    'orange': 131,         # Medium orange
    'carrot': 61,          # Medium carrot
    'bread': 25,           # One slice of bread
    'chicken': 100,        # Average chicken piece (breast)
    'default': 100,        # Default weight if food not found
}


def parse_quantity(quantity_str: str) -> tuple[Optional[float], Optional[str]]:
    """
    Parse a quantity string to extract the numeric value and unit.
    
    Handles various formats:
    - "500g", "500 g", "500gms"
    - "1kg", "1 kg", "1.5kg"
    - "2L", "2 L", "2 liters", "2l"
    - "12 pcs", "12 pieces", "12pc"
    
    Args:
        quantity_str: String containing quantity and unit (e.g., "500g", "1.5kg")
    
    Returns:
        Tuple of (numeric_value, unit) or (None, None) if parsing fails
        Unit will be normalized to: 'g', 'kg', 'ml', 'l', or 'pc'
    
    Examples:
        >>> parse_quantity("500g")
        (500.0, 'g')
        >>> parse_quantity("1.5 kg")
        (1.5, 'kg')
        >>> parse_quantity("2L")
        (2.0, 'l')
        >>> parse_quantity("12 pcs")
        (12.0, 'pc')
    """
    if not quantity_str or not isinstance(quantity_str, str):
        return None, None
    
    # Remove extra whitespace
    quantity_str = quantity_str.strip()
    
    # Pattern to match: number (with optional decimal) + optional space + unit
    # Units: g, kg, gms, grams, l, L, liter, litre, liters, litres, ml, ml, 
    #        pc, pcs, piece, pieces
    pattern = r'(\d+\.?\d*)\s*(g|kg|gms?|grams?|l|L|liter|litre|liters?|litres?|ml|mL|pc|pcs|piece|pieces?)\b'
    
    match = re.search(pattern, quantity_str, re.IGNORECASE)
    if not match:
        return None, None
    
    value = float(match.group(1))
    unit_raw = match.group(2).lower()
    
    # Normalize unit names
    unit_map = {
        'g': 'g',
        'gm': 'g',
        'gms': 'g',
        'gram': 'g',
        'grams': 'g',
        'kg': 'kg',
        'l': 'l',
        'liter': 'l',
        'litre': 'l',
        'liters': 'l',
        'litres': 'l',
        'ml': 'ml',
        'pc': 'pc',
        'pcs': 'pc',
        'piece': 'pc',
        'pieces': 'pc',
    }
    
    unit = unit_map.get(unit_raw, None)
    
    return value, unit


def convert_to_grams(
    quantity_str: str,
    food_name: Optional[str] = None,
    piece_weights: Optional[Dict[str, float]] = None
) -> Optional[float]:
    """
    Convert a quantity string to grams.
    
    Supports conversions:
    - kg → grams (multiply by 1000)
    - L → ml → grams (1L = 1000ml, 1ml = 1g for liquids)
    - pieces (pc) → grams (using average weight per piece)
    - grams → grams (no conversion needed)
    
    Args:
        quantity_str: String containing quantity and unit (e.g., "500g", "1.5kg", "2L", "12 pcs")
        food_name: Optional food name for piece weight lookup (e.g., "apple", "banana")
        piece_weights: Optional dictionary mapping food names to average piece weights (grams).
                      If not provided, uses DEFAULT_PIECE_WEIGHTS.
                      Should use normalized food names (lowercase, singular).
    
    Returns:
        Quantity in grams, or None if conversion fails
    
    Examples:
        >>> convert_to_grams("500g")
        500.0
        >>> convert_to_grams("1.5kg")
        1500.0
        >>> convert_to_grams("2L")
        2000.0
        >>> convert_to_grams("12 pcs", food_name="apple")
        2184.0  # 12 * 182g
        >>> convert_to_grams("6 pcs", food_name="egg")
        300.0  # 6 * 50g
    """
    # Parse the quantity string
    value, unit = parse_quantity(quantity_str)
    
    if value is None or unit is None:
        return None
    
    # Convert based on unit
    if unit == 'g':
        # Already in grams
        return value
    
    elif unit == 'kg':
        # Convert kg to grams: 1 kg = 1000 g
        return value * 1000.0
    
    elif unit == 'l':
        # Convert liters to ml, then to grams
        # 1 L = 1000 ml
        # For liquids, assume 1 ml = 1 g (density of water)
        ml = value * 1000.0
        return ml  # 1ml = 1g for liquids
    
    elif unit == 'ml':
        # Convert ml to grams
        # For liquids, assume 1 ml = 1 g (density of water)
        return value
    
    elif unit == 'pc':
        # Convert pieces to grams using average weight
        # Use provided piece_weights or default
        weights = piece_weights if piece_weights is not None else DEFAULT_PIECE_WEIGHTS
        
        # Try to find weight for the specific food
        if food_name:
            # Normalize food name for lookup (lowercase, singular)
            food_key = food_name.lower().strip()
            # Try exact match first
            piece_weight = weights.get(food_key, None)
            # If not found, try default
            if piece_weight is None:
                piece_weight = weights.get('default', 100.0)
        else:
            # No food name provided, use default weight
            piece_weight = weights.get('default', 100.0)
        
        # Calculate total weight: number of pieces * weight per piece
        return value * piece_weight
    
    else:
        # Unknown unit
        return None


def calculate_nutrition(
    quantity_grams: float,
    calories_per_100g: float,
    protein_per_100g: float,
    carbs_per_100g: float,
    fats_per_100g: float,
    round_decimals: int = 1
) -> Dict[str, float]:
    """
    Calculate nutrition values for a given quantity in grams.
    
    Args:
        quantity_grams: Quantity in grams
        calories_per_100g: Calories per 100g from nutrition database
        protein_per_100g: Protein per 100g from nutrition database
        carbs_per_100g: Carbs per 100g from nutrition database
        fats_per_100g: Fats per 100g from nutrition database
        round_decimals: Number of decimal places for rounding (default: 1)
    
    Returns:
        Dictionary with calculated nutrition values (rounded):
        {
            'quantity_grams': float,
            'calories': float,
            'protein': float,
            'carbs': float,
            'fats': float
        }
    
    Example:
        >>> calculate_nutrition(200, 52, 0.3, 14, 0.2)  # 200g of apple
        {
            'quantity_grams': 200.0,
            'calories': 104.0,      # 200/100 * 52 = 104.0
            'protein': 0.6,         # 200/100 * 0.3 = 0.6
            'carbs': 28.0,          # 200/100 * 14 = 28.0
            'fats': 0.2             # 200/100 * 0.2 = 0.4 -> rounded to 0.2
        }
    """
    # Calculate multiplier: quantity / 100g
    multiplier = quantity_grams / 100.0
    
    # Calculate nutrition values
    calories = calories_per_100g * multiplier
    protein = protein_per_100g * multiplier
    carbs = carbs_per_100g * multiplier
    fats = fats_per_100g * multiplier
    
    # Round all values
    return {
        'quantity_grams': round(quantity_grams, round_decimals),
        'calories': round(calories, round_decimals),
        'protein': round(protein, round_decimals),
        'carbs': round(carbs, round_decimals),
        'fats': round(fats, round_decimals),
    }


# Example usage and test cases
if __name__ == "__main__":
    print("Unit Conversion Test:")
    print("=" * 70)
    
    test_cases = [
        ("500g", None, "Grams - no conversion"),
        ("1kg", None, "Kilograms to grams"),
        ("1.5 kg", None, "Decimal kilograms"),
        ("2L", None, "Liters to grams (via ml)"),
        ("500 ml", None, "Milliliters to grams"),
        ("12 pcs", "apple", "Pieces - apple"),
        ("6 pcs", "egg", "Pieces - egg"),
        ("4 pcs", "banana", "Pieces - banana"),
        ("10 pcs", None, "Pieces - no food name (uses default)"),
        ("2.5kg", None, "Decimal kg without space"),
        ("1 liter", None, "Full word 'liter'"),
        ("500gms", None, "Abbreviated 'gms'"),
    ]
    
    for quantity_str, food_name, description in test_cases:
        result = convert_to_grams(quantity_str, food_name)
        if result is not None:
            print(f"{quantity_str:15} ({description:35}) -> {result:8.1f} grams")
            if food_name:
                print(f"{'':15} Food: {food_name}")
        else:
            print(f"{quantity_str:15} ({description:35}) -> Failed to parse")
    
    print("\n" + "=" * 70)
    print("\nNutrition Calculation Test:")
    print("=" * 70)
    
    # Example: 200g of apple
    apple_grams = convert_to_grams("200g")
    if apple_grams:
        nutrition = calculate_nutrition(apple_grams, 52, 0.3, 14, 0.2)
        print(f"\n200g of Apple:")
        print(f"  Calories: {nutrition['calories']:.1f} kcal")
        print(f"  Protein: {nutrition['protein']:.1f}g")
        print(f"  Carbs: {nutrition['carbs']:.1f}g")
        print(f"  Fats: {nutrition['fats']:.1f}g")
    
    # Example: 1L of milk
    milk_grams = convert_to_grams("1L")
    if milk_grams:
        nutrition = calculate_nutrition(milk_grams, 42, 3.4, 5, 1)
        print(f"\n1L of Milk:")
        print(f"  Quantity: {nutrition['quantity_grams']:.1f}g")
        print(f"  Calories: {nutrition['calories']:.1f} kcal")
        print(f"  Protein: {nutrition['protein']:.1f}g")
        print(f"  Carbs: {nutrition['carbs']:.1f}g")
        print(f"  Fats: {nutrition['fats']:.1f}g")
    
    # Example: 6 eggs
    eggs_grams = convert_to_grams("6 pcs", food_name="egg")
    if eggs_grams:
        nutrition = calculate_nutrition(eggs_grams, 155, 13, 1.1, 11)
        print(f"\n6 Eggs:")
        print(f"  Quantity: {nutrition['quantity_grams']:.1f}g")
        print(f"  Calories: {nutrition['calories']:.1f} kcal")
        print(f"  Protein: {nutrition['protein']:.1f}g")
        print(f"  Carbs: {nutrition['carbs']:.1f}g")
        print(f"  Fats: {nutrition['fats']:.1f}g")
