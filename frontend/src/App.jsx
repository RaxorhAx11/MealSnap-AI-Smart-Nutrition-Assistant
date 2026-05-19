import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Dashboard from './components/Dashboard';
import MealPlan from './components/MealPlan';
import ReceiptUpload from './components/ReceiptUpload';
import ReceiptNextStep from './components/ReceiptNextStep';
import NutritionSummary from './components/NutritionSummary';
import Profile from './components/Profile';
import Recommendations from './components/Recommendations';
import ReceiptHistory from './components/ReceiptHistory';
import Signup from './components/Signup';
import Login from './components/Login';
import ProtectedRoute from './components/ProtectedRoute';
import Layout from './components/Layout';

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/login" element={<Login />} />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/meal-plan"
            element={
              <ProtectedRoute>
                <MealPlan />
              </ProtectedRoute>
            }
          />
          <Route
            path="/nutrition-summary"
            element={
              <ProtectedRoute>
                <NutritionSummary />
              </ProtectedRoute>
            }
          />
          <Route
            path="/profile"
            element={
              <ProtectedRoute>
                <Profile />
              </ProtectedRoute>
            }
          />
          <Route
            path="/recommendations"
            element={
              <ProtectedRoute>
                <Recommendations />
              </ProtectedRoute>
            }
          />
          <Route
            path="/receipt-history"
            element={
              <ProtectedRoute>
                <ReceiptHistory />
              </ProtectedRoute>
            }
          />
          <Route
            path="/upload"
            element={
              <ProtectedRoute>
                <ReceiptUpload />
              </ProtectedRoute>
            }
          />
          <Route
            path="/upload/next"
            element={
              <ProtectedRoute>
                <ReceiptNextStep />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
