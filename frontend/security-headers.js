// Security headers for the web app, shared by the production server (server.mjs) and
// `vite preview` (vite.config.ts). frontend/nginx.conf carries the same policy for Docker.

/** Content-Security-Policy. `extraConnect` = an API origin on another domain (VITE_API_BASE). */
export function contentSecurityPolicy(extraConnect = "") {
  return [
    "default-src 'self'",
    "script-src 'self'",
    // Plotly and React set inline styles on SVG elements.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src 'self' https://*.amazoncognito.com${extraConnect ? ` ${extraConnect}` : ""}`,
    "frame-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self' https://*.amazoncognito.com",
    "frame-ancestors 'none'",
  ].join("; ");
}

export function securityHeaders(extraConnect = "") {
  return {
    "Content-Security-Policy": contentSecurityPolicy(extraConnect),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  };
}
