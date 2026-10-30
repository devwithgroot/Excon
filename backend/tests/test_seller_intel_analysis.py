from app.application.seller_intel.company_analyzer import AnalysisOutput, analyze_company
from app.application.seller_intel.document_models import IntelSourceType, Source
from app.application.seller_intel.evidence_consolidator import consolidate, similar
from app.application.seller_intel.icp_generator import IcpOutput, generate_icp
from app.application.seller_intel.source_extractor import (
    SourceExtraction,
    excerpt_grounded,
    extract_sources,
    pack_sources,
)

WEBSITE = Source(
    source_id="src_web",
    source_type=IntelSourceType.website_page,
    source_name="Acme | Home",
    source_url="https://acme.test/",
    normalized_markdown=(
        "# Acme\n\nAcme builds FieldApp, a sales force automation app for FMCG distributors.\n\n"
        "## Services\n\nWe also run route planning consulting for regional distributors.\n\n"
        "We serve small and growing distributors across India."
    ),
)
BROCHURE = Source(
    source_id="doc_brochure",
    source_type=IntelSourceType.document,
    source_name="brochure.pdf",
    normalized_markdown=(
        "<!-- page 2 -->\n## Who we serve\n\nFieldApp helps enterprise FMCG brands manage field sales teams.\n\n"
        "FieldApp tracks visits, orders and collections in one timeline."
    ),
)


class FakeMlx:
    def __init__(self, replies: dict[type, list]) -> None:
        self.replies = {key: list(value) for key, value in replies.items()}
        self.calls: list[tuple[type, str]] = []

    async def complete_model(self, system, user, model_cls, **kwargs):
        self.calls.append((model_cls, user))
        queue = self.replies.get(model_cls) or [None]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        return model_cls.model_validate(reply) if isinstance(reply, dict) else reply


EXTRACTION = {
    "claims": [
        {"category": "product", "name": "FieldApp", "value": "Sales force automation app for FMCG distributors",
         "excerpt": "Acme builds FieldApp, a sales force automation app for FMCG distributors.", "source": "S1"},
        {"category": "service", "name": "Route planning consulting", "value": "Route planning consulting for distributors",
         "excerpt": "We also run route planning consulting for regional distributors.", "source": "S1"},
        {"category": "customer_segment", "value": "small and growing distributors",
         "excerpt": "We serve small and growing distributors across India.", "source": "S1"},
        {"category": "geography", "value": "India", "excerpt": "We serve small and growing distributors across India.",
         "source": "S2"},
        {"category": "customer_segment", "value": "enterprise FMCG brands",
         "excerpt": "FieldApp helps enterprise FMCG brands manage field sales teams.", "source": "S2"},
        {"category": "feature", "name": "FieldApp", "value": "Tracks visits, orders and collections",
         "excerpt": "FieldApp tracks visits, orders and collections in one timeline.", "source": "S2"},
        {"category": "product", "name": "FieldApp", "value": "Field sales management for enterprise FMCG brands",
         "excerpt": "FieldApp helps enterprise FMCG brands manage field sales teams.", "source": "S2"},
        {"category": "company_size", "value": "5000 employees", "excerpt": "We have 5000 employees worldwide.",
         "source": "S1"},
    ]
}


async def _extract():
    mlx = FakeMlx({SourceExtraction: [EXTRACTION]})
    result = await extract_sources([WEBSITE, BROCHURE], company_name="Acme", mlx=mlx, chunk_chars=6000, max_calls=5)
    return result, mlx


async def test_extraction_packs_sources_and_grounds_every_claim() -> None:
    result, mlx = await _extract()
    assert result.calls == 1, "both small sources share one call"
    assert "=== S1 | brochure.pdf ===" in mlx.calls[0][1], "documents are prioritized"
    assert result.dropped_ungrounded == 1, "the invented headcount has no matching excerpt"
    by_value = {claim.claim.value: claim for claim in result.claims}
    india = by_value["India"]
    assert india.source_id == "src_web", "a mislabelled source is corrected to where the excerpt really is"
    feature = by_value["Tracks visits, orders and collections"]
    assert feature.evidence.section_reference == "page 2, section: Who we serve"
    assert feature.evidence.source_type.value == "document"
    assert all(claim.evidence.field_key.startswith("seller.") for claim in result.claims)


