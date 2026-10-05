import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, api } from "../api/client";
import type { DocumentInfo, ExperimentDetail, FieldSpec, FieldValue } from "../api/types";
import { useConfig } from "../auth/AuthContext";
import { NyquistChart } from "../components/charts/CurveCharts";
import { Card, ConfidenceBadge, ErrorBanner, FieldMessage, PageHeader, Spinner, StatusBadge, issueClass, orgLabel } from "../components/ui";
import { checkSchemaFields, checkText, errorsOf, warningsOf } from "../lib/validation";
import { groupFields } from "./ExperimentDetail";

type Draft = Record<string, string>;

function toDraft(e: ExperimentDetail): Draft {
  return Object.fromEntries(Object.entries(e.fields).map(([k, v]) => [k, v === null ? "" : String(v)]));
}

function fromDraft(draft: Draft, fields: FieldSpec[]): Record<string, FieldValue> {
  const out: Record<string, FieldValue> = {};
  for (const f of fields) {
    const raw = (draft[f.key] ?? "").trim();
    out[f.key] = raw === "" ? null : f.type === "float" || f.type === "int" ? Number(raw.replace(/,/g, "")) : raw;
  }
  return out;
}

/** Source text with the focused field's evidence quote highlighted and scrolled into view. */
function SourceText({ text, highlight }: { text: string; highlight: string | null }) {
  const markRef = useRef<HTMLElement>(null);
  useEffect(() => markRef.current?.scrollIntoView({ block: "center", behavior: "smooth" }), [highlight]);
  const idx = highlight ? text.toLowerCase().indexOf(highlight.toLowerCase()) : -1;
  return (
    <pre className="max-h-[70vh] overflow-auto rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3.5 text-[12px] leading-relaxed whitespace-pre-wrap">
      {idx < 0 || !highlight ? (
        text
      ) : (
        <>
          {text.slice(0, idx)}
          <mark ref={markRef} className="rounded bg-[var(--warn-line)] px-0.5 text-[var(--text)]">
            {text.slice(idx, idx + highlight.length)}
          </mark>
          {text.slice(idx + highlight.length)}
        </>
      )}
    </pre>
  );
}

