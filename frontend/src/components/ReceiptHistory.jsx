import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchReceiptHistory } from '../services/api';

export default function ReceiptHistory() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [rows, setRows] = useState([]);

  const load = async () => {
    setError(null);
    try {
      setLoading(true);
      const data = await fetchReceiptHistory();
      setRows(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e?.message || 'Failed to load receipt history');
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
          <h1 className="advisor-title">Receipt History</h1>
          <p className="advisor-subtitle">Your past receipt scans and a quick nutrition/confirmed-items snapshot by date.</p>
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

      <div className="advisor-card">
        {loading ? (
          <div className="advisor-loading">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="text-muted">No receipt history yet. Upload a receipt to get started.</div>
        ) : (
          <div className="dashboard-weekly-table-wrapper">
            <table className="table" style={{ width: '100%' }}>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Calories</th>
                  <th>Items</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={String(r.receipt_date)}>
                    <td>{String(r.receipt_date)}</td>
                    <td>{typeof r.total_calories === 'number' ? Math.round(r.total_calories) : '—'}</td>
                    <td>{typeof r.items_count === 'number' ? r.items_count : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="advisor-footer" style={{ justifyContent: 'space-between' }}>
        <button type="button" className="btn btn-secondary" onClick={() => navigate('/upload')}>
          Upload Receipt
        </button>
        <button type="button" className="btn btn-primary" onClick={() => navigate('/nutrition-summary')}>
          View Nutrition Summary
        </button>
      </div>
    </div>
  );
}

