from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, reports, research, sellers
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Excon",
        version="0.1.0",
        description="LangGraph + LangChain research agent on FastAPI / Pydantic.",
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
    return application


app = create_app()
