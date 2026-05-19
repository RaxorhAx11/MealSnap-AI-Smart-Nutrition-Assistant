const DEFAULT_DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

function norm(s) {
  return String(s ?? '').trim();
}

function lower(s) {
  return norm(s).toLowerCase();
}

function uniq(arr) {
  const out = [];
  const seen = new Set();
  for (const v of arr) {
    const key = lower(v);
    if (!key) continue;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(norm(v));
  }
  return out;
}

function pickFirstAvailable(candidates, availableSet) {
  for (const c of candidates) {
    const key = lower(c);
    if (availableSet.has(key)) return c;
  }
  return null;
}

// Simple, explainable nutrition-group detection based on common grocery words.
// This is intentionally heuristic (no external AI calls) to keep it deterministic and offline.
export function classifyFoodGroup(itemName) {
  const s = lower(itemName);
  if (!s) return 'other';

  const has = (words) => words.some((w) => s.includes(w));

  if (has(['milk', 'yogurt', 'curd', 'cheese', 'paneer', 'buttermilk'])) return 'dairy';
  if (has(['egg'])) return 'protein';
  if (has(['chicken', 'fish', 'mutton', 'beef', 'pork', 'turkey', 'tofu', 'soy', 'tempeh'])) return 'protein';
  if (has(['dal', 'lentil', 'lentils', 'chickpea', 'chana', 'rajma', 'beans', 'moong', 'masoor', 'urad', 'pulses'])) return 'protein';

  if (has(['apple', 'banana', 'orange', 'mango', 'grape', 'grapes', 'berry', 'berries', 'pear', 'peach', 'guava', 'papaya', 'watermelon', 'melon', 'kiwi', 'pineapple', 'pomegranate', 'dates'])) return 'fruit';

  if (has(['spinach', 'palak', 'carrot', 'tomato', 'cucumber', 'onion', 'potato', 'capsicum', 'pepper', 'broccoli', 'cauliflower', 'cabbage', 'lettuce', 'beans', 'peas', 'okra', 'bhindi', 'brinjal', 'eggplant', 'zucchini', 'mushroom', 'ginger', 'garlic', 'beet'])) return 'vegetable';

  if (has(['rice', 'bread', 'roti', 'chapati', 'paratha', 'oats', 'poha', 'upma', 'pasta', 'noodle', 'noodles', 'idli', 'dosa', 'corn', 'maize', 'flour', 'atta', 'wheat', 'whole wheat', 'quinoa'])) return 'carb';

  return 'other';
}

function groupItems(itemNames) {
  const grouped = {
    carb: [],
    protein: [],
    fruit: [],
    vegetable: [],
    dairy: [],
    other: [],
  };
  for (const n of uniq(itemNames)) {
    const g = classifyFoodGroup(n);
    grouped[g] = grouped[g] || [];
    grouped[g].push(n);
  }
  return grouped;
}

function takeFromGroup(groupList, usedCount, limitPerDay, exclusionsSet) {
  for (const item of groupList) {
    const key = lower(item);
    if (exclusionsSet && exclusionsSet.has(key)) continue;
    const c = usedCount.get(key) ?? 0;
    if (c >= limitPerDay) continue;
    usedCount.set(key, c + 1);
    return item;
  }
  return null;
}

function mealMissingGroups(mealItems) {
  const present = new Set(mealItems.map(classifyFoodGroup));
  const missing = [];
  if (!present.has('carb')) missing.push('carb');
  if (!present.has('protein')) missing.push('protein');
  if (!present.has('vegetable') && !present.has('fruit')) missing.push('produce');
  return missing;
}

function suggestedAdditionsForMissing(missingGroups) {
  const out = [];
  for (const g of missingGroups) {
    if (g === 'carb') out.push('Whole grains (oats / whole wheat bread / brown rice)');
    if (g === 'protein') out.push('Protein (eggs / lentils / paneer / yogurt)');
    if (g === 'produce') out.push('Vegetables or fruit (salad / spinach / carrots / seasonal fruit)');
  }
  return uniq(out);
}

