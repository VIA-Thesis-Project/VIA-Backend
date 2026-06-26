"""FastAPI entry point for the VIA modular monolith."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from via.bounded_contexts.document_management.interfaces.document_router import router as document_router
from via.bounded_contexts.document_management.interfaces.document_router import get_current_user as get_document_current_user
from via.bounded_contexts.iam.application.command_service import AuthenticateUserCommandService, RegisterUserCommandService
from via.bounded_contexts.iam.domain.user import User
from via.bounded_contexts.iam.infrastructure.jwt_adapter import InvalidTokenError, JWTTokenService
from via.bounded_contexts.iam.infrastructure.password_hasher import BcryptPasswordHasher
from via.bounded_contexts.iam.infrastructure.user_repository import SQLAlchemyAuthAuditRepository, SQLAlchemyUserRepository
from via.bounded_contexts.iam.interfaces.auth_router import get_authentication_service, get_register_service
from via.bounded_contexts.iam.interfaces.auth_router import router as auth_router
from via.bounded_contexts.parcel_management.application.command_service import ParcelCommandService
from via.bounded_contexts.parcel_management.application.query_service import ParcelQueryService
from via.bounded_contexts.parcel_management.domain.geometry_validator import ParcelGeometryValidator
from via.bounded_contexts.parcel_management.infrastructure.parcel_repository import SQLAlchemyParcelRepository
from via.bounded_contexts.parcel_management.interfaces.parcel_router import get_current_user as get_parcel_current_user
from via.bounded_contexts.parcel_management.interfaces.parcel_router import get_parcel_command_service, get_parcel_query_service
from via.bounded_contexts.parcel_management.interfaces.parcel_router import router as parcel_router
from via.bounded_contexts.rulebook_management.application.command_service import RulebookCommandService
from via.bounded_contexts.rulebook_management.application.query_service import RulebookQueryService
from via.bounded_contexts.rulebook_management.infrastructure.rulebook_repository import SqlAlchemyRulebookRepository
from via.bounded_contexts.rulebook_management.interfaces.rulebook_router import get_current_user as get_rulebook_current_user
from via.bounded_contexts.rulebook_management.interfaces.rulebook_router import get_rulebook_command_service, get_rulebook_query_service
from via.bounded_contexts.rulebook_management.interfaces.rulebook_router import router as rulebook_router
from via.bounded_contexts.recommendation.application.recommendation_query_service import RecommendationQueryService
from via.bounded_contexts.recommendation.infrastructure.recommendation_query_repository import RecommendationQueryRepository
from via.bounded_contexts.recommendation.interfaces.recommendation_router import get_recommendation_query_service
from via.bounded_contexts.recommendation.interfaces.recommendation_router import router as recommendation_router
from via.bounded_contexts.viability_evaluation.application.query_service import EvaluationQueryService
from via.bounded_contexts.viability_evaluation.infrastructure.evaluation_query_repository import EvaluationQueryRepository
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_router import get_evaluation_query_service, get_process_manager
from via.bounded_contexts.viability_evaluation.interfaces.evaluation_router import router as evaluation_router
from via.config import Settings, get_settings
from via.shared.database.session import get_session_factory
from via.shared.orchestration.evaluation_process_manager.process_manager import EvaluationProcessManager
from via.shared.runtime.application_runtime import configure_application_runtime


def create_app() -> FastAPI:
    """Create the single FastAPI application for all VIA bounded contexts."""

    settings = get_settings()
    session_factory = get_session_factory()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        start = getattr(app.state.relay_worker, "start", None)
        if callable(start):
            start()
        yield
        stop = getattr(app.state.relay_worker, "stop", None)
        if callable(stop):
            stop(timeout=10)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.runtime = configure_application_runtime(session_factory=session_factory)
    app.state.event_bus = app.state.runtime.event_bus
    app.state.relay_worker = app.state.runtime.relay_worker
    app.include_router(auth_router)
    app.include_router(parcel_router)
    app.include_router(rulebook_router)
    app.include_router(document_router)
    app.include_router(evaluation_router)
    app.include_router(recommendation_router)
    _wire_iam_dependencies(app, session_factory, settings)
    _wire_parcel_dependencies(app, session_factory, settings)
    _wire_rulebook_dependencies(app, session_factory)
    _wire_evaluation_dependencies(app, session_factory)
    _wire_recommendation_dependencies(app, session_factory)

    @app.get("/health", tags=["ops"])
    def health() -> dict:
        return {"status": "ok"}

    return app


def _wire_iam_dependencies(
    app: FastAPI,
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> None:
    """Install real IAM infrastructure into FastAPI dependency overrides."""

    hasher = BcryptPasswordHasher()
    token_svc = JWTTokenService(settings)
    bearer = HTTPBearer(auto_error=True)

    def _iam_auth_dep() -> Generator[AuthenticateUserCommandService, None, None]:
        session = session_factory()
        try:
            yield AuthenticateUserCommandService(
                user_repository=SQLAlchemyUserRepository(session),
                password_hasher=hasher,
                token_service=token_svc,
                auth_audit_repository=SQLAlchemyAuthAuditRepository(session),
            )
        finally:
            try:
                session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()

    def _current_user_dep(
        credentials: HTTPAuthorizationCredentials = Depends(bearer),
    ) -> User:
        try:
            payload = token_svc.decode_access_token(credentials.credentials)
            user_id = UUID(str(payload["sub"]))
        except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        session = session_factory()
        try:
            user = SQLAlchemyUserRepository(session).get_by_id(user_id)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return user
        finally:
            session.close()

    def _iam_register_dep() -> Generator[RegisterUserCommandService, None, None]:
        session = session_factory()
        try:
            yield RegisterUserCommandService(
                user_repository=SQLAlchemyUserRepository(session),
                password_hasher=hasher,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_authentication_service] = _iam_auth_dep
    app.dependency_overrides[get_register_service] = _iam_register_dep
    app.dependency_overrides[get_parcel_current_user] = _current_user_dep
    app.dependency_overrides[get_rulebook_current_user] = _current_user_dep
    app.dependency_overrides[get_document_current_user] = _current_user_dep


def _wire_parcel_dependencies(
    app: FastAPI,
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> None:
    """Install real parcel infrastructure into FastAPI dependency overrides."""

    def _parcel_command_dep() -> Generator[ParcelCommandService, None, None]:
        session = session_factory()
        try:
            yield ParcelCommandService(
                parcel_repository=SQLAlchemyParcelRepository(session),
                geometry_validator=ParcelGeometryValidator(settings.parcel_max_area_ha),
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _parcel_query_dep() -> Generator[ParcelQueryService, None, None]:
        session = session_factory()
        try:
            yield ParcelQueryService(SQLAlchemyParcelRepository(session))
        finally:
            session.close()

    app.dependency_overrides[get_parcel_command_service] = _parcel_command_dep
    app.dependency_overrides[get_parcel_query_service] = _parcel_query_dep


def _wire_rulebook_dependencies(
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    """Install real rulebook infrastructure into FastAPI dependency overrides."""

    def _rulebook_command_dep() -> Generator[RulebookCommandService, None, None]:
        session = session_factory()
        try:
            yield RulebookCommandService(repository=SqlAlchemyRulebookRepository(session))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _rulebook_query_dep() -> Generator[RulebookQueryService, None, None]:
        session = session_factory()
        try:
            yield RulebookQueryService(SqlAlchemyRulebookRepository(session))
        finally:
            session.close()

    app.dependency_overrides[get_rulebook_command_service] = _rulebook_command_dep
    app.dependency_overrides[get_rulebook_query_service] = _rulebook_query_dep


def _wire_recommendation_dependencies(
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    """Install real recommendation query infrastructure into FastAPI dependency overrides."""

    def _recommendation_query_dep() -> Generator[RecommendationQueryService, None, None]:
        session = session_factory()
        try:
            yield RecommendationQueryService(RecommendationQueryRepository(session))
        finally:
            session.close()

    app.dependency_overrides[get_recommendation_query_service] = _recommendation_query_dep


def _wire_evaluation_dependencies(
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    """Install real evaluation saga and query dependencies."""

    def _process_manager_dep() -> EvaluationProcessManager:
        return app.state.runtime.process_manager

    def _evaluation_query_dep() -> Generator[EvaluationQueryService, None, None]:
        session = session_factory()
        try:
            yield EvaluationQueryService(EvaluationQueryRepository(session))
        finally:
            session.close()

    app.dependency_overrides[get_process_manager] = _process_manager_dep
    app.dependency_overrides[get_evaluation_query_service] = _evaluation_query_dep


app = create_app()
