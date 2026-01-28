import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { fetchDashboardData, saveWeight, fetchDashboardNutrition, fetchPurchaseSuggestions } from '../services/api';
import { TOKEN_KEY } from './ProtectedRoute';

import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  ArcElement,
  BarElement,
  Tooltip,
  Legend,
} from 'chart.js';
import { Line, Pie } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  ArcElement,
  BarElement,
  Tooltip,
  Legend
);

function fmtNumber(n, digits = 0) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return '—';
  return n.toFixed(digits);
}

function isoToday() {
  const d = new Date();
  // local date -> YYYY-MM-DD (no timezone shifting)
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function lastN(arr, n) {
  if (!Array.isArray(arr)) return [];
  return arr.slice(Math.max(0, arr.length - n));
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  
  // State for latest nutrition summary from /dashboard-nutrition endpoint
  // This is the stored nutrition data (not recalculated)
  const [dashboardNutrition, setDashboardNutrition] = useState(null);
  const [nutritionLoading, setNutritionLoading] = useState(false);
  const [nutritionError, setNutritionError] = useState(null);

  // State for purchase suggestions
  const [purchaseSuggestions, setPurchaseSuggestions] = useState(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [suggestionsError, setSuggestionsError] = useState(null);

  const [weightInput, setWeightInput] = useState('');
  const [weightSaving, setWeightSaving] = useState(false);
  const [weightSaveError, setWeightSaveError] = useState(null);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchDashboardData({ days: 30 });
      setDashboard(data);
    } catch (e) {
      setError(e?.message || 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  };

  // Load latest nutrition summary from /dashboard-nutrition endpoint
  // This reads the stored nutrition data (not recalculated)
  const loadDashboardNutrition = async () => {
    try {
      setNutritionLoading(true);
      setNutritionError(null);
      const data = await fetchDashboardNutrition();
      setDashboardNutrition(data);
    } catch (e) {
      // 404 is expected if no nutrition data exists yet
      if (e?.message?.includes('404') || e?.message?.includes('No nutrition')) {
        setNutritionError(null); // Don't show error for missing data
        setDashboardNutrition(null);
      } else {
        setNutritionError(e?.message || 'Failed to load nutrition summary');
      }
    } finally {
      setNutritionLoading(false);
    }
  };

  // Load purchase suggestions based on stored nutrition summary
  const loadPurchaseSuggestions = async () => {
    try {
      setSuggestionsLoading(true);
      setSuggestionsError(null);
      const data = await fetchPurchaseSuggestions();
      setPurchaseSuggestions(data);
    } catch (e) {
      // 404 is expected if no nutrition data exists yet
      if (e?.message?.includes('404') || e?.message?.includes('No nutrition')) {
        setSuggestionsError(null); // Don't show error for missing data
        setPurchaseSuggestions(null);
      } else {
        setSuggestionsError(e?.message || 'Failed to load purchase suggestions');
      }
    } finally {
      setSuggestionsLoading(false);
    }
  };

  useEffect(() => {
    load();
    loadDashboardNutrition();
    loadPurchaseSuggestions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Use dashboard nutrition from /dashboard-nutrition endpoint (stored data)
  // This matches the data shown on Nutrition Summary page
  // Fallback to historical data if dashboard nutrition is not available
  const latestNutrition = useMemo(() => {
    // Priority: Use stored nutrition from /dashboard-nutrition endpoint
    if (dashboardNutrition) {
      return {
        calories: dashboardNutrition.calories,
        protein: dashboardNutrition.protein,
        carbs: dashboardNutrition.carbs,
        fats: dashboardNutrition.fats,
        date: dashboardNutrition.date,
      };
    }
    // Fallback: Use historical data from /dashboard endpoint
    const hist = dashboard?.nutrition_history;
    if (!Array.isArray(hist) || hist.length === 0) return null;
    return hist[hist.length - 1]; // backend returns asc order
  }, [dashboard, dashboardNutrition]);

  const nutritionLast7 = useMemo(() => lastN(dashboard?.nutrition_history, 7), [dashboard]);
  const weightHist = useMemo(() => dashboard?.weight_history ?? [], [dashboard]);

  const macroPie = useMemo(() => {
    const p = latestNutrition?.protein ?? 0;
    const c = latestNutrition?.carbs ?? 0;
    const f = latestNutrition?.fats ?? 0;
    return {
      data: {
        labels: ['Protein (g)', 'Carbs (g)', 'Fats (g)'],
        datasets: [
          {
            data: [p, c, f],
            backgroundColor: ['#3b82f6', '#22c55e', '#f59e0b'],
            borderColor: ['#2563eb', '#16a34a', '#d97706'],
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { position: 'bottom' },
          tooltip: { enabled: true },
        },
      },
    };
  }, [latestNutrition]);

  const weightLine = useMemo(() => {
    const labels = (Array.isArray(weightHist) ? weightHist : []).map((w) => String(w.date));
    const values = (Array.isArray(weightHist) ? weightHist : []).map((w) =>
      typeof w.weight === 'number' ? w.weight : null
    );
    return {
      data: {
        labels,
        datasets: [
          {
            label: 'Weight (kg)',
            data: values,
            borderColor: '#7c3aed',
            backgroundColor: 'rgba(124, 58, 237, 0.15)',
            tension: 0.25,
            pointRadius: 3,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { position: 'bottom' } },
        scales: {
          x: { ticks: { maxRotation: 0, autoSkip: true } },
        },
      },
    };
  }, [weightHist]);

  const handleLogout = () => {
    localStorage.removeItem(TOKEN_KEY);
    navigate('/login', { replace: true });
  };

  const handleSaveWeight = async () => {
    setWeightSaveError(null);
    const parsed = Number(weightInput);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setWeightSaveError('Enter a valid weight in kg (e.g. 72.5)');
      return;
    }

    try {
      setWeightSaving(true);
      await saveWeight({ date: isoToday(), weight: parsed });
      setWeightInput('');
      await load();
    } catch (e) {
      setWeightSaveError(e?.message || 'Failed to save weight');
    } finally {
      setWeightSaving(false);
    }
  };

  // Weekly meal plan (read-only): render if backend provides it, else show placeholder.
  // Reads from stored data only - does not regenerate
  // NEW FORMAT: Uses daily meal plans instead of breakfast/lunch/dinner
  const weeklyPlanDays = useMemo(() => {
    const plan =
      dashboard?.weekly_meal_plan ??
      dashboard?.meal_plan ??
      dashboard?.mealPlan ??
      dashboard?.plan;
    
    if (!plan) return [];
    
    // Extract days array from the plan structure
    const days = plan?.days ?? plan?.Days ?? null;
    if (!Array.isArray(days)) return [];
    
    // Map to new format - handle both old and new formats
    return days.map((day, idx) => {
      // Check if this is the new format (has daily_meal_plan)
      if (day.daily_meal_plan && Array.isArray(day.daily_meal_plan)) {
        // New format: daily meal plan
        return {
          day: day.day || `Day ${idx + 1}`,
          daily_meal_plan: day.daily_meal_plan,
          total_nutrition_today: day.total_nutrition_today || {
            calories: 0,
            protein: 0,
            carbs: 0,
            fats: 0
          },
          daily_target: day.daily_target || {
            target_calories: 2000,
            status: 'N/A'
          }
        };
      }
      
      // Old format: breakfast/lunch/dinner (for backward compatibility)
      const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
      const dayNum = typeof day.day === 'number' ? day.day : idx + 1;
      const dayName = dayNum >= 1 && dayNum <= 7 ? DAY_NAMES[dayNum - 1] : DAY_NAMES[idx] || `Day ${dayNum}`;
      
      const normalizeMeal = (meal) => {
        if (!meal) return '';
        if (Array.isArray(meal)) return meal.join(', ');
        if (typeof meal === 'string') return meal;
        return String(meal);
      };
      
      // Convert old format to new format for display
      const allMeals = [
        normalizeMeal(day.breakfast),
        normalizeMeal(day.lunch),
        normalizeMeal(day.dinner)
      ].filter(m => m);
      
      const calories = day.estimated_calories ?? day.calories ?? 0;
      const target = 2000;
      const status = calories < target * 0.9 ? 'Deficit' : 
                     calories > target * 1.1 ? 'Excess' : 'Met';
      
      return {
        day: dayName,
        daily_meal_plan: allMeals,
        total_nutrition_today: {
          calories: calories,
          protein: 0, // Old format doesn't have macros
          carbs: 0,
          fats: 0
        },
        daily_target: {
          target_calories: target,
          status: status
        }
      };
    });
  }, [dashboard]);

  const styles = {
    page: {
      padding: 16,
      maxWidth: 1100,
      margin: '0 auto',
      fontFamily: 'var(--font-family-sans, system-ui, Arial)',
    },
    header: {
      display: 'flex',
      alignItems: 'flex-start',
      justifyContent: 'space-between',
      gap: 12,
      marginBottom: 16,
    },
    nav: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      fontSize: 14,
    },
    grid2: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
      gap: 12,
    },
    grid4: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
      gap: 12,
    },
    card: {
      border: '1px solid #e5e7eb',
      borderRadius: 12,
      padding: 14,
      background: '#fff',
      boxShadow: '0 18px 45px rgba(15, 23, 42, 0.05)',
      transition: 'transform 0.12s ease-out, box-shadow 0.12s ease-out',
    },
    cardTitle: { fontSize: 13, color: '#6b7280', margin: 0 },
    cardValue: { fontSize: 22, fontWeight: 700, margin: '6px 0 0 0' },
    sectionTitle: { margin: '0 0 10px 0', fontSize: 16 },
    small: { fontSize: 12, color: '#6b7280' },
    row: { display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' },
    input: { padding: 8, borderRadius: 8, border: '1px solid #d1d5db', minWidth: 140 },
    btn: {
      padding: '8px 12px',
      borderRadius: 8,
      border: '1px solid #1d4ed8',
      background: 'linear-gradient(135deg, #2563eb, #3b82f6)',
      color: '#fff',
      cursor: 'pointer',
      boxShadow: '0 14px 30px rgba(37, 99, 235, 0.25)',
    },
    btnSecondary: {
      padding: '8px 12px',
      borderRadius: 8,
      border: '1px solid #d1d5db',
      background: '#fff',
      color: '#111827',
      cursor: 'pointer',
    },
    table: { width: '100%', borderCollapse: 'collapse' },
    th: { textAlign: 'left', borderBottom: '1px solid #e5e7eb', padding: '8px 6px' },
    td: { borderBottom: '1px solid #f3f4f6', padding: '8px 6px', verticalAlign: 'top' },
    // Purchase suggestions styles (matching MealPlan component)
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
    <div style={styles.page}>
      <div style={styles.header} className="dashboard-header">
        <div>
          <h1 style={{ margin: 0 }}>Dashboard</h1>
          <div style={styles.small}>
            Showing last 30 days{' '}
            {dashboard?.start_date ? `(from ${dashboard.start_date} to ${dashboard.end_date})` : ''}
          </div>
        </div>
        <div style={styles.nav} className="dashboard-header-nav">
          <Link to="/dashboard">Dashboard</Link>
          <Link to="/meal-plan">Meal Plan</Link>
          <Link to="/upload">Upload</Link>
          <button type="button" style={styles.btnSecondary} onClick={handleLogout}>
            Logout
          </button>
        </div>
      </div>

      {loading && <p>Loading...</p>}
      {error && (
        <div style={{ ...styles.card, borderColor: '#fecaca', background: '#fff1f2' }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Section 1: Nutrition Summary Cards */}
      {/* 
        This section displays the latest stored nutrition summary from the database.
        Data comes from /dashboard-nutrition endpoint (not recalculated).
        Values match the Nutrition Summary page.
      */}
      <div style={{ marginTop: 12 }}>
        <h2 style={styles.sectionTitle}>Nutrition summary (latest day)</h2>
        {nutritionLoading && <p style={styles.small}>Loading nutrition data...</p>}
        {nutritionError && (
          <div style={{ ...styles.card, borderColor: '#fecaca', background: '#fff1f2', marginBottom: 12 }}>
            <strong>Error loading nutrition:</strong> {nutritionError}
          </div>
        )}
        {!nutritionLoading && !latestNutrition && (
          <div style={{ ...styles.card, marginBottom: 12 }}>
            <p style={styles.small}>No nutrition summary available. Please analyze nutrition from the Upload page.</p>
          </div>
        )}
        {latestNutrition && (
          <div style={styles.grid4}>
            <div style={styles.card}>
              <p style={styles.cardTitle}>Total calories</p>
              <p style={styles.cardValue}>{fmtNumber(latestNutrition?.calories, 1)}</p>
            </div>
            <div style={styles.card}>
              <p style={styles.cardTitle}>Total Protein (g)</p>
              <p style={styles.cardValue}>{fmtNumber(latestNutrition?.protein, 1)}</p>
            </div>
            <div style={styles.card}>
              <p style={styles.cardTitle}>Total Carbohydrates (g)</p>
              <p style={styles.cardValue}>{fmtNumber(latestNutrition?.carbs, 1)}</p>
            </div>
            <div style={styles.card}>
              <p style={styles.cardTitle}>Total Fats (g)</p>
              <p style={styles.cardValue}>{fmtNumber(latestNutrition?.fats, 1)}</p>
            </div>
          </div>
        )}
        {latestNutrition && (
          <p style={{ ...styles.small, marginTop: 8 }}>
            Source: Stored nutrition summary from database (matches Nutrition Summary page)
          </p>
        )}
        {/* Warning for unknown items */}
        {latestNutrition && latestNutrition.unknown_items && latestNutrition.unknown_items.length > 0 && (
          <div style={{
            ...styles.card,
            backgroundColor: '#fef3c7',
            borderColor: '#fbbf24',
            marginTop: 12,
            padding: '16px',
          }}>
            <div style={{ fontWeight: '600', marginBottom: '8px', fontSize: '14px', color: '#92400e' }}>
              ⚠️ Unknown Food Items ({latestNutrition.unknown_items.length})
            </div>
            <div style={{ fontSize: '13px', marginBottom: '8px', color: '#78350f' }}>
              The following items were not found in the nutrition database and were excluded from calculations:
            </div>
            <ul style={{ margin: '8px 0', paddingLeft: '20px', fontSize: '13px', color: '#78350f' }}>
              {latestNutrition.unknown_items.map((item, index) => (
                <li key={index} style={{ marginBottom: '4px' }}>{item}</li>
              ))}
            </ul>
            <div style={{ fontSize: '12px', fontStyle: 'italic', marginTop: '8px', color: '#92400e' }}>
              These items were not included in the nutrition totals above.
            </div>
          </div>
        )}
      </div>

      <div style={{ marginTop: 12, ...styles.grid2 }}>
        {/* Section 2: Macronutrient Chart */}
        <div style={styles.card}>
          <h2 style={styles.sectionTitle}>Macronutrients</h2>
          {latestNutrition ? <Pie data={macroPie.data} options={macroPie.options} /> : <p>No nutrition data yet.</p>}
          <div style={styles.small}>Source: backend dashboard endpoint.</div>
        </div>

        {/* Section 4: Weight Tracker + chart */}
        <div style={styles.card}>
          <h2 style={styles.sectionTitle}>Weight tracker</h2>
          <div style={styles.row}>
            <input
              style={styles.input}
              type="number"
              step="0.1"
              placeholder="Weight (kg)"
              value={weightInput}
              onChange={(e) => setWeightInput(e.target.value)}
              disabled={weightSaving}
            />
            <button style={styles.btn} onClick={handleSaveWeight} disabled={weightSaving}>
              {weightSaving ? 'Saving…' : 'Update Weight'}
            </button>
            <button style={styles.btnSecondary} onClick={() => { load(); loadDashboardNutrition(); loadPurchaseSuggestions(); }} disabled={loading || nutritionLoading || suggestionsLoading}>
              Refresh
            </button>
          </div>
          {weightSaveError && <p style={{ color: '#b91c1c' }}>{weightSaveError}</p>}
          {Array.isArray(weightHist) && weightHist.length ? (
            <div style={{ marginTop: 8 }}>
              <Line data={weightLine.data} options={weightLine.options} />
            </div>
          ) : (
            <p style={styles.small}>No weight entries yet.</p>
          )}
        </div>
      </div>

      {/* Section 3: Weekly Meal Plan (Read-only) */}
      {/* 
        This section displays the saved meal plan from the database.
        Data comes from /dashboard endpoint (stored data only, not regenerated).
        Plan is saved when generated on the Meal Plan page.
        NEW FORMAT: Shows daily meal plans with nutrition totals and target status.
      */}
      <div style={{ marginTop: 12 }}>
        <div style={styles.card}>
          <h2 style={styles.sectionTitle}>Weekly meal plan</h2>
          {weeklyPlanDays.length ? (
            <>
              <p style={styles.small}>
                This meal plan is read from stored data in the database. Generate a new plan on the Meal Plan page to update it.
              </p>
              <p style={{ ...styles.small, marginBottom: 12, fontStyle: 'italic', color: '#6b7280' }}>
                Daily targets are approximate and based on general guidelines.
              </p>
              <div className="dashboard-weekly-table-wrapper">
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Day</th>
                      <th style={styles.th}>Daily Meal Plan</th>
                      <th style={styles.th}>Total Nutrition Today</th>
                      <th style={styles.th}>Daily Target</th>
                    </tr>
                  </thead>
                  <tbody>
                    {weeklyPlanDays.map((d) => {
                      const nutrition = d.total_nutrition_today || {};
                      const target = d.daily_target || {};
                      const statusColor =
                        target.status === 'Met'
                          ? '#16a34a'
                          : target.status === 'Deficit'
                            ? '#f59e0b'
                            : target.status === 'Excess'
                              ? '#ef4444'
                              : '#6b7280';

                      return (
                        <tr key={String(d.day)}>
                          <td style={styles.td}>
                            <strong>{String(d.day)}</strong>
                          </td>
                          <td style={styles.td}>
                            {Array.isArray(d.daily_meal_plan) && d.daily_meal_plan.length > 0
                              ? d.daily_meal_plan.join(', ')
                              : '—'}
                          </td>
                          <td style={styles.td}>
                            {typeof nutrition.calories === 'number' ? (
                              <div>
                                <strong>{Math.round(nutrition.calories)} kcal</strong>
                                {typeof nutrition.protein === 'number' && nutrition.protein > 0 && (
                                  <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>
                                    P: {Math.round(nutrition.protein)}g, C: {Math.round(nutrition.carbs)}g, F:{' '}
                                    {Math.round(nutrition.fats)}g
                                  </div>
                                )}
                              </div>
                            ) : (
                              '—'
                            )}
                          </td>
                          <td style={styles.td}>
                            {typeof target.target_calories === 'number' ? (
                              <div>
                                <strong>{target.target_calories} kcal</strong>
                                {target.status && (
                                  <div
                                    style={{
                                      fontSize: '12px',
                                      color: statusColor,
                                      marginTop: '4px',
                                      fontWeight: '500',
                                    }}
                                  >
                                    ({target.status})
                                  </div>
                                )}
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

              <div className="dashboard-weekly-cards">
                {weeklyPlanDays.map((d) => {
                  const nutrition = d.total_nutrition_today || {};
                  const target = d.daily_target || {};
                  return (
                    <div key={String(d.day)} className="dashboard-weekly-card">
                      <div className="dashboard-weekly-card-header">
                        <div className="dashboard-weekly-day">{String(d.day)}</div>
                        {typeof target.target_calories === 'number' && (
                          <div className="dashboard-weekly-metrics">
                            Target: {target.target_calories} kcal{target.status ? ` • ${target.status}` : ''}
                          </div>
                        )}
                      </div>
                      <div className="dashboard-weekly-metrics">
                        {typeof nutrition.calories === 'number'
                          ? `${Math.round(nutrition.calories)} kcal`
                          : 'No nutrition data'}
                      </div>
                      <div className="dashboard-weekly-meals">
                        {Array.isArray(d.daily_meal_plan) && d.daily_meal_plan.length > 0
                          ? d.daily_meal_plan.join(', ')
                          : 'No meals listed for this day.'}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <div>
              <p style={{ marginTop: 0 }}>
                No weekly meal plan found in stored data.
              </p>
              <p style={styles.small}>
                Generate a meal plan on the Meal Plan page to save it here. The plan will be automatically saved and displayed on the dashboard.
              </p>
              <button style={styles.btnSecondary} onClick={() => navigate('/meal-plan')}>
                Go to Meal Plan
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Purchase Suggestions Section */}
      <div style={{ marginTop: 12 }}>
        <div style={styles.card}>
          <h2 style={styles.sectionTitle}>What to Buy in Your Next Grocery Trip</h2>
          {suggestionsLoading && <p style={styles.small}>Loading suggestions...</p>}
          {suggestionsError && (
            <div style={{ ...styles.card, borderColor: '#fecaca', background: '#fff1f2', marginBottom: 12 }}>
              <strong>Error loading suggestions:</strong> {suggestionsError}
            </div>
          )}
          {!suggestionsLoading && !suggestionsError && purchaseSuggestions && (
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
          )}
          {!suggestionsLoading && !purchaseSuggestions && !suggestionsError && (
            <p style={styles.small}>
              No purchase suggestions available. Please analyze nutrition from the Upload page to get recommendations.
            </p>
          )}
        </div>
      </div>

      {/* Extra: calories trend from nutrition history */}
      <div style={{ marginTop: 12 }}>
        <div style={styles.card}>
          <h2 style={styles.sectionTitle}>Calories (last 7 days)</h2>
          {nutritionLast7.length ? (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {nutritionLast7.map((n) => (
                <li key={String(n.date)}>
                  {String(n.date)}: {fmtNumber(n.calories, 0)}
                </li>
              ))}
            </ul>
          ) : (
            <p style={styles.small}>No nutrition history yet.</p>
          )}
        </div>
      </div>

      {/* Section 5: Upload New Receipt */}
      <div style={{ marginTop: 12 }}>
        <div style={styles.card}>
          <h2 style={styles.sectionTitle}>Upload new receipt</h2>
          <button style={styles.btn} onClick={() => navigate('/upload')}>
            Go to Upload
          </button>
        </div>
      </div>
    </div>
  );
}

