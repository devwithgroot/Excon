# Module 3 — Lead research orchestrator

**Status:** Done  
**What this module is:** the LangGraph workflow that *uses* the Module 2 LangChain tools. FastAPI starts a research run for a lead (and optional seller site/docs). The graph calls tools, merges one `CollectedResearch`, writes the run to Postgres, then a **gap judge** may retry **one targeted tool once** if other evidence makes that field plausible. If the second call is still empty, the field stays missing. The LLM never invents a fact.

**What this module is not:** it does not score a lead, write a narrative report, or draft outreach. Those are Modules 5–6.

Read [Module-2.md](Module-2.md) first for the four tools, `CollectedResearch`, merge, and evidence rules. Read [Module-0.md](Module-0.md) for FastAPI / Postgres / Compose.

Work lives on the same research graph: [`backend/app/graphs/research.py`](../backend/app/graphs/research.py).

---

## 1. Why this is still LangGraph / LangChain

Module 2 built the retrieve layer. Module 3 is the orchestrator **agent**:

| Layer | What it is | What it is not |
|---|---|---|
| **FastAPI** `POST /research/runs` | Accepts lead + optional seller, starts the graph, returns the finished run | Does not call Tavily / Prospeo / website adapters |
| **LangGraph** `StateGraph(ResearchState)` | Nodes: `create_run` → `seller_profile` → `plan_or_llm` → `tool_node` → `gap_judge` → optional `targeted_tool` → `persist` | Not a Python `for name in TOOL_NAMES` loop in a route |
| **LangChain tools** | The same four tools (`signals`, `news`, `website_docs`, `people`), now with an optional `focus` for a targeted retry | Not a fifth vendor |
| **Gap judge** | Deterministic relatedness, optional MLX classify, fail closed | Not allowed to emit a funding amount or email |
| **Postgres** | `sellers`, `leads`, `research_runs`, `evidence_items` | Not a source of invented facts |

The model (MLX Qwen) still only **chooses tools** or **classifies a retry**. Tools write evidence or `not_found_this_run`.

---

## 2. End-to-end workflow

Two jobs, one graph, one HTTP call:

1. **Seller context** — if the user sent a company name / site / docs, run `website_docs` on the *seller* and store a `SellerProfile`. That payload never merges into the lead’s `CollectedResearch`.
2. **Lead research** — run the four tools on the lead, merge, persist, then gap-judge missing fields.

```text
React  /  →  /lead  →  /run
                    │
                    ▼
         POST /research/runs     (FastAPI)
                    │
                    ▼
         LangGraph StateGraph
           create_run            insert research_runs status=running
                │
                ▼
           seller_profile        website_docs on SELLER (or name-only)
                │
                ▼
           plan_or_llm           MLX bind_tools  (or first_pass_router)
                │
                ├─ tool calls ──► tool_node ──► LangChain tools
                │                      │
                │                      ▼
                │              merge_research(collected, patch)
                │                      │
                └─ unused + missing ─► first_pass_router
                                           │
                                           ▼
                                     tool_node again
                                           │
                                           ▼
                                      gap_judge
                                        │
                          retry one field │ leave
                                ▼                ▼
                         targeted_tool         persist
                                │
                                ▼
                         merge; if still empty, leave
                                │
                                ▼
                             persist
                      collected + evidence + gaps
                      status complete | partial | failed
                                │
                                ▼
                      GET /research/runs/{id}
```

Rules that never change:

- Tools write evidence or `not_found_this_run`. The LLM never fills `signals.funding` with a made-up round.
- Each **first-pass** tool runs **at most once**.
- A **targeted retry** is at most **once per field**, and the graph picks **at most one field** per run.
- Second miss = leave it. That is also a result.
- `unknown` publish dates stay unknown; stale news/signals stay unused (Module 2 freshness).

---

## 3. FastAPI routing

The only product path is the graph.

### Create run

`POST /research/runs`

