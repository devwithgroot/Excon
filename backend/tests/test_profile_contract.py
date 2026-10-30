from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.application.seller_intel.profile_builder import build_profile
from app.application.seller_intel.profile_validator import check_profile, validate_profile
from app.domain.company_intelligence import (
    CompanyIntelligence,
    Conflict,
    ConflictValue,
    ProductInfo,
    ProposedICP,
    ProspectSuggestion,
    ServiceInfo,
    Traced,
)
from app.domain.evidence import EvidenceItem, SourceType
from app.domain.seller_profile import SellerProfile, offering_names, profile_text

LEGACY_ROW = {
    "company_name": "Tezbytes",
    "contact_name": "Sandeep",
    "products": "Ops Audit, workflow automation, custom software",
    "services": "Ops Audit, workflow automation",
    "features": "visit workflows, invoice chasing",
    "problems_solved": "Teams chasing updates on WhatsApp, missing data",
    "geography": "Bengaluru",
    "size": "20 employees",
    "icp": {
        "target_industries": "Indian MSMEs, logistics",
        "departments_roles": "Operations head",
        "problems": "work stuck between people",
        "preferred": "owner-led",
        "exclusions": "enterprises with in-house IT",
    },
    "status": "approved",
    "version": 2,
}


def _evidence(evidence_id: str, value: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        field_key="seller.product",
        extracted_value=value,
        source_type=SourceType.website,
        retrieved_at=datetime.now(timezone.utc),
        supporting_excerpt=value,
    )


def test_legacy_string_rows_upgrade_on_load() -> None:
    profile = SellerProfile.model_validate(LEGACY_ROW)
    assert offering_names(profile) == ["Ops Audit", "workflow automation", "custom software", "Ops Audit", "workflow automation"]
    assert profile.features == ["visit workflows", "invoice chasing"]
    assert profile.problems_solved == ["Teams chasing updates on WhatsApp, missing data"], "sentences are not split"
    assert profile.geography == ["Bengaluru"] and profile.company_size == "20 employees"
    assert profile.icp.target_industries == ["Indian MSMEs", "logistics"]
    assert profile.icp.departments == ["Operations head"]
    assert profile.icp.customer_problems == ["work stuck between people"]
    assert profile.icp.preferred_characteristics == ["owner-led"]
    assert profile.icp.exclusions == ["enterprises with in-house IT"]
    assert SellerProfile.model_validate(profile.model_dump(mode="json")) == profile, "new shape round-trips"


def test_profile_validators_normalize_and_reject_bad_types() -> None:
    profile = SellerProfile(
        company_name="Acme",
        description="   ",
        products=[{"name": " CRM "}, "crm", {"name": ""}],
        features=["Tracking", "tracking", ""],
    )
    assert profile.description is None
    assert [item.name for item in profile.products] == ["CRM"]
    assert profile.features == ["Tracking"]
    with pytest.raises(ValidationError):
        SellerProfile(company_name="Acme", status="published")
    with pytest.raises(ValidationError):
        SellerProfile(company_name="Acme", products=[{"description": "no name"}])


def _intelligence() -> CompanyIntelligence:
    return CompanyIntelligence(
        company_name="Acme",
        website_url="https://www.acme.test/",
        industry=Traced(value="Sales force automation", evidence_ids=["e1"]),
        description=Traced(value="Acme builds FieldApp.", evidence_ids=["e1"], support="inferred"),
        geography=[Traced(value="India", evidence_ids=["e3"])],
        products=[ProductInfo(name="FieldApp", features=["Visit tracking"], evidence_ids=["e1", "ghost"])],
        services=[ServiceInfo(name="Route consulting", evidence_ids=["e2"])],
        features=[Traced(value="Visit tracking", evidence_ids=["e1"])],
        customer_segments=[Traced(value="FMCG distributors", evidence_ids=["e2"])],
        icp=ProposedICP(target_industries=["FMCG distribution"], decision_maker_roles=["Head of Sales"]),
        prospect_suggestions=[ProspectSuggestion(prospect_type="Regional distributors", evidence_ids=["e1"])],
        conflicts=[Conflict(field="company_size", values=[ConflictValue(value="20"), ConflictValue(value="500")])],
        missing=["problem_solved"],
        confidence={"industry": 0.8},
        evidence=[_evidence("e1", "FieldApp"), _evidence("e2", "Route consulting"), _evidence("e3", "India"), _evidence("e9", "unused")],
    )


