import re


def normalize_food_name(food_name: str) -> str:
    """
    Normalize food names for matching by:
    - Lowercasing
    - Removing adjectives (fresh, organic, toned, whole, etc.)
    - Removing brackets and extra words
    - Converting plural to singular
    
    Args:
        food_name: The food name to normalize (e.g., "Fresh Organic Apples (1kg)")
    
    Returns:
        Normalized food name (e.g., "apple")
    
    Examples:
        >>> normalize_food_name("Fresh Organic Apples")
        'apple'
        >>> normalize_food_name("Whole Milk (Toned)")
        'milk'
        >>> normalize_food_name("Chicken Breast - 500g")
        'chicken'
    """
    if not food_name or not isinstance(food_name, str):
        return ""
    
    # Step 1: Lowercase
    normalized = food_name.lower().strip()
    
    # Step 2: Remove content in brackets and parentheses
    normalized = re.sub(r'\([^)]*\)', '', normalized)  # Remove (content)
    normalized = re.sub(r'\[[^\]]*\]', '', normalized)  # Remove [content]
    
    # Step 3: Remove common adjectives and descriptors
    # List of adjectives/descriptors to remove
    adjectives = [
        'fresh', 'organic', 'toned', 'whole', 'skimmed', 'skim', 'full', 'fat',
        'low', 'high', 'free', 'reduced', 'light', 'heavy', 'extra', 'premium',
        'natural', 'pure', 'raw', 'cooked', 'frozen', 'canned', 'dried', 'fresh',
        'ripe', 'unripe', 'large', 'small', 'medium', 'jumbo', 'baby', 'young',
        'old', 'new', 'imported', 'local', 'farm', 'farm-fresh', 'homegrown',
        'wild', 'cultivated', 'pasteurized', 'unpasteurized', 'fortified',
        'enriched', 'wholegrain', 'whole grain', 'multigrain', 'white', 'brown',
        'red', 'yellow', 'green', 'black', 'pink', 'orange'
    ]
    
    # Create a regex pattern to match adjectives at word boundaries
    # This ensures we match whole words only
    adjective_pattern = r'\b(?:' + '|'.join(re.escape(adj) for adj in adjectives) + r')\b'
    normalized = re.sub(adjective_pattern, '', normalized, flags=re.IGNORECASE)
    
    # Step 4: Remove common units and measurements
    # Remove weight/volume units and numbers
    normalized = re.sub(r'\d+\s*(kg|g|mg|lb|oz|l|ml|liter|litre|pack|pcs|pieces?|count)', '', normalized, flags=re.IGNORECASE)
    normalized = re.sub(r'\d+', '', normalized)  # Remove remaining numbers
    
    # Step 5: Remove extra punctuation and special characters
    normalized = re.sub(r'[-–—]', ' ', normalized)  # Replace dashes with spaces
    normalized = re.sub(r'[^\w\s]', '', normalized)  # Remove all punctuation except spaces
    
    # Step 6: Remove extra whitespace
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    # Step 7: Convert plural to singular
    # Handle common pluralization rules
    words = normalized.split()
    singular_words = []
    
    for word in words:
        if len(word) <= 2:  # Keep very short words as-is
            singular_words.append(word)
            continue
            
        # Common plural to singular rules
        # Words ending in 'oes' -> 'o' (potatoes -> potato, tomatoes -> tomato)
        if word.endswith('oes') and len(word) > 3:
            word = word[:-2]  # Remove 'es'
        # Words ending in 'ies' -> 'y' (berries -> berry)
        elif word.endswith('ies') and len(word) > 3:
            word = word[:-3] + 'y'
        # Words ending in 'es' (after s, x, z, ch, sh) -> remove 'es'
        elif word.endswith(('ches', 'shes', 'xes', 'zes', 'ses')) and len(word) > 3:
            word = word[:-2]
        # Words ending in 's' (but not 'ss') -> remove 's'
        elif word.endswith('s') and not word.endswith('ss') and len(word) > 1:
            # Special cases: some words ending in 's' are already singular
            if word in ['rice', 'milk', 'bread', 'cheese', 'yogurt', 'yoghurt']:
                word = word
            else:
                word = word[:-1]
        
        singular_words.append(word)
    
    normalized = ' '.join(singular_words).strip()
    
    # Step 8: Remove common food-related prefixes/suffixes that might be leftover
    # Remove common brand names or packaging terms if they appear at the start/end
    normalized = re.sub(r'^\s*(brand|pack|box|bottle|can|jar|bag|container)\s+', '', normalized, flags=re.IGNORECASE)
    normalized = re.sub(r'\s+(brand|pack|box|bottle|can|jar|bag|container)\s*$', '', normalized, flags=re.IGNORECASE)
    
    # Final cleanup: remove extra spaces and return
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    return normalized


# Example usage and test cases
if __name__ == "__main__":
    test_cases = [
        "Fresh Organic Apples",
        "Whole Milk (Toned)",
        "Chicken Breast - 500g",
        "Bananas (1kg)",
        "Fresh Spinach [Organic]",
        "Bread - White",
        "Eggs (12 pcs)",
        "Potatoes 2kg",
        "Rice - Basmati 1kg",
        "Tomatoes",
        "Fresh Broccoli",
        "Organic Carrots",
        "Whole Wheat Bread",
        "Low Fat Milk",
        "Red Apples",
    ]
    
    print("Food Name Normalization Test:")
    print("=" * 60)
    for test in test_cases:
        result = normalize_food_name(test)
        print(f"{test:35} -> {result}")
