# Excon — Seller Intelligence Extraction & Profile Architecture Refactoring

## Objective

I want to refactor the existing Excon seller onboarding and company profile extraction workflow.

The current implementation collects company information from a website and optional documents, maps the extracted information into Pydantic models, and displays it on the frontend.

However, the information displayed in the UI is incomplete, incorrectly structured, poorly categorized, or missing.

I want to introduce a proper **Company Intelligence Processing Pipeline** between source collection and final Pydantic profile generation.

The system should understand a company's business, products, services, target customers, business model, value proposition, differentiators, and ideal customer profile using information collected from its website and optional uploaded documents.

The final output must be structured, evidence-backed, validated, and ready for human review.

IMPORTANT: Do not immediately start rewriting files. First inspect the existing repository, understand the current implementation, identify the root causes, and prepare an implementation plan. Then implement the changes incrementally.

---

# PART 1 — UNDERSTAND THE EXISTING IMPLEMENTATION

First inspect the following existing components:

### Backend
- `backend/app/application/seller_extract.py`
- `backend/app/domain/seller_profile.py`
- `backend/app/domain/tool_contract.py`
- `backend/app/infrastructure/tools/website_docs.py`
- `backend/app/infrastructure/tools/mlx_client.py`
- `backend/app/api/routes/sellers.py`
- `backend/app/domain/merge.py`
- `backend/app/domain/collected_research.py`
- Existing database and persistence modules.
- Existing LLM client and configuration.
- Existing tool integrations (Tavily, Prospeo, the MLX OpenAI-compatible LLM server). There is no Twilio integration in this repo.

### Frontend
- `frontend/src/pages/OnboardingPage.tsx`
- `frontend/src/pages/ProfileReviewPage.tsx`
- `frontend/src/api.ts`
- `frontend/src/session.tsx`
- Existing profile types and components.

Inspect the actual repository structure before assuming that these paths or implementations are unchanged.

### Identify the following problems

1. Why are extracted fields missing or incorrectly populated?
2. Why are documents not contributing properly to extraction?
3. Why is the LLM analysis not being executed?
4. Why is the existing heuristic extraction insufficient?
5. Where is information being lost during schema mapping?
6. Are backend response fields compatible with frontend expectations?
7. Are frontend merge operations overwriting or hiding extracted values?
8. Are null values, empty strings, nested objects, and arrays handled consistently?
9. Are extraction timeouts causing incomplete fallback profiles to be displayed?
10. Is evidence correctly linked to individual extracted fields?

Provide a short diagnosis before implementation.

Do not remove existing working functionality without identifying its dependencies.

---

# PART 2 — NEW SELLER INTELLIGENCE PIPELINE

Implement a modular pipeline with the following stages.

## Stage 1: Input Collection

The user provides:

- Seller/contact name (required).
- Company name (required).
- Company website URL (required).
- Company documents (optional, multiple files).

The website must always be processed.

Documents are optional. The system must work correctly with:
- Website only.
- Website + one document.
- Website + multiple documents.

Support common document formats where practical:

- PDF
- DOC
- DOCX
- TXT
- MD
- CSV
- JSON
- XLS
- XLSX
- PPT
- PPTX
- HTML

For image-based PDFs and scanned documents, provide OCR support through an appropriate parser when configured.

**v1 scope (implemented):** PDF (text layer), DOCX, XLSX, PPTX, TXT, MD, CSV, JSON, HTML. Legacy binary `.doc`, `.xls` and `.ppt` need LibreOffice, and OCR needs a tesseract binary in the image, so v1 rejects them with an explicit `unsupported_format` status. A PDF with no text layer is reported as `failed` with the error `no_text_layer` (likely scanned), never as an empty success.

Validate file extensions, MIME types, file size, and content before processing.

Do not send document filenames without their actual contents.

The frontend must upload real file contents to the backend, preferably using multipart/form-data or an appropriate secure upload mechanism.

Preserve the original file and its metadata.

Uploaded files and their processing state must survive page refreshes.

## Stage 2: Document Parsing and Markdown Normalization

Create a dedicated document processing module.

Suggested files:

- `document_parser.py`
- `markdown_normalizer.py`
- `document_models.py`

Responsibilities:

