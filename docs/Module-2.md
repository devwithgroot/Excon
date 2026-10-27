# Module 2 — Research tools + LangGraph agent

**Status:** Done  
**What this module is:** evidence-backed research tools, wrapped as **LangChain tools**, and called only from a **LangGraph** orchestrator agent. FastAPI, Pydantic, and Python still sit underneath. The agent never invents facts; it only chooses and runs tools.

**What this module is not:** it does not score a lead, write a report, persist a research run, or send outreach. Those come later.

Read [Module-0.md](Module-0.md) first if you need the runtime (FastAPI, Postgres, Compose, `.env`).

Work lives on the `sandeep/module-2` branch.

---

## 1. Why this is LangGraph / LangChain

The product is evidence-driven **and** agentic. A claim is allowed only when a tool’s source supports it. The LLM (MLX Qwen) is **not** a source of facts.

So we split two layers:

| Layer | What it is | What it is not |
|---|---|---|
| **Python adapters** (`signals.py`, `news.py`, `website_docs.py`, `people.py`) | Fetch Tavily / site / Prospeo, attach evidence, return a Pydantic patch | Not called by FastAPI or the UI directly |
| **LangChain tools** (`application/lc_tools.py`) | Same four tools, exposed with names + descriptions the agent can call | Not a second copy of the fetch logic |
| **LangGraph agent** (`application/research_graph.py`) | Decides which tool to run, merges patches, reads `missing_parameters()`, stops | Does not fill empty fields with model text |

If the model does not emit a tool call (local Qwen may skip tool-calling), a **gap router** inside the same graph still calls the unused tool that owns a missing field. Either way, tools run **from the graph**, not from a handwritten `for name in TOOL_NAMES` loop in a route.

Empty search still means `not_found_this_run`. The agent must not invent a Series A.

---

## 2. What Module 2 actually built

Done:

- One Pydantic model, `CollectedResearch`, for every research parameter
- Four Python adapters (Tavily, website crawl, Prospeo enrich)
- LangChain wrappers for those four adapters
- LangGraph `StateGraph`: `llm_call` → `tool_node` → merge → (optional) `gap_router`
- `POST /research/run` so FastAPI invokes the graph, not the adapters
- 90-day freshness, merge, SSRF, mocks, this document

Not done (later):

- Targeted second-pass gap search (e.g. hiring + launch ⇒ one more funding query)
- Saving the run to Postgres
- Wiring the React `/run` page to `POST /research/run`
- Scores, reports, drafts, login

---

## 3. How the agent calls tools

```text
POST /research/run  (FastAPI)
        │
        ▼
 LangGraph StateGraph
   llm_call  ── MLX Qwen (ChatOpenAI-compatible) + bind_tools
        │
        ├─ tool calls ──► tool_node ──► LangChain tools
        │                      │
        │                      ▼
        │              Python adapters
        │              signals / news / website_docs / people
        │                      │
        │                      ▼
        │              merge_research(collected, patch)
        │                      │
        └─ no tool calls ──► gap_router (if missing + unused tool)
                                    │
                                    ▼
                              tool_node again
                                    │
                                    ▼
                         END → CollectedResearch + missing_parameters()
```

Graph state (`ResearchState`):

| Key | Meaning |
|---|---|
| `messages` | LangChain messages (agent + tool results). Summaries only go back to the model, not raw emails. |
| `company_name` / `domain` / `website_url` | The lead |
| `collected` | `CollectedResearch` as JSON (the one shared schema) |
| `missing` | `collected.missing_parameters()` |
| `tools_used` | Each tool at most once per run |
| `llm_calls` | Cap (8) so the loop cannot run forever |

Each adapter still writes only its own slots on `CollectedResearch`:

| LangChain tool name | Python file | Writes |
|---|---|---|
| `signals` | `signals.py` | `signals.*` |
| `news` | `news.py` | `news[]` |
| `website_docs` | `website_docs.py` | `company.*` |
| `people` | `people.py` | `people[]` |

