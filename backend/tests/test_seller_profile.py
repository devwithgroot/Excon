import re

import pytest
from fastapi.testclient import TestClient

from app.application.seller_intel.company_analyzer import AnalysisOutput
from app.application.seller_intel.document_models import CrawlReport, IntelSourceType, Source
from app.application.seller_intel.icp_generator import IcpOutput
from app.application.seller_intel.profile_validator import _DescriptionRepair
from app.application.seller_intel.source_extractor import SourceExtraction
from app.infrastructure.database import get_db
from app.main import app
from tests.conftest import sqlite_session_factory

HOMEPAGE = (
    "# Acme Logistics Software\n\n"
    "Acme builds FreightDesk, a CRM for freight brokers that tracks loads and carriers.\n\n"
    "## Services\n\nWe also provide onboarding and data migration services for brokerages.\n\n"
    "Acme is a logistics software company serving mid-size freight brokerages in North America."
)
BROCHURE = (
    "# FreightDesk brochure\n\n"
    "FreightDesk reduces manual load tracking for brokers by automating carrier check calls.\n\n"
    "Pricing is a monthly subscription per seat."
)


def _facts(prompt: str) -> list[tuple[str, str, str | None, str]]:
    found = []
    for line in prompt.splitlines():
        match = re.match(r"(F\d+) \((\w+)\)(?: \[([^\]]+)\])?: (.+)", line)
        if match:
            found.append((match.group(1), match.group(2), match.group(3), match.group(4)))
    return found


def _analysis(user: str) -> dict:
    facts = _facts(user)
    first = lambda category: next(((fid, text) for fid, cat, _, text in facts if cat == category), None)  # noqa: E731
    industry = first("industry")
    segment = first("customer_segment")
    problem = first("problem_solved")
    return {
        "industry": {"value": industry[1], "facts": [industry[0]]} if industry else None,
        "products": [
            {"name": name or text, "description": text, "facts": [fid]} for fid, cat, name, text in facts if cat == "product"
        ],
        "services": [
            {"name": name or text, "description": text, "facts": [fid]} for fid, cat, name, text in facts if cat == "service"
        ],
        "customer_segments": [{"value": segment[1], "facts": [segment[0]]}] if segment else [],
        "problems_solved": [{"value": problem[1], "facts": [problem[0]]}] if problem else [],
    }


EXTRACTION = {
    "claims": [
        {"category": "product", "name": "FreightDesk", "value": "CRM for freight brokers that tracks loads and carriers",
         "excerpt": "Acme builds FreightDesk, a CRM for freight brokers that tracks loads and carriers.", "source": "S1"},
        {"category": "service", "name": "Onboarding and data migration", "value": "Onboarding and data migration for brokerages",
         "excerpt": "We also provide onboarding and data migration services for brokerages.", "source": "S1"},
        {"category": "industry", "value": "Logistics software",
         "excerpt": "Acme is a logistics software company serving mid-size freight brokerages", "source": "S1"},
        {"category": "customer_segment", "value": "Mid-size freight brokerages",
         "excerpt": "Acme is a logistics software company serving mid-size freight brokerages", "source": "S1"},
        {"category": "problem_solved", "value": "Manual load tracking",
         "excerpt": "FreightDesk reduces manual load tracking for brokers by automating carrier check calls.", "source": "S2"},
        {"category": "product", "name": "Acme Quantum AI", "value": "Invented product",
         "excerpt": "This sentence is not in any source at all.", "source": "S1"},
    ]
}

ICP = {
    "target_industries": ["Freight brokerage"],
    "customer_problems": ["Manual load tracking"],
    "suggestions": [
        {"prospect_type": "Mid-size freight brokerages adding carriers", "why_relevant": "They track loads by phone",
         "matching_offering": "FreightDesk", "basis": ["P1"]}
    ],
}


class FakeMlx:
    def __init__(self, replies: dict) -> None:
        self.replies = replies
        self.calls: list[type] = []

    async def complete_model(self, system, user, model_cls, **kwargs):
        self.calls.append(model_cls)
        reply = self.replies.get(model_cls)
        if callable(reply):
            reply = reply(user)
        return model_cls.model_validate(reply) if isinstance(reply, dict) else reply


def _site(pages: list[Source]):
    async def crawl(website_url, **kwargs):
        report = CrawlReport(root_url=website_url, pages_fetched=len(pages))
        if not pages:
            report.errors.append(f"{website_url}: ConnectError: unreachable")
        return list(pages), report

    return crawl


