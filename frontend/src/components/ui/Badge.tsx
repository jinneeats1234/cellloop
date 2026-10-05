import type { ReactNode } from "react";
import type { ExperimentStatus, FieldExtraction } from "../../api/types";

export type Tone = "neutral" | "success" | "warn" | "danger" | "info";

const TONE_CLASS: Record<Tone, string> = {
  neutral: "",
  success: "badge-success",
  warn: "badge-warn",
  danger: "badge-danger",
  info: "badge-info",
};

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`badge ${TONE_CLASS[tone]}`} title={title}>
      <span className="badge-dot" aria-hidden />
      {children}
    </span>
  );
}

const STATUS: Record<string, { label: string; tone: Tone }> = {
  pending_review: { label: "Pending review", tone: "warn" },
  approved: { label: "Approved", tone: "success" },
  rejected: { label: "Rejected", tone: "danger" },
  uploaded: { label: "Uploaded", tone: "neutral" },
  extracting: { label: "Extracting", tone: "info" },
  needs_review: { label: "Awaiting review", tone: "warn" },
  reviewed: { label: "Reviewed", tone: "success" },
  indexed: { label: "Indexed", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
};

export function StatusBadge({ status }: { status: ExperimentStatus | string }) {
  const s = STATUS[status] ?? { label: status, tone: "neutral" as Tone };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function ConfidenceBadge({ meta }: { meta?: FieldExtraction }) {
  if (!meta || meta.value === null) return null;
  const tone: Tone = meta.confidence === "high" ? "success" : meta.confidence === "medium" ? "warn" : "danger";
  return (
    <Badge tone={tone} title={meta.derived_from ? `Derived from ${meta.derived_from}` : "AI extraction confidence"}>
      AI · {meta.confidence}
      {meta.derived_from && " · derived"}
    </Badge>
  );
}
