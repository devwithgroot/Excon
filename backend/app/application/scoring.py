from __future__ import annotations

import re

from app.domain.collected_research import CollectedResearch, FieldValue, ParameterStatus
from app.domain.report import LeadScores, ProductMatch, ScoreBreakdown
from app.domain.seller_profile import SellerProfile, accepted_suggestions, offering_names, profile_text

STOP = {
    "that",
    "this",
    "with",
    "from",
    "your",
    "their",
    "about",
    "have",
    "will",
    "they",
    "them",
    "into",
    "company",
    "business",
    "platform",
    "https",
    "www",
    "com",
}

REQUIRED = (
    "company.name",
    "company.domain",
    "company.description",
    "company.industry",
    "company.products",
    "company.size",
    "signals.hiring",
    "signals.funding",
    "signals.new_product",
    "signals.expansion",
    "news",
    "people",
)

DECISION_TITLES = (
    "ceo",
    "founder",
    "owner",
    "president",
    "director",
    "managing",
    "vp",
    "chief",
    "head",
    "partner",
)

QUALIFICATION = (
    ("signals.hiring", 22, "Active hiring"),
    ("signals.new_product", 20, "New product or launch"),
    ("signals.expansion", 18, "Expansion signal"),
    ("signals.funding", 16, "Funding signal"),
    ("signals.tech_shift", 12, "Technology shift"),
    ("signals.acquisition", 12, "Acquisition activity"),
)


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]{4,}", text.lower())
        if token not in STOP
    }


def _field(collected: CollectedResearch, key: str) -> FieldValue | None:
    if key.startswith("company."):
        return getattr(collected.company, key.split(".", 1)[1])
    if key.startswith("signals."):
        return getattr(collected.signals, key.split(".", 1)[1])
    return None


def _supported(collected: CollectedResearch, key: str) -> bool:
    if key == "news":
        return bool(collected.news)
    if key == "people":
        return bool(collected.people)
    field = _field(collected, key)
    return bool(field and field.status == ParameterStatus.supported and field.value)


def _value(collected: CollectedResearch, key: str) -> str:
    if key == "news":
        return " ".join(item.title for item in collected.news)
    if key == "people":
        return " ".join(f"{person.name} {person.title or ''}" for person in collected.people)
    field = _field(collected, key)
    return field.value if field and field.value else ""


def _seller_blob(profile: SellerProfile | None) -> str:
    return profile_text(profile)


def _offering_blobs(profile: SellerProfile | None) -> list[tuple[str, str]]:
    """(offering name, text to match): a bare product name rarely overlaps lead evidence."""
    if profile is None:
        return []
    excerpts = {item.evidence_id: item.supporting_excerpt for item in profile.evidence}
    accepted = accepted_suggestions(profile)

    def context(name: str, evidence_ids: list[str]) -> list[str]:
        parts = [excerpts.get(evidence_id, "") for evidence_id in evidence_ids]
        for suggestion in accepted:
            if (suggestion.matching_offering or "").strip().lower() == name.strip().lower():
                parts += [suggestion.prospect_type, suggestion.why_relevant, suggestion.problem_addressed or ""]
        return parts

    blobs: list[tuple[str, str]] = []
    for product in profile.products:
        text = " ".join(
            [
                product.name,
                product.description or "",
                *product.features,
                *product.target_users,
                *product.problems_solved,
                *context(product.name, product.evidence_ids),
            ]
        )
        blobs.append((product.name, text))
    for service in profile.services:
        text = " ".join(
            [
                service.name,
                service.description or "",
                service.target_customer or "",
                service.business_outcome or "",
                *service.use_cases,
                *context(service.name, service.evidence_ids),
            ]
        )
        blobs.append((service.name, text))
    return blobs


def _lead_blob(collected: CollectedResearch) -> str:
    return " ".join(
        part
        for part in (
            collected.company.description.value,
            collected.company.industry.value,
            collected.company.products.value,
            _value(collected, "news"),
            _value(collected, "signals.hiring"),
            _value(collected, "signals.new_product"),
            _value(collected, "signals.expansion"),
            _value(collected, "signals.tech_shift"),
        )
        if part
    )


def seller_offerings(profile: SellerProfile | None) -> list[str]:
    return offering_names(profile)


