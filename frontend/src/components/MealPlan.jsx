import React, { useMemo, useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { generateMealPlan, fetchPurchaseSuggestions } from '../services/api';

const DAY_ORDER = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
];

function normalizeMealItems(value) {
  if (value == null) return [];
  if (Array.isArray(value)) return value.filter(Boolean).map((v) => (typeof v === 'string' ? { name: v } : v));
  if (typeof value === 'string') return value.trim() ? [{ name: value.trim() }] : [];
  if (typeof value === 'object') return [value];
  return [{ name: String(value) }];
}

function formatPortion(item) {
  const q = item?.portion?.quantity;
  const u = item?.portion?.unit;
  if (typeof q === 'number' && Number.isFinite(q) && typeof u === 'string' && u.trim()) {
    return `${q} ${u}`.trim();
  }
  return null;
}

function formatMacros(item) {
  const m = item?.macros;
  if (!m || typeof m !== 'object') return null;
  const cal = typeof m.calories === 'number' ? Math.round(m.calories) : null;
  const p = typeof m.protein === 'number' ? Math.round(m.protein) : null;
  const c = typeof m.carbs === 'number' ? Math.round(m.carbs) : null;
  const f = typeof m.fats === 'number' ? Math.round(m.fats) : null;
  if (cal == null) return null;
  return { cal, p, c, f };
}

function getCalories(dayObj) {
  const candidates = [
    dayObj?.estimatedCalories,
    dayObj?.estimated_calories,
    dayObj?.calories,
    dayObj?.totalCalories,
    dayObj?.total_calories,
    dayObj?.calorie_estimate,
    dayObj?.total_nutrition_today?.calories,
  ];
  const found = candidates.find((v) => typeof v === 'number' && Number.isFinite(v));
  return found ?? null;
}

/**
 * Normalize API response into a unified day format.
 * Supports both NEW format (daily_meal_plan, total_nutrition_today, daily_target)
 * and OLD format (breakfast, lunch, dinner, estimated_calories).
 */
function normalizeMealPlan(apiResponse) {
  // Handle the response structure: { success: true, plan: { days: [...] }, message: "..." }
  // The plan object contains the days array
  const maybePlan =
    apiResponse?.plan ??
    apiResponse?.meal_plan ??
    apiResponse?.mealPlan ??
    apiResponse?.week_plan ??
    apiResponse?.weekly_meal_plan ??
    apiResponse;

  // Extract days array - it could be directly in maybePlan or in maybePlan.days
  const daysArray = Array.isArray(maybePlan) 
    ? maybePlan 
    : (Array.isArray(maybePlan?.days) 
        ? maybePlan.days 
        : null);
  
  if (!Array.isArray(daysArray) || daysArray.length === 0) {
    console.warn('No days array found in meal plan response:', apiResponse);
    return [];
  }

  return daysArray.map((d, idx) => {
    const dayName = d?.day ?? d?.dayName ?? d?.name ?? DAY_ORDER[idx] ?? `Day ${idx + 1}`;

    // v3 format: breakfast/lunch/dinner arrays of structured items
    if (Array.isArray(d?.breakfast) || Array.isArray(d?.lunch) || Array.isArray(d?.dinner)) {
      const breakfast = normalizeMealItems(d?.breakfast);
      const lunch = normalizeMealItems(d?.lunch);
      const dinner = normalizeMealItems(d?.dinner);
      const calories = getCalories(d);
      const target = typeof d?.calorie_target === 'number' ? d.calorie_target : 2000;
      const status =
        d?.status ||
        d?.daily_target?.status ||
        (typeof calories === 'number'
          ? calories < target * 0.9
            ? 'Deficit'
            : calories > target * 1.1
              ? 'Excess'
              : 'Near Target'
          : 'N/A');

      return {
        day: String(dayName),
        breakfast,
        lunch,
        dinner,
        daily_meal_plan: [],
        total_nutrition_today: d?.total_macros ?? d?.total_nutrition_today ?? {
          calories: typeof calories === 'number' ? calories : 0,
          protein: 0,
          carbs: 0,
          fats: 0,
        },
        daily_target: { target_calories: target, status },
        calories: typeof calories === 'number' ? calories : null,
      };
    }

    // NEW format: daily_meal_plan, total_nutrition_today, daily_target
    if (d?.daily_meal_plan && Array.isArray(d.daily_meal_plan)) {
      return {
        day: String(dayName),
        daily_meal_plan: d.daily_meal_plan,
        total_nutrition_today: d.total_nutrition_today ?? {
          calories: 0,
          protein: 0,
          carbs: 0,
          fats: 0,
        },
        daily_target: d.daily_target ?? {
          target_calories: 2000,
          status: 'N/A',
        },
        // For recommendations: flatten to "all meals"
        breakfast: [],
        lunch: d.daily_meal_plan,
        dinner: [],
        calories: d.total_nutrition_today?.calories ?? getCalories(d),
      };
    }

    // OLD format: breakfast, lunch, dinner
    const breakfast = normalizeMealItems(d?.breakfast);
    const lunch = normalizeMealItems(d?.lunch);
    const dinner = normalizeMealItems(d?.dinner);
    const allMeals = [...breakfast, ...lunch, ...dinner]
      .map((x) => (typeof x === 'string' ? x : x?.name))
      .filter(Boolean);
    const calories = getCalories(d);
    const target = 2000;
    const status =
      typeof calories === 'number'
        ? calories < target * 0.9
          ? 'Deficit'
          : calories > target * 1.1
            ? 'Excess'
            : 'Met'
        : 'N/A';

    return {
      day: String(dayName),
      daily_meal_plan: allMeals,
      total_nutrition_today: {
        calories: typeof calories === 'number' ? calories : 0,
        protein: 0,
        carbs: 0,
        fats: 0,
      },
      daily_target: { target_calories: target, status },
      breakfast,
      lunch,
      dinner,
      calories,
    };
  });
}

