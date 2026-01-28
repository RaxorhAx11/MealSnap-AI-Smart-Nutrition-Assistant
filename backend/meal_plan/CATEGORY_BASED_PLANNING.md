# Category-Based Meal Planning

## Overview

The meal planning system has been enhanced to use food categories from the nutrition database. This ensures balanced nutrition across days and provides intelligent recommendations when categories are low.

## Key Features

### 1. **Category-Based Selection**

The system now uses actual food categories from the nutrition database instead of keyword matching:
- **Grain**: rice, bread, pasta, roti, naan, oats, etc.
- **Vegetable**: spinach, broccoli, carrot, tomato, etc.
- **Protein**: chicken, eggs, dal, beans, nuts, etc.
- **Dairy**: milk, curd, cheese, paneer, etc.
- **Fruit**: apple, banana, mango, etc.
- **Fat**: oils, avocado, etc.

### 2. **Mandatory Daily Requirements**

**Rule: At least one grain + one vegetable per day**

Every day's meal plan is guaranteed to include:
- At least one grain item (rice, bread, roti, etc.)
- At least one vegetable item (spinach, broccoli, etc.)

This ensures basic nutritional balance across all days.

### 3. **Category Tracking and Recommendations**

The system tracks category usage across the 7-day week and provides recommendations:

#### Low Vegetable Category
- **Trigger**: If vegetable count is 30% below average
- **Recommendation**: "Consider adding more vegetables for balanced nutrition"
- **Action**: System prioritizes vegetables when filling remaining slots

#### Low Protein Category
- **Trigger**: If protein count is 30% below average
- **Recommendation**: "Consider adding more protein foods (chicken, dal, eggs, etc.)"
- **Action**: System prioritizes protein items when filling remaining slots

#### Low Grain Category
- **Trigger**: If grain count is 30% below average
- **Recommendation**: "Consider adding more grains (rice, bread, roti, etc.)"
- **Action**: System prioritizes grain items (though grain is already mandatory)

### 4. **Balanced Rotation**

After ensuring mandatory categories (grain + vegetable), the system:
1. Checks for low categories and prioritizes them
2. Rotates through protein, dairy, and fruit categories
3. Fills remaining slots with variety

## Implementation Details

### Category Lookup

```python
def _get_food_category(item: str) -> Optional[str]:
    """Get food category from nutrition database."""
    nutrition_data = get_food_nutrition(item, similarity_threshold=80.0)
    if nutrition_data and 'category' in nutrition_data:
        return nutrition_data['category']
    return None
```

### Selection Algorithm

1. **Step 1**: Always select at least one grain
2. **Step 2**: Always select at least one vegetable
3. **Step 3**: Check category counts and prioritize low categories
4. **Step 4**: Fill remaining slots with balanced rotation

### Category Tracking

```python
category_counts: Dict[str, int] = {
    'grain': 0,
    'fruit': 0,
    'vegetable': 0,
    'dairy': 0,
    'protein': 0,
    'fat': 0
}
```

Counts are updated after each day's selection, allowing later days to adjust based on previous selections.

## Example Output

```json
{
  "day": "Monday",
  "daily_meal_plan": ["rice", "spinach", "chicken"],
  "categories": ["grain", "vegetable", "protein"],
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
}
```

On the last day, if categories are low:

```json
{
  "day": "Sunday",
  "daily_meal_plan": ["bread", "broccoli", "dal"],
  "categories": ["grain", "vegetable", "protein"],
  "recommendations": [
    "Consider adding more vegetables for balanced nutrition",
    "Consider adding more protein foods (chicken, dal, eggs, etc.)"
  ],
  ...
}
```

## Benefits

1. **Nutritional Balance**: Ensures every day has grains and vegetables
2. **Intelligent Recommendations**: Identifies and suggests improvements for low categories
3. **Database-Driven**: Uses actual categories from nutrition database, not keyword guessing
4. **Simple and Rule-Based**: Easy to understand and modify
5. **Adaptive**: Adjusts recommendations based on weekly category distribution

## Rules Summary

1. ✅ **Mandatory**: At least one grain + one vegetable per day
2. ✅ **Recommendation**: If vegetable category is low → recommend vegetables
3. ✅ **Recommendation**: If protein category is low → recommend protein foods
4. ✅ **Recommendation**: If grain category is low → recommend grains
5. ✅ **Rotation**: Balance remaining slots across protein, dairy, fruit categories

## Backward Compatibility

The legacy keyword-based functions (`_is_carb_item`, `_is_protein_item`, etc.) are maintained for backward compatibility but now use database categories internally.