Company details still come from the official website (homepage **and** inner pages), not a firmographics vendor.

---

## 4. Shared domain models

These files live under `backend/app/domain/`. They must not import FastAPI, LangChain, Tavily, Prospeo, or SQLAlchemy.

### 4.1 `CollectedResearch`

File: [`backend/app/domain/collected_research.py`](../backend/app/domain/collected_research.py)

| Block | Fields | Who fills them |
|---|---|---|
| `company` | name, domain, description, industry, headquarters, products, size, founded | `website_docs` |
| `signals` | funding, hiring, tech_shift, acquisition, new_product, expansion | `signals` |
| `news` | list of recent items (title, url, published_at, excerpt, evidence_id) | `news` |
| `people` | list of people (name, title, role, email, phone, LinkedIn, evidence_id) | `people` |
| `evidence` | every claim’s source record | all tools |

Company and signal fields are wrapped in `FieldValue`:

| Field | Meaning |
|---|---|
| `value` | The extracted string, or `null` |
| `status` | See the table below |
| `evidence_ids` | IDs of `EvidenceItem` rows that support this value |

### 4.2 Field status

| Status | When it is used | What it does **not** mean |
|---|---|---|
| `unknown` | This tool did not write the field. Another tool owns it, or nothing has run yet. | Not “we searched and failed.” |
| `supported` | We have a value **and** evidence. | Not a guess. |
| `not_found_this_run` | This tool looked and found nothing usable. | Not “the company has no funding / no HQ / no people.” |

Example after a signals run that found hiring but not funding:

```text
signals.hiring.status   = supported      value = "Acme is hiring engineers"
signals.funding.status  = not_found_this_run   value = null
company.name.status     = unknown        (signals does not touch company)
```

`missing_parameters()` returns every company/signal field whose status is not `supported`, plus `"news"` if the news list is empty and `"people"` if the people list is empty.

### 4.3 Evidence

File: [`backend/app/domain/evidence.py`](../backend/app/domain/evidence.py)

Every supported claim carries an `EvidenceItem`:

| Field | Purpose |
|---|---|
| `evidence_id` | Hex UUID; `FieldValue.evidence_ids` points here |
| `field_key` | e.g. `signals.funding`, `company.headquarters`, `news`, `people` |
| `extracted_value` | The claim we stored |
| `source_url` | Page or provider URL when we have one |
| `source_type` | `web_search` / `news` / `website` / `document` / `people` |
| `source_published_at` | Publish date from the source, or `null` |
| `retrieved_at` | When we fetched it |
| `supporting_excerpt` | Short quote from the source |
| `extraction_method` | `tavily`, `heuristic`, `grounded`, `web_search`, `web+prospeo`, … |
| `confidence` | 0–1, informational |
| `freshness` | `fresh` / `stale` / `unknown` |

A tool must not store a supported value without evidence.

### 4.4 Freshness (3 months)

File: [`backend/app/domain/freshness.py`](../backend/app/domain/freshness.py)

Window: **90 days**.

| Publish date | Freshness | Signals / news treat it as |
|---|---|---|
| Within 90 days | `fresh` | Usable |
| Older than 90 days | `stale` | Dropped. A year-old article is not current news. |
| Missing | `unknown` | Kept. The tool does **not** invent a date. Module 3 decides whether to trust it. |

`is_usable()` is `freshness != stale`.

### 4.5 Tool contract

File: [`backend/app/domain/tool_contract.py`](../backend/app/domain/tool_contract.py)

**Input** (`ToolRequest`):

| Field | Meaning |
|---|---|
| `company_name` | Required. Used in search queries and grounding. |
| `company_domain` | Optional root domain (`acme.com`, no `www`). |
| `website_url` | Optional official page to fetch. |
| `documents` | Optional uploads: `filename`, `text`, and/or `raw_bytes` (PDF or plain). |

