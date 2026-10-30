# Module 4 — Seller company profile (review and approve)

**Status:** Done  
**What this module is:** build a draft seller profile from uploaded documents and the company website, show every value with its source, let the user correct it, then **approve** a version. Scoring, reports and outreach use the approved profile only. Extraction never overwrites an approved version.

**What this module is not:** login, S3 file store, OCR for scanned PDFs, legacy `.doc/.xls/.ppt`, or workspaces.

---

## Flow

```text
Onboarding form (name, company, website, files)
    → POST /sellers/extract            multipart; creates a new seller + extraction job (202)
    → GET  /sellers/extract/{job_id}   poll: stage, per-document status, final draft
    → /profile                         8-section review with sources, inferred markers, gaps, conflicts
    → PATCH /sellers/{id}/draft        user corrections (provenance stays server-owned)
    → POST /sellers/{id}/suggestions/{sid}/accept|reject
    → POST /sellers/{id}/approve       needs at least one product or service
    → /lead
```

The background job runs these stages and records the current one on `extraction_jobs`:

`uploading_documents → parsing_documents → crawling_website → normalizing_sources → extracting_facts → consolidating_evidence → analyzing_company → generating_icp → building_profile → validating_profile → ready_for_review`

Code: `backend/app/application/seller_intel/` (`pipeline.py` wires the stages).

## Storage

| Table | Holds |
|---|---|
| `extraction_jobs` | status (`queued/running/succeeded/partial/failed`), stage, warnings, summary |
| `source_documents` | upload metadata, sha256, stored path, parse status and error |
| `normalized_sources` | Markdown of every page and document, per-source extraction status |
| `company_intelligence` | analyzed company model for the job |
| `profile_suggestions` | prospect suggestions and their accept/reject status |
| `sellers.profile` / `approved_profile` | current draft / last approved snapshot |
| `seller_profile_versions` | one row per approval |

Original files are stored under `UPLOAD_DIR` (Docker volume `excon_uploads`).

## API

| Method | Path | Result |
|---|---|---|
| POST | `/sellers/extract` | New seller + job; files validated before storage |
| GET | `/sellers/extract/{job_id}` | Job progress; includes the seller once finished |
| POST | `/sellers` | Manual seller without extraction |
| GET | `/sellers/{id}` and `/sellers/{id}/draft` | Draft + approved + latest job |
| PATCH | `/sellers/{id}/draft` | User corrections; changed fields are marked `edited` |
| POST | `/sellers/{id}/suggestions/{sid}/accept` / `reject` | Suggestion status |
| POST | `/sellers/{id}/approve` | Copy draft → approved, new version |
| POST | `/research/runs` | Requires an approved `seller_id` |

## Rules

1. Every extracted claim needs an excerpt found in its source; ungrounded claims are dropped.
2. Analyzed values must cite facts; uncited values are kept only as `inferred`. Company size and geography need a citation.
3. The ICP and prospect suggestions are always `inferred`; only accepted suggestions affect scoring.
4. Conflicting sources and missing required information are reported, not resolved silently.
5. If the LLM or every source fails, the job is `failed` and an identity-only draft is kept for manual entry.
6. A job still running when the API restarts is marked `failed` at startup.