export default function ReviewPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const config = useConfig();
  const [exp, setExp] = useState<ExperimentDetail | null>(null);
  const [doc, setDoc] = useState<DocumentInfo | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [focus, setFocus] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [warnings, setWarnings] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"text" | "original">("text");

  useEffect(() => {
    let url: string | null = null;
    (async () => {
      try {
        const e = await api.experiment(id);
        setExp(e);
        setDraft(toDraft(e));
        if (e.document_id) {
          const d = await api.document(e.document_id);
          setDoc(d);
          if (d.content_type === "application/pdf") {
            url = await api.documentBlobUrl(d.id);
            setPdfUrl(url);
            setView("original");
          }
        }
      } catch (err) {
        setError(err);
      }
    })();
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [id]);

  const changed = useMemo(() => {
    if (!exp) return new Set<string>();
    const original = toDraft(exp);
    return new Set(Object.keys(draft).filter((k) => (draft[k] ?? "") !== (original[k] ?? "")));
  }, [draft, exp]);

  const aiChanged = useMemo(() => {
    const out = new Set<string>();
    for (const [k, m] of Object.entries(exp?.extraction ?? {})) {
      const ai = m.value === null ? "" : String(m.value);
      if (ai !== (draft[k] ?? "")) out.add(k);
    }
    return out;
  }, [draft, exp]);

  const issues = useMemo(() => checkSchemaFields(config.fields, draft), [config.fields, draft]);
  const errorKeys = errorsOf(issues);
  // Implausible values (range, future date) need an explicit "I've checked" before approval;
  // missing required metadata is allowed and only lowers the record's completeness.
  const flaggedKeys = warningsOf(issues).filter((k) => (draft[k] ?? "").trim() !== "");
  const missingKeys = warningsOf(issues).filter((k) => (draft[k] ?? "").trim() === "");
  const [acknowledged, setAcknowledged] = useState(false);
  const commentIssue = checkText(comment, { label: "Comment", max: 2000 });
  const rejectIssue = rejectReason ? checkText(rejectReason, { label: "Reason", min: 3, max: 2000, required: true }) : null;
  const labelOf = (key: string) => config.fields.find((f) => f.key === key)?.label ?? key;
  const jumpTo = (key: string) => {
    setFocus(key);
    document.getElementById(key)?.focus();
  };

  if (error && !exp)
    return (
      <>
        <ErrorBanner error={error} />
        <Link className="link text-[13px]" to="/review">
          Back to review queue
        </Link>
      </>
    );
  if (!exp) return <Spinner />;

  const values = () => fromDraft(draft, config.fields);
  const done = exp.status !== "pending_review";

  const approve = async (acknowledge = false) => {
    setBusy(true);
    setError(null);
    try {
      await api.approve(exp.id, values(), comment.trim(), acknowledge || acknowledged);
      navigate("/review");
    } catch (err) {
      if (err instanceof ApiError && err.status === 422 && typeof err.detail === "object" && err.detail && "warnings" in err.detail) {
        setWarnings((err.detail as { warnings: Record<string, string> }).warnings);
      } else setError(err);
    } finally {
      setBusy(false);
    }
  };

  const saveDraft = async () => {
    setBusy(true);
    try {
      const updated = await api.updateDraft(exp.id, values());
      setExp(updated);
      setDraft(toDraft(updated));
      setWarnings(updated.warnings && Object.keys(updated.warnings).length ? updated.warnings : null);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    setBusy(true);
    try {
      await api.reject(exp.id, rejectReason);
      navigate("/review");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const focusedEvidence = focus ? (exp.extraction?.[focus]?.evidence ?? null) : null;
  const lowConfidence = Object.entries(exp.extraction ?? {}).filter(([, m]) => m.value !== null && m.confidence === "low").length;

  return (
    <>
      <PageHeader
        eyebrow="Review"
        title={`${exp.code} · ${exp.fields.cell_id ?? "Unidentified cell"}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={exp.status} /> {orgLabel(exp.organization)} · {doc?.title ?? "manual record"}
            {lowConfidence > 0 && <span className="text-[var(--danger)]">· {lowConfidence} low-confidence field(s) to check</span>}
          </span>
        }
        actions={
          <Link className="btn" to="/review">
            Back to queue
          </Link>
        }
      />
      <ErrorBanner error={error} />
      {doc?.extraction_notes && (
        <div className="note note-info mb-4 whitespace-pre-line">
          <span className="font-semibold">Extraction notes: </span>
          {doc.extraction_notes}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        {/* Left: the source document */}
        <div className="space-y-4 xl:sticky xl:top-4 xl:self-start">
          <Card
            title="Source document"
            actions={
              pdfUrl && (
                <div className="segmented" role="group" aria-label="Source view">
                  <button type="button" aria-pressed={view === "original"} onClick={() => setView("original")}>
                    Original
                  </button>
                  <button type="button" aria-pressed={view === "text"} onClick={() => setView("text")}>
                    Extracted text
                  </button>
                </div>
              )
            }
          >
            {!doc ? (
              <p className="muted text-sm">This record has no source document.</p>
            ) : view === "original" && pdfUrl ? (
              <iframe title="Source PDF" src={pdfUrl} className="h-[70vh] w-full rounded-lg border border-[var(--border)]" sandbox="allow-same-origin" />
            ) : (
              <SourceText text={doc.extracted_text ?? ""} highlight={focusedEvidence} />
            )}
            <p className="muted mt-2 text-xs">Click a field on the right to highlight the passage the AI quoted for it.</p>
          </Card>
          {exp.eis_data && (
            <Card title="Impedance data in this file">
              <NyquistChart eis={exp.eis_data} area={Number(draft.active_area_cm2) || null} />
            </Card>
          )}
        </div>

        {/* Right: extracted fields */}
        <div className="space-y-4">
          {groupFields(config.fields).map(([group, specs]) => (
            <Card key={group} title={group}>
              <div className="space-y-3">
                {specs.map((f) => {
                  const meta = exp.extraction?.[f.key];
                  const issue = issues[f.key];
                  const serverWarn = warnings?.[f.key] ?? meta?.problem;
                  const msgId = `${f.key}-msg`;
                  return (
                    <div
                      key={f.key}
                      className={`rounded-lg p-2 ${focus === f.key ? "bg-[var(--accent-soft)] ring-1 ring-[var(--accent-ring)]" : ""}`}
                      onClick={() => setFocus(f.key)}
                    >
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <label className="text-xs font-medium" htmlFor={f.key}>
                          {f.label}
                          {f.unit && <span className="muted"> ({f.unit})</span>}
                          {f.required && <span className="text-[var(--danger)]" aria-label="required"> *</span>}
                        </label>
                        <ConfidenceBadge meta={meta} />
                        {aiChanged.has(f.key) && meta && <span className="text-xs text-[var(--accent)]">✎ edited from AI value</span>}
                      </div>
                      <input
                        id={f.key}
                        className={`input ${issueClass(issue) || (changed.has(f.key) ? "input-changed" : "")}`}
                        type={f.type === "date" ? "date" : "text"}
                        inputMode={f.type === "int" ? "numeric" : f.type === "float" ? "decimal" : undefined}
                        aria-invalid={issue?.level === "error" || undefined}
                        aria-describedby={issue ? msgId : undefined}
                        value={draft[f.key] ?? ""}
                        disabled={done}
                        onFocus={() => setFocus(f.key)}
                        onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                        placeholder={f.examples[0] ? `e.g. ${f.examples[0]}` : "not reported"}
                      />
                      {meta?.evidence && (
                        <p className="muted mt-1 text-xs">
                          {meta.evidence_verified ? "✓ Found in source: " : "✕ Not found in source: "}
                          <q className="italic">{meta.evidence}</q>
                        </p>
                      )}
                      {meta?.derived_from && <p className="muted mt-1 text-xs">Computed from the {meta.derived_from}.</p>}
                      <FieldMessage id={msgId} issue={issue} />
                      {serverWarn && serverWarn !== issue?.message && (
                        <p className="mt-1 text-xs text-[var(--danger)]">! {serverWarn}</p>
                      )}
                    </div>
                  );
                })}
              </div>
            </Card>
          ))}

          {!done && (
            <Card title="Decision">
              {errorKeys.length > 0 && (
                <div role="alert" className="note note-error mb-3">
                  <p className="font-semibold">Fix {errorKeys.length} field{errorKeys.length === 1 ? "" : "s"} before approving:</p>
                  <ul className="mt-1 list-disc pl-5">
                    {errorKeys.map((k) => (
                      <li key={k}>
                        <button type="button" className="link" onClick={() => jumpTo(k)}>
                          {labelOf(k)}
                        </button>
                        : {issues[k].message}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {(flaggedKeys.length > 0 || warnings) && (
                <div className="mb-3 note note-warn">
                  <p className="font-semibold">Some values look implausible:</p>
                  <ul className="mt-1 list-disc pl-5">
                    {flaggedKeys.map((k) => (
                      <li key={k}>
                        <button type="button" className="link" onClick={() => jumpTo(k)}>
                          {labelOf(k)}
                        </button>
                        : {issues[k].message}
                      </li>
                    ))}
                    {Object.entries(warnings ?? {})
                      .filter(([k]) => !flaggedKeys.includes(k))
                      .map(([k, w]) => (
                        <li key={k}>{w}</li>
                      ))}
                  </ul>
                  <label className="mt-2 flex items-center gap-2">
                    <input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />
                    I've checked these values against the source
                  </label>
                </div>
              )}
              {missingKeys.length > 0 && (
                <p className="muted mb-3 text-xs">
                  Missing required metadata ({missingKeys.length}): {missingKeys.map(labelOf).join(", ")}. You can still approve; the record
                  will count as incomplete.
                </p>
              )}
              <label className="label" htmlFor="comment">
                Review comment (optional, saved to the audit log)
              </label>
              <textarea
                id="comment"
                className={`input ${issueClass(commentIssue)}`}
                rows={2}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                aria-describedby="comment-msg"
              />
              <div className="mb-3 flex justify-between">
                <FieldMessage id="comment-msg" issue={commentIssue} />
                <span className="muted ml-auto text-xs tabular-nums">{comment.length}/2000</span>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  className="btn btn-primary"
                  disabled={busy || errorKeys.length > 0 || !!commentIssue || ((flaggedKeys.length > 0 || !!warnings) && !acknowledged)}
                  onClick={() => approve(false)}
                >
                  Approve record
                </button>
                <button className="btn" disabled={busy || !changed.size || errorKeys.length > 0} onClick={saveDraft}>
                  Save draft ({changed.size} change{changed.size === 1 ? "" : "s"})
                </button>
              </div>
              <div className="mt-4 border-t border-[var(--border)] pt-4">
                <label className="label" htmlFor="reject">
                  Reject (e.g. duplicate, unusable data). Reason required
                </label>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <input
                    id="reject"
                    className={`input ${issueClass(rejectIssue)}`}
                    value={rejectReason}
                    onChange={(e) => setRejectReason(e.target.value)}
                    aria-describedby="reject-msg"
                  />
                  <button className="btn btn-danger" disabled={busy || rejectReason.trim().length < 3 || !!rejectIssue} onClick={reject}>
                    Reject
                  </button>
                </div>
                <FieldMessage id="reject-msg" issue={rejectIssue} />
              </div>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