function formatErrorMessage(e) {
  if (!e) return 'Failed to generate meal plan';
  if (typeof e === 'string') return e;
  if (e instanceof Error && typeof e.message === 'string') return e.message;
  if (typeof e?.message === 'string') return e.message;
  if (typeof e?.detail === 'string') return e.detail;
  try {
    return JSON.stringify(e);
  } catch {
    return String(e);
  }
}

/** Get all meal items for a day (daily_meal_plan or breakfast+lunch+dinner). */
function getAllMealsForDay(day) {
  const b = Array.isArray(day.breakfast) ? day.breakfast : [];
  const l = Array.isArray(day.lunch) ? day.lunch : [];
  const d = Array.isArray(day.dinner) ? day.dinner : [];
  const structured = [...b, ...l, ...d]
    .map((x) => (typeof x === 'string' ? x : x?.name))
    .filter(Boolean);
  if (structured.length > 0) return structured;
  if (Array.isArray(day.daily_meal_plan) && day.daily_meal_plan.length > 0) return day.daily_meal_plan;
  return [];
}

/**
 * Analyzes the meal plan and generates friendly, rule-based recommendations.
 * Works with both daily_meal_plan format and legacy breakfast/lunch/dinner.
 * @param {Array} days - Array of day objects with meals and calories
 * @returns {Array} Array of recommendation strings
 */
