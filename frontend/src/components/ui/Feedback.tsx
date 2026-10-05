import type { ReactNode } from "react";
import type { Issue } from "../../lib/validation";
import { ApiError } from "../../api/client";
import { Icon } from "./Icon";

/** Error callout. Shows a user-safe message, a Retry button for transient failures, and the
 *  server reference ID so a problem can be traced in the logs. */
export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  const apiErr = error instanceof ApiError ? error : null;
  const ref = apiErr?.requestId && !msg.includes(apiErr.requestId) ? apiErr.requestId : null;
  const canRetry = onRetry && (!apiErr || apiErr.retryable);
  return (
    <div role="alert" className="note note-error mb-4 flex items-start gap-2.5">
      <span className="mt-0.5 text-[var(--danger)]">
        <Icon name="alert" size={14} />
      </span>
      <div className="min-w-0 flex-1">
        <div>{msg}</div>
        {ref && <div className="subtle mt-0.5 text-[11.5px]">Reference: {ref}</div>}
      </div>
      {canRetry && (
        <button type="button" className="btn btn-sm flex-none" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="subtle flex items-center gap-2.5 py-10 text-[13px]" role="status">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-current border-t-transparent" />
      {label}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="subtle rounded-lg border border-dashed border-[var(--border-strong)] px-6 py-10 text-center text-[13px]">{children}</div>;
}

/** Inline validation message under a form control. Pair the control with aria-describedby={id}. */
export function FieldMessage({ id, issue }: { id: string; issue: Issue | null | undefined }) {
  if (!issue) return null;
  const error = issue.level === "error";
  return (
    <p id={id} role={error ? "alert" : undefined} className={`mt-1.5 flex items-start gap-1 text-[12px] ${error ? "text-[var(--danger)]" : "text-[var(--warn)]"}`}>
      <span className="mt-[2px]">
        <Icon name="alert" size={12} />
      </span>
      {issue.message}
    </p>
  );
}

/** Border style for a control with a validation issue. */
export function issueClass(issue: Issue | null | undefined): string {
  if (!issue) return "";
  return issue.level === "error" ? "input-error" : "input-warn";
}
