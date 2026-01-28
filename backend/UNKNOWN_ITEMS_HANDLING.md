# Unknown Food Items Handling

## Overview

The system now gracefully handles food items that cannot be matched to the nutrition database. Instead of failing or breaking the flow, unknown items are marked as "Unknown" and excluded from nutrition calculations, with clear warnings displayed to users.

## Implementation

### Backend Changes

#### 1. **Item Marking**
When a food item cannot be matched or processed, it is now marked as:
- `matched: False`
- `matched_name: "Unknown"`
- `error: "Food item '{name}' not found in database"` (or appropriate error message)

#### 2. **Exclusion from Calculations**
Unknown items are:
- **Excluded** from total nutrition calculations (calories, protein, carbs, fats)
- **Tracked** in a separate `unknown_items` list in the summary
- **Counted** in `unmatched_items` count

#### 3. **Response Model Enhancement**
The `NutritionSummary` model now includes:
```python
unknown_items: List[str] = []  # List of unknown item names
```

#### 4. **Error Scenarios Handled**
Unknown items are created in these scenarios:
- Food name cannot be normalized
- No match found in database (similarity below threshold)
- Quantity cannot be converted to grams
- Nutrition data not found for matched item
- Nutrition calculation fails
- Any unexpected processing error

### Frontend Changes

#### 1. **Warning Display in NutritionSummary Component**
A prominent warning box is displayed when unknown items exist:
- Shows count of unknown items
- Lists all unknown item names
- Explains that items were excluded from calculations
- Uses yellow/amber color scheme for visibility

#### 2. **Warning Display in Dashboard Component**
Similar warning is shown on the Dashboard:
- Displays unknown items from stored nutrition summary
- Maintains consistency with NutritionSummary page
- Uses same styling and messaging

## User Experience

### Before
- Unknown items caused errors or were silently ignored
- Users had no visibility into which items failed
- Flow could break if items couldn't be processed

### After
- Unknown items are clearly marked and displayed
- Users see exactly which items couldn't be matched
- Flow continues smoothly - other items are still processed
- Nutrition totals reflect only matched items
- Clear warnings guide users to verify item names

## Example Flow

1. **User uploads receipt** with items: ["Apple", "Banana", "XyzUnknownFood"]
2. **System processes items**:
   - Apple → Matched ✓ (included in totals)
   - Banana → Matched ✓ (included in totals)
   - XyzUnknownFood → Unknown ✗ (excluded from totals)
3. **Response includes**:
   ```json
   {
     "summary": {
       "total_calories": 141.0,  // Only Apple + Banana
       "unknown_items": ["XyzUnknownFood"],
       "matched_items": 2,
       "unmatched_items": 1
     },
     "items": [
       {"original_name": "Apple", "matched": true, ...},
       {"original_name": "Banana", "matched": true, ...},
       {"original_name": "XyzUnknownFood", "matched": false, "matched_name": "Unknown", "error": "..."}
     ]
   }
   ```
4. **UI displays warning**:
   ```
   ⚠️ Unknown Food Items (1)
   The following items were not found in the nutrition database:
   - XyzUnknownFood
   These items were not included in the nutrition totals above.
   ```

## Benefits

1. **Graceful Degradation**: System continues working even with unknown items
2. **User Transparency**: Users know exactly which items failed
3. **Accurate Totals**: Nutrition calculations only include matched items
4. **No Flow Breaks**: Processing continues for all other items
5. **Clear Guidance**: Warnings help users verify item names

## Technical Notes

- Unknown items are still saved to the database (as confirmed items) if user confirms them
- Meal planning can still use unknown items (they'll be categorized as 'unknown')
- Unknown items don't affect the nutrition summary totals
- Error messages are descriptive to help debugging

## Future Enhancements

Potential improvements:
- Allow users to manually add nutrition data for unknown items
- Suggest similar items from database for unknown items
- Allow users to edit item names and retry matching
- Track unknown items separately for database expansion
