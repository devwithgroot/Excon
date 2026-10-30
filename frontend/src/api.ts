const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export type FieldValue = {
  value: string | null;
  status: "unknown" | "supported" | "not_found_this_run";
  evidence_ids: string[];
};

export type Support = "explicit" | "inferred";

export type EvidenceItem = {
  evidence_id: string;
  field_key: string;
  extracted_value: string | null;
  source_url: string | null;
  source_type: string;
  supporting_excerpt: string;
  freshness: string;
  source_id?: string | null;
  source_title?: string | null;
  section_reference?: string | null;
  confidence?: number | null;
  support?: Support;
};

export type NewsItem = {
  title: string;
  url: string;
  published_at: string | null;
  excerpt: string;
  evidence_id: string;
};

export type PersonRecord = {
  name: string;
  title: string | null;
  role_description: string | null;
  email: string | null;
  phone: string | null;
  linkedin_url: string | null;
  evidence_id: string;
};

export type CollectedResearch = {
  company: Record<string, FieldValue>;
  signals: Record<string, FieldValue>;
  news: NewsItem[];
  people: PersonRecord[];
  evidence: EvidenceItem[];
};

export const ICP_LIST_FIELDS = [
  "target_industries",
  "geography",
  "departments",
  "decision_makers",
  "customer_problems",
  "pain_points",
  "buying_signals",
  "use_cases",
  "preferred_characteristics",
  "exclusions",
  "disqualifiers",
] as const;

export type IcpListField = (typeof ICP_LIST_FIELDS)[number];

export type SellerIcp = Record<IcpListField, string[]> & {
  company_size: string | null;
};

export type ProductItem = {
  name: string;
  description?: string | null;
  features?: string[];
  target_users?: string[];
  problems_solved?: string[];
  business_value?: string | null;
  evidence_ids?: string[];
  support?: Support;
};

export type ServiceItem = {
  name: string;
  description?: string | null;
  target_customer?: string | null;
  business_outcome?: string | null;
  use_cases?: string[];
  evidence_ids?: string[];
  support?: Support;
};

export type FieldTrace = {
  evidence_ids: string[];
  support: Support;
  confidence: number | null;
  edited?: boolean;
};

export type ProspectSuggestion = {
  suggestion_id: string;
  prospect_type: string;
  why_relevant: string;
  matching_offering: string | null;
  problem_addressed: string | null;
  decision_makers: string[];
  buying_signals: string[];
  evidence_ids: string[];
  support: Support;
  status: "pending" | "accepted" | "rejected";
};

export type ConflictValue = { value: string; evidence_ids: string[]; source_ids: string[] };

export type Conflict = { field: string; values: ConflictValue[]; note: string };

export type SourceSummary = {
  source_id: string;
  source_type: string;
  name: string;
  url: string | null;
  status: string;
  error: string | null;
};

export type ValidationIssue = {
  field: string;
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
  resolved: boolean;
};

export type ExtractionMetadata = {
  job_id: string | null;
  status: "complete" | "partial" | "failed" | "manual";
  pipeline_version: string;
  sources: SourceSummary[];
  warnings: string[];
  missing: string[];
  conflicts: Conflict[];
  validation: ValidationIssue[];
  completeness: number;
  completed_at: string | null;
};

export const PROFILE_LIST_FIELDS = [
  "geography",
  "features",
  "problems_solved",
  "differentiators",
  "limitations",
  "customer_segments",
  "industries_served",
  "use_cases",
] as const;

export type ProfileListField = (typeof PROFILE_LIST_FIELDS)[number];

export type SellerProfileOut = Record<ProfileListField, string[]> & {
  seller_id: string | null;
  company_name: string;
  contact_name: string | null;
  domain: string | null;
  website_url: string | null;
  industry: string | null;
  sub_industry: string | null;
  description: string | null;
  business_model: string | null;
  market_positioning: string | null;
  company_size: string | null;
  value_proposition: string | null;
  products: ProductItem[];
  services: ServiceItem[];
  icp: SellerIcp;
  suggested_prospect_characteristics: ProspectSuggestion[];
  traces: Record<string, FieldTrace>;
  evidence_ids: string[];
  evidence: EvidenceItem[];
  extraction_metadata: ExtractionMetadata;
  status: string;
  version: number;
};

export type DocumentStatus = {
  document_id: string;
  filename: string;
  format: string;
  size_bytes: number;
  status: string;
  error: string | null;
  page_count: number | null;
};

export type ExtractionJob = {
  job_id: string;
  seller_id: string;
  status: "queued" | "running" | "succeeded" | "partial" | "failed";
  stage: string;
  stage_label: string;
  stage_index: number;
  stage_total: number;
  stages: string[];
  detail: string | null;
  error: string | null;
  warnings: string[];
  summary: Record<string, unknown>;
  documents: DocumentStatus[];
  created_at: string | null;
  finished_at: string | null;
};

export type SellerResponse = {
  seller_id: string;
  status: string;
  approved_version: number;
  draft: SellerProfileOut;
  approved: SellerProfileOut | null;
  job: ExtractionJob | null;
};

export type ExtractionStatus = ExtractionJob & { seller: SellerResponse | null };

export function jobFinished(job: Pick<ExtractionJob, "status">): boolean {
  return job.status === "succeeded" || job.status === "partial" || job.status === "failed";
}

export function offeringNames(profile: Pick<SellerProfileOut, "products" | "services">): string[] {
  return [...profile.products, ...profile.services].map((item) => item.name);
}

export type ScoreBreakdown = {
  key: string;
  label: string;
  score: number;
  reasons: string[];
  matched: string[];
  gaps: string[];
};

