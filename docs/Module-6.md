# Module 6 — Personalized outreach drafts

**Status:** Done  
**What this module is:** after a research run and report, a LangGraph agent selects people on the lead and writes a **distinct** LinkedIn connect note, LinkedIn message, and WhatsApp for each person. Copy is grounded in the approved seller offering, that person's title, and evidenced company motion (including last-three-months news when dates exist). You review, edit, approve, or reject. Nothing is sent.

**What this module is not:** sending mail or WhatsApp, inventing emails/phones/funding, or a generic one-message-for-the-company blast.

---

## Flow

```text
Approved seller + research run + report
    → POST /research/runs/{run_id}/drafts   (LangGraph outreach agent)
    → /drafts                               (person-wise cards)
    → PATCH /drafts/{id}                    (your edits, versioned)
    → POST /drafts/{id}/approve | reject
```

Approved drafts are left alone on regenerate. Draft / rejected rows are rewritten and the previous body is stored in `outreach_draft_versions`.

## Agent

`graphs/outreach.py` is a StateGraph:

1. **select_and_compose** — decision-makers first, then other named people (cap 8). Each draft names the person, uses their designation, cites only stored facts, and leads with the offering that scored as the best fit.
2. **persist** — upsert by `(run_id, person_evidence_id)`.

There is no LLM invention path. If a fact was not evidenced this run, it does not appear.

## API

| Method | Path | Result |
|---|---|---|
| POST | `/research/runs/{run_id}/drafts` | Generate / regenerate |
| GET | `/research/runs/{run_id}/drafts` | List |
| GET | `/drafts/{id}` | One draft |
| PATCH | `/drafts/{id}` | Edit copy, new version |
| POST | `/drafts/{id}/approve` | Mark approved (still not sent) |
| POST | `/drafts/{id}/reject` | Mark rejected |

## Rules

1. Personalize only with facts in `CollectedResearch` or the approved seller profile.
2. Never invent emails, phones, LinkedIn URLs, or funding.
3. LinkedIn connect notes stay at or under 300 characters.
4. Generation is separate from sending. There is no send endpoint.