async def test_extraction_budget_and_failures_are_reported() -> None:
    mlx = FakeMlx({SourceExtraction: [None]})
    result = await extract_sources([WEBSITE, BROCHURE], company_name="Acme", mlx=mlx, chunk_chars=200, max_calls=2)
    assert result.calls == 2 and result.failed_calls == 2 and not result.claims
    assert "skipped_budget" in result.source_status.values()
    assert len(pack_sources([WEBSITE, BROCHURE], 200)) > 2


async def test_consolidation_merges_across_sources_and_flags_conflicts() -> None:
    result, _ = await _extract()
    consolidation = consolidate(result.claims)
    products = consolidation.by_category("product")
    assert len(products) == 1 and products[0].name == "FieldApp"
    assert set(products[0].source_ids) == {"src_web", "doc_brochure"}
    assert products[0].confidence > 0.7, "two agreeing sources raise confidence"
    conflict = next(c for c in consolidation.conflicts if c.field == "customer_segment")
    assert {v.value for v in conflict.values} == {"small and growing distributors", "enterprise FMCG brands"}
    assert "description" in consolidation.missing and "industry" in consolidation.missing
    assert similar("FieldApp", "FieldApp app") and not similar("software", "custom software for logistics teams")


async def test_analyzer_requires_citations_and_keeps_uncovered_offerings() -> None:
    result, _ = await _extract()
    consolidation = consolidate(result.claims)
    ids = {fact.category + ":" + (fact.name or fact.value): fact.fact_id for fact in consolidation.facts}
    product_id = ids["product:FieldApp"]
    analysis = {
        "industry": {"value": "Sales force automation software", "facts": [product_id]},
        "description": {"value": "Acme sells a field sales app and route consulting.", "facts": []},
        "company_size": {"value": "200 employees", "facts": []},
        "products": [
            {"name": "FieldApp", "features": ["Visit tracking"], "facts": [product_id]},
            {"name": "QuantumCRM", "facts": [product_id]},
        ],
        "services": [],
    }
    mlx = FakeMlx({AnalysisOutput: [analysis]})
    intelligence, warnings = await analyze_company(consolidation, company_name="Acme", website_url=None, mlx=mlx)
    assert not warnings
    assert [p.name for p in intelligence.products] == ["FieldApp"], "an invented product name is dropped"
    assert intelligence.industry.support == "explicit" and intelligence.industry.evidence_ids
    assert intelligence.description.support == "inferred", "no citations means interpretation"
    assert intelligence.company_size is None, "sizes need a cited fact"
    assert [s.name for s in intelligence.services] == ["Route planning consulting"], "skipped service facts are kept"
    assert intelligence.conflicts and intelligence.evidence
    assert {"India"} <= {g.value for g in intelligence.geography}


async def test_analyzer_falls_back_to_facts_when_llm_fails() -> None:
    result, _ = await _extract()
    intelligence, warnings = await analyze_company(
        consolidate(result.claims), company_name="Acme", website_url=None, mlx=FakeMlx({AnalysisOutput: [None]})
    )
    assert warnings and warnings[0].startswith("analysis_llm_failed")
    assert intelligence.products[0].name == "FieldApp"
    assert intelligence.features and intelligence.customer_segments


async def test_icp_suggestions_are_inferred_and_traced() -> None:
    result, _ = await _extract()
    intelligence, _ = await analyze_company(
        consolidate(result.claims), company_name="Acme", website_url=None, mlx=FakeMlx({AnalysisOutput: [None]})
    )
    icp_reply = {
        "target_industries": ["FMCG distribution"],
        "decision_maker_roles": ["Head of Sales"],
        "exclusions": [],
        "suggestions": [
            {"prospect_type": "Regional FMCG distributors with 20-200 field reps", "matching_offering": "FieldApp",
             "decision_makers": ["Sales Director"], "basis": ["P1", "nonsense"]},
        ],
    }
    icp, suggestions, warnings = await generate_icp(intelligence, mlx=FakeMlx({IcpOutput: [icp_reply]}))
    assert not warnings
    assert "FMCG distribution" in icp.target_industries
    assert icp.company_types, "fact-derived segments are kept alongside LLM proposals"
    assert suggestions[0].support == "inferred" and suggestions[0].status == "pending"
    assert suggestions[0].evidence_ids == intelligence.products[0].evidence_ids


def test_excerpt_grounding_tolerates_markdown_but_not_invention() -> None:
    text = "## Services\n\nWe **also** run route planning consulting."
    assert excerpt_grounded("We also run route planning consulting", text)
    assert not excerpt_grounded("We run blockchain audits for banks", text)