HOME_SOURCE = Source(
    source_type=IntelSourceType.website_page,
    source_name="Acme | Home",
    source_url="https://acme.example/",
    normalized_markdown=HOMEPAGE,
)


@pytest.fixture
def api(monkeypatch, tmp_path):
    factory = sqlite_session_factory()
    monkeypatch.setattr("app.api.routes.sellers.get_session_factory", lambda: factory)
    monkeypatch.setattr("app.infrastructure.uploads._root", lambda: tmp_path)
    monkeypatch.setattr("app.api.routes.sellers.seller_search", lambda: None)

    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db

    def configure(*, mlx, pages):
        monkeypatch.setattr("app.api.routes.sellers.seller_llm", lambda: mlx)
        monkeypatch.setattr("app.application.seller_intel.pipeline.crawl_site", _site(pages))

    yield TestClient(app), configure, factory
    app.dependency_overrides.clear()


def _start(client, files=None, company="Acme"):
    return client.post(
        "/sellers/extract",
        data={"name": "Alex", "company_name": company, "website_url": "acme.example"},
        files=files or [],
    )


def test_extraction_job_builds_grounded_draft_and_approval_is_explicit(api, tmp_path) -> None:
    client, configure, _ = api
    mlx = FakeMlx(
        {
            SourceExtraction: EXTRACTION,
            AnalysisOutput: _analysis,
            IcpOutput: ICP,
            _DescriptionRepair: {"description": "Acme sells FreightDesk, a CRM for freight brokers."},
        }
    )
    configure(mlx=mlx, pages=[HOME_SOURCE])

    started = _start(
        client,
        files=[
            ("files", ("brochure.md", BROCHURE.encode(), "text/markdown")),
            ("files", ("old-deck.ppt", b"\xd0\xcf\x11\xe0legacy", "application/vnd.ms-powerpoint")),
        ],
    )
    assert started.status_code == 202, started.text
    job = started.json()
    assert job["stage"] == "uploading_documents" and job["stage_total"] == 11
    rejected = next(doc for doc in job["documents"] if doc["filename"] == "old-deck.ppt")
    assert rejected["status"] == "unsupported_format" and "legacy" in rejected["error"]
    assert list(tmp_path.rglob("*brochure.md")), "the original upload is stored"

    status = client.get(f"/sellers/extract/{job['job_id']}").json()
    assert status["status"] == "succeeded", status
    assert status["stage"] == "ready_for_review"
    parsed = next(doc for doc in status["documents"] if doc["filename"] == "brochure.md")
    assert parsed["status"] == "parsed"

    seller = status["seller"]
    assert seller["status"] == "draft" and seller["approved"] is None, "extraction never auto-approves"
    draft = seller["draft"]
    assert [item["name"] for item in draft["products"]] == ["FreightDesk"]
    assert [item["name"] for item in draft["services"]] == ["Onboarding and data migration"]
    assert "Acme Quantum AI" not in str(draft), "ungrounded claims are dropped"
    assert draft["industry"] == "Logistics software"
    assert draft["website_url"] == "https://acme.example" and draft["domain"] == "acme.example"
    assert draft["evidence"] and all(item["source_id"] for item in draft["evidence"])
    assert {item["source_type"] for item in draft["evidence"]} == {"website", "document"}
    assert draft["traces"]["icp"]["support"] == "inferred"
    suggestion = draft["suggested_prospect_characteristics"][0]
    assert suggestion["status"] == "pending" and suggestion["support"] == "inferred"
    metadata = draft["extraction_metadata"]
    assert metadata["job_id"] == job["job_id"]
    assert any(source["source_type"] == "document" for source in metadata["sources"])
    assert any("document_unsupported_format" in warning for warning in metadata["warnings"])

    seller_id = seller["seller_id"]
    accepted = client.post(f"/sellers/{seller_id}/suggestions/{suggestion['suggestion_id']}/accept")
    assert accepted.status_code == 200
    assert accepted.json()["draft"]["suggested_prospect_characteristics"][0]["status"] == "accepted"
    assert accepted.json()["status"] == "draft"

    edited = accepted.json()["draft"]
    edited["products"].append({"name": "Dispatch board", "description": "Added by the user"})
    edited["evidence"] = []
    patched = client.patch(f"/sellers/{seller_id}/draft", json={"profile": edited})
    assert patched.status_code == 200
    patched_draft = patched.json()["draft"]
    assert [item["name"] for item in patched_draft["products"]] == ["FreightDesk", "Dispatch board"]
    assert patched_draft["traces"]["products"]["edited"] is True
    assert patched_draft["evidence"], "provenance is server-owned and survives client edits"

    approved = client.post(f"/sellers/{seller_id}/approve")
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "approved" and body["approved_version"] == 1
    assert [item["name"] for item in body["approved"]["products"]] == ["FreightDesk", "Dispatch board"]

    again = _start(client)
    assert again.json()["seller_id"] != seller_id, "onboarding always creates a new seller"


