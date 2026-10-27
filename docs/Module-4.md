# Module 4 — Seller company profile (review and approve)

**Status:** Done  
**What this module is:** extract a draft seller profile from the company site and any uploaded text, let the user correct it, then **approve** a version. Later scoring and reports use the approved profile only. Extraction never overwrites an approved version.

**What this module is not:** login, S3 file store, OCR, or workspaces.

---

## Flow

```text
Onboarding form
    → POST /sellers/extract     (website_docs + optional MLX, saved as draft)
    → /profile                  (user edits)
    → PATCH /sellers/{id}/draft
    → POST /sellers/{id}/approve
    → /lead
```

Draft and approved are stored separately. Each approve writes `seller_profile_versions` and increments `approved_version`.

## API

| Method | Path | Result |
|---|---|---|
| POST | `/sellers/extract` | Upsert seller, write draft |
| GET | `/sellers/{id}` | Draft + approved + version |
| PATCH | `/sellers/{id}/draft` | User corrections |
| POST | `/sellers/{id}/approve` | Copy draft → approved, new version |

The profile includes company fields, products/services, and ICP (industries, size, geography, roles, problems, buying signals, exclusions).

## Rules

1. Extracted facts are candidates until the user approves.
2. The LLM does not silently overwrite approved data.
3. Research uses `approved_profile` when `seller_id` is sent on `POST /research/runs`.
