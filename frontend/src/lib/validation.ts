// Client-side validation. Rules mirror the backend (experiment_schema.coerce_value and the
// request models) so problems are caught as the user types. The server still re-validates.
import type { FieldSpec } from "../api/types";

/** "error" blocks submission; "warning" is allowed after the user confirms they checked it. */
export interface Issue {
  level: "error" | "warning";
  message: string;
}

export type Issues = Record<string, Issue>;

const MAX_TEXT = 5000;
/** Matches the backend: beyond this it's a typo or an attack, never a measurement. */
const ABSURD_MAGNITUDE = 1e9;

function parseNumber(raw: string): number | null {
  const cleaned = raw.replace(/,/g, "").trim();
  if (!/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(cleaned)) return null;
  return Number(cleaned);
}

function rangeText(min: number | null, max: number | null, unit?: string | null): string {
  const u = unit ? ` ${unit}` : "";
  if (min !== null && max !== null) return `${min}–${max}${u}`;
  if (min !== null) return `≥ ${min}${u}`;
  return `≤ ${max}${u}`;
}

/** Validate one experiment-schema field. Missing required metadata is a warning, not an error,
 *  because partners sometimes don't report everything (the completeness metric tracks it). */
export function checkSchemaField(spec: FieldSpec, raw: string): Issue | null {
  const value = raw.trim();
  if (!value) return spec.required ? { level: "warning", message: "Required metadata is missing" } : null;

  if (value.includes("\u0000")) return { level: "error", message: "Contains an invalid character" };
  if (spec.type === "str") {
    return value.length > MAX_TEXT ? { level: "error", message: `Keep this under ${MAX_TEXT} characters` } : null;
  }
  if (spec.type === "date") {
    const d = new Date(`${value}T00:00:00`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(d.getTime())) return { level: "error", message: "Use a valid date (YYYY-MM-DD)" };
    if (d.getTime() > Date.now()) return { level: "warning", message: "This date is in the future" };
    return null;
  }
  const n = parseNumber(value);
  if (n === null) return { level: "error", message: "Enter a number (digits and an optional decimal point)" };
  if (!Number.isFinite(n) || Math.abs(n) > ABSURD_MAGNITUDE) return { level: "error", message: "That number is far outside any plausible value" };
  if (spec.type === "int" && !Number.isInteger(n)) return { level: "error", message: "Enter a whole number" };
  if ((spec.min !== null && n < spec.min) || (spec.max !== null && n > spec.max)) {
    return { level: "warning", message: `Outside the plausible range (${rangeText(spec.min, spec.max, spec.unit)}). Check units` };
  }
  return null;
}

export function checkSchemaFields(fields: FieldSpec[], draft: Record<string, string>): Issues {
  const out: Issues = {};
  for (const f of fields) {
    const issue = checkSchemaField(f, draft[f.key] ?? "");
    if (issue) out[f.key] = issue;
  }
  return out;
}

export function errorsOf(issues: Issues): string[] {
  return Object.keys(issues).filter((k) => issues[k].level === "error");
}

export function warningsOf(issues: Issues): string[] {
  return Object.keys(issues).filter((k) => issues[k].level === "warning");
}

/** Generic number rule for simple forms. Empty is allowed unless `required`. */
export function checkNumber(
  raw: string,
  opts: { label: string; min?: number; max?: number; integer?: boolean; required?: boolean; unit?: string },
): Issue | null {
  const value = raw.trim();
  if (!value) return opts.required ? { level: "error", message: `${opts.label} is required` } : null;
  const n = parseNumber(value);
  if (n === null || !Number.isFinite(n)) return { level: "error", message: `${opts.label} must be a number` };
  if (opts.integer && !Number.isInteger(n)) return { level: "error", message: `${opts.label} must be a whole number` };
  if ((opts.min !== undefined && n < opts.min) || (opts.max !== undefined && n > opts.max)) {
    return { level: "error", message: `${opts.label} must be ${rangeText(opts.min ?? null, opts.max ?? null, opts.unit)}` };
  }
  return null;
}

export function checkText(raw: string, opts: { label: string; min?: number; max: number; required?: boolean }): Issue | null {
  const value = raw.trim();
  if (!value) return opts.required ? { level: "error", message: `${opts.label} is required` } : null;
  if (opts.min !== undefined && value.length < opts.min) return { level: "error", message: `${opts.label} needs at least ${opts.min} characters` };
  if (value.length > opts.max) return { level: "error", message: `${opts.label} must be under ${opts.max} characters` };
  return null;
}

export const UPLOAD_EXTENSIONS = [".pdf", ".xlsx", ".csv", ".tsv", ".txt", ".z", ".dta", ".json", ".md"];
export const MAX_UPLOAD_MB = 25;

export function checkUploadFile(file: File | null): Issue | null {
  if (!file) return { level: "error", message: "Choose a file to upload" };
  const ext = file.name.includes(".") ? `.${file.name.split(".").pop()!.toLowerCase()}` : "";
  if (!UPLOAD_EXTENSIONS.includes(ext)) {
    return { level: "error", message: `"${ext || "no extension"}" files aren't supported. Use ${UPLOAD_EXTENSIONS.join(", ")}` };
  }
  if (file.size === 0) return { level: "error", message: "This file is empty" };
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    return { level: "error", message: `File is ${(file.size / 1024 / 1024).toFixed(1)} MB; the limit is ${MAX_UPLOAD_MB} MB` };
  }
  return null;
}
