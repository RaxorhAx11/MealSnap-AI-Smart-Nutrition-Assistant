import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Dashboard from './components/Dashboard';
import MealPlan from './components/MealPlan';
import ReceiptUpload from './components/ReceiptUpload';
import ReceiptNextStep from './components/ReceiptNextStep';
import NutritionSummary from './components/NutritionSummary';
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
          <Route path="/upload" element={<ReceiptUpload />} />
          <Route path="/upload/next" element={<ReceiptNextStep />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