1. Identify document type.
2. Extract text.
3. Extract tables and meaningful structural information where possible.
4. Preserve headings and sections.
5. Preserve document metadata.
6. Normalize extracted content into Markdown.
7. Store normalized Markdown.
8. Maintain references to the original document.

Example:

Original PDF:

Company Profile:
We provide cloud-based inventory management solutions for retail businesses.

Normalized Markdown:

# Company Profile

## Business Description

We provide cloud-based inventory management solutions for retail businesses.

The normalized Markdown must retain useful structure rather than flattening everything into plain text.

For every document, maintain:

- Document ID.
- Original filename.
- Original format.
- Original file reference.
- Normalized Markdown.
- Parsing status.
- Parsing errors.
- Page or section references where available.
- Extraction timestamp.

Do not treat a failed document parser as a successful empty extraction.

The system should clearly report unsupported formats, encrypted files, corrupt files, and parsing failures.

## Stage 3: Website Deep Crawling

Create or refactor the website crawling module.

Suggested file:

`website_crawler.py`

The crawler should:

1. Fetch the homepage.
2. Extract internal links.
3. Identify relevant company pages.
4. Crawl relevant pages within the same domain.
5. Extract meaningful content.
6. Normalize the content into Markdown.
7. Maintain the source URL and metadata.

Prioritize pages such as:

- About Us
- Company
- Products
- Services
- Solutions
- Industries
- Use Cases
- Features
- Pricing
- Customers
- Case Studies
- Testimonials
- Integrations
- Partners
- Contact
- Careers

Use sitemap.xml when available.

Use internal link discovery and configurable crawl limits.

Avoid:
- Login pages.
- Privacy pages.
- Cookie banners.
- Duplicate pages.
- Irrelevant navigation content.
- External domains unless explicitly supported by a separate research tool.

Use Tavily or the existing configured search integration for additional company research where appropriate.

The system should not rely only on the homepage or fixed URL paths.

Implement configurable limits for:
- Maximum pages.
- Maximum crawl depth.
- Request timeout.
- Page size.
- Concurrent requests.

Retain the existing SSRF protection, redirect validation, public IP checks, and safe-fetching rules.

Every crawled page must become an identifiable source.

## Stage 4: Unified Source Registry

Create a central source registry.

Suggested file:

`source_registry.py`

Every source must be represented independently.

Possible source types:

- Website page.
- Uploaded document.
- Search result.
- External research source.
- Other configured tool output.

Each source should maintain:

- `source_id`
- `source_type`
- `source_name`
- `source_url`
- `original_content_reference`
- `normalized_markdown`
- `extraction_status`
- `created_at`

Do not immediately merge all source content into one large string.

Keep individual sources identifiable throughout the entire pipeline.

This is important for evidence tracking, source comparison, and debugging.

---

# PART 3 — SOURCE-WISE EXTRACTION AND EVIDENCE

## Stage 5: Individual Source Extraction

Create:

`source_extractor.py`

Before generating the final company profile, extract information from each source independently.

For example:

Website extraction:
- Company description.
- Products.
- Services.
- Features.
- Industries.
- Use cases.
- Business model.
- Value proposition.
- Differentiators.
- Customer segments.
- Geographic presence.

Document extraction:
- Company overview.
- Product catalogues.
- Service descriptions.
- Technical capabilities.
- Customer segments.
- Industry specialization.
- Case studies.
- Business claims.
- Target customers.
- Commercial information.

The extraction process should be source-aware.

Do not assume that every document contains every field.

Use structured LLM extraction with Pydantic-compatible outputs.

The extraction prompt must instruct the model to:

1. Extract only information supported by the supplied source.
2. Preserve the original meaning.
3. Avoid inventing missing details.
4. Distinguish explicit statements from inferred information.
5. Return unknown fields as null or an explicit unknown status.
6. Include supporting excerpts and source references.
7. Avoid confusing products, services, features, and use cases.

Create a normalized intermediate extraction model.

Do not map these results directly into `SellerProfile`.

## Stage 6: Evidence Management

Every important extracted fact should have evidence.

Create or extend `EvidenceItem`.

Suggested fields:

- `evidence_id`
- `source_id`
- `source_type`
- `source_url`
- `source_title`
- `field_name`
- `extracted_value`
- `supporting_excerpt`
- `page_number` or `section_reference`
- `confidence`
- `extraction_method`
- `created_at`

