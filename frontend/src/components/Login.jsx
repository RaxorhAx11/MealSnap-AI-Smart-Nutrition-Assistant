import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { login } from '../services/api';

const TOKEN_KEY = 'jwt_token';

function Login() {
  const [usernameOrEmail, setUsernameOrEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await login({
        username_or_email: usernameOrEmail,
        password,
      });
      localStorage.setItem(TOKEN_KEY, res.access_token);
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setError(err.message || 'Login failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-card-header">
          <h1 className="auth-card-title">Welcome back</h1>
          <p className="auth-card-subtitle">
            Log in to view your nutrition insights and meal plans.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="stack-md">
          <div className="form-field">
            <label htmlFor="usernameOrEmail" className="form-label">
              Username or email
            </label>
            <input
              id="usernameOrEmail"
              className="input"
              type="text"
              value={usernameOrEmail}
              onChange={(e) => setUsernameOrEmail(e.target.value)}
              required
              autoComplete="username"
            />
          </div>

          <div className="form-field">
            <label htmlFor="password" className="form-label">
              Password
            </label>
            <input
              id="password"
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </div>

          {error && <div className="form-error">{error}</div>}

          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? 'Logging in…' : 'Log in'}
          </button>
        </form>

        <div className="auth-footer">
          <span>Don&apos;t have an account? </span>
          <Link to="/signup" className="link-inline">
            Sign up
          </Link>
        </div>
      </div>
    </div>
  );
}

export default Login;