**Output** (`ToolResult`):

| Field | Meaning |
|---|---|
| `success` | Provider call completed (even if it found nothing). |
| `tool_name` / `tool_version` | Which adapter ran. |
| `patch` | Partial `CollectedResearch` for **this tool’s fields only**. |
| `evidence` | The evidence items also copied onto `patch.evidence`. |
| `error_code` | Set when `success` is false (`signals_provider_error`, `people_not_configured`, …). |
| `retryable` | True for timeouts / provider outages. False when the API key is missing. |

`ResearchTool` is a protocol: `name`, `version`, `fulfills` (the parameter keys this tool is allowed to write), and `async execute(request) -> ToolResult`.

### 4.6 Merge

File: [`backend/app/domain/merge.py`](../backend/app/domain/merge.py)

`merge_research(base, patch)` applies one tool’s fill onto the accumulated object.

| Kind | Rule |
|---|---|
| Company / signal `FieldValue` | First `supported` value **wins**. An empty or `not_found_this_run` patch does not overwrite a supported value. |
| `unknown` + `not_found_this_run` | Becomes `not_found_this_run` (we now know this tool looked). |
| News | Append by URL. Same URL is not added twice. |
| People | Append by `(name.lower(), title)`. Same person is not added twice. |
| Evidence | First item for a given `evidence_id` is kept. |

This is why tools can run in any order: a later empty result cannot wipe an earlier good one.

---

## 5. The four tools

All adapters live under [`backend/app/infrastructure/tools/`](../backend/app/infrastructure/tools/). Domain code does not import these files.

### 5.1 Signals — `signals.py`

**Provider:** Tavily.  
**Writes:** `signals.funding`, `hiring`, `tech_shift`, `acquisition`, `new_product`, `expansion`.  
**Does not write:** company, news, people.

For each signal it runs a targeted query, e.g. `"{company} funding raised series investment"`, with `days=90`.

A hit is kept only if:

1. Its text actually contains keywords for that signal (so a picnic article does not become “funding”)
2. Its publish date is not stale

If nothing usable is left, that signal is `not_found_this_run` with `value = null`. The tool never invents a round, a headcount, or an acquisition.

On Tavily failure it returns `success=false`, `error_code=signals_provider_error`, `retryable=true`.

### 5.2 News — `news.py`

**Provider:** Tavily, `topic=news`, `days=90`.  
**Writes:** `news[]`.  
**Does not write:** company, signals, people.

Each usable hit becomes a `NewsItem` (title, url, published_at, excerpt) plus an `EvidenceItem` of type `news`. Hits with no URL are skipped. Hits older than 90 days are skipped. Hits with no date are kept and marked `freshness=unknown`.

If every hit is stale or empty, `news` stays `[]` and `missing_parameters()` will include `"news"`.

### 5.3 Website + documents — `website_docs.py`

**Provider:** HTTP fetch of the official site, plus uploaded text/PDF. No company-data vendor.  
**Writes:** `company.name`, `domain`, `description`, `industry`, `headquarters`, `products`, `size`, `founded`.  
**Does not write:** signals, news, people.

HQ, products, size, and founded date are often **not on the homepage**. This tool scrapes more than the front page.

What it reads:

1. The homepage (`website_url`, or `https://{company_domain}`)
2. Same-domain inner pages: `/about`, `/about-us`, `/company`, `/our-story`, `/locations`, `/contact`, `/products`, `/solutions`, plus homepage links that look like those sections
3. If HQ / products / size / founded is still missing: Tavily `site:{domain}` search, then fetch only same-domain URLs whose path still looks official (about, company, locations, products)
4. Uploaded documents (`text`, or `raw_bytes` for `.pdf` / plain files)

It stays on the company’s own site (SSRF + same-root-domain). Budget: `website_max_pages` (default 8), plus up to three targeted `site:` follow-up pages. About / company / locations rank above other pages when two pages disagree. Blog, docs, guides, use-cases, and job listings (`/listing/`, `/job/`) are skipped.

