# Lead research workflow

**What this document covers:** everything that happens **after** the seller profile is approved — entering a lead, the LangGraph orchestrator, the four research tools, gap-based retry, how facts land in Pydantic schemas and Postgres, how that evidence is scored against the approved seller profile, and how the report (and drafts) are produced for the UI.

**What it does not cover:** seller extraction / document crawl / profile review. That is [Workflow.md](Workflow.md) and [Module-4.md](Module-4.md). This path **never re-reads the seller’s website**. It only uses the **approved** `SellerProfile`.

Related modules: [Module-2.md](Module-2.md) (tools), [Module-3.md](Module-3.md) (orchestrator), [Module-5.md](Module-5.md) (report), [Module-6.md](Module-6.md) (outreach drafts).

---

## 1. Big picture

```text
Seller approved (session.sellerId + sellerApproved)
        │
        ▼
  Lead page  — user enters lead company (+ optional website)
        │
        ▼
  Run page   — POST /research/runs { lead, seller_id }
        │         (timeline: approved profile → researching lead → building report)
        ▼
  LangGraph research orchestrator
        create_run → seller_profile → plan/tools loop → gap_judge → [one targeted retry] → persist
        │
        │  Tools write patches into CollectedResearch (Pydantic).
        │  Evidence items travel with those patches. Nothing is invented.
        ▼
  research_runs + evidence_items in Postgres
        │
        ▼
  POST /research/runs/{id}/report
        score approved SellerProfile × lead CollectedResearch
        → LeadReport (pursue / consider / deprioritize)
        │
        ▼
  Run page shows briefing + raw fields
        │
        ▼
  Drafts page (optional) — person-wise LinkedIn / WhatsApp from the same run
```

The lead is a **prospect candidate**. The system does not mark “won” or “qualified in CRM” — it answers: *given what we sell and what we found on this company, should you spend time on them?*

---

## 2. Gate: approved seller only

| Check | Where | Effect |
|---|---|---|
| Session has `sellerApproved` | `LeadPage`, `RunPage` | Redirect to `/profile` |
| Session has `sellerId` | `RunPage` | Redirect to `/profile` if missing |
| Seller has `approved_profile` | `POST /research/runs` | **409** if the draft was never approved |

The API loads the seller and builds:

```text
seller_input = {
  seller_id, name, company_name, website_url,
  approved_profile   ← snapshot used for this run
}
```

Code: `frontend/src/pages/LeadPage.tsx`, `RunPage.tsx`, `backend/app/api/routes/research.py`.

---

## 3. User enters the lead

On `/lead` the user submits:

| Field | Required | Notes |
|---|---|---|
| Company / lead name | yes | Stored as `leads.company_name` |
| Website | no | Normalized to `https://…`; helps `website_docs` |
| Domain | not on the form | Derived server-side from the URL when possible |

That lead is written into the browser session (`setLead`) and the UI navigates to `/run`. No research has started yet.

---

## 4. Starting the run

`RunPage` calls:

```http
POST /research/runs
{
  "lead": {
    "company_name": "…",
    "website_url": "…",
    "company_domain": null
  },
  "seller_id": "<approved seller uuid>"
}
```

**UI progress:** the left-hand steps track the two HTTP calls — approved profile is already loaded from session, then “Collecting company details” stays active until `POST /research/runs` returns, then “Building the intelligence report” until `POST .../report` returns. Individual tool calls inside the orchestrator are not streamed to the UI; `tools_used` appears after research finishes.

Code: `frontend/src/pages/RunPage.tsx`, `frontend/src/api.ts` → `createResearchRun`.

---

## 5. Orchestrator (LangGraph)

Entry: `run_research` in `backend/app/graphs/research.py`.

### 5.1 State (`ResearchState`)

| Field | Role |
|---|---|
| `company_name` / `company_domain` / `website_url` | Lead identity |
| `seller_input` / `seller_profile` | Approved seller snapshot |
| `collected` | Growing `CollectedResearch` JSON |
| `missing` | Fields still not `supported` |
| `tools_used` | Tool names already called (each tool once in the first pass) |
| `gap_decisions` / `targeted_attempts` | Gap-judge output and retry counts |
| `messages` | LangChain chat / tool messages for the planner LLM |
| `run_id` / `seller_id` / `lead_id` / `status` / `error` | Persistence |

### 5.2 Node order

```text
START
  → create_run          insert leads + research_runs (status=running); link seller
  → seller_profile      copy approved_profile into state (no seller website crawl)
  → plan_or_llm  ⇄  tool_node     loop until tools done or LLM call cap
       └─ if LLM won't call tools → first_pass_router picks next unused tool
  → gap_judge           decide at most one field worth a second look
  → targeted_tool?      optional single focused retry
  → persist             write collected + evidence; status complete | partial | failed
END
```

### 5.3 Planner vs router