Every final company profile field should reference its supporting evidence.

If information is inferred by the LLM, clearly distinguish it from directly stated facts.

An inferred claim must not be presented as verified company information.

---

# PART 4 — COMPANY INTELLIGENCE ANALYSIS

## Stage 7: Evidence Consolidation

Create:

`evidence_consolidator.py`

This stage combines extracted information from different sources.

Responsibilities:

1. Deduplicate information.
2. Identify similar statements.
3. Merge complementary information.
4. Detect conflicting statements.
5. Preserve supporting evidence.
6. Identify missing information.
7. Assign field-level confidence.
8. Maintain source provenance.

Example:

Website:
"We provide sales automation software."

Company brochure:
"Our platform helps FMCG distributors manage field sales operations."

Consolidated understanding:

"The company provides field-sales automation software for FMCG distributors."

The consolidated statement must retain references to both sources.

Conflict example:

Website says the company serves small businesses.

Uploaded document says the company serves enterprise clients.

Do not silently discard either statement.

Represent the conflict and, where appropriate, show it for user review.

Website and uploaded documents should complement each other rather than blindly overwrite one another.

Use source reliability, recency, explicitness, and evidence strength when determining whether a claim can be consolidated.

## Stage 8: Company Intelligence Analyzer

Create:

`company_analyzer.py`

This is the most important new component.

Use the configured LLM provider and existing LLM client.

Do not hardcode a particular model or provider.

The analyzer receives the consolidated source facts and evidence.

Its job is to understand the company's actual business.

Analyze the following dimensions:

### A. Company Identity
- Company name.
- Industry.
- Sub-industry.
- Company description.
- Business model.
- Geographic presence.
- Company size, if supported.
- Market positioning.

### B. Products
For each product:
- Name.
- Description.
- Main functionality.
- Features.
- Target users.
- Problems solved.
- Business value.
- Supporting evidence.

### C. Services
For each service:
- Name.
- Description.
- Target customer.
- Business outcome.
- Use cases.
- Supporting evidence.

### D. Value Proposition
- What the company offers.
- Why customers would buy it.
- What problems it solves.
- How it creates business value.
- Its competitive differentiation.

### E. Customer Segmentation
- Target industries.
- Customer types.
- Business sizes.
- Geographic markets.
- Departments.
- Buyer personas.

### F. Business Understanding
Understand the relationship between:
- Products and services.
- Features and business outcomes.
- Customer problems and offerings.
- Industries and use cases.
- Value proposition and customer segments.

Do not simply copy extracted sentences into fields.

The model should organize and interpret the information into meaningful business categories.

However, every factual claim must remain traceable to source evidence.

---

# PART 5 — IDEAL CUSTOMER PROFILE AND PROSPECT SUGGESTIONS

## Stage 9: ICP Generator

Create:

`icp_generator.py`

Based on the complete company intelligence, generate a proposed Ideal Customer Profile.

The system must understand:

**Who should this company sell to?**

Generate:

1. Target industries.
2. Ideal company types.
3. Company size.
4. Geographic markets.
5. Target departments.
6. Decision-maker roles.
7. Customer pain points.
8. Buying triggers.
9. Business requirements.
10. Ideal customer characteristics.
11. Excluded customer segments.
12. Reasons why a prospect would need the company's product or service.

Also generate a section called:

### Suggested Prospect Characteristics

This section should explain the type of companies that would make good prospects.

Example:

"Companies operating FMCG distribution networks with 50–500 field representatives, multiple territories, and a requirement for sales-force visibility and route monitoring."

Also explain:

- Why this prospect type is relevant.
- Which company offering matches the prospect.
- Which business problem is being addressed.
- Which decision-makers should be targeted.
- What buying signals might indicate demand.

These are proposed ICP recommendations, not verified facts about actual customers.

The system must clearly differentiate:
- Source-supported company information.
- LLM-derived business interpretation.
- Suggested ICP characteristics.

Do not fabricate existing customer names, revenue, employee counts, or verified adoption information.

---

# PART 6 — FINAL STRUCTURED MODELS

## Stage 10: Intermediate Intelligence Model

Create a dedicated `CompanyIntelligence` model.

This should represent the output of the analysis stage, before final seller profile construction.

It should contain:

- Company identity.
- Industry.
- Business model.
- Company description.
- Products.
- Services.
- Features.
- Value proposition.
- Problems solved.
- Differentiators.
- Customer segments.
- Geographic presence.
- Company limitations.
- Proposed ICP.
- Suggested prospect characteristics.
- Evidence references.
- Conflicts.
- Missing information.
- Confidence information.

Use appropriate nested Pydantic models rather than placing every field in one large flat model.

## Stage 11: Final SellerProfile

Refactor `seller_profile.py` only where necessary.

The final SellerProfile should represent the information that the frontend needs to display and the downstream lead-research engine needs to consume.

Recommended structure:

SellerProfile
- seller_id
- company_name
- contact_name
- website_url
- industry
- sub_industry
- description
- business_model
- geography
- company_size
- products[]
- services[]
- features[]
- value_proposition
- problems_solved[]
- differentiators[]
- limitations[]
- customer_segments[]
- icp
- suggested_prospect_characteristics[]
- evidence_ids[]
- extraction_metadata
- status
- version

SellerICP
- target_industries[]
- company_types[]
- company_size
- geography[]
- departments[]
- decision_maker_roles[]
- customer_problems[]
- buying_signals[]
- exclusions[]
- preferred_characteristics[]

Use structured objects for products, services, and suggestions instead of putting everything into one string.

Use `list` fields for multiple values.

Use enums or Literal types for controlled status fields.

Use Pydantic validators for actual data integrity, not for attempting to perform LLM extraction.

The model must support incomplete information. Missing information should be represented explicitly instead of being filled with guessed values.

Maintain compatibility with the existing downstream research, scoring, and outreach functionality. If existing consumers expect string fields, update them through an explicit compatibility or migration layer rather than silently breaking them.

---

# PART 7 — VALIDATION AND PROFILE BUILDER

## Stage 12: Profile Builder

Create:

`profile_builder.py`

This component takes the final `CompanyIntelligence` output and maps it into the `SellerProfile` schema.

Responsibilities:

1. Map every analyzed field correctly.
2. Preserve evidence references.
3. Normalize strings, lists, and nested objects.
4. Remove duplicate values.
5. Preserve unknown fields as null or empty collections according to the schema contract.
6. Validate all evidence references.
7. Ensure required fields are present.
8. Generate a clear validation report.

Never silently move information between unrelated categories.

For example:
- A feature must not automatically become a product.
- A product must not automatically become a service.
- An industry must not automatically become a customer type.
- A suggested buying signal must not be represented as an observed buying signal.

## Stage 13: Validation and Repair

Create:

`profile_validator.py`

Validation should check:

- Pydantic schema validity.
- Correct field types.
- Required field availability.
- Valid evidence references.
- Empty or duplicate values.
- Contradictory claims.
- Unsupported claims.
- Invalid nested structures.
- Completeness.

If validation fails:

1. Identify the exact field.
2. Record the validation error.
3. Attempt a limited structured repair using the LLM if appropriate.
4. Validate again.
5. If still unsuccessful, mark the field as unresolved.

Never repeatedly regenerate the entire profile just because one field failed.

Do not force every field to be populated.

A partially complete but accurate profile is better than a complete fabricated profile.

---

# PART 8 — FRONTEND PROFILE REVIEW

## Stage 14: Profile Review UI

Refactor:

`ProfileReviewPage.tsx`

The frontend should receive a predictable, documented response structure.

The UI should display the extracted and analyzed information in clearly separated sections.

### Section 1: Company Overview
- Company name.
- Industry.
- Description.
- Business model.
- Geographic presence.

### Section 2: Products and Services
- Product name.
- Product description.
- Features.
- Target users.
- Services.
- Business outcomes.

### Section 3: Value Proposition
- Problems solved.
- Business value.
- Differentiators.
- Limitations.

### Section 4: Customer Segmentation
- Target industries.
- Company types.
- Company sizes.
- Geographic markets.
- Departments.

### Section 5: Ideal Customer Profile
- Decision-maker roles.
- Customer problems.
- Buying signals.
- Preferred characteristics.
- Exclusions.

### Section 6: Suggested Prospect Characteristics
Show the LLM-generated suggestions in a clearly distinguishable section.