Facts are taken from the page that actually states them. Example: Stripe’s homepage did not state HQ; `/about` did (`South San Francisco`). If products, size, or founded still do not appear on those pages, they stay `not_found_this_run`.

What it will not fetch (SSRF):

- Non-`http`/`https` URLs
- `localhost`, `*.local`, `0.0.0.0`
- Private, loopback, link-local, reserved, or multicast IPs (checked after DNS)
- More than three redirects; **each hop** is re-checked
- Responses over `website_max_bytes` (default 2 MB)
- Content types other than `text/html`, `text/plain`, `application/xhtml+xml`

Extraction is conservative:

- Heuristics look for phrases already in the page (“headquartered in …”, “200 employees”, “Industry: …”, “Products include …”, “Founded in 2011”)
- Size requires the word `employees` (not a loose “15 people” from a job post)
- Description skips navigation chrome (“Sign in”, “See all products”)
- Company name is stored only if that name appears in the retrieved text
- Domain may be taken from the requested URL/domain (that is the page we fetched, not an invented host)
- Optional MLX JSON extract is applied **after** heuristics, then `grounded_only()` drops any value that is not in the excerpt

If a field is not in the text, it is `not_found_this_run`. The model cannot invent “quantum computing” or “Mars Colony” when the page only says “Acme sells bolts.”

### 5.4 People — `people.py`

**Writes:** `people[]`.  
**Does not write:** company, signals, news.

Prospeo company-wide search is **not** the source of who matters. It often returns the wrong people, and `/search-person` never reveals email or mobile.

The flow is:

1. **Web search first** (Tavily), two queries:
   - `{company} (CEO OR founder OR "managing director" OR owner) site:linkedin.com/in`
   - `{company} CEO founder owner director "managing director" MD president chairman`
   Capture name, role, and LinkedIn from those hits.
2. **Then Prospeo**, only for those named people:
   - `POST https://api.prospeo.io/enrich-person` with `full_name` + `company_website` + `linkedin_url` when we have it. This is the endpoint that can reveal email and mobile.
   - If enrich misses: `POST /search-person` with `filters.person_name` + company website, then enrich by `person_id`.
3. **Show the web-found person** even if Prospeo has no contact. Do not invent email/phone. Do not dump a random Prospeo employee list for the domain.
4. If Prospeo matches a **different company**, drop its email/phone and keep the web name / title / LinkedIn.

Enrich costs credits (1 per email; 10 if `enrich_mobile` is on). We cap at `prospeo_enrich_limit` (default 5).

Mapping rules (no invention):

| Input | Stored |
|---|---|
| Web name, or Prospeo `full_name` | `name` |
| Web role, or `current_job_title` | `title` |
| Enrich `email` only if `revealed: true` and unmasked | `email` |
| Enrich `mobile` only if `revealed: true` and unmasked | `phone` |
| LinkedIn from web search or Prospeo | `linkedin_url` — never built from a name |

Missing API key → `success=false`, `people_not_configured`, `retryable=false`.  
Provider/network error on the web search → `people_provider_error`, `retryable=true`.  
Zero people → empty list; `missing_parameters()` includes `"people"`.

---

## 5.5 LangChain wrappers and the graph

**Wrappers** — [`backend/app/application/lc_tools.py`](../backend/app/application/lc_tools.py)

`langchain_research_tools(registry)` builds four `StructuredTool`s. Each one accepts `company_name`, `company_domain`, `website_url`, runs the Python adapter, and returns JSON `{ success, patch, summary }`. The graph merges `patch`. The model only sees `summary` (counts and titles, not raw secrets).

**Graph** — [`backend/app/application/research_graph.py`](../backend/app/application/research_graph.py)

