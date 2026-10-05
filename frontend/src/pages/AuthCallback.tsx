import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useAuth } from "../auth/AuthContext";
import { completeCognitoLogin } from "../auth/cognito";
import { ErrorBanner, Spinner } from "../components/ui";

export default function AuthCallback() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<unknown>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // StrictMode double-invokes effects; the code is single-use
    started.current = true;
    completeCognitoLogin(window.location.search)
      .then(signIn)
      .then(() => navigate("/", { replace: true }))
      .catch(setError);
  }, [signIn, navigate]);

  return <div className="mx-auto max-w-md p-8">{error ? <ErrorBanner error={error} /> : <Spinner label="Signing you in…" />}</div>;
}