For each suggestion, display:
- Suggested prospect type.
- Why it matches.
- Relevant product/service.
- Problem being solved.
- Target decision-maker.
- Supporting evidence or mark it as an inference.

### Section 7: Sources and Evidence
Allow the user to understand where the information came from.

Where practical, show:
- Source document or website page.
- Relevant excerpt.
- Confidence.
- Whether the information is directly supported or inferred.

### Section 8: Missing Information and Conflicts
Show fields that could not be extracted.

Show conflicting source information separately.

Do not hide missing fields or silently substitute unrelated information.

## User Actions

The user must be able to:

- Edit any profile field.
- Accept an individual suggestion.
- Reject an individual suggestion.
- Modify a suggested ICP.
- Approve the complete profile.
- Save the profile as a draft.

An individual suggestion approval must not automatically approve the entire seller profile.

Only final profile approval should move the seller into the lead section.

Preserve the existing approval and versioning system.

The approved profile must be an immutable snapshot for downstream research until the user approves a new version.

---

# PART 9 — PROCESSING STATUS AND API DESIGN

The extraction process can take longer than a normal HTTP request.

Replace the current short blocking extraction workflow with a proper processing-job architecture.

Suggested endpoints:

POST `/sellers/extract`
- Accept company information and optional documents.
- Create an extraction job.
- Return job ID.

GET `/sellers/extract/{job_id}`
- Return processing status.
- Return current stage.
- Return errors, if any.
- Return extraction result when complete.

GET `/sellers/{seller_id}/draft`
- Return the latest seller profile draft.

PATCH `/sellers/{seller_id}/draft`
- Save user edits.

POST `/sellers/{seller_id}/approve`
- Approve the profile.
- Create an immutable version.

Suggested processing stages:

1. Uploading documents.
2. Parsing documents.
3. Crawling website.
4. Normalizing sources.
5. Extracting facts.
6. Consolidating evidence.
7. Analyzing company intelligence.
8. Generating ICP.
9. Building profile.
10. Validating profile.
11. Ready for review.

The frontend should show actual backend progress, not a timer-based progress animation.

Use background tasks or a suitable job queue based on the existing infrastructure.

Add polling initially, or use SSE/WebSockets if the existing application already supports them appropriately.

Do not introduce unnecessary infrastructure solely for this feature.

---

# PART 10 — DATABASE AND PERSISTENCE

Inspect the existing database schema before making changes.

Reuse existing tables where appropriate and introduce new tables only when required.

Potential additions:

- `extraction_jobs`
- `source_documents`
- `normalized_sources`
- `company_intelligence`
- `profile_suggestions`

Preserve existing:

- `sellers`
- `seller_profile_versions`
- `evidence_items`
- `research_runs`
- `lead_reports`
- `outreach_drafts`
- `outreach_draft_versions`

Ensure source documents, normalized content, evidence, intelligence results, and profile versions can be associated with the correct seller.

Do not use company name as the only tenant or ownership identifier. Preserve existing behavior where necessary for compatibility, but design new records around stable seller IDs and workspace/user ownership when authentication is available.

---

# PART 11 — LLM AND TOOL INTEGRATION

Inspect the current LLM abstraction and all existing configured integrations.

Reuse existing providers and credentials.

The pipeline must not depend on one specific model provider.

Support the existing hosted and local inference configurations.

For LLM processing:

- Use structured outputs.
- Use Pydantic schemas.
- Separate extraction prompts from analysis prompts.
- Separate ICP generation from company analysis.
- Use chunking for large sources.
- Keep prompts versioned and testable.
- Handle model timeouts and malformed responses.
- Use bounded retries.
- Preserve evidence references.
- Never fabricate missing information.

Existing integrations (Tavily, Prospeo) should not be removed or repurposed without understanding their current responsibility. There is no Twilio integration.

The configured LLM is a local Qwen3 model behind an OpenAI-compatible MLX server. It does not reliably support `response_format` / JSON schema, so "structured output" means: prompt with the Pydantic JSON schema, strip `<think>` blocks, parse, validate with Pydantic, and allow one bounded repair call (`MlxClient.complete_model`).

Only use an integration in this pipeline if its function genuinely fits the task.

LangGraph should be used where orchestration, conditional execution, or retries provide real value. Do not introduce additional agents or graph complexity where straightforward Python functions are sufficient.

---

