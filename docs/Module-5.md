# Module 5 — Summarized report (score and fit)

**Status:** Done  
**What this module is:** after a research run, combine the **approved seller profile** with the lead’s `CollectedResearch` and decide whether the lead is worth conversion time. Scores are computed in Python. The LLM may write the narrative; it does not invent scores or facts.

---

## Scores (0–100, each with reasons)

| Score | Meaning |
|---|---|
| Seller–lead fit | Token overlap of approved offerings / ICP vs lead description, industry, products, signals |
| Lead qualification | Buying motion: hiring, launch, expansion, funding, tech shift, news |
| Research completeness | How many core fields have evidence |
| Evidence quality | Freshness × confidence of stored evidence |
| Contact relevance | Decision-maker titles and reachable people |
| Overall | 35% fit + 30% qualification + 20% completeness + 15% contacts |

Recommendation:

- **pursue** — fit and motion are both strong enough to spend energy
- **consider** — some fit or motion, but gaps remain
- **deprioritize** — weak fit and weak motion

The report also lists why it is a fit, why it is not, which offerings match, a next step, and a conversation angle.

## API

| Method | Path |
|---|---|
| POST | `/research/runs/{run_id}/report` |
| GET | `/research/runs/{run_id}/report` |
| GET | `/reports/{id}` |

Persisted in `lead_reports` (scores JSON + full body + recommendation). The `/run` page generates the report after research finishes and shows it above the raw fields.
