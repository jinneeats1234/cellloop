import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { startCognitoLogin } from "../auth/cognito";
import { Avatar, ErrorBanner, Icon, Logo, orgLabel } from "../components/ui";

export default function LoginPage() {
  const { config, signIn } = useAuth();
  const [devUsers, setDevUsers] = useState<User[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const devMode = config?.auth_mode === "dev";

  useEffect(() => {
    if (devMode) api.devUsers().then(setDevUsers).catch(setError);
  }, [devMode]);

  const devLogin = async (email: string) => {
    setBusy(email);
    try {
      const { token } = await api.devLogin(email);
      await signIn(token);
    } catch (e) {
      setError(e);
      setBusy(null);
    }
  };

  const ROLE_ORDER = ["scientist", "leadership", "admin"];
  const internal = devUsers.filter((u) => u.is_internal).sort((a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role));
  const partners = devUsers.filter((u) => !u.is_internal);

  const AccountRow = ({ u }: { u: User }) => (
    <button
      className="group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-[var(--surface-3)] disabled:opacity-50"
      disabled={busy !== null}
      onClick={() => devLogin(u.email)}
    >
      <Avatar name={u.name} size={30} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium">{u.name}</span>
        <span className="subtle block truncate text-[12px]">{u.email}</span>
      </span>
      <span className="subtle text-[12px] capitalize">{u.is_internal ? u.role : orgLabel(u.organization)}</span>
      <span className="text-[var(--text-3)] opacity-0 transition-opacity group-hover:opacity-100">
        {busy === u.email ? <span className="block h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-current border-t-transparent" /> : <Icon name="arrow" size={14} />}
      </span>
    </button>
  );

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-[440px]">
        <div className="mb-8 flex flex-col items-center text-center">
          <Logo size={40} />
          <h1 className="mt-4 text-[22px] font-semibold tracking-[-0.015em]">Sign in to CellLoop</h1>
          <p className="muted mt-1.5 text-[13.5px]">The prediction-to-validation loop for metal-supported SOFCs</p>
        </div>

        <div className="card p-2">
          <div className="px-2 pt-2">
            <ErrorBanner error={error} />
          </div>
          {devMode ? (
            <>
              <div className="eyebrow px-3 pt-2 pb-1">CellLoop team</div>
              {internal.map((u) => (
                <AccountRow key={u.id} u={u} />
              ))}
              <div className="divider mx-3 my-2" />
              <div className="eyebrow px-3 pt-1 pb-1">Partner labs</div>
              {partners.map((u) => (
                <AccountRow key={u.id} u={u} />
              ))}
            </>
          ) : (
            <div className="p-4">
              <button className="btn btn-primary h-10 w-full" onClick={() => startCognitoLogin().catch(setError)}>
                Continue with your organization account
              </button>
            </div>
          )}
        </div>

        <p className="subtle mt-5 text-center text-[12px] leading-relaxed">
          {devMode
            ? "Development sign-in with demo accounts. Production uses Amazon Cognito with MFA."
            : "Partner labs see only their own submissions. All activity is audited."}
        </p>
      </div>
    </div>
  );
}