function buildMeal({ grouped, usedCount, limitPerDay, target, excludeSet }) {
  const items = [];
  const suggestions = [];
  const exclusions = excludeSet || new Set();

  // Always try to satisfy carbs + protein for lunch/dinner.
  if (target === 'main') {
    const carb = takeFromGroup(grouped.carb, usedCount, limitPerDay, exclusions);
    if (carb) items.push(carb);
    const protein = takeFromGroup(grouped.protein, usedCount, limitPerDay, exclusions);
    if (protein) items.push(protein);

    // Add produce if available
    const veg = takeFromGroup(grouped.vegetable, usedCount, limitPerDay, exclusions);
    if (veg) items.push(veg);
    else {
      const fruit = takeFromGroup(grouped.fruit, usedCount, limitPerDay, exclusions);
      if (fruit) items.push(fruit);
    }

    // Optional dairy if it exists and not already used heavily
    if (!items.some((i) => classifyFoodGroup(i) === 'dairy')) {
      const dairy = takeFromGroup(grouped.dairy, usedCount, limitPerDay, exclusions);
      if (dairy) items.push(dairy);
    }
  } else if (target === 'breakfast') {
    // Breakfast: prioritize dairy + fruit if present (example requirement)
    const dairy = takeFromGroup(grouped.dairy, usedCount, limitPerDay, exclusions);
    if (dairy) items.push(dairy);
    const fruit = takeFromGroup(grouped.fruit, usedCount, limitPerDay, exclusions);
    if (fruit) items.push(fruit);

    // Add carb/protein if missing
    if (!items.some((i) => classifyFoodGroup(i) === 'carb')) {
      const carb = takeFromGroup(grouped.carb, usedCount, limitPerDay, exclusions);
      if (carb) items.push(carb);
    }
    if (!items.some((i) => classifyFoodGroup(i) === 'protein')) {
      const protein = takeFromGroup(grouped.protein, usedCount, limitPerDay, exclusions);
      if (protein) items.push(protein);
    }
  } else if (target === 'snack') {
    // Snacks: fruit/dairy first, else any leftover
    const fruit = takeFromGroup(grouped.fruit, usedCount, limitPerDay, exclusions);
    if (fruit) items.push(fruit);
    const dairy = takeFromGroup(grouped.dairy, usedCount, limitPerDay, exclusions);
    if (dairy && items.length < 2) items.push(dairy);
    if (items.length === 0) {
      const any =
        takeFromGroup(grouped.other, usedCount, limitPerDay, exclusions) ||
        takeFromGroup(grouped.vegetable, usedCount, limitPerDay, exclusions) ||
        takeFromGroup(grouped.carb, usedCount, limitPerDay, exclusions) ||
        takeFromGroup(grouped.protein, usedCount, limitPerDay, exclusions);
      if (any) items.push(any);
    }
  }

  const missing = mealMissingGroups(items);
  if (missing.length) suggestions.push(...suggestedAdditionsForMissing(missing));

  return { items, suggestedAdditions: uniq(suggestions) };
}

function computeSuggestedItemsToBuy(grouped) {
  const suggestionsByGroup = {
    protein: ['Eggs', 'Lentils (dal)', 'Greek yogurt', 'Paneer', 'Chickpeas'],
    vegetable: ['Spinach', 'Carrots', 'Tomatoes', 'Cucumbers', 'Mixed vegetables'],
    fruit: ['Bananas', 'Seasonal fruit (apples/oranges)', 'Berries'],
    carb: ['Whole wheat flour (atta)', 'Brown rice', 'Oats', 'Whole wheat bread'],
    dairy: ['Milk', 'Curd / yogurt'],
  };

  const missingGroups = [];
  for (const g of ['carb', 'protein', 'vegetable', 'fruit', 'dairy']) {
    if (!Array.isArray(grouped[g]) || grouped[g].length === 0) missingGroups.push(g);
  }

  const out = [];
  const availableSet = new Set(
    Object.values(grouped)
      .flat()
      .map(lower)
  );

  for (const g of missingGroups) {
    const candidates = suggestionsByGroup[g] || [];
    // Prefer suggestions not already present on the receipt list
    for (const c of candidates) {
      if (!availableSet.has(lower(c))) out.push(c);
    }
  }
  return uniq(out).slice(0, 12);
}

export function buildAiWeeklyMealPlan(itemNames, { dayNames = DEFAULT_DAYS } = {}) {
  const items = uniq(itemNames);
  const grouped = groupItems(items);
  const usedCount = new Map();
  const limitPerDay = 1;

  const days = dayNames.map((day) => {
    // Per-day repetition control: reset counts for each day
    usedCount.clear();

    const lunchExclude = new Set();
    const dinnerExclude = new Set();

    const breakfast = buildMeal({ grouped, usedCount, limitPerDay, target: 'breakfast' });
    breakfast.items.forEach((i) => lunchExclude.add(lower(i)));
    breakfast.items.forEach((i) => dinnerExclude.add(lower(i)));

    const lunch = buildMeal({ grouped, usedCount, limitPerDay, target: 'main', excludeSet: lunchExclude });
    lunch.items.forEach((i) => dinnerExclude.add(lower(i))); // prevent lunch=dinner duplication

    const dinner = buildMeal({ grouped, usedCount, limitPerDay, target: 'main', excludeSet: dinnerExclude });

    // Optional snack if we still have fruit/dairy not used today
    const snack = buildMeal({ grouped, usedCount, limitPerDay, target: 'snack' });
    const snacks = snack.items.length ? [snack] : [];

    return {
      day,
      meals: {
        breakfast,
        lunch,
        dinner,
        snacks,
      },
    };
  });

  const suggestedItemsToBuyNextTime = computeSuggestedItemsToBuy(grouped);

  return {
    days,
    suggestedItemsToBuyNextTime,
    meta: {
      inputItemCount: items.length,
    },
  };
}

