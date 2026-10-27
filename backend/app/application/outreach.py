from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.application.scoring import DECISION_TITLES, product_matches, seller_offerings
from app.domain.collected_research import CollectedResearch, ParameterStatus, PersonRecord
from app.domain.outreach import OutreachDraft
from app.domain.report import LeadReportBody, ProductMatch
from app.domain.seller_profile import SellerProfile

CONNECT_LIMIT = 300
WHATSAPP_LIMIT = 700
MAX_RECIPIENTS = 8

ROLE_HINTS = {
    "ops": ("coo", "operat", "field", "logistics", "supply"),
    "sales": ("cro", "sales", "revenue", "commercial", "growth"),
    "tech": ("cto", "cio", "engineer", "product", "technology", "digital"),
    "finance": ("cfo", "finance", "controller"),
    "founder": ("ceo", "founder", "owner", "president", "managing director", "partner"),
}


ROLE_NAME_WORDS = {
    "assistant",
    "executive",
    "managing",
    "director",
    "manager",
    "officer",
    "team",
    "office",
    "intern",
    "coordinator",
    "lead",
    "head",
}


def first_name(name: str) -> str:
    parts = [part for part in re.split(r"\s+", name.strip()) if part]
    if not parts:
        return "there"
    honorifics = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir"}
    if parts[0].lower().rstrip(".") in honorifics and len(parts) > 1:
        return parts[1]
    tokens = [part.lower().rstrip(".,") for part in parts]
    if tokens and all(token in ROLE_NAME_WORDS for token in tokens):
        return "there"
    return parts[0]


def _title_blob(title: str | None) -> str:
    return (title or "").lower()


def is_decision_maker(person: PersonRecord) -> bool:
    title = _title_blob(person.title)
    if not title:
        return False
    return any(hint in title for hint in DECISION_TITLES)


def role_family(title: str | None) -> str:
    blob = _title_blob(title)
    for family, hints in ROLE_HINTS.items():
        if any(hint in blob for hint in hints):
            return family
    return "general"