```json
{
  "lead": {
    "company_name": "Acme Logistics",
    "company_domain": "acme.com",
    "website_url": "https://acme.com"
  },
  "seller": {
    "name": "Alex Rivera",
    "company_name": "Excon Seller Co",
    "website_url": "https://seller.example",
    "documents": [{ "filename": "pitch.txt", "text": "We sell a CRM for freight brokers." }]
  }
}
```

- `lead.company_name` is required.
- `lead.website_url` / `company_domain` are optional. The website tool uses them when present.
- `seller` is optional but recommended. Documents are extracted text (and later `raw_bytes` for PDF). No S3 in this module.

The MVP is **synchronous `200`**: the row exists as `running` before tools finish, then the response is the finished run (`complete` / `partial` / `failed`). A background worker can come later if runs exceed ~60s.

`POST /research/run` still exists as a lead-only alias. It also goes through the graph.

### Read run

`GET /research/runs/{run_id}` → seller snapshot, collected research, evidence (inside `collected`), missing list, gap decisions (`retried` / `left_missing` + reason).

404 if the id is unknown.

---

## 4. LangGraph state and nodes

File: [`backend/app/graphs/research.py`](../backend/app/graphs/research.py)

`ResearchState`:

| Key | Meaning |
|---|---|
| `messages` | LangChain messages (agent + tool results) |
| `run_id` / `seller_id` / `lead_id` | Postgres ids (or an in-memory uuid when tests skip the DB) |
| `company_name` / `company_domain` / `website_url` | The **lead** |
| `seller_input` | Optional onboarding payload (name, site, docs) |
| `seller_profile` | Extracted `SellerProfile` JSON — not mixed into `collected` |
| `collected` | `CollectedResearch` as JSON |
| `missing` | `collected.missing_parameters()` |
| `tools_used` | First-pass tools, each at most once |
| `targeted_attempts` | e.g. `{ "signals.funding": 1 }` |
| `gap_decisions` | `{ field, verdict, reason, related_supported, retried, left_missing }` |
| `llm_calls` | Cap (8) so the first-pass loop cannot run forever |
| `status` | `running` / `complete` / `partial` / `failed` |
| `error` | Set only on failure |

| Node | Does | Does not |
|---|---|---|
| `create_run` | Upsert seller by company name, insert lead + `research_runs` row | Call Tavily |
| `seller_profile` | If seller site/docs exist, call LangChain `website_docs` with **seller** args; map products / description into `SellerProfile` | Research the lead or merge into `collected` |
| `plan_or_llm` | Bind the four tools; if Qwen skips tool-calling, `first_pass_router` still runs unused owners | Invent values |
| `tool_node` | `tool.ainvoke(args)` → parse patch → `merge_research(base, patch)` | Overwrite a `supported` field with empty |
| `gap_judge` | Deterministic relatedness + optional MLX classify | Call tools except by returning one structured retry |
| `targeted_tool` | One LangChain tool with a narrower `focus` (e.g. `funding`) | Loop |
| `persist` | Write JSON collected + evidence rows + missing + gap decisions; `complete` if nothing is missing, else `partial` | Change facts |

First-pass tool ownership is unchanged:

- `website_docs` → `company.*`
- `signals` → `signals.*`
- `news` → `news[]`
- `people` → `people[]`

Merge stays [`merge_research`](../backend/app/domain/merge.py): first supported wins; news/people de-dupe.

---

## 5. Gap judge

File: [`backend/app/application/gap_judge.py`](../backend/app/application/gap_judge.py)

After all four first-pass tools have run (or failed), `missing = collected.missing_parameters()`.

Fields of interest, in priority order (at most **one** retry):

`signals.funding` → `company.size` → `company.headquarters` → `company.products` → `company.founded` → `people` → `news`

### Deterministic relatedness (primary)

