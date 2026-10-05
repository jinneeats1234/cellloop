import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import ErrorBoundary from "./components/ErrorBoundary";
import { AuthProvider } from "./auth/AuthContext";
import "./styles/index.css";

// Last-resort safety net: async errors that escape a handler are logged with context instead of
// vanishing silently. Rendering errors are caught by ErrorBoundary; API errors become ApiError.
window.addEventListener("unhandledrejection", (event) => {
  console.error("[CellLoop] Unhandled async error:", event.reason);
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <AuthProvider>
        <App />
      </AuthProvider>
    </ErrorBoundary>
  </StrictMode>,
);
