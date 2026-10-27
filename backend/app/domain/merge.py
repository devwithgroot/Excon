from app.domain.collected_research import (
    CollectedResearch,
    CompanyBlock,
    FieldValue,
    ParameterStatus,
    SignalsBlock,
)
from app.domain.evidence import EvidenceItem


def merge_field(base: FieldValue, incoming: FieldValue) -> FieldValue:
    if incoming.status == ParameterStatus.supported and incoming.value:
        if base.status != ParameterStatus.supported:
            return incoming.model_copy()
        return base
    if (
        base.status == ParameterStatus.unknown
        and incoming.status == ParameterStatus.not_found_this_run
    ):
        return incoming.model_copy()
    return base


def _merge_block(base: CompanyBlock | SignalsBlock, incoming: CompanyBlock | SignalsBlock):
    data = {}
    for name, _ in base:
        data[name] = merge_field(getattr(base, name), getattr(incoming, name))
    return type(base)(**data)


def merge_research(base: CollectedResearch, patch: CollectedResearch) -> CollectedResearch:
    evidence_by_id: dict[str, EvidenceItem] = {item.evidence_id: item for item in base.evidence}
    for item in patch.evidence:
        evidence_by_id.setdefault(item.evidence_id, item)

    news = list(base.news)
    seen_news = {item.url for item in news}
    for item in patch.news:
        if item.url not in seen_news:
            news.append(item)
            seen_news.add(item.url)

    people = list(base.people)
    seen_people = {(item.name.lower(), item.title) for item in people}
    for item in patch.people:
        key = (item.name.lower(), item.title)
        if key not in seen_people:
            people.append(item)
            seen_people.add(key)

    return CollectedResearch(
        company=_merge_block(base.company, patch.company),
        signals=_merge_block(base.signals, patch.signals),
        news=news,
        people=people,
        evidence=list(evidence_by_id.values()),
    )
