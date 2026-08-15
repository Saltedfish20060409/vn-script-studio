import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { ConfirmProvider } from "./components/ConfirmDialog";
import { StudioErrorBoundary } from "./components/StudioErrorBoundary";
import LoginPage from "./pages/LoginPage";
import SharePage from "./pages/SharePage";
import { StudioApp } from "./components/StudioApp";

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return <div style={{ padding: "3rem", textAlign: "center" }}>加载中…</div>;
  }
  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <AuthProvider>
      <ConfirmProvider>
        <StudioErrorBoundary label="应用根">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/share/:token" element={<SharePage />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <StudioApp />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </StudioErrorBoundary>
      </ConfirmProvider>
    </AuthProvider>
  );
}
