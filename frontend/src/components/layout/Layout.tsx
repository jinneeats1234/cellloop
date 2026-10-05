import { useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import type { Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import ErrorBoundary from "../ErrorBoundary";
import { Avatar, Icon, Logo, orgLabel } from "../ui";

const NAV: { to: string; label: string; icon: string; roles: Role[]; group: "Program" | "Data" }[] = [
  { to: "/dashboard", label: "Dashboard", icon: "dashboard", roles: ["scientist", "leadership", "admin"], group: "Program" },
  { to: "/recommend", label: "Next experiment", icon: "recommend", roles: ["scientist", "leadership", "admin"], group: "Program" },
  { to: "/ask", label: "Ask the program", icon: "ask", roles: ["scientist", "leadership", "admin"], group: "Program" },
  { to: "/review", label: "Review queue", icon: "review", roles: ["scientist", "admin"], group: "Data" },
  { to: "/experiments", label: "Experiments", icon: "registry", roles: ["scientist", "leadership", "admin", "partner"], group: "Data" },
  { to: "/upload", label: "Upload report", icon: "upload", roles: ["partner", "scientist", "admin"], group: "Data" },
  { to: "/submissions", label: "Submissions", icon: "submissions", roles: ["partner", "scientist", "admin"], group: "Data" },
  { to: "/audit", label: "Audit log", icon: "audit", roles: ["scientist", "leadership", "admin"], group: "Data" },
];

const navClass = ({ isActive }: { isActive: boolean }) =>
  `flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] whitespace-nowrap transition-colors ${
    isActive
      ? "bg-[var(--accent-soft)] font-medium text-[var(--accent)]"
      : "text-[var(--text-2)] hover:bg-[var(--surface-3)] hover:text-[var(--text)]"
  }`;

export default function Layout() {
  const { user, config, signOut } = useAuth();
  const { pathname } = useLocation();
  // On phones the nav scrolls sideways; keep the current page's tab visible.
  useEffect(() => {
    document.querySelector('nav[aria-label="Main"] a[aria-current="page"]')?.scrollIntoView({ inline: "center", block: "nearest" });
  }, [pathname]);
  if (!user) return null;

  const items = NAV.filter((n) => n.roles.includes(user.role));
  const groups = (["Program", "Data"] as const).map((g) => ({ name: g, items: items.filter((n) => n.group === g) })).filter((g) => g.items.length);
  const offline = config?.llm_provider === "mock";

  return (
    <div className="min-h-screen md:flex">
      <aside className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--surface)] md:flex md:h-screen md:w-[232px] md:shrink-0 md:flex-col md:border-r md:border-b-0">
        {/* Brand row (+ account controls on phones) */}
        <div className="flex items-center gap-2.5 px-4 py-3 md:px-5 md:pt-5 md:pb-4">
          <Logo />
          <div className="leading-tight">
            <div className="text-[14px] font-semibold tracking-[-0.01em]">CellLoop</div>
            <div className="subtle text-[11px]">MS-SOFC R&amp;D</div>
          </div>
          <div className="ml-auto flex items-center gap-2 md:hidden">
            <Avatar name={user.name || user.email} size={26} />
            <button className="btn btn-ghost btn-sm" onClick={signOut} aria-label="Sign out">
              <Icon name="logout" size={15} />
            </button>
          </div>
        </div>

        <nav
          aria-label="Main"
          className="flex gap-1 overflow-x-auto px-3 pb-2.5 [mask-image:linear-gradient(to_right,black_85%,transparent)] md:block md:flex-1 md:overflow-y-auto md:px-3 md:pb-3 md:[mask-image:none]"
        >
          {groups.map((g) => (
            <div key={g.name} className="contents md:mb-5 md:block">
              <div className="eyebrow hidden px-2.5 pb-1.5 md:block">{g.name}</div>
              <div className="contents md:flex md:flex-col md:gap-0.5">
                {g.items.map((n) => (
                  <NavLink key={n.to} to={n.to} className={navClass}>
                    <Icon name={n.icon} size={16} />
                    {n.label}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/* Account (desktop) */}
        <div className="hidden border-t border-[var(--border)] p-3 md:block">
          {offline && (
            <div className="mx-1 mb-3 flex items-center gap-2 text-[11.5px] text-[var(--warn)]" title="LLM_PROVIDER=mock: extraction and Q&A use the offline stand-in, not Claude">
              <span className="badge-dot" />
              Offline AI mode
            </div>
          )}
          <div className="flex items-center gap-2.5 rounded-md px-1 py-1">
            <Avatar name={user.name || user.email} />
            <div className="min-w-0 flex-1 leading-tight">
              <div className="truncate text-[13px] font-medium">{user.name || user.email}</div>
              <div className="subtle truncate text-[11.5px] capitalize">
                {user.role} · {orgLabel(user.organization)}
              </div>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={signOut} title="Sign out" aria-label="Sign out">
              <Icon name="logout" size={15} />
            </button>
          </div>
        </div>
      </aside>

      <main className="mx-auto w-full max-w-[1240px] min-w-0 px-4 py-6 sm:px-6 md:px-10 md:py-9">
        {/* Keyed by route so a crash on one page clears when you navigate away. */}
        <ErrorBoundary key={pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  );
}