| Missing | Retry if | Else leave |
|---|---|---|
| `signals.funding` | `hiring` **and** (`new_product` or `expansion` or `tech_shift`) | “No supporting motion; an empty funding search is not ‘no funding’.” |
| `company.size` / `headquarters` / `products` / `founded` | Website URL or `company.domain` is known | No site to crawl |
| `people` | Company name or domain is known | Leave |
| `news` | First news list was empty **and** a company name is known | Leave |

If the field was already in `targeted_attempts`, it is left: “Already retried once.”

### LLM role (classifier only)

Input = supported field keys + short excerpts + the missing field.  
Output JSON `{ "verdict": "retry"|"leave", "field", "reason" }`.

Fail closed:

- If deterministic says **leave**, a model `retry` is ignored.
- If deterministic says **retry**, the model may **veto** (leave).
- The model must not emit a funding amount, email, or date.

Then:

- `retry` → `targeted_tool` once for that field, with `focus`.
- Still missing after retry → `left_missing`, do not call again.
- `leave` → reason stored on the run.

That is the “hiring + new product ⇒ maybe funding; if we still get nothing, that is also a result” behavior.

---

## 6. Targeted `focus` on tools

`ToolRequest.focus` is ignored on the first pass. The targeted node sets it:

| Field | Tool | `focus` |
|---|---|---|
| `signals.funding` | `signals` | `funding` (only that query) |
| `company.size` | `website_docs` | `size` (about / careers + site: query) |
| `company.headquarters` | `website_docs` | `headquarters` |
| `company.products` | `website_docs` | `products` |
| `company.founded` | `website_docs` | `founded` |
| `people` | `people` | `linkedin` (LinkedIn-only web search) |
| `news` | `news` | `news` (tighter “latest news announcement” query) |

A focused signals call writes **only** the focused field. Other signal slots stay `unknown`, so merge keeps earlier hiring / product values.

---

## 7. Seller profile

Onboarding already collects seller name, website, and files. Module 3 persists that.

Pydantic [`SellerProfile`](../backend/app/domain/seller_profile.py):

| Field | Meaning |
|---|---|
| `company_name` | Seller company |
| `contact_name` | Person who filled the form |
| `domain` / `website_url` | From the site or extraction |
| `description` | From `website_docs` |
| `products` / `services` | Same products string until a dedicated services field exists |
| `evidence` / `evidence_ids` | Seller-side evidence only |

If the seller sent only a name (no site/docs), the graph stores the name and skips the seller tool.

Seller HQ / products **must not** appear on the lead’s `company.*`. The leak test locks this down: first supported wins, so a mistaken merge could not be overwritten later.

---

## 8. Postgres

First product tables. Alembic revision [`0001_research_tables`](../backend/alembic/versions/0001_research_tables.py).

| Table | Role |
|---|---|
| `sellers` | Upsert by `company_name`. `profile` JSON is the `SellerProfile`. |
| `leads` | One row per run (name / domain / website). |
| `research_runs` | Status, collected JSON, missing, tools_used, gap_decisions, targeted_attempts, seller_profile snapshot, error. |
| `evidence_items` | Queryable copy of `collected.evidence` (field, excerpt, url, freshness, …). |

JSON on `research_runs.collected` is enough to reload `CollectedResearch`. No auth tables. One implicit seller (upsert by company name) is enough.

Apply:

```bash
cd backend
alembic upgrade head
```

Docker API uses the same `DATABASE_URL`. Tests use in-memory SQLite (`StaticPool`) and `Base.metadata.create_all`.

---

## 9. Frontend

[`RunPage.tsx`](../frontend/src/pages/RunPage.tsx) calls `POST /research/runs` with the onboarding seller and the lead (optional website). It waits for the synchronous response and renders:

- Seller products / description (separate from the lead)
- Lead `company.*` and `signals.*` (supported vs not found)
- News and people
- Gap decisions and the remaining missing list

No scores or recommended outreach yet (Module 5). The timeline is the live run; completion is the API, not a fake timer.

The lead form accepts an optional website so `website_docs` can crawl about / locations pages.