def score_research(collected: CollectedResearch, seller: SellerProfile | None) -> LeadScores:
    supported = [key for key in REQUIRED if _supported(collected, key)]
    missing = [key for key in REQUIRED if key not in supported]
    completeness = round(100 * len(supported) / len(REQUIRED))
    completeness_reasons = [
        f"{len(supported)} of {len(REQUIRED)} core fields have evidence."
    ]
    if missing:
        completeness_reasons.append("Still open: " + ", ".join(missing[:6]))

    evidence_items = [item for item in collected.evidence if item.extracted_value]
    if evidence_items:
        weights = []
        for item in evidence_items:
            fresh = {"fresh": 1.0, "unknown": 0.6, "stale": 0.0}.get(
                item.freshness.value if hasattr(item.freshness, "value") else str(item.freshness),
                0.5,
            )
            weights.append(fresh * max(item.confidence, 0.2))
        quality = round(100 * (sum(weights) / len(weights)))
        quality_reasons = [f"{len(evidence_items)} evidence items stored for this run."]
    else:
        quality = 0
        quality_reasons = ["No evidence items were stored."]

    qual = 0
    qual_matched: list[str] = []
    qual_gaps: list[str] = []
    for key, points, label in QUALIFICATION:
        if _supported(collected, key):
            qual += points
            qual_matched.append(label)
        else:
            qual_gaps.append(label)
    if collected.news:
        qual = min(100, qual + 8)
        qual_matched.append("Recent news exists")
    else:
        qual_gaps.append("No usable news")
    qualification = min(100, qual)
    qual_reasons = [f"Buying-motion score {qualification}/100."]
    if qual_matched:
        qual_reasons.append("Supported: " + ", ".join(qual_matched))

    seller_tokens = _tokens(_seller_blob(seller))
    lead_tokens = _tokens(_lead_blob(collected))
    overlap = sorted(seller_tokens & lead_tokens)
    offerings = seller_offerings(seller)
    product_hits = [name for name, text in _offering_blobs(seller) if _tokens(text) & lead_tokens]
    if not seller or not seller_tokens:
        fit = 20
        fit_reasons = ["No approved seller offerings to compare, so fit stays low."]
        fit_gaps = ["Approve a seller profile with products or ICP first."]
    elif overlap or product_hits:
        fit = min(100, 35 + min(len(overlap), 12) * 4 + min(len(product_hits), 3) * 8)
        fit_reasons = [
            "Seller offerings overlap the lead's public description or signals."
        ]
        if product_hits:
            fit_reasons.append("Possible product matches: " + ", ".join(product_hits[:4]))
        fit_gaps = []
        if seller.icp.exclusions and _tokens(" ".join(seller.icp.exclusions)) & lead_tokens:
            fit = max(0, fit - 25)
            fit_gaps.append("Lead terms overlap the seller ICP exclusions.")
    else:
        fit = 28
        fit_reasons = ["No token overlap between approved seller offerings and lead evidence."]
        fit_gaps = offerings[:4] or ["No specific offering names to match"]

    people = collected.people
    if not people:
        contacts = 0
        contact_reasons = ["No decision-makers were found this run."]
        contact_matched: list[str] = []
    else:
        titled = [
            person
            for person in people
            if person.title and any(hint in person.title.lower() for hint in DECISION_TITLES)
        ]
        reachable = [person for person in people if person.email or person.linkedin_url]
        contacts = min(100, 25 + min(len(people), 5) * 8 + min(len(titled), 4) * 10 + min(len(reachable), 3) * 5)
        contact_reasons = [f"{len(people)} people found; {len(titled)} look like decision-makers."]
        contact_matched = [f"{person.name} ({person.title})" for person in titled[:4]]

    overall = round(
        0.35 * fit + 0.30 * qualification + 0.20 * completeness + 0.15 * contacts
    )
    if fit >= 58 and qualification >= 48 and completeness >= 35:
        recommendation: str = "pursue"
        rec_reason = (
            "Fit and buying motion are both strong enough to justify conversion time."
        )
    elif fit >= 40 or qualification >= 40:
        recommendation = "consider"
        rec_reason = (
            "Some fit or motion exists, but gaps or a weak match mean it is not a sure bet."
        )
    else:
        recommendation = "deprioritize"
        rec_reason = (
            "Fit and buying motion are both weak. Do not spend conversion energy yet."
        )

    return LeadScores(
        completeness=ScoreBreakdown(
            key="completeness",
            label="Research completeness",
            score=completeness,
            reasons=completeness_reasons,
            matched=supported,
            gaps=missing,
        ),
        evidence_quality=ScoreBreakdown(
            key="evidence_quality",
            label="Evidence quality",
            score=quality,
            reasons=quality_reasons,
        ),
        qualification=ScoreBreakdown(
            key="qualification",
            label="Lead qualification",
            score=qualification,
            reasons=qual_reasons,
            matched=qual_matched,
            gaps=qual_gaps,
        ),
        fit=ScoreBreakdown(
            key="fit",
            label="Seller–lead fit",
            score=fit,
            reasons=fit_reasons,
            matched=overlap[:12] + product_hits,
            gaps=fit_gaps,
        ),
        contact_relevance=ScoreBreakdown(
            key="contact_relevance",
            label="Contact relevance",
            score=contacts,
            reasons=contact_reasons,
            matched=contact_matched,
            gaps=[] if people else ["people"],
        ),
        overall=overall,
        recommendation=recommendation,  # type: ignore[arg-type]
        recommendation_reason=rec_reason,
    )


def product_matches(collected: CollectedResearch, seller: SellerProfile | None) -> list[ProductMatch]:
    if seller is None:
        return []
    lead_tokens = _tokens(_lead_blob(collected))
    scored: list[tuple[int, ProductMatch]] = []
    for offering, text in _offering_blobs(seller):
        hit = sorted(_tokens(text) & lead_tokens)
        if not hit:
            continue
        match = ProductMatch(
            offering=offering,
            reason=f"Lead evidence mentions {', '.join(hit[:6])}.",
            matched_lead_signals=hit[:8],
        )
        scored.append((len(hit), match))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [match for _, match in scored]
