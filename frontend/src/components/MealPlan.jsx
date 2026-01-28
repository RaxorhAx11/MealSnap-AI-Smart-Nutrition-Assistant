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

function normalizeMeal(value) {
  if (value == null) return [];
  if (Array.isArray(value)) return value.map(String);
  if (typeof value === 'string') return value.trim() ? [value] : [];
  if (typeof value === 'object') {
    // e.g. { name, calories } or other structured meal objects
    if (typeof value.name === 'string') return [value.name];
    return [JSON.stringify(value)];
  }
  return [String(value)];
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
    const breakfast = normalizeMeal(d?.breakfast);
    const lunch = normalizeMeal(d?.lunch);
    const dinner = normalizeMeal(d?.dinner);
    const allMeals = [...breakfast, ...lunch, ...dinner];
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
  if (Array.isArray(day.daily_meal_plan) && day.daily_meal_plan.length > 0) {
    return day.daily_meal_plan;
  }
  return [
    ...(day.breakfast || []),
    ...(day.lunch || []),
    ...(day.dinner || []),
  ];
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
  const [isButtonHovered, setIsButtonHovered] = useState(false);
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
        
        // Call /generate-meal-plan endpoint - backend will automatically
        // fetch the latest confirmed items from the database
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
    const byName = new Map(normalized.map((d) => [String(d.day).toLowerCase(), d]));
    const ordered = DAY_ORDER.map((n) => byName.get(n.toLowerCase())).filter(Boolean);
    return ordered.length ? ordered : normalized;
  }, [raw]);

  // Generate recommendations based on the meal plan
  const recommendations = useMemo(() => {
    return generateRecommendations(days);
  }, [days]);

  // Styles for the meal plan UI
  const styles = {
    container: {
      maxWidth: '1200px',
      margin: '0 auto',
      padding: '24px',
      fontFamily: 'var(--font-family-sans, system-ui, -apple-system, Arial, sans-serif)',
    },
    title: {
      fontSize: '28px',
      fontWeight: 650,
      color: '#111827',
      marginBottom: 6,
      marginTop: 0,
      letterSpacing: '-0.02em',
    },
    subtitle: {
      fontSize: 14,
      color: '#6b7280',
      marginBottom: 24,
    },
    loadingContainer: {
      padding: '40px',
      textAlign: 'center',
      fontSize: '18px',
      color: '#6b7280',
    },
    errorContainer: {
      backgroundColor: '#fef2f2',
      border: '1px solid #fecaca',
      borderRadius: '8px',
      padding: '20px',
      marginBottom: '24px',
      color: '#991b1b',
    },
    errorTitle: {
      fontSize: '20px',
      fontWeight: '600',
      marginTop: '0',
      marginBottom: '8px',
    },
    tableSection: {
      marginTop: 20,
    },
    tableNote: {
      fontSize: 13,
      color: '#6b7280',
      fontStyle: 'italic',
      marginBottom: 10,
      marginTop: 0,
    },
    macrosLine: {
      fontSize: '13px',
      color: '#6b7280',
      marginTop: '4px',
    },
    emptyState: {
      textAlign: 'center',
      padding: '40px',
      color: '#6b7280',
      fontSize: '16px',
    },
    explanationSection: {
      backgroundColor: '#f0f9ff',
      border: '1px solid #bae6fd',
      borderRadius: 12,
      padding: 18,
      marginBottom: 24,
      marginTop: 8,
    },
    explanationTitle: {
      fontSize: '18px',
      fontWeight: '600',
      color: '#0c4a6e',
      marginTop: '0',
      marginBottom: '12px',
    },
    explanationText: {
      fontSize: '15px',
      color: '#075985',
      lineHeight: '1.6',
      margin: '0',
    },
    recommendationsSection: {
      marginTop: 32,
      paddingTop: 24,
      borderTop: '1px solid #e5e7eb',
    },
    recommendationsTitle: {
      fontSize: '24px',
      fontWeight: '600',
      color: '#111827',
      marginBottom: '16px',
      marginTop: '0',
    },
    recommendationsCard: {
      backgroundColor: '#f9fafb',
      border: '1px solid #e5e7eb',
      borderRadius: '12px',
      padding: '24px',
      marginTop: '16px',
    },
    recommendationItem: {
      padding: '16px 0',
      borderBottom: '1px solid #e5e7eb',
      fontSize: '15px',
      color: '#374151',
      lineHeight: '1.6',
    },
    recommendationItemLast: {
      padding: '16px 0',
      borderBottom: 'none',
      fontSize: '15px',
      color: '#374151',
      lineHeight: '1.6',
    },
    buttonContainer: {
      marginTop: 32,
      paddingTop: 24,
      borderTop: '1px solid #e5e7eb',
      display: 'flex',
      justifyContent: 'center',
    },
    purchaseSuggestionsSection: {
      marginTop: '48px',
      paddingTop: '32px',
      borderTop: '2px solid #e5e7eb',
    },
    purchaseSuggestionsTitle: {
      fontSize: '24px',
      fontWeight: '600',
      color: '#111827',
      marginBottom: '16px',
      marginTop: '0',
    },
    purchaseSuggestionsCard: {
      backgroundColor: '#f0fdf4',
      border: '1px solid #bbf7d0',
      borderRadius: '12px',
      padding: '24px',
      marginTop: '16px',
    },
    purchaseSuggestionsMessage: {
      fontSize: '15px',
      color: '#166534',
      lineHeight: '1.6',
      marginBottom: '16px',
      marginTop: '0',
    },
    purchaseSuggestionsList: {
      listStyle: 'none',
      padding: '0',
      margin: '0',
    },
    purchaseSuggestionsItem: {
      padding: '10px 0',
      paddingLeft: '24px',
      position: 'relative',
      fontSize: '15px',
      color: '#166534',
      lineHeight: '1.6',
    },
    purchaseSuggestionsBullet: {
      position: 'absolute',
      left: '8px',
      top: '14px',
      width: '6px',
      height: '6px',
      borderRadius: '50%',
      backgroundColor: '#16a34a',
    },
  };

  return (
    <div style={styles.container}>
      <h1 style={styles.title}>Weekly Meal Plan</h1>
      <p style={styles.subtitle}>
        Your personalized meal plan based on confirmed items and nutrition summary
      </p>

      {/* Explanation section */}
      {!loading && !error && (
        <div style={styles.explanationSection}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h2 style={{ ...styles.explanationTitle, marginBottom: 0 }}>How this plan was built</h2>
            <button
              onClick={reloadMealPlan}
              disabled={loading}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: '1px solid #0c4a6e',
                background: '#0c4a6e',
                color: '#fff',
                cursor: loading ? 'not-allowed' : 'pointer',
                fontSize: '14px',
                fontWeight: '500',
              }}
            >
              {loading ? 'Refreshing...' : 'Refresh Meal Plan'}
            </button>
          </div>
          <p style={styles.explanationText}>
            This plan is generated from your confirmed items and latest nutrition summary. Each day has a simple
            daily meal list with estimated calories and macros, compared against a general daily target (e.g. 2000 kcal).
          </p>
        </div>
      )}

      {/* Show loading message while generating meal plan */}
      {loading && (
        <div style={styles.loadingContainer}>
          Generating meal plan...
        </div>
      )}

      {/* Error display */}
      {error && (
        <div style={styles.errorContainer}>
          <h3 style={styles.errorTitle}>Error</h3>
          <p>{typeof error === 'string' ? error : formatErrorMessage(error)}</p>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && days.length === 0 && (
        <div style={styles.emptyState}>
          No meal plan available. Please analyze nutrition first to generate a meal plan.
        </div>
      )}

      {/* Weekly meal plan table (daily targets format) */}
      {!loading && !error && days.length > 0 && (
        <div style={styles.tableSection}>
          <p style={styles.tableNote}>
            Daily targets are approximate and based on general guidelines.
          </p>
          {/* Desktop/tablet: table view */}
          <div className="mealplan-table-wrapper">
            <table className="mealplan-table">
              <thead>
                <tr>
                  <th>Day</th>
                  <th>Daily meal plan</th>
                  <th>Total today</th>
                  <th>Target</th>
                </tr>
              </thead>
              <tbody>
                {days.map((day) => {
                  const nutrition = day.total_nutrition_today ?? {};
                  const target = day.daily_target ?? {};
                  const status = target.status || 'N/A';
                  const statusColor =
                    status === 'Met'
                      ? '#16a34a'
                      : status === 'Deficit'
                        ? '#f59e0b'
                        : status === 'Excess'
                          ? '#ef4444'
                          : '#6b7280';
                  return (
                    <tr key={String(day.day)}>
                      <td>
                        <strong>{String(day.day)}</strong>
                      </td>
                      <td>
                        {Array.isArray(day.daily_meal_plan) && day.daily_meal_plan.length > 0
                          ? day.daily_meal_plan.join(', ')
                          : '—'}
                      </td>
                      <td>
                        {typeof nutrition.calories === 'number' ? (
                          <div>
                            <strong>{Math.round(nutrition.calories)} kcal</strong>
                            {[nutrition.protein, nutrition.carbs, nutrition.fats].some(
                              (v) => typeof v === 'number',
                            ) && (
                              <div style={styles.macrosLine}>
                                P: {Math.round(nutrition.protein ?? 0)}g, C:{' '}
                                {Math.round(nutrition.carbs ?? 0)}g, F:{' '}
                                {Math.round(nutrition.fats ?? 0)}g
                              </div>
                            )}
                          </div>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td>
                        {typeof target.target_calories === 'number' ? (
                          <div>
                            <strong>{target.target_calories} kcal</strong>
                            <div
                              style={{
                                ...styles.macrosLine,
                                color: statusColor,
                                fontWeight: 500,
                              }}
                            >
                              {status}
                            </div>
                          </div>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile: stacked cards */}
          <div className="mealplan-cards">
            {days.map((day) => {
              const nutrition = day.total_nutrition_today ?? {};
              const target = day.daily_target ?? {};
              const status = target.status || 'N/A';
              const statusClass =
                status === 'Met'
                  ? 'mealplan-status-met'
                  : status === 'Deficit'
                    ? 'mealplan-status-deficit'
                    : status === 'Excess'
                      ? 'mealplan-status-excess'
                      : 'mealplan-status-na';

              return (
                <div key={String(day.day)} className="mealplan-card">
                  <div className="mealplan-card-header">
                    <div className="mealplan-day">{String(day.day)}</div>
                    <div className={`mealplan-status-pill ${statusClass}`}>
                      <span className="mealplan-status-pill-dot" />
                      <span>{status}</span>
                    </div>
                  </div>
                  <div className="mealplan-macros">
                    {typeof nutrition.calories === 'number' ? (
                      <>
                        <strong>{Math.round(nutrition.calories)} kcal</strong>
                        {[nutrition.protein, nutrition.carbs, nutrition.fats].some(
                          (v) => typeof v === 'number',
                        ) && (
                          <>
                            {'  •  '}
                            P: {Math.round(nutrition.protein ?? 0)}g, C:{' '}
                            {Math.round(nutrition.carbs ?? 0)}g, F:{' '}
                            {Math.round(nutrition.fats ?? 0)}g
                          </>
                        )}
                      </>
                    ) : (
                      'No nutrition data'
                    )}
                    {typeof target.target_calories === 'number' && (
                      <>  • Target: {target.target_calories} kcal</>
                    )}
                  </div>
                  <div className="mealplan-meals">
                    {Array.isArray(day.daily_meal_plan) && day.daily_meal_plan.length > 0
                      ? day.daily_meal_plan.join(', ')
                      : 'No meals listed for this day.'}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Recommendations Section */}
      {!loading && !error && days.length > 0 && recommendations.length > 0 && (
        <div style={styles.recommendationsSection}>
          <h2 style={styles.recommendationsTitle}>Meal Plan Recommendations</h2>
          <div style={styles.recommendationsCard}>
            {recommendations.map((rec, index) => (
              <div
                key={index}
                style={
                  index === recommendations.length - 1
                    ? styles.recommendationItemLast
                    : styles.recommendationItem
                }
              >
                {rec}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Purchase Suggestions Section */}
      {!suggestionsLoading && !suggestionsError && purchaseSuggestions && (
        <div style={styles.purchaseSuggestionsSection}>
          <h2 style={styles.purchaseSuggestionsTitle}>What to Buy in Your Next Grocery Trip</h2>
          <div style={styles.purchaseSuggestionsCard}>
            {purchaseSuggestions.message && (
              <p style={styles.purchaseSuggestionsMessage}>
                {purchaseSuggestions.message}
              </p>
            )}
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
                        {reason && (
                          <p className="purchase-card-reason">
                            {reason}
                          </p>
                        )}
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
              <p style={styles.purchaseSuggestionsMessage}>
                Your nutrition intake looks balanced. No specific recommendations at this time.
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
      <div style={styles.buttonContainer}>
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