async def test_analysis_accepts_bare_strings_from_small_models_as_inferred() -> None:
    result, _ = await _extract()
    consolidation = consolidate(result.claims)
    product_id = next(fact.fact_id for fact in consolidation.facts if fact.category == "product")
    loose = AnalysisOutput.model_validate(
        {
            "industry": "Sales force automation software",
            "geography": "India",
            "problems_solved": ["workflow mapping and bottleneck analysis"],
            "products": ["FieldApp", {"name": "Route planner", "features": "Visit tracking", "facts": f"{product_id}"}],
        }
    )
    assert loose.products[0].name == "FieldApp" and loose.products[1].facts == [product_id]
    assert loose.products[1].features == ["Visit tracking"]
    mlx = FakeMlx({AnalysisOutput: [loose]})
    intelligence, warnings = await analyze_company(consolidation, company_name="Acme", website_url=None, mlx=mlx)
    assert not warnings, "a loosely shaped answer is still used"
    assert intelligence.industry.support == "inferred", "uncited strings are never explicit"
    assert all(item.value != "India" or item.evidence_ids for item in intelligence.geography), "strict fields need citations"
    assert intelligence.problems_solved[0].support == "inferred"


async def test_analysis_drops_services_that_are_product_features_and_picks_one_wording() -> None:
    result, _ = await _extract()
    consolidation = consolidate(result.claims)
    ids = {fact.category + ":" + (fact.name or fact.value): fact.fact_id for fact in consolidation.facts}
    product_id, service_id = ids["product:FieldApp"], ids["service:Route planning consulting"]
    analysis = AnalysisOutput.model_validate(
        {
            "value_proposition": {"value": "Field sales app for distributors / Route consulting", "facts": [product_id]},
            "products": [{"name": "FieldApp", "features": ["Route planning consulting"], "facts": [product_id]}],
            "services": [{"name": "Route planning consulting", "facts": [service_id]}],
        }
    )
    intelligence, _ = await analyze_company(
        consolidation, company_name="Acme", website_url=None, mlx=FakeMlx({AnalysisOutput: [analysis]})
    )
    assert intelligence.value_proposition.value == "Field sales app for distributors"
    assert not intelligence.services, "a capability already listed as a product feature is not also a service"


async def test_icp_suggestion_offering_ids_resolve_to_names() -> None:
    result, _ = await _extract()
    intelligence, _ = await analyze_company(consolidate(result.claims), company_name="Acme", website_url=None, mlx=None)
    icp_reply = {"suggestions": [{"prospect_type": "Regional FMCG distributors", "matching_offering": "P1", "basis": ["P1"]}]}
    _, suggestions, _ = await generate_icp(intelligence, mlx=FakeMlx({IcpOutput: [icp_reply]}))
    assert suggestions[0].matching_offering == intelligence.products[0].name


async def test_analysis_drops_services_that_are_product_features_and_picks_one_wording() -> None:
    result, _ = await _extract()
    consolidation = consolidate(result.claims)
    ids = {fact.category + ":" + (fact.name or fact.value): fact.fact_id for fact in consolidation.facts}
    product_id, service_id = ids["product:FieldApp"], ids["service:Route planning consulting"]
    analysis = AnalysisOutput.model_validate(
        {
            "value_proposition": {"value": "Field sales app for distributors / Route consulting", "facts": [product_id]},
            "products": [{"name": "FieldApp", "features": ["Route planning consulting"], "facts": [product_id]}],
            "services": [{"name": "Route planning consulting", "facts": [service_id]}],
        }
    )
    intelligence, _ = await analyze_company(
        consolidation, company_name="Acme", website_url=None, mlx=FakeMlx({AnalysisOutput: [analysis]})
    )
    assert intelligence.value_proposition.value == "Field sales app for distributors"
    assert not intelligence.services, "a capability already listed as a product feature is not also a service"


async def test_icp_suggestion_offering_ids_resolve_to_names() -> None:
    result, _ = await _extract()
    intelligence, _ = await analyze_company(consolidate(result.claims), company_name="Acme", website_url=None, mlx=None)
    icp_reply = {"suggestions": [{"prospect_type": "Regional FMCG distributors", "matching_offering": "P1", "basis": ["P1"]}]}
    _, suggestions, _ = await generate_icp(intelligence, mlx=FakeMlx({IcpOutput: [icp_reply]}))
    assert suggestions[0].matching_offering == intelligence.products[0].name