`VITE_API_URL` defaults to `http://localhost:8000`.

---

## 10. Files

```text
backend/app/domain/seller_profile.py
backend/app/domain/gap.py
backend/app/application/gap_judge.py
backend/app/graphs/research.py          (the orchestrator)
backend/app/infrastructure/models/research.py
backend/app/infrastructure/repositories/research.py
backend/alembic/versions/0001_research_tables.py
backend/app/api/routes/research.py
backend/app/api/schemas.py
backend/tests/test_gap_judge.py
backend/tests/test_orchestrator.py
backend/tests/test_research_api.py

frontend/src/api.ts
frontend/src/pages/RunPage.tsx
frontend/src/pages/LeadPage.tsx

docs/Module-3.md
```

Tools gained an optional `focus` argument. First-pass behavior is unchanged.

---

## 11. How to call the orchestrator

```python
from app.graphs.research import run_research
from app.domain.tool_contract import ToolRequest

state = await run_research(
    ToolRequest(company_name="Acme", website_url="https://acme.com"),
    seller_input={
        "name": "Alex",
        "company_name": "Excon Seller Co",
        "website_url": "https://seller.example",
        "documents": [{"filename": "pitch.txt", "text": "We sell a CRM."}],
    },
    session_factory=get_session_factory(),
)
```

Or HTTP:

```bash
curl -X POST http://localhost:8000/research/runs ^
  -H "Content-Type: application/json" ^
  -d "{\"lead\":{\"company_name\":\"Acme\",\"website_url\":\"https://acme.com\"},\"seller\":{\"company_name\":\"Excon Seller Co\",\"website_url\":\"https://seller.example\"}}"
```

Tests inject a silent chat model and a fake tool registry so pytest never hits MLX, Tavily, or Prospeo.

---

## 12. Tests

From `backend/`:

```bash
.\.venv\Scripts\Activate.ps1
pytest tests/test_gap_judge.py tests/test_orchestrator.py tests/test_research_api.py tests/test_research_graph.py tests/test_merge.py
```

| File | What it proves |
|---|---|
| `test_gap_judge.py` | Funding retries only when hiring + motion; classifier cannot force a retry; only one field is selected |
| `test_orchestrator.py` | First pass merges; funding retry once then stays missing; seller products do not leak into lead `company.*`; run + evidence rows exist in SQLite |
| `test_research_api.py` | `POST /research/runs` then `GET /research/runs/{id}`; missing id is 404 |
| `test_research_graph.py` | Module 2 first-pass still runs all unused tools and merges |

---

## 13. Rules this module must keep

1. **Never invent a fact.** Missing stays `not_found_this_run` or `unknown`.
2. **An empty funding search is not “they have no funding.”**
3. **Seller data and lead data stay in different objects.**
4. **First-pass tools run at most once. Targeted retry at most once per field, one field per run.**
5. **The LLM does not write `CollectedResearch`.** It calls tools or classifies a gap.
6. **Fail closed.** Deterministic leave beats a model retry.
7. **FastAPI does not call adapters.** The graph is the only path.
8. **Do not log API keys.**

---

## 14. What happens next

The orchestrator now accepts a lead, extracts the seller, calls tools, judges gaps, and stores the run.

Later:

1. Scores and a written intelligence report (Module 5)
2. Outreach drafts (Module 6)
3. Login / workspaces
4. Background queue if runs get long
5. S3 for original uploads

A typical picture: the user types **Acme** (and has already entered seller Excon + site). FastAPI creates a run. The graph extracts seller products from Excon’s site/docs and saves them. It calls `website_docs`, `signals`, `news`, `people` for Acme and merges into one object. Hiring and a new product are supported; funding is missing. The gap judge says **retry funding once**. Signals runs a funding-focused search. Still nothing → funding stays `not_found_this_run`, decision stored: “retried; still empty.” Response + DB show everything we *do* have, plus honest gaps. That is the orchestrator.
