import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchUserProfile, updateUserProfile } from '../services/api';

export default function Profile() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [profile, setProfile] = useState(null);

  const [form, setForm] = useState({
    age: '',
    gender: 'male',
    height_cm: '',
    current_weight_kg: '',
    target_weight_kg: '',
    activity_level: 'moderate',
    diet_preference: 'non-veg',
    fitness_goal: 'maintain_weight',
  });

  const load = async () => {
    setError(null);
    try {
      setLoading(true);
      const p = await fetchUserProfile();
      setProfile(p);
      setForm({
        age: p?.age ?? '',
        gender: p?.gender ?? 'male',
        height_cm: p?.height_cm ?? '',
        current_weight_kg: p?.current_weight_kg ?? '',
        target_weight_kg: p?.target_weight_kg ?? '',
        activity_level: p?.activity_level ?? 'moderate',
        diet_preference: p?.diet_preference ?? 'non-veg',
        fitness_goal: p?.fitness_goal ?? 'maintain_weight',
      });
    } catch (e) {
      // 404 means no profile yet; keep empty defaults
      const msg = e?.message || 'Failed to load profile';
      if (/profile not found/i.test(msg) || /404/.test(msg)) {
        setProfile(null);
        setError(null);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onChange = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const toNumberOrNull = (v) => {
    if (v == null) return null;
    const s = String(v).trim();
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  };

  const save = async () => {
    setError(null);
    try {
      setSaving(true);
      const payload = {
        age: toNumberOrNull(form.age),
        gender: String(form.gender || '').trim() || null,
        height_cm: toNumberOrNull(form.height_cm),
        current_weight_kg: toNumberOrNull(form.current_weight_kg),
        target_weight_kg: toNumberOrNull(form.target_weight_kg),
        activity_level: form.activity_level || null,
        diet_preference: form.diet_preference || null,
        fitness_goal: form.fitness_goal || null,
      };
      const updated = await updateUserProfile(payload);
      setProfile(updated);
    } catch (e) {
      setError(e?.message || 'Failed to save profile');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="advisor-page">
      <div className="advisor-header">
        <div>
          <h1 className="advisor-title">Profile & Personalization</h1>
          <p className="advisor-subtitle">Update your personal details so the system can personalize targets and insights.</p>
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
        ) : (
          <div className="stack-md">
            <div className="dashboard-actions-grid" style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
              <label className="stack-sm">
                <span className="text-muted">Age</span>
                <input className="input" type="number" value={form.age} onChange={onChange('age')} min="1" max="120" />
              </label>
              <label className="stack-sm">
                <span className="text-muted">Gender</span>
                <select className="input" value={form.gender} onChange={onChange('gender')}>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                </select>
              </label>
              <label className="stack-sm">
                <span className="text-muted">Height (cm)</span>
                <input className="input" type="number" value={form.height_cm} onChange={onChange('height_cm')} step="0.1" />
              </label>
              <label className="stack-sm">
                <span className="text-muted">Current weight (kg)</span>
                <input className="input" type="number" value={form.current_weight_kg} onChange={onChange('current_weight_kg')} step="0.1" />
              </label>
              <label className="stack-sm">
                <span className="text-muted">Target weight (kg)</span>
                <input className="input" type="number" value={form.target_weight_kg} onChange={onChange('target_weight_kg')} step="0.1" />
              </label>
              <label className="stack-sm">
                <span className="text-muted">Activity level</span>
                <select className="input" value={form.activity_level} onChange={onChange('activity_level')}>
                  <option value="low">Low</option>
                  <option value="moderate">Moderate</option>
                  <option value="high">High</option>
                </select>
              </label>
              <label className="stack-sm">
                <span className="text-muted">Diet preference</span>
                <select className="input" value={form.diet_preference} onChange={onChange('diet_preference')}>
                  <option value="non-veg">Non-veg</option>
                  <option value="veg">Veg</option>
                  <option value="vegan">Vegan</option>
                </select>
              </label>
              <label className="stack-sm">
                <span className="text-muted">Fitness goal</span>
                <select className="input" value={form.fitness_goal} onChange={onChange('fitness_goal')}>
                  <option value="lose_weight">Lose weight</option>
                  <option value="maintain_weight">Maintain weight</option>
                  <option value="gain_weight">Gain weight</option>
                </select>
              </label>
            </div>

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              <button type="button" className="btn btn-primary" onClick={save} disabled={saving}>
                {saving ? 'Saving…' : 'Save profile'}
              </button>
            </div>

            {profile && (
              <div className="text-muted" style={{ fontSize: 13 }}>
                Profile saved for user #{profile.user_id}.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

