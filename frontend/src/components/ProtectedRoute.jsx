import React from 'react';
import { Navigate } from 'react-router-dom';

const TOKEN_KEY = 'jwt_token';

function ProtectedRoute({ children }) {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

export default ProtectedRoute;
export { TOKEN_KEY };
