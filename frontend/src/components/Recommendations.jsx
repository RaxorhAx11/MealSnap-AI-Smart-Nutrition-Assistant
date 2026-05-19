import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchPurchaseSuggestions, fetchWeightRecommendations } from '../services/api';

export default function Recommendations() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [grocery, setGrocery] = useState(null);
  const [weight, setWeight] = useState(null);

  const load = async () => {
    setError(null);
    try {
      setLoading(true);
      const [g, w] = await Promise.allSettled([fetchPurchaseSuggestions(), fetchWeightRecommendations()]);
      setGrocery(g.status === 'fulfilled' ? g.value : null);
      setWeight(w.status === 'fulfilled' ? w.value : null);
    } catch (e) {
      setError(e?.message || 'Failed to load recommendations');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="advisor-page">
      <div className="advisor-header">
        <div>
          <h1 className="advisor-title">Recommendations</h1>
          <p className="advisor-subtitle">Actionable suggestions based on your nutrition and weight trends.</p>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button type="button" className="btn btn-secondary" onClick={() => navigate('/dashboard')}>
            Back to Dashboard
          </button>
          <button type="button" className="btn btn-secondary" onClick={load} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="advisor-error">
          <strong>Error:</strong> {error}
        </div>
      )}

      {loading && <div className="advisor-loading">Loading…</div>}

      <div className="advisor-section">
        <h2 className="advisor-section-title">Weight recommendations</h2>
        <div className="advisor-card">
          {Array.isArray(weight?.recommendations) && weight.recommendations.length > 0 ? (
            <ul className="advisor-bullets">
              {weight.recommendations.map((r, idx) => (
                <li key={idx}>{r}</li>
              ))}
            </ul>
          ) : (
            <div className="text-muted">No weight recommendations yet. Add weight logs and nutrition summaries to unlock insights.</div>
          )}
        </div>
      </div>

      <div className="advisor-section">
        <h2 className="advisor-section-title">Grocery recommendations</h2>
        <div className="advisor-card">
          {grocery?.message && <p className="advisor-paragraph">{grocery.message}</p>}
          {Array.isArray(grocery?.suggestions) && grocery.suggestions.length > 0 ? (
            <div className="purchase-list">
              {grocery.suggestions.map((item, index) => {
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
            <div className="text-muted">No grocery recommendations yet. Analyze nutrition to get next-trip suggestions.</div>
          )}
        </div>
      </div>

      <div className="advisor-footer" style={{ justifyContent: 'space-between' }}>
        <button type="button" className="btn btn-secondary" onClick={() => navigate('/upload')}>
          Upload Receipt
        </button>
        <button type="button" className="btn btn-primary" onClick={() => navigate('/meal-plan')}>
          Generate Meal Plan
        </button>
      </div>
    </div>
  );
}

