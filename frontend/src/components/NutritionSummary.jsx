import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { analyzeNutrition, fetchDashboardNutrition } from '../services/api';

const NutritionSummary = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [nutritionData, setNutritionData] = useState(null);

  useEffect(() => {
    // Get items from location state or try to fetch from API
    const items = location?.state?.items;
    const summaryData = location?.state?.summary;

    if (summaryData) {
      // If summary data is already passed, use it directly
      setNutritionData(summaryData);
    } else if (items && items.length > 0) {
      // If items are passed, fetch nutrition data
      fetchNutritionData(items);
    } else {
      // Fallback: load the latest stored summary (dashboard source) so navigation from Dashboard works.
      (async () => {
        setLoading(true);
        setError(null);
        try {
          const stored = await fetchDashboardNutrition();
          // Map stored (date, calories, protein, carbs, fats) into this page's expected shape.
          setNutritionData({
            total_calories: stored?.calories ?? 0,
            total_protein: stored?.protein ?? 0,
            total_carbs: stored?.carbs ?? 0,
            total_fats: stored?.fats ?? 0,
            date: stored?.date,
            unknown_items: [],
          });
        } catch (e) {
          setError('No items or nutrition data provided');
        } finally {
          setLoading(false);
        }
      })();
    }
  }, [location]);

  const fetchNutritionData = async (items) => {
    setLoading(true);
    setError(null);
    try {
      const response = await analyzeNutrition(items);
      if (response.summary) {
        setNutritionData(response.summary);
      } else {
        setError('Nutrition summary not found in response');
      }
    } catch (err) {
      setError(err.message || 'Failed to fetch nutrition data');
    } finally {
      setLoading(false);
    }
  };

  const styles = {
    container: {
      padding: 24,
      maxWidth: 880,
      margin: '0 auto',
      fontFamily: 'var(--font-family-sans, system-ui, -apple-system, Arial, sans-serif)',
    },
    title: {
      marginTop: 0,
      marginBottom: 8,
      fontSize: 26,
      fontWeight: 650,
      color: '#111827',
      letterSpacing: '-0.02em',
    },
    subtitle: {
      marginTop: 0,
      marginBottom: 24,
      fontSize: 14,
      color: '#6b7280',
    },
    cardsGrid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
      gap: 16,
      marginBottom: 20,
    },
    cardBase: {
      backgroundColor: '#ffffff',
      borderRadius: 16,
      padding: 18,
      border: '1px solid #e5e7eb',
      boxShadow: '0 18px 45px rgba(15, 23, 42, 0.06)',
    },
    caloriesCard: {
      background:
        'radial-gradient(circle at top left, rgba(59,130,246,0.14), transparent 55%), #ffffff',
    },
    caloriesLabel: {
      fontSize: 13,
      textTransform: 'uppercase',
      letterSpacing: '0.08em',
      color: '#6b7280',
    },
    caloriesValue: {
      fontSize: 34,
      fontWeight: 700,
      color: '#111827',
      marginTop: 8,
    },
    caloriesUnit: {
      fontSize: 14,
      color: '#6b7280',
      marginLeft: 4,
    },
    macroLabelRow: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: 8,
    },
    macroName: {
      fontSize: 14,
      fontWeight: 500,
      color: '#374151',
    },
    macroPill: (colorBg, colorText) => ({
      padding: '2px 8px',
      borderRadius: 999,
      fontSize: 11,
      fontWeight: 500,
      backgroundColor: colorBg,
      color: colorText,
    }),
    macroValueRow: {
      display: 'flex',
      alignItems: 'baseline',
      gap: 4,
    },
    macroValue: {
      fontSize: 22,
      fontWeight: 600,
      color: '#111827',
    },
    macroUnit: {
      fontSize: 13,
      color: '#6b7280',
    },
    secondaryCard: {
      backgroundColor: '#f9fafb',
      borderRadius: 14,
      padding: 16,
      border: '1px solid #e5e7eb',
      marginBottom: 16,
    },
    error: {
      backgroundColor: '#fef2f2',
      border: '1px solid #fecaca',
      borderRadius: 12,
      padding: 16,
      color: '#991b1b',
      marginBottom: 16,
    },
    loading: {
      textAlign: 'center',
      padding: 24,
      color: '#6b7280',
    },
    helperNote: {
      backgroundColor: '#eff6ff',
      border: '1px solid #bfdbfe',
      borderRadius: 12,
      padding: 14,
      marginBottom: 16,
      color: '#1e40af',
      fontSize: 14,
      textAlign: 'center',
    },
    buttonRow: {
      marginTop: 20,
      display: 'flex',
      justifyContent: 'flex-end',
    },
  };

  if (loading) {
    return (
      <div style={styles.container}>
        <h1 style={styles.title}>Nutrition summary</h1>
        <div style={styles.loading}>Loading nutrition data...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={styles.container}>
        <h1 style={styles.title}>Nutrition summary</h1>
        <div style={styles.error}>
          <strong>Error:</strong> {error}
        </div>
        <button
          className="btn btn-secondary"
          style={{ marginTop: 16 }}
          onClick={() => navigate('/upload/next')}
        >
          Go Back
        </button>
      </div>
    );
  }

  if (!nutritionData) {
    return (
      <div style={styles.container}>
        <h1 style={styles.title}>Nutrition summary</h1>
        <div style={styles.error}>
          No nutrition data available
        </div>
        <button
          className="btn btn-secondary"
          style={{ marginTop: 16 }}
          onClick={() => navigate('/upload/next')}
        >
          Go Back
        </button>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <h1 style={styles.title}>Nutrition summary</h1>
      <p style={styles.subtitle}>
        Based on the items from your latest analyzed receipt. Values are approximate.
      </p>

      <div style={styles.cardsGrid}>
        {/* Calories card */}
        <div style={{ ...styles.cardBase, ...styles.caloriesCard }}>
          <div style={styles.caloriesLabel}>Total calories</div>
          <div style={styles.caloriesValue}>
            {nutritionData.total_calories?.toFixed(1) || '0.0'}
            <span style={styles.caloriesUnit}>kcal</span>
          </div>
        </div>

        {/* Protein */}
        <div style={styles.cardBase}>
          <div style={styles.macroLabelRow}>
            <span style={styles.macroName}>Protein</span>
            <span style={styles.macroPill('rgba(16,185,129,0.08)', '#047857')}>Muscle</span>
          </div>
          <div style={styles.macroValueRow}>
            <span style={styles.macroValue}>
              {nutritionData.total_protein?.toFixed(1) || '0.0'}
            </span>
            <span style={styles.macroUnit}>g</span>
          </div>
        </div>

        {/* Carbohydrates */}
        <div style={styles.cardBase}>
          <div style={styles.macroLabelRow}>
            <span style={styles.macroName}>Carbohydrates</span>
            <span style={styles.macroPill('rgba(37,99,235,0.08)', '#1d4ed8')}>Energy</span>
          </div>
          <div style={styles.macroValueRow}>
            <span style={styles.macroValue}>
              {nutritionData.total_carbs?.toFixed(1) || '0.0'}
            </span>
            <span style={styles.macroUnit}>g</span>
          </div>
        </div>

        {/* Fats */}
        <div style={styles.cardBase}>
          <div style={styles.macroLabelRow}>
            <span style={styles.macroName}>Fats</span>
            <span style={styles.macroPill('rgba(249,115,22,0.08)', '#c2410c')}>Support</span>
          </div>
          <div style={styles.macroValueRow}>
            <span style={styles.macroValue}>
              {nutritionData.total_fats?.toFixed(1) || '0.0'}
            </span>
            <span style={styles.macroUnit}>g</span>
          </div>
        </div>
      </div>

      {/* Warning for unknown items */}
      {nutritionData.unknown_items && nutritionData.unknown_items.length > 0 && (
        <div
          style={{
            backgroundColor: '#fef3c7',
            border: '1px solid #fbbf24',
            borderRadius: 12,
            padding: 16,
            marginBottom: 16,
            color: '#92400e',
          }}
        >
          <div style={{ fontWeight: '600', marginBottom: '8px', fontSize: '16px' }}>
            ⚠️ Unknown Food Items ({nutritionData.unknown_items.length})
          </div>
          <div style={{ fontSize: '14px', marginBottom: '8px' }}>
            The following items were not found in the nutrition database and were excluded from calculations:
          </div>
          <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
            {nutritionData.unknown_items.map((item, index) => (
              <li key={index} style={{ marginBottom: '4px' }}>{item}</li>
            ))}
          </ul>
          <div style={{ fontSize: '13px', fontStyle: 'italic', marginTop: '8px' }}>
            These items were not included in the nutrition totals above. Please verify the item names or add them to the database.
          </div>
        </div>
      )}

      {/* Message about dashboard */}
      <div style={styles.helperNote}>
        <strong>Note:</strong> This nutrition data has been saved and will be displayed on your dashboard.
      </div>

      <div style={styles.buttonRow}>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => navigate('/meal-plan')}
        >
          Continue to meal planning
        </button>
      </div>
    </div>
  );
};

export default NutritionSummary;
