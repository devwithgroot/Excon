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