1. **`plan_or_llm`** — MLX (OpenAI-compatible) with the four tools bound. The system prompt lists the company, tools already used, and still-missing fields. The model may **only call tools**; it must not invent facts. If MLX is unreachable, the node logs a warning and continues — research does **not** 500.
2. **`tool_node`** — runs each `tool_call` once, validates the JSON `patch` as `CollectedResearch`, merges it, appends the tool name to `tools_used`.
3. **`first_pass_router`** — if the LLM stops early, fails, or refuses tools while gaps remain, a deterministic picker (`next_gap_tool`) synthesizes the next tool call. Default tool order: **signals → news → website_docs → people**.
4. Cap: **`MAX_LLM_CALLS = 8`**, then force remaining tools via the router or jump to the gap judge.

The LLM never writes company fields itself. Tools do.

---

## 6. The four tools (lead only)

Registry: `backend/app/infrastructure/tools/registry.py` — `TOOL_NAMES = ("signals", "news", "website_docs", "people")`.

| Tool | Provider | What it fills |
|---|---|---|
| `signals` | Tavily | Hiring, funding, expansion, new product, tech shift, acquisition, … |
| `news` | Tavily | Recent news items (title, url, excerpt) |
| `website_docs` | HTTP crawl (+ optional MLX extract) | Company description, industry, products, HQ, size, founded, … |
| `people` | Prospeo (+ Tavily assist) | People with titles; optional email / LinkedIn enrich |

### Contract

```text
ToolRequest  → company_name, domain, website_url, optional focus
ToolResult   → success, tool_name, patch: CollectedResearch, error_code?
```

Every supported value should carry **evidence**: excerpt, source URL/type, confidence, freshness, `field_key`. Evidence lives inside `patch.evidence` and on `FieldValue.evidence_ids`.

If a tool fails (API key missing, timeout, empty page), the run does **not** fail. The patch is empty or fields stay `unknown` / `not_found_this_run`.

---

## 7. How facts enter the Pydantic schema

### 7.1 `CollectedResearch` (`domain/collected_research.py`)

| Block | Shape |
|---|---|
| `company.*` | `FieldValue`: `value`, `status` (`unknown` \| `supported` \| `not_found_this_run`), `evidence_ids` |
| `signals.*` | same |
| `news[]` | title, url, published_at, excerpt, evidence_id |
| `people[]` | name, title, email, phone, linkedin_url, evidence_id |
| `evidence[]` | full `EvidenceItem` list for the run |

### 7.2 Merge rules (`domain/merge.py`)

When tool B returns after tool A:

- A field that is already **`supported` with a value is not overwritten** (first supported wins).
- `unknown` can become `not_found_this_run` or `supported`.
- News dedupe by URL; people by `(name, title)`; evidence by `evidence_id`.

### 7.3 Missing detection

`collected.missing_parameters()` returns every company/signals field that is not `supported`, plus `news` / `people` when those lists are empty. That list drives the planner prompt, the first-pass router, and the final run status.

---

## 8. Gap-based retrieval (second pass)

After the first pass, **`gap_judge`** (`application/gap_judge.py`) looks at fields of interest that are still missing:

`signals.funding`, `company.size|headquarters|products|founded`, `people`, `news`

For each it emits a `GapDecision`:

| Field | Meaning |
|---|---|
| `verdict` | `retry` or `leave` |
| `reason` | Why (e.g. website exists so HQ might be on it) |
| `related_supported` | Evidence that makes a retry plausible |
| `tool_name` / `focus` | Which tool and focus string to call |
| `retried` / `left_missing` | Filled after the optional targeted call |

Rules are **deterministic** (e.g. don’t retry funding without other motion; don’t retry website fields without a URL/domain; at most one attempt per field in `targeted_attempts`). An optional MLX classifier can only **veto** a retry → leave; the production API path currently does not inject that classifier, so the judge is rule-based.

**Important limits:**

1. Only **one** field is retried per run (others are demoted).
2. There is **no second gap loop** after that retry — next node is always `persist`.
3. Because merge keeps the first supported value, a targeted retry can fill a hole but cannot replace an earlier answer.

```text
gap_judge
   │
   ├─ leave all ──────────────────────► persist
   │
   └─ retry one field
          │
          ▼
     targeted_tool  (e.g. website_docs focus=headquarters)
          │
          ▼
     merge patch; if still empty → left_missing=true
          │
          ▼
     persist
```

---

## 9. Persist

`persist` writes:

| Store | Content |
|---|---|
| `research_runs` | `status`, `collected` JSON, `missing`, `tools_used`, `gap_decisions`, `targeted_attempts`, `seller_profile` snapshot, `error` |
| `evidence_items` | Flattened from `collected.evidence` (replaced for that run) |
| `leads` | Already created in `create_run` |

Final status:

| Status | When |
|---|---|
| `complete` | `missing_parameters()` is empty (rare in practice — news + people + every company/signals field must be supported) |
| `partial` | Anything still missing (normal outcome) |
| `failed` | Exception in create/persist — **not** a single tool failure |

Response shape (`ResearchRunResponse`): `run_id`, `status`, `lead`, `seller_profile`, `collected`, `missing`, `tools_used`, `gap_decisions`, `targeted_attempts`, `error`.