- Model: `ChatOpenAI` pointed at `MLX_BASE_URL` / `MLX_MODEL` (OpenAI-compatible).
- `llm_call` binds the four tools and asks the model which to run.
- `tool_node` executes those LangChain tools and `merge_research`.
- `gap_router` runs if the model stops early while unused tools still own missing fields.
- `run_research(ToolRequest)` compiles and `ainvoke`s the graph.

**HTTP** — `POST /research/run` in [`backend/app/api/routes/research.py`](../backend/app/api/routes/research.py). Body is `ToolRequest`. Response is `collected`, `missing`, `tools_used`, `llm_calls`. Do not call `SignalsTool().execute` from a route.

---

## 6. Shared helpers (not tools)

These are not a fifth research tool. Other adapters use them.

| File | Role |
|---|---|
| `tavily.py` | `POST https://api.tavily.com/search`. Used by signals, news, people (decision-maker search), and website_docs (`site:` follow-up). |
| `http_safety.py` | `url_is_public_http()` — scheme + host + resolved IP checks. |
| `mlx_client.py` | OpenAI-compatible chat to `MLX_BASE_URL`. Temperature 0. Parses JSON (including fenced ` ```json `). `grounded_only(value, excerpt)` keeps a value only if it appears in the excerpt (or its first few tokens do). |
| `registry.py` | Python adapters by name. The graph wraps this registry as LangChain tools. |
| `mocks.py` | `FakeTavilyClient`, `FakeMlxClient`, `FakeProspeoClient` for pytest. |

MLX is allowed to **structure** text we already retrieved. If it adds a fact that is not in that text, the fact is dropped. It is never treated as a verified source.

---

## 7. Repository layout (what Module 2 added)

```text
backend/app/graphs/
  research.py             LangGraph StateGraph (the agent)
backend/app/tools/
  lc_tool.py              wrap a Pydantic adapter as a LangChain tool
  __init__.py             research_tools() — the four tools the agent can call

backend/app/domain/
  collected_research.py   CollectedResearch, FieldValue, company/signals/news/people
  evidence.py             EvidenceItem, SourceType, Freshness
  freshness.py            90-day classify_freshness / is_usable
  merge.py                merge_field / merge_research
  tool_contract.py        ToolRequest, ToolResult, DocumentInput, ResearchTool
  __init__.py             re-exports

backend/app/infrastructure/tools/
  signals.py              Tavily business signals
  news.py                 Tavily news, last 90 days
  website_docs.py         Homepage + inner pages + site: follow-up → company.*
  people.py               Web decision-makers, then Prospeo enrich
  registry.py             name → Python adapter
  tavily.py               Tavily HTTP client
  http_safety.py          SSRF checks
  mlx_client.py           Grounded JSON extract
  mocks.py                fakes for tests
  __init__.py

backend/tests/
  test_freshness.py
  test_merge.py
  test_signals.py
  test_news.py
  test_website_docs.py
  test_http_safety.py
  test_people.py
  test_mlx_client.py
  test_registry.py
  test_research_graph.py
  test_health.py          (Module 0, still here)

docs/Module-2.md          this file
```

The React `/run` page does not call `POST /research/run` yet.

---

## 8. Configuration

Keys stay in `.env` (gitignored). `.env.example` has names only.

| Setting | Default | Used by |
|---|---|---|
| `TAVILY_API_KEY` | empty | signals, news, people web search, website site: follow-up |
| `PROSPEO_API_KEY` | empty | people |
| `MLX_BASE_URL` | `http://127.0.0.1:8080` | LangGraph agent + optional website extract |
| `MLX_MODEL` | `mlx-community/Qwen3-8B-4bit` | same |
| `http_timeout_seconds` | `20` | Tavily, Prospeo, website fetch |
| `website_max_bytes` | `2000000` | website fetch size cap |
| `website_max_pages` | `8` | homepage + inner pages + site: follow-ups |
| `prospeo_page_size` | `10` | named-search page cap |
| `prospeo_enrich_limit` | `5` | max decision-makers to enrich |
| `prospeo_enrich_mobile` | `true` | reveal mobile on enrich (10 credits if found) |

Timeouts, page caps, and enrich limits are Settings defaults in [`backend/app/config.py`](../backend/app/config.py). They do not need to be in `.env` unless you want to override them.

`GET /health/providers` still returns **booleans only** (`tavily_configured`, `prospeo_configured`, `mlx_configured`). It never returns key values or prefixes.

---

## 9. How to call research (always through the graph)

Do **not** loop the four adapters from a route. Call the LangGraph runner:

```python
from app.application.research_graph import run_research
from app.domain.tool_contract import ToolRequest

state = await run_research(
    ToolRequest(
        company_name="Acme",
        company_domain="acme.com",
        website_url="https://acme.com",
    )
)
collected = state["collected"]
gaps = state["missing"]
```

Or HTTP:

```bash
curl -X POST http://localhost:8000/research/run ^
  -H "Content-Type: application/json" ^
  -d "{\"company_name\":\"Acme\",\"company_domain\":\"acme.com\",\"website_url\":\"https://acme.com\"}"
```

Tests inject a fake chat model and a fake registry so pytest never hits MLX, Tavily, or Prospeo.

---

## 10. Tests

From `backend/`:

```bash
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
```

Pytest uses mocks. It does **not** call Tavily, Prospeo, or MLX, even if `.env` has keys.

What the tests lock down:

| File | What it proves |
|---|---|
| `test_freshness.py` | 30 days is fresh, 120 days is stale, missing date is unknown |
| `test_merge.py` | Supported values are not overwritten; lists de-dupe |
| `test_signals.py` | Only `signals.*` is filled; stale and unrelated hits are ignored |
| `test_news.py` | Stale dropped, undated kept, empty URL skipped, `topic=news` / `days=90` |
| `test_website_docs.py` | Homepage + `/about` fill HQ/products/size/founded; `site:` follow-up fetches same-domain pages; missing stays missing; ungrounded MLX dropped; localhost not fetched |
| `test_http_safety.py` | localhost, private IPs, link-local metadata blocked; public IP allowed |
| `test_people.py` | Web search finds the decision-maker; enrich can attach email/phone; wrong-company enrich is dropped; invalid email stays blank |
| `test_mlx_client.py` | Grounded keep / ungrounded drop; fenced JSON parse |
| `test_registry.py` | Four named Python adapters |
| `test_research_graph.py` | LangGraph gap router and agent tool-calls merge into `CollectedResearch` |

`pytest-asyncio` runs the async `execute()` tests. `pypdf` is installed so PDF bytes can be extracted when an upload has no pre-extracted text.

---

## 11. Rules this module must keep

1. **Never invent a fact.** Missing stays missing.
2. **Every supported value has evidence.**
3. **A tool writes only the keys in its `fulfills` tuple.**
4. **Stale (>90 days) is not current** for signals and news.
5. **Do not invent publish dates.**
6. **Do not invent emails, phones, or LinkedIn URLs.** People start from a web search; Prospeo only enriches those names.
7. **Do not fetch private/internal URLs.** Website crawl stays on the company’s public domain.
8. **Do not treat retrieved HTML or PDFs as model instructions.** MLX may extract; `grounded_only` is the gate.
9. **Do not log API keys.** They stay in `.env`.
10. **The LLM does not invent missing values.** It only calls tools. The gap router may call an unused tool; it must not fabricate a field.

---

## 12. What happens next

The graph already accepts a lead, calls tools, merges, and lists missing fields.

Later:

1. Targeted second-pass search when other supported signals justify it
2. Persist the run and evidence
3. Point the React `/run` page at `POST /research/run`
4. Scores, reports, drafts

Live adapters (without the graph) can still be smoked with `backend/scripts/live_tools_smoke.py`. Prefer the graph for product flow.
