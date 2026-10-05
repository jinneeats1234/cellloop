// Amazon Cognito Hosted UI, authorization-code flow with PKCE (no client secret in the browser).
// Cognito groups (partner | scientist | leadership | admin) and the custom:organization
// attribute travel in the ID token; the backend verifies it against the pool's JWKS.

import { cognitoConfigured, env } from "../config/env";

const { domain: DOMAIN, clientId: CLIENT_ID, redirectUri: REDIRECT_URI } = env.cognito;
const VERIFIER_KEY = "cellloop.pkce_verifier";
const STATE_KEY = "cellloop.oauth_state";

function base64url(bytes: ArrayBuffer | Uint8Array): string {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  return btoa(String.fromCharCode(...arr)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(n = 48): string {
  return base64url(crypto.getRandomValues(new Uint8Array(n)));
}

export async function startCognitoLogin(): Promise<void> {
  if (!cognitoConfigured) throw new Error("Sign-in isn't configured: set VITE_COGNITO_DOMAIN and VITE_COGNITO_CLIENT_ID in frontend/.env and rebuild.");
  const verifier = randomString();
  const state = randomString(16);
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);
  const challenge = base64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const params = new URLSearchParams({
    response_type: "code",
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    scope: "openid email profile",
    code_challenge_method: "S256",
    code_challenge: challenge,
    state,
  });
  window.location.assign(`${DOMAIN}/oauth2/authorize?${params}`);
}

export async function completeCognitoLogin(search: string): Promise<string> {
  const params = new URLSearchParams(search);
  const code = params.get("code");
  if (!code) throw new Error(params.get("error_description") ?? "Missing authorization code");
  if (params.get("state") !== sessionStorage.getItem(STATE_KEY)) throw new Error("OAuth state mismatch");
  const verifier = sessionStorage.getItem(VERIFIER_KEY) ?? "";
  sessionStorage.removeItem(VERIFIER_KEY);
  sessionStorage.removeItem(STATE_KEY);
  const res = await fetch(`${DOMAIN}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: CLIENT_ID,
      code,
      redirect_uri: REDIRECT_URI,
      code_verifier: verifier,
    }),
  });
  if (!res.ok) throw new Error(`Sign-in failed while exchanging the authorization code (HTTP ${res.status}). Please try again.`);
  const tokens = (await res.json()) as { id_token: string };
  return tokens.id_token;
}

export function cognitoLogoutUrl(): string | null {
  if (!cognitoConfigured) return null;
  const params = new URLSearchParams({ client_id: CLIENT_ID, logout_uri: window.location.origin });
  return `${DOMAIN}/logout?${params}`;
}