def _recent_news(collected: CollectedResearch) -> list[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    titles: list[str] = []
    for item in collected.news:
        if item.published_at:
            try:
                published = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                if published < cutoff:
                    continue
            except ValueError:
                pass
        if item.title:
            titles.append(item.title.strip())
    return titles[:4]


def company_facts(collected: CollectedResearch) -> list[str]:
    facts: list[str] = []
    company = collected.company
    if company.description.status == ParameterStatus.supported and company.description.value:
        facts.append(company.description.value.strip()[:220])
    if company.industry.status == ParameterStatus.supported and company.industry.value:
        facts.append(f"Industry: {company.industry.value.strip()}")
    if company.products.status == ParameterStatus.supported and company.products.value:
        facts.append(f"They publish: {company.products.value.strip()[:180]}")
    for name, field in collected.signals:
        if field.status == ParameterStatus.supported and field.value:
            facts.append(f"{name.replace('_', ' ').title()}: {field.value.strip()[:180]}")
    for title in _recent_news(collected):
        facts.append(f"Recent: {title}")
    return facts


def pick_offering(
    collected: CollectedResearch,
    seller: SellerProfile | None,
    report: LeadReportBody | None = None,
) -> tuple[str | None, str | None]:
    matches: list[ProductMatch] = []
    if report and report.product_matches:
        matches = report.product_matches
    else:
        matches = product_matches(collected, seller)
    if matches:
        top = matches[0]
        return top.offering, top.reason
    offerings = seller_offerings(seller)
    if offerings:
        lead = collected.company.name.value or "this company"
        return offerings[0], f"Your approved offering, mapped to what {lead} publishes."
    if seller and seller.description:
        return seller.company_name, seller.description[:180]
    if seller:
        return seller.company_name, None
    return None, None


def recipient_relevance(person: PersonRecord, offering: str | None, family: str) -> str:
    title = person.title or "a published contact"
    if family == "founder":
        return f"{person.name} is {title}, so the note is about company motion and where {offering or 'we'} fit."
    if family == "ops":
        return f"{person.name} owns operations ({title}); the draft leads with how the offering lands in the operating picture."
    if family == "sales":
        return f"{person.name} is {title}; the draft talks pipeline and field conversion, not a generic intro."
    if family == "tech":
        return f"{person.name} is {title}; the draft stays on product and how work actually runs."
    if family == "finance":
        return f"{person.name} is {title}; the draft is about cost of motion, not a product dump."
    return f"{person.name} is listed as {title}; the draft uses only evidenced company points."


def select_recipients(people: list[PersonRecord]) -> list[PersonRecord]:
    seen: set[str] = set()
    ordered: list[PersonRecord] = []
    for person in people:
        if is_decision_maker(person):
            key = person.evidence_id or person.name.lower()
            if key not in seen:
                seen.add(key)
                ordered.append(person)
    for person in people:
        key = person.evidence_id or person.name.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(person)
    return ordered[:MAX_RECIPIENTS]


def _trim(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    cut = compact[: limit - 1].rsplit(" ", 1)[0]
    return (cut or compact[: limit - 1]).rstrip(".,;:") + "…"


def _hook(facts: list[str], family: str) -> str:
    preferred: tuple[str, ...]
    if family == "sales":
        preferred = ("Hiring", "New Product", "Expansion", "Recent")
    elif family == "ops":
        preferred = ("Expansion", "Hiring", "New Product", "They publish", "Recent")
    elif family == "tech":
        preferred = ("Tech Shift", "New Product", "They publish", "Recent")
    elif family == "finance":
        preferred = ("Funding", "Expansion", "Recent")
    else:
        preferred = ("Recent", "Hiring", "New Product", "Expansion", "Funding")
    for prefix in preferred:
        for fact in facts:
            if fact.startswith(prefix) or fact.startswith("Recent"):
                return fact.split(": ", 1)[-1] if ": " in fact else fact
    return facts[0] if facts else ""


def _role_line(family: str, title: str | None, offering: str | None) -> str:
    seat = title or "your seat"
    product = offering or "what we sell"
    if family == "founder":
        return f"As {seat}, you own how the company is proceeding — that is where {product} is meant to land."
    if family == "ops":
        return f"Your {seat} role is the operating picture {product} is built for."
    if family == "sales":
        return f"From a {seat} seat, the useful question is whether {product} tightens field conversion."
    if family == "tech":
        return f"From a {seat} seat, this is about how work actually runs, not a slide deck."
    if family == "finance":
        return f"From a {seat} seat, the question is the cost of the current motion versus {product}."
    return f"I am writing you because you are listed as {seat}."


def compose_person_draft(
    *,
    run_id: str,
    person: PersonRecord,
    collected: CollectedResearch,
    seller: SellerProfile | None,
    seller_id: str | None = None,
    offering: str | None,
    offering_reason: str | None,
    contact_name: str | None = None,
    lead_name: str | None = None,
    draft_id: str | None = None,
) -> OutreachDraft:
    lead = lead_name or collected.company.name.value or "your company"
    seller_name = seller.company_name if seller else "our team"
    sender = (contact_name or (seller.contact_name if seller else None) or seller_name).strip()
    family = role_family(person.title)
    facts = company_facts(collected)
    hook = _hook(facts, family)
    given = first_name(person.name)
    title = person.title
    relevance = recipient_relevance(person, offering, family)
    cited = [item for item in facts[:6]]
    if offering:
        cited.append(f"Our offering: {offering}")
    if offering_reason:
        cited.append(offering_reason)

    if hook and offering:
        connect = (
            f"Hi {given} — been following {lead}"
            + (f" ({title})" if title else "")
            + f", especially {hook}. We sell {offering} at {seller_name}. "
            f"Your seat is where that can fit. Open to a short note?"
        )
    elif offering:
        connect = (
            f"Hi {given} — I've been following {lead} and your work"
            + (f" as {title}" if title else "")
            + f". We sell {offering} at {seller_name} and I think it maps to what you publish. "
            "Open to a short note?"
        )
    else:
        connect = (
            f"Hi {given} — I've been following {lead}"
            + (f" and your work as {title}" if title else "")
            + f". {sender} at {seller_name}. Worth a short note?"
        )

    bullets = "\n".join(f"• {fact}" for fact in facts[:4]) or f"• Public description of {lead}"
    who = seller.description if seller and seller.description else None
    problems = seller.problems_solved if seller else None
    intro = f"I'm {sender} at {seller_name}."
    if who:
        intro += f" {who[:180]}"
    if offering:
        intro += f" We sell {offering}."
        if offering_reason:
            intro += f" {offering_reason}"
    if problems:
        intro += f" We solve: {problems[:140]}."

    message = (
        f"Hi {given},\n\n"
        f"I've been following {lead}"
        + (f" and your work as {title}" if title else "")
        + " for a while — not a cold spray, a few public points from the last stretch stood out:\n\n"
        f"{bullets}\n\n"
        f"{_role_line(family, title, offering)}\n\n"
        f"{intro}\n\n"
        "That is why I am reaching out. If it is useful I can send a one-page on the fit — "
        "no deck dump, just the overlap.\n\n"
        f"{sender}\n{seller_name}"
    )

    wa_hook = hook or (facts[0] if facts else f"what {lead} publishes")
    if offering:
        whatsapp = (
            f"Hi {given} — {sender} from {seller_name}. Been following {lead}"
            + (f" ({title})" if title else "")
            + f", especially {wa_hook}. We sell {offering}; it looks like a fit for your seat. "
            "Happy to send a short note if useful."
        )
    else:
        whatsapp = (
            f"Hi {given} — {sender} from {seller_name}. Been following {lead} "
            f"and wanted to introduce ourselves. Happy to send a short note if useful."
        )

    return OutreachDraft(
        draft_id=draft_id or str(uuid4()),
        run_id=run_id,
        seller_id=seller_id,
        person_evidence_id=person.evidence_id or str(uuid4()),
        person_name=person.name,
        person_title=person.title,
        person_linkedin_url=person.linkedin_url,
        offering=offering,
        offering_reason=offering_reason,
        relevance=relevance,
        cited_facts=cited,
        linkedin_connect=_trim(connect, CONNECT_LIMIT),
        linkedin_message=message.strip(),
        whatsapp=_trim(whatsapp, WHATSAPP_LIMIT),
        status="draft",
        version=1,
    )


def validate_draft(draft: OutreachDraft, facts: list[str]) -> OutreachDraft:
    connect = _trim(draft.linkedin_connect, CONNECT_LIMIT)
    whatsapp = _trim(draft.whatsapp, WHATSAPP_LIMIT)
    message = draft.linkedin_message.strip()
    if not draft.person_name.strip():
        return draft.model_copy(update={"skipped_reason": "Missing person name"})
    if not connect or not message or not whatsapp:
        return draft.model_copy(update={"skipped_reason": "Empty channel copy"})
    banned = ("i invented", "as an ai", "as a language model")
    lowered = f"{connect} {message} {whatsapp}".lower()
    if any(token in lowered for token in banned):
        return draft.model_copy(update={"skipped_reason": "Unusable generated copy"})
    return draft.model_copy(
        update={
            "linkedin_connect": connect,
            "linkedin_message": message,
            "whatsapp": whatsapp,
            "cited_facts": draft.cited_facts or facts[:6],
            "skipped_reason": None,
        }
    )


def compose_batch(
    *,
    run_id: str,
    collected: CollectedResearch,
    seller: SellerProfile | None,
    seller_id: str | None = None,
    report: LeadReportBody | None = None,
    contact_name: str | None = None,
    lead_name: str | None = None,
) -> tuple[list[OutreachDraft], list[dict]]:
    offering, reason = pick_offering(collected, seller, report)
    facts = company_facts(collected)
    drafts: list[OutreachDraft] = []
    skipped: list[dict] = []
    for person in select_recipients(collected.people):
        if not person.name.strip():
            skipped.append({"name": "", "reason": "Person has no name"})
            continue
        draft = compose_person_draft(
            run_id=run_id,
            person=person,
            collected=collected,
            seller=seller,
            seller_id=seller_id,
            offering=offering,
            offering_reason=reason,
            contact_name=contact_name,
            lead_name=lead_name,
        )
        draft = validate_draft(draft, facts)
        if draft.skipped_reason:
            skipped.append({"name": person.name, "reason": draft.skipped_reason})
            continue
        drafts.append(draft)
    return drafts, skipped
