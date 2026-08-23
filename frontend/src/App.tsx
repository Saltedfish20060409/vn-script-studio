import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { useAuth } from "./lib/authContext";
import { ConfirmProvider } from "./components/ConfirmDialog";
import { StudioErrorBoundary } from "./components/StudioErrorBoundary";
import { NoticeBanner } from "./components/NoticeBanner";

// Route-level code splitting — the heavy workspace loads on demand.
const LoginPage = lazy(() =>
  import("./pages/LoginPage").then((m) => ({ default: m.default }))
);
const VerifyEmailPage = lazy(() =>
  import("./pages/VerifyEmailPage").then((m) => ({ default: m.default }))
);
const ResetPasswordPage = lazy(() =>
  import("./pages/ResetPasswordPage").then((m) => ({ default: m.default }))
);
const SharePage = lazy(() =>
  import("./pages/SharePage").then((m) => ({ default: m.default }))
);
const InvitePage = lazy(() =>
  import("./pages/InvitePage").then((m) => ({ default: m.default }))
);
const HelpPage = lazy(() =>
  import("./pages/HelpPage").then((m) => ({ default: m.default }))
);
const LegalPage = lazy(() =>
  import("./pages/LegalPage").then((m) => ({ default: m.default }))
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
            {/* 公告模态：任意页面拉取 /notice，未读版本自动弹出一次 */}
            <NoticeBanner />
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/verify-email" element={<VerifyEmailPage />} />
              <Route path="/reset-password" element={<ResetPasswordPage />} />
              <Route path="/share/:token" element={<SharePage />} />
              <Route path="/invite" element={<InvitePage />} />
              <Route path="/help" element={<HelpPage />} />
              <Route path="/legal" element={<LegalPage />} />
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