# PART 12 — TESTING

Add unit and integration tests.

### Document Tests
- PDF extraction.
- DOCX extraction.
- TXT extraction.
- Markdown normalization.
- Multiple documents.
- Empty documents.
- Unsupported formats.
- Corrupt documents.
- Scanned PDF/OCR handling where configured.

### Website Tests
- Homepage extraction.
- Internal link discovery.
- Product and service page extraction.
- Sitemap discovery.
- Duplicate pages.
- Invalid URLs.
- SSRF protection.
- Slow website and timeout behavior.

### Intelligence Tests
- Website-only extraction.
- Website + documents.
- Complementary sources.
- Conflicting sources.
- Missing information.
- Product/service classification.
- ICP generation.
- Evidence preservation.
- LLM malformed output.

### Pydantic Tests
- Valid profile.
- Partially complete profile.
- Invalid field types.
- Missing evidence references.
- Duplicate values.
- Nested object validation.

### API and Frontend Tests
- Extraction job creation.
- Job status polling.
- Correct response mapping.
- Empty and null values.
- Editing extracted fields.
- Accepting/rejecting suggestions.
- Saving draft.
- Approving profile.
- Preserving approved versions.

---

# PART 13 — IMPLEMENTATION RULES

Follow these rules throughout implementation:

1. First inspect the existing codebase.
2. Do not rewrite the complete application.
3. Do not unnecessarily replace the existing research graph.
4. Preserve existing lead research, scoring, reports, and outreach functionality.
5. Do not break the existing seller approval workflow.
6. Keep modules small and responsibilities clearly separated.
7. Avoid duplicate extraction logic.
8. Use Pydantic as the validation and data-contract layer.
9. Do not use regex as the primary company intelligence engine.
10. Do not pass raw unstructured content directly into the final profile builder.
11. Do not invent company information.
12. Preserve evidence and source attribution.
13. Make all processing stages observable and debuggable.
14. Add proper logging and error handling.
15. Keep the frontend and backend response contracts synchronized.
16. Do not silently substitute empty values with guessed values.
17. Maintain compatibility with existing database records.
18. Do not hardcode company names, product names, or industry-specific heuristics.
19. Do not add unnecessary paid infrastructure or services.
20. Do not mark the extraction as successful merely because a fallback Pydantic object was created.

---

# PART 14 — EXPECTED FINAL RESULT

The final user experience should work as follows:

### Step 1 — Seller onboarding

The seller enters:

- Name.
- Company name.
- Company website.
- Optional company documents.

### Step 2 — Automated company understanding

The system:

- Crawls the website.
- Parses optional documents.
- Converts document content into Markdown.
- Normalizes all source content.
- Extracts information independently.
- Consolidates information and evidence.
- Analyzes the complete company profile.
- Understands its products and services.
- Identifies its value proposition.
- Generates a proposed ideal customer profile.
- Generates company-specific prospect characteristics.
- Validates the final structured output.

### Step 3 — Profile review

The user sees a properly structured company profile.

The user can edit fields, accept or reject suggestions, and inspect evidence.

The system should not show random, incorrectly categorized, or fabricated information.

### Step 4 — Profile approval

The user approves the complete seller profile.

The system saves an immutable approved version.

### Step 5 — Lead section

The user proceeds to the existing lead-research workflow.

The downstream lead research and scoring system should use the approved seller profile and ICP to determine whether a prospective company is a suitable sales opportunity.

---

# FINAL INSTRUCTION TO CURSOR

Before writing code, return:

1. Your understanding of the existing architecture.
2. The exact reasons for the current incorrect or missing UI output.
3. The proposed updated architecture.
4. Files that need modification.
5. New files that need creation.
6. Database changes required.
7. API contract changes required.
8. An incremental implementation plan.

After presenting this plan, implement the architecture in logical phases.

After each phase:
- Run relevant tests.
- Verify frontend/backend contracts.
- Fix regressions.
- Document what was changed.

Do not stop after creating new Pydantic schemas or placeholder modules. The complete pipeline must be connected end-to-end and verified using actual extraction results.

The primary success criterion is:

**When a seller provides a company website, with or without documents, Excon must understand the company, consolidate all available information, generate an evidence-backed company profile and ICP, validate the output, and display it correctly in the profile review UI for human approval.**