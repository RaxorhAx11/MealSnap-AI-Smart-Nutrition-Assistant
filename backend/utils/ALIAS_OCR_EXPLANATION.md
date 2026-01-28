# How Aliases Improve OCR Error Handling

## Overview

The fuzzy matching system uses aliases to significantly improve food recognition accuracy, especially when dealing with OCR (Optical Character Recognition) errors from receipt scanning. This document explains how aliases enhance error handling and matching confidence.

## The Problem with OCR

OCR systems often introduce errors when reading text from receipts, especially with:
- **Handwritten text**: Poor handwriting leads to character misrecognition
- **Low-quality images**: Blurry or low-resolution receipts
- **Font variations**: Unusual fonts or stylized text
- **Language mixing**: Mixed English and regional language text (e.g., Hindi/English)
- **Special characters**: Currency symbols, dashes, and punctuation
- **Noise and artifacts**: Stains, creases, or shadows on receipts

### Common OCR Errors:
- Character substitutions: "dahi" → "dah1" (1 instead of i)
- Character deletions: "curd" → "cud" (missing 'r')
- Character insertions: "milk" → "milik" (extra 'i')
- Word splitting: "chicken breast" → "chicken bre ast"
- Case variations: "Apple" vs "apple" vs "APPLE"

## How Aliases Solve This

### 1. **Multiple Recognition Paths**

Aliases provide multiple ways to match the same food item:

**Example:**
- Canonical name: `curd`
- Aliases: `yogurt, dahi, yoghurt`

When OCR reads "dahi" from a receipt:
- **Without aliases**: System tries fuzzy match "dahi" → "curd" (might fail if OCR error is severe)
- **With aliases**: System can match "dahi" directly to alias "dahi" → canonical "curd" (exact match, 100% confidence)

### 2. **Increased Match Confidence**

The system applies a **confidence boost** (+10 points) when a match is found via an alias:

```python
# Example matching scores:
"dahi" matched to alias "dahi" → 100% + 10% boost = 100% (capped)
"dah1" matched to alias "dahi" → 80% + 10% boost = 90% (passes threshold)
"dah1" matched to canonical "curd" → 60% (fails threshold)
```

This boost helps alias matches pass the similarity threshold even when OCR introduces minor errors.

### 3. **Language and Regional Variations**

Aliases handle regional language variations that OCR might capture:

**Example:**
- Canonical: `rice`
- Aliases: `basmati rice, long grain rice, chawal` (Hindi)

When OCR reads "chawal" (Hindi word for rice):
- System matches "chawal" → alias "chawal" → canonical "rice"
- Without aliases, "chawal" would need fuzzy matching to "rice" (low similarity)

### 4. **Common Name Variations**

Aliases handle common alternative names that appear on receipts:

**Example:**
- Canonical: `chicken`
- Aliases: `chicken breast, chicken meat, murgh` (Hindi)

Receipt might show:
- "Chicken Breast - 500g" → matches alias "chicken breast"
- "Murgh" → matches alias "murgh"
- Both resolve to canonical "chicken"

### 5. **OCR Error Tolerance**

Aliases provide a "safety net" for OCR errors:

**Scenario 1: Character substitution**
- OCR reads: "dah1" (1 instead of i)
- Alias "dahi" fuzzy matches "dah1" with 80% similarity
- Boost applied: 80% + 10% = 90% → **Match succeeds**

**Scenario 2: Missing character**
- OCR reads: "cur" (missing 'd')
- Alias "curd" fuzzy matches "cur" with 75% similarity
- Boost applied: 75% + 10% = 85% → **Match succeeds** (if threshold is 80%)

**Scenario 3: Extra character**
- OCR reads: "curdd" (extra 'd')
- Alias "curd" fuzzy matches "curdd" with 80% similarity
- Boost applied: 80% + 10% = 90% → **Match succeeds**

## Technical Implementation

### Matching Process

1. **Normalize input**: Remove adjectives, units, punctuation
   - "Fresh Organic Dahi (500g)" → "dahi"

2. **Match against database**: Check both canonical names and aliases
   - Compare "dahi" against all normalized food names and aliases
   - Find best match using fuzzy string matching (RapidFuzz)

3. **Apply confidence boost**: If match is on an alias
   - Base score: 85%
   - Alias boost: +10%
   - Final score: 95% (capped at 100%)

4. **Return canonical name**: Always return the canonical food name
   - Match "dahi" (alias) → Return "curd" (canonical)

### Code Example

```python
# Input from OCR: "dah1" (OCR error: 1 instead of i)
normalized = normalize_food_name("dah1")  # → "dah1"

# Match against database (includes aliases)
result = match_food_name(normalized, similarity_threshold=80.0)
# Returns: ('curd', 90.0, True)
# - Canonical name: 'curd'
# - Confidence: 90% (80% base + 10% alias boost)
# - Matched via alias: True

# Get nutrition data
nutrition = get_food_nutrition("dah1")
# Returns nutrition data for 'curd'
```

## Benefits Summary

1. **Higher Accuracy**: More matches succeed due to multiple recognition paths
2. **Better Confidence**: Alias matches get boosted confidence scores
3. **Language Support**: Handles regional language variations
4. **Error Resilience**: Tolerates OCR character errors better
5. **Flexibility**: Supports common name variations and abbreviations

## Real-World Examples

### Example 1: Indian Receipt
```
OCR Text: "Dah1 500gm" (OCR error: 1 instead of i)
Without aliases: Might fail to match or match incorrectly
With aliases: Matches alias "dahi" → canonical "curd" (90% confidence)
```

### Example 2: Mixed Language Receipt
```
OCR Text: "Chawal 1kg" (Hindi word for rice)
Without aliases: Low similarity match to "rice" (might fail)
With aliases: Exact match to alias "chawal" → canonical "rice" (100% confidence)
```

### Example 3: Abbreviated Receipt
```
OCR Text: "Chkn Brst" (abbreviated)
Without aliases: Low similarity to "chicken"
With aliases: Matches alias "chicken breast" → canonical "chicken" (high confidence)
```

## Conclusion

Aliases significantly improve OCR error handling by:
- Providing multiple recognition paths for the same food
- Increasing match confidence through boost mechanism
- Supporting regional language variations
- Tolerating common OCR character errors
- Handling name variations and abbreviations

This makes the nutrition tracking system more robust and accurate when processing real-world receipts with OCR errors.
