// Mirrors the FastAPI responses. Experiment field keys come from /api/config at runtime
// (backend/app/experiment_schema.py is the single source of truth).

export type Role = "partner" | "scientist" | "leadership" | "admin";

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  organization: string;
  is_internal: boolean;
}

export type FieldType = "str" | "float" | "int" | "date";

export interface FieldSpec {
  key: string;
  label: string;
  group: string;
  type: FieldType;
  unit: string | null;
  required: boolean;
  description: string;
  min: number | null;
  max: number | null;
  examples: string[];
}

export interface DesignVar {
  key: string;
  label: string;
  unit: string | null;
  min: number;
  max: number;
}

export interface AppConfig {
  auth_mode: "dev" | "cognito";
  llm_provider: "mock" | "bedrock";
  fields: FieldSpec[];
  design_space: DesignVar[];
  targets: { asr_ohm_cm2: number; operating_temp_c: number; turnaround_hours: number };
}

export type FieldValue = string | number | null;
export type ExperimentStatus = "pending_review" | "approved" | "rejected";

export interface Experiment {
  id: string;
  code: string;
  organization: string;
  status: ExperimentStatus;
  source: string;
  document_id: string | null;
  document_title: string | null;
  completeness: number;
  submitted_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  review_comment: string | null;
  fields: Record<string, FieldValue>;
  has_eis: boolean;
  has_iv: boolean;
}

export interface FieldExtraction {
  value: FieldValue;
  confidence: "high" | "medium" | "low";
  evidence: string | null;
  evidence_verified: boolean;
  problem: string | null;
  derived_from?: string;
}

export interface EisData {
  freq_hz: number[];
  z_real: number[];
  z_imag: number[];
}

export interface IvData {
  current_density_a_cm2: number[];
  voltage_v: number[];
}

export interface ExperimentDetail extends Experiment {
  extraction: Record<string, FieldExtraction> | null;
  eis_data: EisData | null;
  iv_data: IvData | null;
  analysis: {
    eis?: Record<string, number | string>;
    iv?: Record<string, number>;
  };
  warnings?: Record<string, string>;
}

export interface DocumentInfo {
  id: string;
  title: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  kind: "partner_report" | "internal_report";
  organization: string;
  status: "uploaded" | "extracting" | "needs_review" | "reviewed" | "failed" | "indexed";
  extraction_notes: string | null;
  error: string | null;
  uploaded_at: string;
  uploaded_by: string | null;
  experiment_ids: string[];
  extracted_text?: string | null;
}

export interface Candidate {
  rank: number;
  params: Record<string, number>;
  predicted_asr: number | null;
  ci95: [number, number] | null;
  p_beats_target: number | null;
  uncertainty: "low" | "medium" | "high" | "unknown";
  acquisition: number | null;
  nearest_experiment: { code: string; id: string; asr: number; distance_pct: number } | null;
  rationale: string;
}

export interface RecommendationResult {
  mode: "bayesian_optimization" | "exploration";
  engine: string;
  message: string | null;
  n_training: number;
  n_excluded: number;
  target_asr?: number;
  target_temp_c?: number;
  best_observed: { code: string; id: string; asr: number; params: Record<string, number> } | null;
  feature_relevance: { key: string; label: string; relevance: number }[];
  candidates: Candidate[];
}

export interface Citation {
  id: string;
  label: string;
  document_id: string | null;
  experiment_id: string | null;
  snippet: string;
  similarity: number;
}

export interface QAResult {
  answered: boolean;
  answer: string;
  citations: Citation[];
  reason: string | null;
}

export interface Dashboard {
  targets: {
    asr_ohm_cm2: number;
    operating_temp_c: number;
    turnaround_hours: number;
    completeness_pct: number;
    cycle_reduction_pct: number;
    baseline_cycles_to_target: number;
  };
  counts: Record<ExperimentStatus, number> & { total: number; documents: number; partners: number };
  turnaround: { median_hours: number | null; pct_within_target: number | null; n: number };
  completeness: {
    pct_complete: number | null;
    n: number;
    missing_by_field: { key: string; label: string; missing_pct: number }[];
  };
  progress: {
    series: { cycle: number; date: string; code: string; id: string; asr: number; best: number; organization: string }[];
    best_asr: number | null;
    cycles_to_target: number | null;
    cycle_reduction_pct: number | null;
  };
  asr_vs_temp: { code: string; id: string; temp: number; asr: number; cathode: string | null; organization: string }[];
  by_partner: Record<string, Record<ExperimentStatus, number>>;
  recent_activity: { at: string; actor: string; action: string; entity_type: string; entity_id: string | null }[];
}

export interface AuditEntry {
  id: number;
  at: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  organization: string | null;
  details: Record<string, unknown> | null;
}
