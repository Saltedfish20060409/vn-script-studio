import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { ConfirmProvider } from "./components/ConfirmDialog";
import { StudioErrorBoundary } from "./components/StudioErrorBoundary";

// Route-level code splitting — the heavy workspace loads on demand.
const LoginPage = lazy(() =>
  import("./pages/LoginPage").then((m) => ({ default: m.default }))
);
const SharePage = lazy(() =>
  import("./pages/SharePage").then((m) => ({ default: m.default }))
);
const InvitePage = lazy(() =>
  import("./pages/InvitePage").then((m) => ({ default: m.default }))
);
const StudioApp = lazy(() =>
  import("./components/StudioApp").then((m) => ({ default: m.StudioApp }))
);

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

function RouteFallback() {
  return <div style={{ padding: "3rem", textAlign: "center" }}>加载中…</div>;
}

export default function App() {
  return (
    <AuthProvider>
      <ConfirmProvider>
        <StudioErrorBoundary label="应用根">
          <Suspense fallback={<RouteFallback />}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/share/:token" element={<SharePage />} />
              <Route path="/invite" element={<InvitePage />} />
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
          </Suspense>
        </StudioErrorBoundary>
      </ConfirmProvider>
    </AuthProvider>
  );
}
