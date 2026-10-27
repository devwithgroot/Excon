from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.application.report import build_lead_report
from app.domain.collected_research import CollectedResearch
from app.domain.report import LeadReportBody
from app.domain.seller_profile import SellerProfile
from app.infrastructure.database import get_db
from app.infrastructure.repositories.research import ResearchStore

router = APIRouter(tags=["reports"])


def _seller_for_run(store: ResearchStore, run) -> tuple[SellerProfile | None, str | None, int]:
    if run.seller_id:
        seller = store.get_seller(run.seller_id)
        if seller and seller.approved_profile:
            profile = SellerProfile.model_validate(seller.approved_profile)
            return profile, seller.id, seller.approved_version or 0
        if seller and seller.profile:
            return SellerProfile.model_validate(seller.profile), seller.id, 0
    if run.seller_profile:
        return SellerProfile.model_validate(run.seller_profile), run.seller_id, 0
    return None, run.seller_id, 0


@router.post("/research/runs/{run_id}/report", response_model=LeadReportBody)
async def create_run_report(run_id: str, db: Session = Depends(get_db)) -> LeadReportBody:
    store = ResearchStore(db)
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    collected = CollectedResearch.model_validate(run.collected or {})
    seller, seller_id, version = _seller_for_run(store, run)
    report = await build_lead_report(
        collected,
        seller,
        run_id=run.id,
        seller_id=seller_id,
        mlx=None,
    )
    report = report.model_copy(update={"seller_version": version, "seller_id": seller_id})
    store.save_report(report)
    db.commit()
    return report


@router.get("/research/runs/{run_id}/report", response_model=LeadReportBody)
def get_run_report(run_id: str, db: Session = Depends(get_db)) -> LeadReportBody:
    store = ResearchStore(db)
    row = store.get_report_for_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return LeadReportBody.model_validate(row.body)


@router.get("/reports/{report_id}", response_model=LeadReportBody)
def get_report(report_id: str, db: Session = Depends(get_db)) -> LeadReportBody:
    row = ResearchStore(db).get_report(report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return LeadReportBody.model_validate(row.body)
