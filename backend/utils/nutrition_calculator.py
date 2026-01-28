from typing import Optional, Dict

# Handle both relative import (when used as module) and absolute import (when run directly)
try:
    from .food_matcher import get_food_nutrition
    from .unit_converter import convert_to_grams, calculate_nutrition
    from .food_normalizer import normalize_food_name
except ImportError:
    from food_matcher import get_food_nutrition
    from unit_converter import convert_to_grams, calculate_nutrition
    from food_normalizer import normalize_food_name


def calculate_food_nutrition(
    food_name: str,
    quantity_grams: float,
    similarity_threshold: float = 80.0,
    round_decimals: int = 1
) -> Optional[Dict[str, float]]:
    """
    Calculate total nutrition for a food item given its name and quantity.
    
    This function:
    1. Matches the food name against the nutrition database
    2. Retrieves per-100g nutrition values
    3. Calculates total nutrition based on quantity in grams
    4. Returns rounded values
    
    Args:
        food_name: Food name to match (will be normalized and matched)
        quantity_grams: Quantity in grams
        similarity_threshold: Minimum similarity score for food matching (default: 80.0)
        round_decimals: Number of decimal places for rounding (default: 1)
    
    Returns:
        Dictionary with calculated nutrition values, or None if food not found:
        {
            'food_name': str,           # Matched food name from database
            'quantity_grams': float,     # Quantity in grams (rounded)
            'calories': float,           # Total calories (rounded)
            'protein': float,            # Total protein in grams (rounded)
            'carbs': float,              # Total carbs in grams (rounded)
            'fats': float                # Total fats in grams (rounded)
        }
    
    Examples:
        >>> calculate_food_nutrition("apple", 200)
        {
            'food_name': 'apple',
            'quantity_grams': 200.0,
            'calories': 104.0,
            'protein': 0.6,
            'carbs': 28.0,
            'fats': 0.2
        }
    """
    # Get nutrition data for the food item
    nutrition_data = get_food_nutrition(food_name, similarity_threshold)
    
    if nutrition_data is None:
        return None
    
    # Calculate nutrition using per-100g values
    result = calculate_nutrition(
        quantity_grams=quantity_grams,
        calories_per_100g=nutrition_data['calories_per_100g'],
        protein_per_100g=nutrition_data['protein_per_100g'],
        carbs_per_100g=nutrition_data['carbs_per_100g'],
        fats_per_100g=nutrition_data['fats_per_100g']
    )
    
    # Round all numeric values
    result['food_name'] = nutrition_data['food_name']
    result['quantity_grams'] = round(result['quantity_grams'], round_decimals)
    result['calories'] = round(result['calories'], round_decimals)
    result['protein'] = round(result['protein'], round_decimals)
    result['carbs'] = round(result['carbs'], round_decimals)
    result['fats'] = round(result['fats'], round_decimals)
    
    return result


def calculate_nutrition_from_quantity_string(
    food_name: str,
    quantity_str: str,
    similarity_threshold: float = 80.0,
    round_decimals: int = 1
) -> Optional[Dict[str, float]]:
    """
    Calculate nutrition from food name and quantity string (e.g., "500g", "1kg", "12 pcs").
    
    This is a convenience function that:
    1. Converts quantity string to grams
    2. Matches food name against database
    3. Calculates total nutrition
    4. Returns rounded values
    
    Args:
        food_name: Food name to match (will be normalized and matched)
        quantity_str: Quantity string (e.g., "500g", "1.5kg", "2L", "12 pcs")
        similarity_threshold: Minimum similarity score for food matching (default: 80.0)
        round_decimals: Number of decimal places for rounding (default: 1)
    
    Returns:
        Dictionary with calculated nutrition values, or None if food/quantity parsing fails:
        {
            'food_name': str,
            'quantity_grams': float,
            'calories': float,
            'protein': float,
            'carbs': float,
            'fats': float
        }
    
    Examples:
        >>> calculate_nutrition_from_quantity_string("apple", "200g")
        {
            'food_name': 'apple',
            'quantity_grams': 200.0,
            'calories': 104.0,
            'protein': 0.6,
            'carbs': 28.0,
            'fats': 0.2
        }
        >>> calculate_nutrition_from_quantity_string("Fresh Organic Apples", "1.5kg")
        {
            'food_name': 'apple',
            'quantity_grams': 1500.0,
            'calories': 780.0,
            'protein': 4.5,
            'carbs': 210.0,
            'fats': 3.0
        }
    """
    # Convert quantity string to grams
    # For piece conversion, we need the normalized food name
    normalized_food = normalize_food_name(food_name)
    quantity_grams = convert_to_grams(quantity_str, food_name=normalized_food)
    
    if quantity_grams is None:
        return None
    
    # Calculate nutrition
    return calculate_food_nutrition(
        food_name=food_name,
        quantity_grams=quantity_grams,
        similarity_threshold=similarity_threshold,
        round_decimals=round_decimals
    )


# Example usage and test cases
if __name__ == "__main__":
    print("Nutrition Calculation Test:")
    print("=" * 70)
    
    test_cases = [
        ("apple", 200, "200g of apple"),
        ("Fresh Organic Apples", 500, "500g of normalized apple"),
        ("banana", 118, "1 medium banana (118g)"),
        ("milk", 1000, "1L of milk"),
        ("chicken", 150, "150g of chicken"),
        ("egg", 50, "1 large egg (50g)"),
        ("rice", 100, "100g of rice"),
    ]
    
    print("\nDirect quantity in grams:")
    print("-" * 70)
    for food_name, quantity, description in test_cases:
        result = calculate_food_nutrition(food_name, quantity)
        if result:
            print(f"\n{description}:")
            print(f"  Food: {result['food_name']}")
            print(f"  Quantity: {result['quantity_grams']}g")
            print(f"  Calories: {result['calories']} kcal")
            print(f"  Protein: {result['protein']}g")
            print(f"  Carbs: {result['carbs']}g")
            print(f"  Fats: {result['fats']}g")
        else:
            print(f"\n{description}: Food not found")
    
    print("\n" + "=" * 70)
    print("\nFrom quantity strings:")
    print("-" * 70)
    
    quantity_string_tests = [
        ("apple", "200g", "200g of apple"),
        ("Fresh Organic Apples", "1.5kg", "1.5kg of normalized apple"),
        ("banana", "1 pcs", "1 banana"),
        ("milk", "1L", "1 liter of milk"),
        ("chicken", "500g", "500g of chicken"),
        ("egg", "6 pcs", "6 eggs"),
        ("rice", "1kg", "1kg of rice"),
    ]
    
    for food_name, quantity_str, description in quantity_string_tests:
        result = calculate_nutrition_from_quantity_string(food_name, quantity_str)
        if result:
            print(f"\n{description}:")
            print(f"  Food: {result['food_name']}")
            print(f"  Quantity: {result['quantity_grams']}g")
            print(f"  Calories: {result['calories']} kcal")
            print(f"  Protein: {result['protein']}g")
            print(f"  Carbs: {result['carbs']}g")
            print(f"  Fats: {result['fats']}g")
        else:
            print(f"\n{description}: Failed to calculate")