function generateRecommendations(days) {
  if (!days || days.length === 0) {
    return [];
  }

  const recommendations = [];

  // 1. Daily coverage - check if each day has items planned
  const daysWithItems = days.filter((d) => getAllMealsForDay(d).length > 0).length;
  if (daysWithItems < days.length / 2) {
    recommendations.push(
      "💡 Try to include a variety of items for each day. Having a balanced daily meal plan helps maintain steady energy levels."
    );
  } else if (daysWithItems === days.length) {
    recommendations.push(
      "✨ Great job! You have items planned for every day. This balanced approach supports consistent nutrition."
    );
  }

  // 2. Protein intake
  const proteinKeywords = [
    'chicken', 'beef', 'pork', 'fish', 'salmon', 'tuna', 'turkey', 'lamb',
    'egg', 'eggs', 'tofu', 'tempeh', 'beans', 'lentil', 'chickpea', 'protein',
    'yogurt', 'cheese', 'milk', 'paneer', 'dal', 'pulses', 'meat', 'poultry'
  ];
  let totalMeals = 0;
  let mealsWithProtein = 0;
  days.forEach((day) => {
    getAllMealsForDay(day).forEach((meal) => {
      totalMeals++;
      if (proteinKeywords.some((kw) => String(meal).toLowerCase().includes(kw))) {
        mealsWithProtein++;
      }
    });
  });
  const proteinPct = totalMeals > 0 ? (mealsWithProtein / totalMeals) * 100 : 0;
  if (proteinPct < 30) {
    recommendations.push(
      "🥩 Consider adding more protein-rich foods like chicken, fish, eggs, beans, or lentils. Protein helps keep you full and supports muscle health."
    );
  } else if (proteinPct >= 30 && proteinPct < 50) {
    recommendations.push(
      "👍 You're including a good amount of protein. Keep it up for balanced nutrition!"
    );
  }

  // 3. Vegetable intake
  const vegetableKeywords = [
    'vegetable', 'vegetables', 'salad', 'spinach', 'broccoli', 'carrot', 'tomato',
    'cucumber', 'pepper', 'onion', 'cabbage', 'cauliflower', 'green', 'leafy',
    'lettuce', 'kale', 'coriander', 'mint', 'sabzi', 'sabji'
  ];
  let mealsWithVeg = 0;
  days.forEach((day) => {
    getAllMealsForDay(day).forEach((meal) => {
      if (vegetableKeywords.some((kw) => String(meal).toLowerCase().includes(kw))) {
        mealsWithVeg++;
      }
    });
  });
  const vegPct = totalMeals > 0 ? (mealsWithVeg / totalMeals) * 100 : 0;
  if (vegPct < 40) {
    recommendations.push(
      "🥬 Adding more vegetables would boost your nutrition. Try a side salad, steamed veggies, or vegetables in main dishes."
    );
  } else if (vegPct >= 40) {
    recommendations.push(
      "🌱 Excellent! You're including plenty of vegetables. They provide essential vitamins and fiber."
    );
  }

  // 4. Calorie distribution and daily target status
  const calories = days
    .map((d) => d.total_nutrition_today?.calories ?? d.calories)
    .filter((c) => typeof c === 'number' && c > 0);
  if (calories.length > 1) {
    const avg = calories.reduce((s, c) => s + c, 0) / calories.length;
    const range = Math.max(...calories) - Math.min(...calories);
    const variation = (range / avg) * 100;
    if (variation > 30) {
      recommendations.push(
        "⚖️ Daily calories vary quite a bit. For more consistent energy, aim for more even distribution across the week."
      );
    } else if (variation < 15 && avg > 0) {
      recommendations.push(
        "📊 Your calorie distribution looks balanced across the week. This helps maintain steady energy levels."
      );
    }
  }

  const deficitCount = days.filter((d) => d.daily_target?.status === 'Deficit').length;
  const excessCount = days.filter((d) => d.daily_target?.status === 'Excess').length;
  if (deficitCount > days.length / 2) {
    recommendations.push(
      "📉 Many days are below your calorie target. Consider adding a bit more variety or portion sizes to meet your daily goals."
    );
  } else if (excessCount > days.length / 2) {
    recommendations.push(
      "📈 Many days exceed your calorie target. You might reduce portions or swap some items for lighter options."
    );
  }

  if (recommendations.length < 3) {
    recommendations.push(
      "💧 Remember to stay hydrated. Water supports digestion and helps your body process nutrients effectively."
    );
  }

  return recommendations.slice(0, 4);
}