---

## 10. Scoring and the report (seller × lead)

Research only **collects** lead evidence. **Fit** is a separate step:

```http
POST /research/runs/{run_id}/report
```

Code: `api/routes/reports.py` → `build_lead_report` → `score_research` + `product_matches` + template narrative (`application/report.py`, `application/scoring.py`).

### 10.1 Inputs

1. Lead: `CollectedResearch` from the run.
2. Seller: live **approved** profile (preferred) so edits after the run still count; `seller_version` is recorded on the report.

### 10.2 Score dimensions (0–100)

| Score | What it measures |
|---|---|
| Completeness | How many of 12 core lead fields have evidence |
| Evidence quality | Freshness × confidence of stored evidence |
| Qualification | Buying motion (hiring, funding, expansion, news, …) |
| Fit | Token overlap of approved seller text / offerings / ICP / **accepted** suggestions vs lead description, industry, products, signals, news |
| Contact relevance | People present and decision-maker-like titles |
| Overall | `0.35×fit + 0.30×qual + 0.20×completeness + 0.15×contacts` |

### 10.3 Offering matches

`product_matches` builds a text blob per product/service from:

- name, description, features, target users, problems
- supporting excerpts from seller evidence
- **accepted** prospect suggestions tied to that offering

It ranks offerings by overlap with the lead blob. That is how FieldAXIS can beat TezCafe for an interior-materials lead even when product descriptions are short.

### 10.4 Recommendation

| Label | Meaning for the user |
|---|---|
| **pursue** | Strong enough fit and motion to spend time |
| **consider** | Some fit or motion; gaps or a soft match |
| **deprioritize** | Weak fit and weak motion |

The report body also has: overview, why_fit / why_not, product_matches, recommended_action, conversation_angle, people_summary, gaps. Narrative text is **templated from scores and evidence** — the LLM does not invent the recommendation.

Persisted in `lead_reports`. The run page shows it above the raw collected fields.

---

## 11. What the user sees on `/run`

1. Fake step progress while waiting.
2. When research returns: lead name, status (`partial` / `complete`), tools used.
3. If report succeeds: pursue/consider/deprioritize, scores, why fit / why not, matching offerings, next step.
4. Raw blocks: your company (from approved profile), lead company fields, signals, news, people, gaps.
5. Link to **Write person-wise drafts** → `/drafts`.

If the report call fails, the page still shows the collected research; scoring is optional for viewing evidence.

---

## 12. Outreach drafts (same run, next step)

Optional Module 6 flow on the same `run_id`:

```http
POST /research/runs/{run_id}/drafts
```

Uses `collected.people`, the approved seller, and (when present) report `product_matches` to pick an offering angle. Writes LinkedIn connect / message / WhatsApp drafts per person into `outreach_drafts`. Nothing is sent; the user reviews, edits, approves or rejects on `/drafts`.

---

## 13. End-to-end checklist

| Step | Actor | Artifact |
|---|---|---|
| 1. Approve seller | User | `sellers.approved_profile` + session flag |
| 2. Enter lead | User | Session `lead` |
| 3. Start research | UI → API → LangGraph | `research_runs` status=running |
| 4. Load seller snapshot | Graph `seller_profile` | No seller crawl |
| 5. Call tools | LLM + router | Patches merged into `CollectedResearch` |
| 6. Gap judge | Deterministic rules | 0–1 targeted retry |
| 7. Persist | Graph | `complete` / `partial` + evidence rows |
| 8. Score & report | Separate POST | `lead_reports` + recommendation |
| 9. (Optional) Drafts | Separate POST | Person-wise outreach drafts |

---

## 14. Design rules (how to read “supported”)

1. **A value is only `supported` if a tool returned evidence** (or an explicit not-found). The orchestrator LLM does not fill fields.
2. **Seller and lead never share a merge.** Seller context is a separate approved profile; lead tools only patch `CollectedResearch`.
3. **Missing ≠ failed.** Partial runs with honest gaps are expected.
4. **Prospect ≠ customer.** The report recommends effort (`pursue` / `consider` / `deprioritize`); it does not claim the lead already buys from you.
5. **Accepted seller suggestions affect fit scoring; pending/rejected ones do not.**

---

## 15. Key files

| Area | Path |
|---|---|
| Lead form | `frontend/src/pages/LeadPage.tsx` |
| Run UI | `frontend/src/pages/RunPage.tsx` |
| Research API | `backend/app/api/routes/research.py` |
| Orchestrator | `backend/app/graphs/research.py` |
| Gap judge | `backend/app/application/gap_judge.py` |
| Tools | `backend/app/infrastructure/tools/` |
| Schemas | `backend/app/domain/collected_research.py`, `evidence.py`, `gap.py`, `seller_profile.py`, `report.py` |
| Merge | `backend/app/domain/merge.py` |
| Scoring / report | `backend/app/application/scoring.py`, `report.py` |
| Report API | `backend/app/api/routes/reports.py` |
| Persistence | `backend/app/infrastructure/repositories/research.py` |
