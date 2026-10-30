from app.application.scoring import score_research
from app.domain.collected_research import (
    CollectedResearch,
    CompanyBlock,
    FieldValue,
    NewsItem,
    ParameterStatus,
    PersonRecord,
    SignalsBlock,
)
from app.domain.seller_profile import SellerICP, SellerProfile


def _supported(value: str) -> FieldValue:
    return FieldValue(value=value, status=ParameterStatus.supported, evidence_ids=["e1"])


def test_strong_fit_and_motion_is_pursue() -> None:
    seller = SellerProfile(
        company_name="Excon Seller Co",
        products="payments billing invoicing",
        services="payment processing",
        problems_solved="online checkout",
        icp=SellerICP(target_industries="fintech payments", buying_signals="hiring expansion"),
        status="approved",
        version=1,
    )
    collected = CollectedResearch(
        company=CompanyBlock(
            name=_supported("Stripe"),
            domain=_supported("stripe.com"),
            description=_supported("Stripe processes online payments and billing for businesses."),
            industry=_supported("fintech payments"),
            products=_supported("payments billing"),
            size=_supported("8000"),
        ),
        signals=SignalsBlock(
            hiring=_supported("Stripe is hiring engineers"),
            new_product=_supported("Stripe launched billing"),
            expansion=_supported("Stripe opened a London office"),
            funding=_supported("Stripe funding round"),
        ),
        news=[NewsItem(title="Stripe payments news", url="https://news.example/s", evidence_id="n1")],
        people=[PersonRecord(name="Patrick Collison", title="CEO", evidence_id="p1")],
    )
    scores = score_research(collected, seller)
    assert scores.recommendation == "pursue"
    assert scores.fit.score >= 50
    assert scores.qualification.score >= 50
    assert any("payments" in item.lower() for item in scores.fit.matched)


def test_no_seller_offerings_stays_low_fit() -> None:
    collected = CollectedResearch(
        company=CompanyBlock(name=_supported("Acme")),
    )
    scores = score_research(collected, None)
    assert scores.fit.score <= 30
    assert scores.recommendation == "deprioritize"


def test_offering_match_uses_source_excerpts_and_accepted_suggestions() -> None:
    from datetime import datetime, timezone

    from app.application.scoring import product_matches
    from app.domain.company_intelligence import ProspectSuggestion
    from app.domain.evidence import EvidenceItem, SourceType

    evidence = EvidenceItem(
        evidence_id="ev-field",
        field_key="seller.product",
        extracted_value="FieldAXIS",
        source_type=SourceType.website,
        retrieved_at=datetime.now(timezone.utc),
        supporting_excerpt="FieldAXIS is custom field software for the plywood and laminates trade.",
    )
    suggestion = ProspectSuggestion(
        prospect_type="Interior materials manufacturers with dealer networks",
        matching_offering="FieldAXIS",
        status="accepted",
    )
    pending = ProspectSuggestion(prospect_type="Plywood laminates veneers interior", matching_offering="TezCafe")
    seller = SellerProfile(
        company_name="Tezbytes",
        products=[
            {"name": "TezCafe", "features": ["QR-based ordering for restaurants"]},
            {"name": "FieldAXIS", "evidence_ids": ["ev-field"]},
        ],
        evidence=[evidence],
        suggested_prospect_characteristics=[pending, suggestion],
    )
    collected = CollectedResearch(
        company=CompanyBlock(
            name=_supported("Greenply"),
            description=_supported("Interior infrastructure brand making plywood, laminates and veneers for dealer networks"),
        )
    )
    matches = product_matches(collected, seller)
    assert [match.offering for match in matches] == ["FieldAXIS"], "pending suggestions never count"
