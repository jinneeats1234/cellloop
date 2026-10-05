import type { ReactNode } from "react";

/* Minimal stroke icon set (24px grid, 1.6 stroke), drawn to match Inter's weight. */
const ICONS: Record<string, ReactNode> = {
  dashboard: (
    <>
      <rect x="3.5" y="3.5" width="7" height="9" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="5" rx="1.5" />
      <rect x="13.5" y="11.5" width="7" height="9" rx="1.5" />
      <rect x="3.5" y="15.5" width="7" height="5" rx="1.5" />
    </>
  ),
  review: (
    <>
      <path d="M9 11.5l2 2 4-4.5" />
      <path d="M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0z" />
    </>
  ),
  registry: (
    <>
      <ellipse cx="12" cy="6" rx="7.5" ry="2.75" />
      <path d="M4.5 6v6c0 1.5 3.4 2.75 7.5 2.75s7.5-1.25 7.5-2.75V6" />
      <path d="M4.5 12v6c0 1.5 3.4 2.75 7.5 2.75s7.5-1.25 7.5-2.75v-6" />
    </>
  ),
  recommend: (
    <>
      <path d="M12 3.5l1.9 4.6 4.6 1.9-4.6 1.9L12 16.5l-1.9-4.6L5.5 10l4.6-1.9z" />
      <path d="M18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z" />
    </>
  ),
  ask: (
    <>
      <path d="M20 11.5c0 4-3.6 7-8 7-1.1 0-2.2-.2-3.1-.5L4 19.5l1.4-3.6C4.5 14.7 4 13.2 4 11.5c0-4 3.6-7 8-7s8 3 8 7z" />
      <path d="M9.5 10h5M9.5 13h3" />
    </>
  ),
  upload: (
    <>
      <path d="M12 15.5V4.5M7.5 9L12 4.5 16.5 9" />
      <path d="M4.5 15v3a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-3" />
    </>
  ),
  submissions: (
    <>
      <path d="M14 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5z" />
      <path d="M14 3.5v5h5M9 13h6M9 16.5h4" />
    </>
  ),
  audit: (
    <>
      <path d="M12 3.5l7 3v5c0 4.5-3 7.6-7 9-4-1.4-7-4.5-7-9v-5z" />
      <path d="M9.5 12l1.8 1.8 3.4-3.6" />
    </>
  ),
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  alert: (
    <>
      <path d="M12 8.5v4.5M12 16.2v.3" />
      <path d="M20.5 12a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0z" />
    </>
  ),
  logout: (
    <>
      <path d="M14.5 4.5h3a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-3" />
      <path d="M10 16l-4-4 4-4M6 12h9.5" />
    </>
  ),
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  back: <path d="M19 12H5M11 18l-6-6 6-6" />,
};

export function Icon({ name, size = 16 }: { name: keyof typeof ICONS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden className="flex-none">
      {ICONS[name]}
    </svg>
  );
}

export function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden className="flex-none">
      <rect x="1" y="1" width="30" height="30" rx="8" fill="var(--accent)" />
      <circle cx="16" cy="16" r="7.5" fill="none" stroke="var(--on-accent)" strokeWidth="2.2" strokeDasharray="36 12" strokeLinecap="round" />
      <circle cx="16" cy="16" r="2.2" fill="var(--on-accent)" />
    </svg>
  );
}