export type LeadReport = {
  report_id: string;
  run_id: string;
  seller_id: string | null;
  seller_version: number;
  scores: {
    completeness: ScoreBreakdown;
    evidence_quality: ScoreBreakdown;
    qualification: ScoreBreakdown;
    fit: ScoreBreakdown;
    contact_relevance: ScoreBreakdown;
    overall: number;
    recommendation: "pursue" | "consider" | "deprioritize";
    recommendation_reason: string;
  };
  overview: string;
  why_fit: string[];
  why_not: string[];
  product_matches: { offering: string; reason: string; matched_lead_signals: string[] }[];
  recommended_action: string;
  conversation_angle: string;
  people_summary: string;
  gaps: string[];
};

export type GapDecision = {
  field: string;
  verdict: "retry" | "leave";
  reason: string;
  related_supported: string[];
  retried: boolean;
  left_missing: boolean;
};

export type OutreachDraft = {
  draft_id: string;
  run_id: string;
  seller_id: string | null;
  person_evidence_id: string;
  person_name: string;
  person_title: string | null;
  person_linkedin_url: string | null;
  offering: string | null;
  offering_reason: string | null;
  relevance: string;
  cited_facts: string[];
  linkedin_connect: string;
  linkedin_message: string;
  whatsapp: string;
  status: "draft" | "approved" | "rejected";
  version: number;
  skipped_reason: string | null;
};

export type OutreachBatch = {
  run_id: string;
  status: string;
  drafts: OutreachDraft[];
  skipped: { name?: string; reason?: string }[];
  error: string | null;
};

export type ResearchRunResponse = {
  run_id: string;
  status: string;
  lead: {
    company_name: string;
    company_domain: string | null;
    website_url: string | null;
  };
  seller_profile: SellerProfileOut | null;
  collected: CollectedResearch;
  missing: string[];
  tools_used: string[];
  gap_decisions: GapDecision[];
  targeted_attempts: Record<string, number>;
  error: string | null;
};

let inflight: Promise<ResearchRunResponse> | null = null;

async function fetchJson<T>(url: string, init?: RequestInit, timeoutMs = 20_000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    return await readJson<T>(response);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Request timed out. Try again.");
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // not JSON; keep the raw body
    }
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export async function startExtraction(body: {
  name: string;
  company_name: string;
  website_url: string;
  files: File[];
}): Promise<ExtractionJob> {
  const form = new FormData();
  form.append("name", body.name);
  form.append("company_name", body.company_name);
  form.append("website_url", body.website_url);
  for (const file of body.files) form.append("files", file, file.name);
  return fetchJson<ExtractionJob>(
    `${API_URL}/sellers/extract`,
    { method: "POST", body: form },
    120_000,
  );
}

export async function getExtraction(jobId: string): Promise<ExtractionStatus> {
  return fetchJson<ExtractionStatus>(`${API_URL}/sellers/extract/${jobId}`);
}

export async function getSeller(sellerId: string): Promise<SellerResponse> {
  return fetchJson<SellerResponse>(`${API_URL}/sellers/${sellerId}`);
}

export async function setSuggestionStatus(
  sellerId: string,
  suggestionId: string,
  action: "accept" | "reject",
): Promise<SellerResponse> {
  return fetchJson<SellerResponse>(
    `${API_URL}/sellers/${sellerId}/suggestions/${suggestionId}/${action}`,
    { method: "POST" },
  );
}

export async function saveSellerDraft(
  sellerId: string,
  profile: SellerProfileOut,
): Promise<SellerResponse> {
  return fetchJson<SellerResponse>(`${API_URL}/sellers/${sellerId}/draft`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile }),
  });
}

export async function approveSeller(sellerId: string): Promise<SellerResponse> {
  return fetchJson<SellerResponse>(`${API_URL}/sellers/${sellerId}/approve`, {
    method: "POST",
  });
}

export async function createRunReport(runId: string): Promise<LeadReport> {
  const response = await fetch(`${API_URL}/research/runs/${runId}/report`, {
    method: "POST",
  });
  return readJson<LeadReport>(response);
}

export async function createResearchRun(body: {
  lead: {
    company_name: string;
    company_domain?: string;
    website_url?: string;
  };
  seller_id: string;
}): Promise<ResearchRunResponse> {
  if (inflight) {
    return inflight;
  }
  inflight = (async () => {
    const response = await fetch(`${API_URL}/research/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return readJson<ResearchRunResponse>(response);
  })().finally(() => {
    inflight = null;
  });
  return inflight;
}

export async function generateRunDrafts(runId: string): Promise<OutreachBatch> {
  return fetchJson<OutreachBatch>(
    `${API_URL}/research/runs/${runId}/drafts`,
    { method: "POST" },
    25_000,
  );
}

export async function listRunDrafts(runId: string): Promise<OutreachBatch> {
  return fetchJson<OutreachBatch>(`${API_URL}/research/runs/${runId}/drafts`);
}

export async function saveOutreachDraft(
  draftId: string,
  body: { linkedin_connect: string; linkedin_message: string; whatsapp: string },
): Promise<OutreachDraft> {
  return fetchJson<OutreachDraft>(`${API_URL}/drafts/${draftId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function approveOutreachDraft(draftId: string): Promise<OutreachDraft> {
  return fetchJson<OutreachDraft>(`${API_URL}/drafts/${draftId}/approve`, {
    method: "POST",
  });
}

export async function rejectOutreachDraft(draftId: string): Promise<OutreachDraft> {
  return fetchJson<OutreachDraft>(`${API_URL}/drafts/${draftId}/reject`, {
    method: "POST",
  });
}