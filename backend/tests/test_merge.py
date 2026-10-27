from datetime import datetime, timezone

from app.domain.collected_research import (
    CollectedResearch,
    CompanyBlock,
    FieldValue,
    ParameterStatus,
    PersonRecord,
    SignalsBlock,
)
from app.domain.evidence import EvidenceItem, SourceType
from app.domain.merge import merge_field, merge_research


def test_merge_field_does_not_overwrite_supported() -> None:
    base = FieldValue(value="Acme", status=ParameterStatus.supported, evidence_ids=["a"])
    incoming = FieldValue(value="Other", status=ParameterStatus.supported, evidence_ids=["b"])
    merged = merge_field(base, incoming)
    assert merged.value == "Acme"
    assert merged.evidence_ids == ["a"]


def test_merge_field_empty_does_not_replace_supported() -> None:
    base = FieldValue(value="Acme", status=ParameterStatus.supported, evidence_ids=["a"])
    incoming = FieldValue(status=ParameterStatus.not_found_this_run)
    assert merge_field(base, incoming).value == "Acme"


def test_merge_field_promotes_unknown_to_supported() -> None:
    base = FieldValue()
    incoming = FieldValue(value="Austin", status=ParameterStatus.supported, evidence_ids=["e1"])
    merged = merge_field(base, incoming)
    assert merged.status == ParameterStatus.supported
    assert merged.value == "Austin"


def test_merge_research_keeps_supported_and_appends_lists() -> None:
    first_evidence = EvidenceItem(
        evidence_id="e1",
        field_key="company.name",
        extracted_value="Acme",
        source_type=SourceType.website,
        retrieved_at=datetime.now(timezone.utc),
    )
    second_evidence = EvidenceItem(
        evidence_id="e2",
        field_key="signals.hiring",
        extracted_value="Hiring engineers",
        source_type=SourceType.web_search,
        retrieved_at=datetime.now(timezone.utc),
    )
    base = CollectedResearch(
        company=CompanyBlock(
            name=FieldValue(value="Acme", status=ParameterStatus.supported, evidence_ids=["e1"])
        ),
        evidence=[first_evidence],
        people=[
            PersonRecord(name="Ada", title="CTO", evidence_id="e1"),
        ],
    )
    patch = CollectedResearch(
        company=CompanyBlock(name=FieldValue(status=ParameterStatus.not_found_this_run)),
        signals=SignalsBlock(
            hiring=FieldValue(
                value="Hiring engineers",
                status=ParameterStatus.supported,
                evidence_ids=["e2"],
            )
        ),
        people=[PersonRecord(name="Ada", title="CTO", evidence_id="e9")],
        evidence=[second_evidence],
    )
    merged = merge_research(base, patch)
    assert merged.company.name.value == "Acme"
    assert merged.signals.hiring.value == "Hiring engineers"
    assert len(merged.people) == 1
    assert {item.evidence_id for item in merged.evidence} == {"e1", "e2"}
    assert "signals.funding" in merged.missing_parameters()
    assert "company.name" not in merged.missing_parameters()
