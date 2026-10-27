from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.domain.collected_research import CollectedResearch, FieldValue, ParameterStatus
from app.domain.gap import GapDecision, GapVerdict

ClassifyFn = Callable[[str, list[str], list[str]], Awaitable[dict[str, Any] | None]]

FIELDS_OF_INTEREST = (
    "signals.funding",
    "company.size",
    "company.headquarters",
    "company.products",
    "company.founded",
    "people",
    "news",
)

FIELD_TOOL = {
    "signals.funding": ("signals", "funding"),
    "company.size": ("website_docs", "size"),
    "company.headquarters": ("website_docs", "headquarters"),
    "company.products": ("website_docs", "products"),
    "company.founded": ("website_docs", "founded"),
    "people": ("people", "linkedin"),
    "news": ("news", "news"),
}

CLASSIFY_SYSTEM = (
    "You are a gap classifier, not a researcher. "
    "Decide only whether a second targeted search is plausible. "
    'Return JSON: {"verdict": "retry"|"leave", "field": "...", "reason": "..."}. '
    "Never invent a value, funding amount, email, phone, or date."
)


def field_value(collected: CollectedResearch, key: str) -> FieldValue | None:
    if key.startswith("company."):
        return getattr(collected.company, key.split(".", 1)[1])
    if key.startswith("signals."):
        return getattr(collected.signals, key.split(".", 1)[1])
    return None


def is_supported(collected: CollectedResearch, key: str) -> bool:
    if key == "news":
        return bool(collected.news)
    if key == "people":
        return bool(collected.people)
    field = field_value(collected, key)
    return bool(field and field.status == ParameterStatus.supported and field.value)


def supported_keys(collected: CollectedResearch) -> list[str]:
    keys: list[str] = []
    for name, field in collected.company:
        if field.status == ParameterStatus.supported and field.value:
            keys.append(f"company.{name}")
    for name, field in collected.signals:
        if field.status == ParameterStatus.supported and field.value:
            keys.append(f"signals.{name}")
    if collected.news:
        keys.append("news")
    if collected.people:
        keys.append("people")
    return keys


def short_excerpts(collected: CollectedResearch, limit: int = 8) -> list[str]:
    excerpts: list[str] = []
    for item in collected.evidence:
        if item.supporting_excerpt:
            excerpts.append(f"{item.field_key}: {item.supporting_excerpt[:180]}")
        if len(excerpts) >= limit:
            break
    return excerpts


def _has_site(collected: CollectedResearch, website_url: str | None) -> bool:
    return bool(website_url) or is_supported(collected, "company.domain")


def deterministic_decision(
    collected: CollectedResearch,
    field: str,
    *,
    website_url: str | None = None,
    targeted_attempts: dict[str, int] | None = None,
) -> GapDecision:
    attempts = targeted_attempts or {}
    tool_name, focus = FIELD_TOOL.get(field, (None, None))
    related: list[str] = []

    if attempts.get(field, 0) >= 1:
        return GapDecision(
            field=field,
            verdict=GapVerdict.leave,
            reason="Already retried once; a second miss stays missing.",
            related_supported=related,
            retried=True,
            left_missing=True,
            tool_name=tool_name,
            focus=focus,
        )

    if field == "signals.funding":
        hiring = is_supported(collected, "signals.hiring")
        motion = any(
            is_supported(collected, key)
            for key in ("signals.new_product", "signals.expansion", "signals.tech_shift")
        )
        if hiring:
            related.append("signals.hiring")
        related.extend(
            key
            for key in ("signals.new_product", "signals.expansion", "signals.tech_shift")
            if is_supported(collected, key)
        )
        if hiring and motion:
            return GapDecision(
                field=field,
                verdict=GapVerdict.retry,
                reason="Hiring plus a product, expansion, or tech-shift signal makes a funding search plausible.",
                related_supported=related,
                tool_name=tool_name,
                focus=focus,
            )
        return GapDecision(
            field=field,
            verdict=GapVerdict.leave,
            reason="No supporting motion; an empty funding search is not 'no funding'.",
            related_supported=related,
            left_missing=True,
            tool_name=tool_name,
            focus=focus,
        )

    if field.startswith("company."):
        if _has_site(collected, website_url):
            return GapDecision(
                field=field,
                verdict=GapVerdict.retry,
                reason="A website or domain is known; retry website_docs once with a focused about/locations crawl.",
                related_supported=[
                    key for key in ("company.domain", "company.name") if is_supported(collected, key)
                ],
                tool_name=tool_name,
                focus=focus,
            )
        return GapDecision(
            field=field,
            verdict=GapVerdict.leave,
            reason="No website or domain to crawl for this company field.",
            left_missing=True,
            tool_name=tool_name,
            focus=focus,
        )

    if field == "people":
        if is_supported(collected, "company.name") or is_supported(collected, "company.domain"):
            return GapDecision(
                field=field,
                verdict=GapVerdict.retry,
                reason="Company identity is supported; retry people once with a LinkedIn-only query.",
                related_supported=[
                    key for key in ("company.name", "company.domain") if is_supported(collected, key)
                ],
                tool_name=tool_name,
                focus=focus,
            )
        return GapDecision(
            field=field,
            verdict=GapVerdict.leave,
            reason="Company name/domain is not supported, so a people retry is not justified.",
            left_missing=True,
            tool_name=tool_name,
            focus=focus,
        )

    if field == "news":
        if not collected.news and is_supported(collected, "company.name"):
            return GapDecision(
                field=field,
                verdict=GapVerdict.retry,
                reason="First news list was empty and the company name is supported; retry news once.",
                related_supported=["company.name"],
                tool_name=tool_name,
                focus=focus,
            )
        return GapDecision(
            field=field,
            verdict=GapVerdict.leave,
            reason="News is not retried unless the first list was empty.",
            left_missing=True,
            tool_name=tool_name,
            focus=focus,
        )

    return GapDecision(
        field=field,
        verdict=GapVerdict.leave,
        reason="Field is not in the retry list.",
        left_missing=True,
        tool_name=tool_name,
        focus=focus,
    )