def test_builder_maps_each_category_to_its_own_field() -> None:
    profile = build_profile(_intelligence(), contact_name="Sandeep", seller_id="s1", job_id="j1")
    assert profile.domain == "acme.test"
    assert [p.name for p in profile.products] == ["FieldApp"]
    assert [s.name for s in profile.services] == ["Route consulting"]
    assert profile.features == ["Visit tracking"], "features are not promoted to products"
    assert profile.customer_segments == ["FMCG distributors"] and profile.icp.target_industries == ["FMCG distribution"]
    assert profile.traces["industry"].support == "explicit" and profile.traces["industry"].confidence == 0.8
    assert profile.traces["description"].support == "inferred"
    assert profile.traces["icp"].support == "inferred"
    assert {e.evidence_id for e in profile.evidence} == {"e1", "e2", "e3"}, "unused evidence is not carried"
    assert profile.extraction_metadata.job_id == "j1" and profile.extraction_metadata.missing == ["problem_solved"]
    assert profile.suggested_prospect_characteristics[0].status == "pending"


async def test_validator_repairs_safely_and_reports_the_rest() -> None:
    profile = build_profile(_intelligence(), contact_name=None)
    checked = await validate_profile(profile)
    codes = {issue.code for issue in checked.extraction_metadata.validation}
    assert "dangling_evidence" in codes
    assert checked.products[0].evidence_ids == ["e1"]
    assert "conflict" in codes and "inferred" in codes
    assert 0 < checked.extraction_metadata.completeness < 1
    assert checked.extraction_metadata.status == "complete"

    empty = build_profile(CompanyIntelligence(company_name="Acme", website_url="https://acme.test"), contact_name=None)
    empty = await validate_profile(empty)
    assert empty.extraction_metadata.status == "partial"
    assert any(issue.code == "missing_offerings" and issue.severity == "error" for issue in empty.extraction_metadata.validation)


async def test_validator_makes_one_targeted_description_repair() -> None:
    class RepairMlx:
        calls = 0

        async def complete_model(self, system, user, model_cls, **kwargs):
            RepairMlx.calls += 1
            return model_cls(description="Acme sells FieldApp for field sales teams.")

    intelligence = _intelligence()
    intelligence.description = None
    repaired = await validate_profile(build_profile(intelligence, contact_name=None), mlx=RepairMlx())
    assert RepairMlx.calls == 1
    assert repaired.description.startswith("Acme sells FieldApp")
    assert repaired.traces["description"].support == "inferred"


def test_check_flags_product_service_overlap() -> None:
    profile = SellerProfile(company_name="Acme", website_url="https://acme.test", products=["Ops Audit"], services=["Ops Audit"])
    _, issues = check_profile(profile)
    assert any(issue.code == "product_service_overlap" for issue in issues)


def test_scoring_text_excludes_unaccepted_suggestions() -> None:
    profile = SellerProfile(
        company_name="Acme",
        products=[{"name": "FieldApp", "description": "route planning for reps"}],
        suggested_prospect_characteristics=[
            ProspectSuggestion(prospect_type="pharma wholesalers", status="pending"),
            ProspectSuggestion(prospect_type="cement dealers", status="accepted"),
        ],
    )
    text = profile_text(profile)
    assert "route planning" in text and "cement dealers" in text and "pharma" not in text
