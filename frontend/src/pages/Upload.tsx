import { useState } from "react";
import { Link } from "react-router";
import { ApiError, api } from "../api/client";
import type { DocumentInfo } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Card, ErrorBanner, FieldMessage, PageHeader, StatusBadge, issueClass, orgLabel } from "../components/ui";
import { MAX_UPLOAD_MB, UPLOAD_EXTENSIONS, checkText, checkUploadFile } from "../lib/validation";

const PARTNER_ORGS = ["northgate-univ", "ridgeline-lab", "lakeshore-univ"];
const ACCEPT = UPLOAD_EXTENSIONS.join(",");

export default function UploadPage() {
  const { user } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<"partner_report" | "internal_report">("partner_report");
  const [org, setOrg] = useState(PARTNER_ORGS[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [uploaded, setUploaded] = useState<DocumentInfo | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [fileKey, setFileKey] = useState(0); // remounts the file input so the same file can be re-picked

  const fileIssue = checkUploadFile(file);
  const titleIssue = checkText(title, { label: "Title", max: 500 });
  const showFileIssue = attempted || file !== null;
  const valid = !fileIssue && !titleIssue;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAttempted(true);
    if (!valid || !file) return;
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    if (title.trim()) form.append("title", title.trim());
    if (user?.is_internal) {
      form.append("kind", kind);
      if (kind === "partner_report") form.append("organization", org);
    }
    try {
      let doc = await api.upload(form);
      setUploaded(doc);
      setFile(null);
      setTitle("");
      setAttempted(false);
      setFileKey((k) => k + 1);
      // Poll until the AI extraction finishes.
      for (let i = 0; i < 60 && (doc.status === "uploaded" || doc.status === "extracting"); i++) {
        await new Promise((r) => setTimeout(r, 2000));
        doc = await api.document(doc.id);
        setUploaded(doc);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setError(new Error("This exact file was already submitted."));
      else setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Data"
        title="Upload a test report"
        subtitle="PDF reports, spreadsheets and raw impedance exports. Claude extracts parameters and results, and a CellLoop scientist verifies every value against your file before it becomes a record."
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <ErrorBanner error={error} />
          <form onSubmit={submit} className="space-y-4">
            <label
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
              }}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed p-6 text-center sm:p-10 ${
                dragOver
                  ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                  : showFileIssue && fileIssue
                    ? "border-[var(--danger)]"
                    : "border-[var(--border-strong)]"
              }`}
            >
              <input
                key={fileKey}
                type="file"
                accept={ACCEPT}
                className="sr-only"
                aria-describedby="file-msg"
                aria-invalid={(showFileIssue && !!fileIssue) || undefined}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <span className="font-medium break-all">{file ? file.name : "Drop a file here or tap to choose"}</span>
              <span className="muted mt-1 text-xs">
                {file ? `${(file.size / 1024).toFixed(1)} KB · ` : ""}PDF, XLSX, CSV/TSV/TXT, ZView .z, Gamry .dta · up to {MAX_UPLOAD_MB} MB
              </span>
            </label>
            <FieldMessage id="file-msg" issue={showFileIssue ? fileIssue : null} />
            <div>
              <label className="label" htmlFor="title">
                Title (optional)
              </label>
              <input
                id="title"
                className={`input ${issueClass(titleIssue)}`}
                maxLength={600}
                aria-describedby="title-msg"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Batch 14 button cells, 650 °C EIS"
              />
              <FieldMessage id="title-msg" issue={titleIssue} />
            </div>
            {user?.is_internal && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="kind">
                    Document type
                  </label>
                  <select id="kind" className="input" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
                    <option value="partner_report">Partner test report (extract experiments)</option>
                    <option value="internal_report">Internal report (index for Q&amp;A only)</option>
                  </select>
                </div>
                {kind === "partner_report" && (
                  <div>
                    <label className="label" htmlFor="org">
                      Received from partner
                    </label>
                    <select id="org" className="input" value={org} onChange={(e) => setOrg(e.target.value)}>
                      {PARTNER_ORGS.map((o) => (
                        <option key={o} value={o}>
                          {orgLabel(o)}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
            )}
            <button className="btn btn-primary w-full sm:w-auto" disabled={busy || (attempted && !valid)}>
              {busy ? "Uploading & extracting…" : "Upload"}
            </button>
          </form>
        </Card>
        <Card title="What happens next">
          <ol className="muted list-decimal space-y-2 pl-4 text-sm">
            <li>Your file is stored encrypted in CellLoop's AWS account. Only your organization and the CellLoop team can see it.</li>
            <li>Claude (via Amazon Bedrock) extracts parameters and results, quoting the line each value came from.</li>
            <li>A scientist compares every field with your original file and approves, corrects or rejects it.</li>
            <li>Approved records appear in the registry, usually within 48 hours.</li>
          </ol>
        </Card>
      </div>
      {uploaded && (
        <Card className="mt-4" title="Latest upload">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="font-medium">{uploaded.title}</span>
            <StatusBadge status={uploaded.status} />
            {uploaded.status === "needs_review" && <span>{uploaded.experiment_ids.length} experiment(s) extracted and queued for review.</span>}
            {uploaded.status === "indexed" && <span>{uploaded.extraction_notes}</span>}
            {uploaded.error && <span className="text-[var(--danger)]">{uploaded.error}</span>}
            <Link className="link" to="/submissions">
              View all submissions →
            </Link>
          </div>
        </Card>
      )}
    </>
  );
}
