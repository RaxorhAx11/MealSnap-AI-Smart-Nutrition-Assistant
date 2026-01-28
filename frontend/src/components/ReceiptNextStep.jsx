import React, { useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { analyzeNutrition } from '../services/api';

export default function ReceiptNextStep() {
  const navigate = useNavigate();
  const location = useLocation();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const items = useMemo(() => {
    const stateItems = location?.state?.items;
    return Array.isArray(stateItems) ? stateItems : [];
  }, [location?.state?.items]);

  const handleViewNutritionSummary = async () => {
    if (items.length === 0) {
      setError('No items available to analyze');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await analyzeNutrition(items);
      if (response.summary) {
        // Navigate to NutritionSummary with the summary data
        navigate('/nutrition-summary', {
          state: {
            summary: response.summary,
            items: items, // Also pass items in case needed
          },
        });
      } else {
        setError('Nutrition summary not found in response');
      }
    } catch (err) {
      setError(err.message || 'Failed to analyze nutrition');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 16, maxWidth: 1100, margin: '0 auto', fontFamily: 'system-ui, Arial' }}>
      <h1 style={{ marginTop: 0 }}>Next Step</h1>

      {items.length === 0 ? (
        <div>
          <p>No items were passed from the upload step.</p>
          <button onClick={() => navigate('/upload')}>Go back to Upload</button>
        </div>
      ) : (
        <div>
          <p style={{ marginTop: 0 }}>
            Received <strong>{items.length}</strong> item(s). You can now continue your flow from here.
          </p>

          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ textAlign: 'left', borderBottom: '1px solid #e5e7eb', padding: '8px 6px' }}>#</th>
                <th style={{ textAlign: 'left', borderBottom: '1px solid #e5e7eb', padding: '8px 6px' }}>
                  Item
                </th>
                <th style={{ textAlign: 'left', borderBottom: '1px solid #e5e7eb', padding: '8px 6px' }}>
                  Quantity
                </th>
                <th style={{ textAlign: 'left', borderBottom: '1px solid #e5e7eb', padding: '8px 6px' }}>Unit</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, idx) => (
                <tr key={`${idx}-${String(it?.name ?? '')}`}>
                  <td style={{ borderBottom: '1px solid #f3f4f6', padding: '8px 6px' }}>{idx + 1}</td>
                  <td style={{ borderBottom: '1px solid #f3f4f6', padding: '8px 6px' }}>
                    {String(it?.name ?? '')}
                  </td>
                  <td style={{ borderBottom: '1px solid #f3f4f6', padding: '8px 6px' }}>
                    {String(it?.quantity ?? '')}
                  </td>
                  <td style={{ borderBottom: '1px solid #f3f4f6', padding: '8px 6px' }}>
                    {String(it?.unit ?? '')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {error && (
            <div style={{ 
              marginTop: 12, 
              padding: '12px', 
              backgroundColor: '#fef2f2', 
              border: '1px solid #fecaca', 
              borderRadius: '6px', 
              color: '#991b1b' 
            }}>
              {error}
            </div>
          )}

          <div style={{ marginTop: 12, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <button onClick={() => navigate('/upload')}>Back to Upload</button>
            <button
              onClick={handleViewNutritionSummary}
              disabled={loading}
              style={{
                backgroundColor: '#3b82f6',
                color: '#ffffff',
                border: 'none',
                borderRadius: '6px',
                padding: '8px 16px',
                fontSize: '14px',
                fontWeight: '500',
                cursor: loading ? 'not-allowed' : 'pointer',
                opacity: loading ? 0.6 : 1,
              }}
            >
              {loading ? 'Analyzing...' : 'View Nutrition Summary'}
            </button>
            <Link to="/meal-plan">Go to Meal Plan</Link>
            <Link to="/dashboard">Go to Dashboard</Link>
          </div>
        </div>
      )}
    </div>
  );
}

