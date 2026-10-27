from app.application.gap_judge import deterministic_decision, judge_gaps
from app.domain.collected_research import (
    CollectedResearch,
    CompanyBlock,
    FieldValue,
    NewsItem,
    ParameterStatus,
    PersonRecord,
    SignalsBlock,
)
from app.domain.gap import GapVerdict


def _supported(value: str) -> FieldValue:
    return FieldValue(value=value, status=ParameterStatus.supported, evidence_ids=["e1"])


def test_funding_retries_when_hiring_and_new_product_supported() -> None:
    collected = CollectedResearch(
        signals=SignalsBlock(
            hiring=_supported("Acme is hiring"),
            new_product=_supported("Acme launched a warehouse OS"),
        )
    )
    decision = deterministic_decision(collected, "signals.funding")
    assert decision.verdict == GapVerdict.retry
    assert decision.tool_name == "signals"
    assert decision.focus == "funding"
    assert "signals.hiring" in decision.related_supported
    assert "signals.new_product" in decision.related_supported


def test_funding_left_when_only_hiring_supported() -> None:
    collected = CollectedResearch(
        signals=SignalsBlock(hiring=_supported("Acme is hiring"))
    )
    decision = deterministic_decision(collected, "signals.funding")
    assert decision.verdict == GapVerdict.leave
    assert "no supporting motion" in decision.reason.lower()
    assert decision.left_missing is True


def test_already_retried_field_is_left() -> None:
    collected = CollectedResearch()
    decision = deterministic_decision(
        collected,
        "signals.funding",
        targeted_attempts={"signals.funding": 1},
    )
    assert decision.verdict == GapVerdict.leave
    assert decision.retried is True
    assert decision.left_missing is True


def test_company_field_retries_when_website_known() -> None:
    collected = CollectedResearch(
        company=CompanyBlock(name=_supported("Acme")),
    )
    decision = deterministic_decision(
        collected,
        "company.size",
        website_url="https://acme.example",
    )
    assert decision.verdict == GapVerdict.retry
    assert decision.tool_name == "website_docs"
    assert decision.focus == "size"


async def test_classifier_cannot_override_deterministic_leave() -> None:
    collected = CollectedResearch(
        signals=SignalsBlock(hiring=_supported("Acme is hiring")),
        people=[PersonRecord(name="Ada", title="CTO", evidence_id="p1")],
        news=[NewsItem(title="Update", url="https://news.example/a", evidence_id="n1")],
        company=CompanyBlock(name=_supported("Acme")),
    )

    async def always_retry(field, supported, excerpts):
        return {"verdict": "retry", "field": field, "reason": "model wants another search"}

    decisions = await judge_gaps(collected, classify=always_retry)
    funding = next(item for item in decisions if item.field == "signals.funding")
    assert funding.verdict == GapVerdict.leave
    assert funding.left_missing is True


async def test_classifier_may_veto_a_deterministic_retry() -> None:
    collected = CollectedResearch(
        signals=SignalsBlock(
            hiring=_supported("Acme is hiring"),
            new_product=_supported("New product"),
        ),
        people=[PersonRecord(name="Ada", title="CTO", evidence_id="p1")],
        news=[NewsItem(title="Update", url="https://news.example/a", evidence_id="n1")],
    )

    async def always_leave(field, supported, excerpts):
        return {"verdict": "leave", "field": field, "reason": "not plausible enough"}

    decisions = await judge_gaps(collected, classify=always_leave)
    funding = next(item for item in decisions if item.field == "signals.funding")
    assert funding.verdict == GapVerdict.leave
    assert "not plausible" in funding.reason


async def test_only_one_retry_is_selected() -> None:
    collected = CollectedResearch(
        signals=SignalsBlock(
            hiring=_supported("hiring"),
            expansion=_supported("new office"),
        )
    )
    decisions = await judge_gaps(
        collected,
        company_name="Acme",
        website_url="https://acme.example",
    )
    retries = [item for item in decisions if item.verdict == GapVerdict.retry]
    assert len(retries) == 1
    assert retries[0].field == "signals.funding"