def test_llm_failure_keeps_identity_draft_and_reports_failure(api) -> None:
    client, configure, _ = api
    configure(mlx=FakeMlx({}), pages=[HOME_SOURCE])
    job = _start(client).json()
    status = client.get(f"/sellers/extract/{job['job_id']}").json()
    assert status["status"] == "failed"
    assert status["error"].startswith("llm_unavailable")
    draft = status["seller"]["draft"]
    assert draft["company_name"] == "Acme" and draft["contact_name"] == "Alex"
    assert draft["products"] == [] and draft["extraction_metadata"]["status"] == "failed"

    approve = client.post(f"/sellers/{status['seller_id']}/approve")
    assert approve.status_code == 400 and "product or service" in approve.json()["detail"]


def test_unreachable_site_without_documents_fails_clearly(api) -> None:
    client, configure, _ = api
    configure(mlx=FakeMlx({SourceExtraction: EXTRACTION}), pages=[])
    job = _start(client).json()
    status = client.get(f"/sellers/extract/{job['job_id']}").json()
    assert status["status"] == "failed" and status["error"].startswith("no_usable_sources")
    assert any("website_unreachable" in warning for warning in status["warnings"])


def test_documents_still_extract_when_website_is_down(api) -> None:
    client, configure, _ = api
    mlx = FakeMlx({SourceExtraction: EXTRACTION, AnalysisOutput: _analysis, IcpOutput: ICP})
    configure(mlx=mlx, pages=[])
    pitch = HOMEPAGE.replace("# Acme Logistics Software", "# Pitch")
    job = _start(client, files=[("files", ("pitch.txt", pitch.encode(), "text/plain"))]).json()
    status = client.get(f"/sellers/extract/{job['job_id']}").json()
    assert status["status"] == "partial", status
    assert [item["name"] for item in status["seller"]["draft"]["products"]] == ["FreightDesk"]


def test_upload_validation_and_manual_seller(api) -> None:
    client, configure, _ = api
    configure(mlx=FakeMlx({}), pages=[HOME_SOURCE])
    bad_url = client.post("/sellers/extract", data={"name": "Alex", "company_name": "Acme", "website_url": "not a url"})
    assert bad_url.status_code == 400
    missing = client.post("/sellers/extract", data={"name": " ", "company_name": "Acme", "website_url": "acme.example"})
    assert missing.status_code == 400

    created = client.post(
        "/sellers",
        json={
            "name": "Alex",
            "company_name": "Quick Seller Co",
            "website_url": "https://quick.example",
            "profile": {"company_name": "Quick Seller Co", "products": "Yard cameras", "icp": {"target_industries": "warehousing"}},
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "draft" and body["approved"] is None
    assert body["draft"]["products"][0]["name"] == "Yard cameras"
    assert body["draft"]["icp"]["target_industries"] == ["warehousing"]
    assert client.get(f"/sellers/{body['seller_id']}/draft").status_code == 200
    assert client.post(f"/sellers/{body['seller_id']}/suggestions/sug_missing/accept").status_code == 404


def test_interrupted_jobs_are_failed_on_startup(api, monkeypatch) -> None:
    client, configure, factory = api
    from app.infrastructure.models import ExtractionJob
    from app.infrastructure.repositories.research import ResearchStore
    from app.main import fail_interrupted_jobs

    db = factory()
    seller = ResearchStore(db).create_seller(company_name="Acme")
    db.add(ExtractionJob(seller_id=seller.id, status="running", stage="extracting_facts", warnings=[], summary={}))
    db.commit()
    db.close()

    monkeypatch.setattr("app.infrastructure.database.get_session_factory", lambda: factory)
    fail_interrupted_jobs()
    db = factory()
    job = db.query(ExtractionJob).one()
    assert job.status == "failed" and job.error.startswith("interrupted")
    db.close()
