import type { ReactNode } from "react";
import { Icon } from "./Icon";

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: string; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: string }) {
  return (
    <header className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-1.5">{eyebrow}</div>}
        <h1 className="text-[22px] leading-tight font-semibold tracking-[-0.015em]">{title}</h1>
        {subtitle && <div className="muted mt-1.5 max-w-3xl text-[13.5px] leading-relaxed">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Card({
  title,
  description,
  children,
  className = "",
  actions,
}: {
  title?: string;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
  actions?: ReactNode;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            {title && <h2 className="card-title">{title}</h2>}
            {description && <p className="subtle mt-0.5 text-xs">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, unit, hint, status }: { label: string; value: ReactNode; unit?: string; hint?: ReactNode; status?: "good" | "warn" | null }) {
  return (
    <div className="card flex flex-col">
      <div className="subtle text-[12px] font-medium">{label}</div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="text-[26px] leading-none font-semibold tracking-[-0.02em] tabular-nums">{value}</span>
        {unit && <span className="muted text-[13px]">{unit}</span>}
      </div>
      {hint && (
        <div className="muted mt-3 flex items-center gap-1.5 text-[12px] leading-snug">
          {status === "good" && (
            <span className="text-[var(--success)]" aria-label="on target">
              <Icon name="check" size={13} />
            </span>
          )}
          {status === "warn" && (
            <span className="text-[var(--warn)]" aria-label="below target">
              <Icon name="alert" size={13} />
            </span>
          )}
          <span>{hint}</span>
        </div>
      )}
    </div>
  );
}
