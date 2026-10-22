import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { AppLayout } from '../components/layout/AppLayout';
import { LoginPage } from '../pages/LoginPage';
import { RegisterPage } from '../pages/RegisterPage';
import { IncidentsPage } from '../pages/IncidentsPage';
import { IncidentDetailPage } from '../pages/IncidentDetailPage';
import { EventsPage } from '../pages/EventsPage';
import { KnowledgePage } from '../pages/KnowledgePage';
import { OperationsPage } from '../pages/OperationsPage';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

const ProtectedRoute: React.FC<{ children: React.ReactElement }> = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-sre-950 flex items-center justify-center">
        <LoadingSpinner message="Verifying operator session..." size="lg" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
};

export const AppRoutes: React.FC = () => {
  return (
    <Routes>
      {/* Public Authentication routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      {/* Protected SRE Console routes */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/incidents" replace />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/:id" element={<IncidentDetailPage />} />
        <Route path="events" element={<EventsPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="operations" element={<OperationsPage />} />
      </Route>

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/incidents" replace />} />
    </Routes>
  );
};
