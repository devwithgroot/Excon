const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export type FieldValue = {
  value: string | null;
  status: "unknown" | "supported" | "not_found_this_run";
  evidence_ids: string[];
};

export type EvidenceItem = {
  evidence_id: string;
  field_key: string;
  extracted_value: string | null;
  source_url: string | null;
  source_type: string;
  supporting_excerpt: string;
  freshness: string;
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

export type SellerIcp = {
  target_industries: string | null;
  company_size: string | null;
  geography: string | null;
  departments_roles: string | null;
  problems: string | null;
  buying_signals: string | null;
  exclusions: string | null;
  preferred: string | null;
};

export type SellerProfileOut = {
  company_name: string;
  contact_name: string | null;
  domain: string | null;
  website_url: string | null;
  industry: string | null;
  description: string | null;
  geography: string | null;
  size: string | null;
  products: string | null;
  services: string | null;
  features: string | null;
  problems_solved: string | null;
  differentiators: string | null;
  limitations: string | null;
  icp: SellerIcp;
  status: string;
  version: number;
};

export type SellerResponse = {
  seller_id: string;
  status: string;
  approved_version: number;
  draft: SellerProfileOut;
  approved: SellerProfileOut | null;
};

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

export type DocumentPayload = {
  filename: string;
  text?: string;
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
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export async function createSeller(body: {
  name?: string;
  company_name: string;
  website_url?: string;
  profile?: SellerProfileOut;
}): Promise<SellerResponse> {
  return fetchJson<SellerResponse>(`${API_URL}/sellers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function extractSeller(body: {
  name?: string;
  company_name: string;
  website_url?: string;
  documents?: DocumentPayload[];
}): Promise<SellerResponse> {
  try {
    return await fetchJson<SellerResponse>(
      `${API_URL}/sellers/extract`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
      22_000,
    );
  } catch (err) {
    if (err instanceof Error && err.message.includes("timed out")) {
      throw new Error(
        "Website read timed out. Fill the profile yourself, then approve.",
      );
    }
    throw err;
  }
}

export async function getSeller(sellerId: string): Promise<SellerResponse> {
  return fetchJson<SellerResponse>(`${API_URL}/sellers/${sellerId}`);
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
  seller?: {
    name?: string;
    company_name: string;
    website_url?: string;
    documents?: DocumentPayload[];
  };
  seller_id?: string;
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

export async function documentsFromFiles(files: File[]): Promise<DocumentPayload[]> {
  const docs: DocumentPayload[] = [];
  for (const file of files) {
    const isText =
      /\.(txt|md|csv|json)$/i.test(file.name) || file.type.startsWith("text/");
    docs.push({
      filename: file.name,
      text: isText ? await file.text() : undefined,
    });
  }
  return docs;
}