async def classify_with_mlx(
    field: str,
    supported: list[str],
    excerpts: list[str],
    mlx: Any | None = None,
) -> dict[str, Any] | None:
    if mlx is None:
        return None
    user = (
        f"Missing field: {field}\n"
        f"Supported keys: {', '.join(supported) or '(none)'}\n"
        f"Excerpts:\n" + "\n".join(excerpts[:8])
    )
    try:
        payload = await mlx.complete_json(CLASSIFY_SYSTEM, user)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    verdict = str(payload.get("verdict") or "").lower()
    if verdict not in {GapVerdict.retry.value, GapVerdict.leave.value}:
        return None
    return {
        "verdict": verdict,
        "field": payload.get("field") or field,
        "reason": str(payload.get("reason") or "").strip(),
    }


async def judge_gaps(
    collected: CollectedResearch,
    *,
    company_name: str | None = None,
    website_url: str | None = None,
    targeted_attempts: dict[str, int] | None = None,
    classify: ClassifyFn | None = None,
    mlx: Any | None = None,
) -> list[GapDecision]:
    """Pick at most one retry. Deterministic rules win; the LLM may only veto."""

    missing = set(collected.missing_parameters())
    attempts = targeted_attempts or {}
    decisions: list[GapDecision] = []
    retry_chosen = False

    async def maybe_classify(decision: GapDecision) -> GapDecision:
        if decision.verdict != GapVerdict.retry:
            return decision
        payload: dict[str, Any] | None = None
        if classify is not None:
            payload = await classify(decision.field, supported_keys(collected), short_excerpts(collected))
        elif mlx is not None:
            payload = await classify_with_mlx(
                decision.field,
                supported_keys(collected),
                short_excerpts(collected),
                mlx,
            )
        if payload and payload.get("verdict") == GapVerdict.leave.value:
            return decision.model_copy(
                update={
                    "verdict": GapVerdict.leave,
                    "reason": payload.get("reason")
                    or "Classifier declined the retry; fail closed.",
                    "left_missing": True,
                }
            )
        return decision

    for field in FIELDS_OF_INTEREST:
        if field not in missing:
            continue
        decision = deterministic_decision(
            collected,
            field,
            website_url=website_url,
            targeted_attempts=attempts,
        )
        if field == "people" and decision.verdict == GapVerdict.leave and company_name:
            tool_name, focus = FIELD_TOOL[field]
            decision = GapDecision(
                field=field,
                verdict=GapVerdict.retry,
                reason="A company name was provided; retry people once with a LinkedIn-only query.",
                related_supported=["input.company_name"],
                tool_name=tool_name,
                focus=focus,
            )
        if field == "news" and decision.verdict == GapVerdict.leave and company_name and not collected.news:
            tool_name, focus = FIELD_TOOL[field]
            decision = GapDecision(
                field=field,
                verdict=GapVerdict.retry,
                reason="First news list was empty and a company name was provided; retry news once.",
                related_supported=["input.company_name"],
                tool_name=tool_name,
                focus=focus,
            )
        if decision.verdict == GapVerdict.retry:
            decision = await maybe_classify(decision)
        if decision.verdict == GapVerdict.retry:
            if retry_chosen:
                decisions.append(
                    decision.model_copy(
                        update={
                            "verdict": GapVerdict.leave,
                            "reason": "Another field was already selected for the single targeted retry.",
                            "left_missing": True,
                        }
                    )
                )
                continue
            retry_chosen = True
        decisions.append(decision)
    return decisions


def retry_decision(decisions: list[GapDecision]) -> GapDecision | None:
    for decision in decisions:
        if decision.verdict == GapVerdict.retry:
            return decision
    return None
