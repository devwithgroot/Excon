from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.application.scoring import product_matches, score_research
from app.domain.collected_research import CollectedResearch, ParameterStatus
from app.domain.report import LeadReportBody, ProductMatch
from app.domain.seller_profile import SellerProfile, offerings_text


def _supported_signals(collected: CollectedResearch) -> list[str]:
    lines: list[str] = []
    for name, field in collected.signals:
        if field.status == ParameterStatus.supported and field.value:
            lines.append(f"{name.replace('_', ' ')} — {field.value}")
    return lines


def _template_report(
    *,
    report_id: str,
    run_id: str,
    seller: SellerProfile | None,
    collected: CollectedResearch,
    scores,
    matches: list[ProductMatch],
) -> LeadReportBody:
    lead = collected.company.name.value or "This company"
    industry = collected.company.industry.value
    description = collected.company.description.value
    size = collected.company.size.value
    hq = collected.company.headquarters.value
    seller_name = seller.company_name if seller else "Your company"
    offerings = offerings_text(seller)
    icp = ", ".join(seller.icp.target_industries) if seller else None
    problems = "; ".join(seller.problems_solved) if seller else None

    identity = lead
    if industry:
        identity += f" ({industry})"
    if size:
        identity += f", size {size}"
    if hq:
        identity += f", HQ {hq}"

    overview_parts = [
        f"{identity}.",
        f"You ({seller_name}) sell {offerings or 'an offering that is not yet specified'}.",
    ]
    if description:
        overview_parts.append(description[:280])
    overview_parts.append(
        f"Verdict: {scores.recommendation} ({scores.overall}/100). {scores.recommendation_reason}"
    )
    overview = " ".join(overview_parts)

    why_fit: list[str] = []
    if offerings and description:
        why_fit.append(
            f"{seller_name} sells {offerings}. {lead} describes itself as: {description[:220]}"
        )
    if icp and industry:
        why_fit.append(f"Your ICP industries include “{icp}”. Their industry is {industry}.")
    if problems and description:
        why_fit.append(f"You solve: {problems}.")
    for match in matches:
        why_fit.append(f"Offering “{match.offering}” matches lead evidence ({match.reason})")
    for line in _supported_signals(collected):
        why_fit.append(f"{lead} signal: {line}")
    if collected.news:
        why_fit.append("Recent news: " + "; ".join(item.title for item in collected.news[:3]))
    if not why_fit:
        why_fit.append(
            f"No clear overlap yet between what {seller_name} sells and what we found on {lead}."
        )

    why_not: list[str] = []
    if not offerings:
        why_not.append(
            "Your approved profile has no products or services, so fit cannot be judged usefully."
        )
    if offerings and not matches and not (icp and industry):
        why_not.append(
            f"No specific overlap found between “{offerings}” and {lead}’s industry/description."
        )
    if seller and seller.limitations:
        why_not.append(f"You said you are not a fit when: {'; '.join(seller.limitations)}")
    if seller and seller.icp.exclusions:
        why_not.append(f"Your ICP exclusions: {'; '.join(seller.icp.exclusions)}")
    for name, field in collected.company:
        if name in {"industry", "products", "size", "headquarters"} and (
            field.status != ParameterStatus.supported or not field.value
        ):
            why_not.append(f"We could not evidence {lead} {name} this run.")
    missing_motion = [
        label
        for key, _points, label in (
            ("signals.hiring", 0, "hiring"),
            ("signals.new_product", 0, "a new product"),
            ("signals.expansion", 0, "expansion"),
            ("signals.funding", 0, "funding"),
        )
        if collected.signals.__getattribute__(key.split(".", 1)[1]).status != ParameterStatus.supported
    ]
    if missing_motion:
        why_not.append(f"No evidenced {', '.join(missing_motion)} for {lead}.")
    if not collected.people:
        why_not.append("No decision-maker was found, so outreach has no named owner.")

    people = collected.people
    if people:
        people_summary = "; ".join(
            " · ".join(
                part
                for part in (
                    person.name,
                    person.title,
                    person.email,
                    "LinkedIn" if person.linkedin_url else None,
                )
                if part
            )
            for person in people[:5]
        )
    else:
        people_summary = f"No decision-makers found for {lead}."

    first_person = people[0] if people else None
    if scores.recommendation == "pursue":
        action = (
            f"Spend time on {lead}. "
            + (
                f"Start with {first_person.name} ({first_person.title}). "
                if first_person
                else "Find a named owner before a full sequence. "
            )
            + (
                f"Open with {matches[0].offering}."
                if matches
                else f"Open with how {offerings or 'your offering'} maps to what they published."
            )
        )
    elif scores.recommendation == "consider":
        action = (
            f"{lead} is only a maybe. Confirm the missing facts "
            f"({', '.join(scores.completeness.gaps[:4]) or 'fit overlap'}) before a full conversion cycle."
        )
    else:
        action = (
            f"Do not invest conversion energy in {lead} yet. "
            f"Fit {scores.fit.score}/100 and qualification {scores.qualification.score}/100 are too weak."
        )

    if matches:
        angle = f"Ask {first_person.name if first_person else lead} about {matches[0].offering}: {matches[0].reason}"
    elif offerings and description:
        angle = f"Ask how they handle {offerings} given they say: “{description[:160]}”"
    else:
        angle = f"Do not pitch a specific product until {lead}’s need is evidenced."

    return LeadReportBody(
        report_id=report_id,
        run_id=run_id,
        seller_id=None,
        seller_version=seller.version if seller else 0,
        scores=scores,
        overview=overview,
        why_fit=why_fit[:10],
        why_not=why_not[:10],
        product_matches=matches,
        recommended_action=action,
        conversation_angle=angle,
        people_summary=people_summary,
        gaps=list(scores.completeness.gaps),
    )


async def build_lead_report(
    collected: CollectedResearch,
    seller: SellerProfile | None,
    *,
    run_id: str,
    seller_id: str | None = None,
    mlx: Any | None = None,
) -> LeadReportBody:
    scores = score_research(collected, seller)
    matches = product_matches(collected, seller)
    report = _template_report(
        report_id=str(uuid4()),
        run_id=run_id,
        seller=seller,
        collected=collected,
        scores=scores,
        matches=matches,
    )
    return report.model_copy(update={"seller_id": seller_id})