export default function MealPlan() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [raw, setRaw] = useState(null);
  const [purchaseSuggestions, setPurchaseSuggestions] = useState(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [suggestionsError, setSuggestionsError] = useState(null);
  
  // Function to reload meal plan
  const reloadMealPlan = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await generateMealPlan({});
      setRaw(data);
    } catch (err) {
      setError(formatErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  /**
   * Automatically generate meal plan on component mount
   * Calls /generate-meal-plan endpoint inside useEffect
   * Uses confirmed items and nutrition summary stored in the backend
   * No manual input required - items are automatically fetched from database
   */
  useEffect(() => {
    const loadMealPlan = async () => {
      try {
        setLoading(true);
        setError(null);
        setRaw(null);

        // Generate backend meal plan (uses confirmed items + nutrition gaps + user calorie target).
        const data = await generateMealPlan({});
        setRaw(data);
      } catch (err) {
        console.error('Error loading meal plan:', err);
        setError(formatErrorMessage(err));
      } finally {
        setLoading(false);
      }
    };

    // Load meal plan automatically when component mounts
    loadMealPlan();
  }, []); // Empty dependency array - only run on mount

  /**
   * Fetch purchase suggestions based on stored nutrition summary
   * This runs independently of meal plan loading
   */
  useEffect(() => {
    const loadPurchaseSuggestions = async () => {
      try {
        setSuggestionsLoading(true);
        setSuggestionsError(null);
        const data = await fetchPurchaseSuggestions();
        setPurchaseSuggestions(data);
      } catch (err) {
        // Don't show error if it's 404 (no nutrition data yet)
        if (err.message && err.message.includes('404')) {
          setPurchaseSuggestions(null);
        } else {
          setSuggestionsError(formatErrorMessage(err));
        }
      } finally {
        setSuggestionsLoading(false);
      }
    };

    loadPurchaseSuggestions();
  }, []); // Empty dependency array - only run on mount

  const days = useMemo(() => {
    if (!raw) return [];
    const normalized = normalizeMealPlan(raw);
    const looksLikeDayLabels = normalized.some((d) => String(d?.day || '').toLowerCase().startsWith('day-'));
    if (looksLikeDayLabels) return normalized;
    const byName = new Map(normalized.map((d) => [String(d.day).toLowerCase(), d]));
    const ordered = DAY_ORDER.map((n) => byName.get(n.toLowerCase())).filter(Boolean);
    return ordered.length ? ordered : normalized;
  }, [raw]);

  const addSuggestions = useMemo(() => {
    const maybePlan = raw?.plan ?? raw;
    const daysArray = Array.isArray(maybePlan) ? maybePlan : Array.isArray(maybePlan?.days) ? maybePlan.days : [];
    const first = Array.isArray(daysArray) && daysArray.length > 0 ? daysArray[0] : null;
    const suggestions = first?.suggested_additions;
    if (!Array.isArray(suggestions)) return [];
    return suggestions
      .map((s) => ({
        food: typeof s?.food === 'string' ? s.food : null,
        nutrition_benefit: typeof s?.nutrition_benefit === 'string' ? s.nutrition_benefit : null,
      }))
      .filter((x) => x.food && x.nutrition_benefit);
  }, [raw]);

  // Generate recommendations based on the meal plan
  const recommendations = useMemo(() => {
    return generateRecommendations(days);
  }, [days]);

  return (
    <div className="advisor-page">
      <div className="advisor-header">
        <div>
          <h1 className="advisor-title">AI Nutrition Advisor Meal Plan</h1>
          <p className="advisor-subtitle">
            Balanced meals built from your grocery receipt items, with smart additions when needed.
          </p>
        </div>
      </div>

      {/* Explanation section */}
      {!loading && !error && (
        <div className="advisor-card advisor-explainer">
          <div className="advisor-explainer-row">
            <h2 className="advisor-section-title" style={{ margin: 0 }}>How this plan is built</h2>
            <button type="button" className="btn btn-secondary" onClick={reloadMealPlan} disabled={loading}>
              Refresh
            </button>
          </div>
          <p className="advisor-explainer-text">
            Your receipt items are prioritized first. Each main meal aims for <strong>carbs + protein</strong>, plus
            daily <strong>fruits/vegetables</strong>. If a meal is missing a nutrition group, you&apos;ll see suggested
            additions.
          </p>
        </div>
      )}

      {/* Show loading message while generating meal plan */}
      {loading && (
        <div className="advisor-loading">Generating meal plan…</div>
      )}

      {/* Error display */}
      {error && (
        <div className="advisor-error">
          <strong>Error:</strong> {typeof error === 'string' ? error : formatErrorMessage(error)}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && days.length === 0 && (
        <div className="advisor-empty">
          No meal plan available yet. Upload a receipt and analyze nutrition first.
        </div>
      )}

      {/* Weekly meal plan (backend v3) */}
      {!loading && !error && days.length > 0 && (
        <div className="advisor-section">
          <h2 className="advisor-section-title">3-day meal plan</h2>
          <div className="advisor-day-grid">
            {days.map((day) => {
              const dayCalories = day?.total_nutrition_today?.calories ?? day?.calories;
              const status = day?.daily_target?.status ?? '—';

              const renderMeal = (title, items) => (
                <div className="advisor-meal-card">
                  <div className="advisor-meal-title">{title}</div>
                  {Array.isArray(items) && items.length > 0 ? (
                    <ul className="advisor-bullets" style={{ marginTop: 8 }}>
                      {items.map((it, idx) => {
                        const name = typeof it === 'string' ? it : it?.name;
                        const portion = formatPortion(it);
                        const macros = formatMacros(it);
                        const why = it?.why;
                        return (
                          <li key={`${title}-${idx}-${name || 'item'}`}>
                            <div>
                              <strong>{name || '—'}</strong>
                              {portion ? ` (${portion})` : ''}
                              {macros ? ` → ${macros.cal} kcal` : ''}
                              {macros ? (
                                <span className="text-muted">
                                  {`  •  P ${macros.p ?? 0}g  C ${macros.c ?? 0}g  F ${macros.f ?? 0}g`}
                                </span>
                              ) : null}
                            </div>
                            {why?.nutrition_benefit ? (
                              <div className="text-muted" style={{ marginTop: 4 }}>
                                {why?.nutrition_benefit ? <div><strong>Benefit:</strong> {why.nutrition_benefit}</div> : null}
                              </div>
                            ) : null}
                          </li>
                        );
                      })}
                    </ul>
                  ) : (
                    <div className="text-muted">—</div>
                  )}
                </div>
              );

              return (
                <div key={String(day.day)} className="advisor-day-card">
                  <div className="advisor-day-header">
                    <div className="advisor-day-title">{String(day.day)}</div>
                    <div className="advisor-day-badge">
                      {typeof dayCalories === 'number' ? `${Math.round(dayCalories)} kcal` : '—'} • {status}
                    </div>
                  </div>
                  <div className="advisor-meal-grid">
                    {renderMeal('Breakfast', day.breakfast)}
                    {renderMeal('Lunch', day.lunch)}
                    {renderMeal('Dinner', day.dinner)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* What to add next + what you get */}
      {!loading && !error && addSuggestions.length > 0 && (
        <div className="advisor-section">
          <h2 className="advisor-section-title">What to add next (and what you get)</h2>
          <div className="advisor-card">
            <div className="purchase-list">
              {addSuggestions.map((s, idx) => (
                <div key={`${s.food}-${idx}`} className="purchase-card">
                  <div className="purchase-card-body">
                    <p className="purchase-card-title">{s.food}</p>
                    <div className="purchase-card-benefit">
                      <span className="purchase-card-benefit-dot" />
                      <span>{s.nutrition_benefit}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Recommendations Section */}
      {!loading && !error && days.length > 0 && recommendations.length > 0 && (
        <div className="advisor-section">
          <h2 className="advisor-section-title">Nutrition recommendations</h2>
          <div className="advisor-card">
            <ul className="advisor-bullets">
              {recommendations.map((rec, index) => (
                <li key={index}>{rec}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Backend purchase suggestions (kept for compatibility; shown as an additional advisor insight) */}
      {!suggestionsLoading && !suggestionsError && purchaseSuggestions && (
        <div className="advisor-section">
          <h2 className="advisor-section-title">Additional nutrition suggestions</h2>
          <div className="advisor-card">
            {purchaseSuggestions.message && <p className="advisor-paragraph">{purchaseSuggestions.message}</p>}
            {purchaseSuggestions.suggestions && purchaseSuggestions.suggestions.length > 0 ? (
              <div className="purchase-list">
                {purchaseSuggestions.suggestions.map((item, index) => {
                  const foodName = typeof item === 'string' ? item : item.food || item.food_name;
                  const reason = typeof item === 'object' ? item.reason : null;
                  const nutritionBenefit = typeof item === 'object' ? item.nutrition_benefit : null;

                  return (
                    <div key={index} className="purchase-card">
                      <div className="purchase-card-body">
                        <p className="purchase-card-title">{foodName}</p>
                        {reason && <p className="purchase-card-reason">{reason}</p>}
                        {nutritionBenefit && (
                          <div className="purchase-card-benefit">
                            <span className="purchase-card-benefit-dot" />
                            <span>{nutritionBenefit}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="advisor-paragraph text-muted">
                No specific recommendations at this time.
              </p>
            )}
          </div>
        </div>
      )}

      {/* Navigation Button: Go to Dashboard */}
      {/* 
        This button allows users to navigate back to the Dashboard page.
        It does not regenerate the meal plan - it simply redirects to the Dashboard
        where previously saved nutrition summary and meal plan data will be displayed.
      */}
      <div className="advisor-footer">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => navigate('/dashboard')}
        >
          Go to Dashboard
        </button>
      </div>
    </div>
  );
}

