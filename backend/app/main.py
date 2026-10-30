import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import drafts, health, reports, research, sellers
from app.config import get_settings

logger = logging.getLogger(__name__)


def fail_interrupted_jobs() -> None:
    """Background jobs live in-process, so anything still running after a restart is lost."""
    from app.infrastructure.database import get_session_factory
    from app.infrastructure.repositories.seller_intel import SellerIntelStore

    try:
        db = get_session_factory()()
        try:
            count = SellerIntelStore(db).fail_interrupted_jobs()
            db.commit()
        finally:
            db.close()
        if count:
            logger.warning("marked %d interrupted extraction job(s) as failed", count)
    except Exception as exc:
        logger.warning("could not sweep interrupted extraction jobs: %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    fail_interrupted_jobs()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Excon",
        version="0.1.0",
        description="LangGraph + LangChain research agent on FastAPI / Pydantic.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health.router)
    application.include_router(research.router)
    application.include_router(sellers.router)
    application.include_router(reports.router)
    application.include_router(drafts.router)
    return application


app = create_app()
