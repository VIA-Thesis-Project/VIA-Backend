"""FastAPI entry point for the VIA modular monolith."""

from __future__ import annotations

from fastapi import FastAPI

from via.bounded_contexts.document_management.interfaces.document_router import router as document_router
from via.bounded_contexts.iam.interfaces.auth_router import router as auth_router
from via.bounded_contexts.parcel_management.interfaces.parcel_router import router as parcel_router
from via.bounded_contexts.rulebook_management.interfaces.rulebook_router import router as rulebook_router
from via.bounded_contexts.recommendation.interfaces.recommendation_router import router as recommendation_router
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_router import router as evaluation_router
from via.config import get_settings
from via.shared.runtime.application_runtime import configure_application_runtime


def create_app() -> FastAPI:
    """Create the single FastAPI application for all VIA bounded contexts."""

    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.state.runtime = configure_application_runtime()
    app.state.event_bus = app.state.runtime.event_bus
    app.state.relay_worker = app.state.runtime.relay_worker
    app.include_router(auth_router)
    app.include_router(parcel_router)
    app.include_router(rulebook_router)
    app.include_router(document_router)
    app.include_router(evaluation_router)
    app.include_router(recommendation_router)
    return app


app = create_app()
