from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.infrastructure.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def health_ready(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok", "database": "ok"}


@router.get("/health/providers")
def health_providers(settings: Settings = Depends(get_settings)) -> dict[str, bool]:
    return {
        "mlx_configured": bool(settings.mlx_base_url),
        "tavily_configured": bool(settings.tavily_api_key),
        "prospeo_configured": bool(settings.prospeo_api_key),
    }
