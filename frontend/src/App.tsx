import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { useAuth } from "./auth/AuthContext";
import Layout from "./components/layout/Layout";
import { Spinner } from "./components/ui";
import AskPage from "./pages/Ask";
import AuditPage from "./pages/Audit";
import AuthCallback from "./pages/AuthCallback";
import DashboardPage from "./pages/Dashboard";
import ExperimentDetailPage from "./pages/ExperimentDetail";
import ExperimentsPage from "./pages/Experiments";
import LoginPage from "./pages/Login";
import NotFoundPage from "./pages/NotFound";
import RecommendPage from "./pages/Recommend";
import ReviewPage from "./pages/Review";
import ReviewQueuePage from "./pages/ReviewQueue";
import SubmissionsPage from "./pages/Submissions";
import UploadPage from "./pages/Upload";

function ApiDown({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="card max-w-lg">
        <h1 className="mb-2 text-lg font-semibold">Can't reach the CellLoop API</h1>
        <p className="muted mb-3 text-sm">
          The web page is running, but the backend at port 8000 isn't responding. Start both together from the
          project folder:
        </p>
        <pre className="mb-4 rounded-lg bg-[var(--surface-3)] p-3 text-[13px]">./start.sh</pre>
        <p className="muted mb-4 text-sm">
          If it's already running, check its terminal output for errors.
        </p>
        <button className="btn btn-primary" onClick={onRetry}>
          Try again
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const { user, loading, apiDown, retry } = useAuth();
  if (loading) return <Spinner label="Starting CellLoop…" />;
  if (apiDown) return <ApiDown onRetry={retry} />;

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/auth/callback" element={<AuthCallback />} />
        {!user ? (
          <Route path="*" element={<LoginPage />} />
        ) : (
          <Route element={<Layout />}>
            <Route index element={<Navigate to={user.is_internal ? "/dashboard" : "/submissions"} replace />} />
            {user.is_internal && (
              <>
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/recommend" element={<RecommendPage />} />
                <Route path="/ask" element={<AskPage />} />
                <Route path="/audit" element={<AuditPage />} />
              </>
            )}
            {(user.role === "scientist" || user.role === "admin") && (
              <>
                <Route path="/review" element={<ReviewQueuePage />} />
                <Route path="/review/:id" element={<ReviewPage />} />
              </>
            )}
            <Route path="/experiments" element={<ExperimentsPage />} />
            <Route path="/experiments/:id" element={<ExperimentDetailPage />} />
            {user.role !== "leadership" && <Route path="/upload" element={<UploadPage />} />}
            <Route path="/submissions" element={<SubmissionsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        )}
      </Routes>
    </BrowserRouter>
  );
}
