"""Protected Document Management routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from via.bounded_contexts.document_management.application.command_service import (
    DocumentCommandService,
    RegisterDocumentCommand,
    RegisterFragmentCommand,
)
from via.bounded_contexts.document_management.application.ports import DocumentSearchResult
from via.bounded_contexts.document_management.application.query_service import (
    DocumentNotFoundError,
    DocumentQueryService,
    DocumentSearchService,
    SearchDocumentFragmentsQuery,
)
from via.bounded_contexts.document_management.domain.document import TechnicalDocument
from via.bounded_contexts.document_management.domain.fragment import DocumentFragment
from via.bounded_contexts.document_management.domain.value_objects import DocumentDomainError
from via.bounded_contexts.document_management.interfaces.resources import (
    DocumentCreateRequest,
    DocumentFragmentResponse,
    DocumentFragmentSearchResponse,
    DocumentResponse,
)
from via.bounded_contexts.iam.domain.role import Role
from via.bounded_contexts.iam.domain.user import User


router = APIRouter(prefix="/documentos", tags=["documentos"])
DOCUMENT_COMMAND_ROLES = {Role.ADMINISTRADOR}
DOCUMENT_QUERY_ROLES = {Role.ADMINISTRADOR}


def get_current_user() -> User:
    """Return the authenticated user dependency."""

    raise RuntimeError("Authenticated user dependency is not configured")


def get_document_command_service() -> DocumentCommandService:
    """Return the configured document command service dependency."""

    raise RuntimeError("Document command service dependency is not configured")


def get_document_query_service() -> DocumentQueryService:
    """Return the configured document query service dependency."""

    raise RuntimeError("Document query service dependency is not configured")


def get_document_search_service() -> DocumentSearchService:
    """Return the configured document search service dependency."""

    raise RuntimeError("Document search service dependency is not configured")


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DocumentResponse)
def create_document(
    request: DocumentCreateRequest,
    current_user: User = Depends(get_current_user),
    command_service: DocumentCommandService = Depends(get_document_command_service),
) -> DocumentResponse:
    """Register a technical document with already structured fragments."""

    _ensure_role(current_user, DOCUMENT_COMMAND_ROLES)
    try:
        document = command_service.register_document(
            RegisterDocumentCommand(
                title=request.title,
                format=request.format,
                crop_tags=request.crop_tags,
                size_bytes=request.size_bytes,
                fragments=[
                    RegisterFragmentCommand(
                        text=fragment.text,
                        page_ref=fragment.page_ref,
                        crop_tags=fragment.crop_tags,
                        token_count=fragment.token_count,
                    )
                    for fragment in request.fragments
                ],
            )
        )
    except (DocumentDomainError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _document_to_response(document)


@router.get("/fragmentos/buscar", response_model=list[DocumentFragmentSearchResponse])
def search_fragments(
    crop_tag: str = Query(min_length=1),
    query: str = Query(min_length=1),
    limit: int = Query(default=10, gt=0),
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
    current_user: User = Depends(get_current_user),
    search_service: DocumentSearchService = Depends(get_document_search_service),
) -> list[DocumentFragmentSearchResponse]:
    """Search relevant fragments by crop tag and query text."""

    _ensure_role(current_user, DOCUMENT_QUERY_ROLES)
    try:
        results = search_service.search(
            SearchDocumentFragmentsQuery(text=query, crop_tags=[crop_tag], max_results=limit)
        )
    except (DocumentDomainError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if min_score is not None:
        results = [result for result in results if result.score >= min_score]
    return [_search_result_to_response(result) for result in results]


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    query_service: DocumentQueryService = Depends(get_document_query_service),
) -> DocumentResponse:
    """Return one registered technical document."""

    _ensure_role(current_user, DOCUMENT_QUERY_ROLES)
    try:
        return _document_to_response(query_service.get_document(document_id))
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc


@router.get("/{document_id}/fragmentos", response_model=list[DocumentFragmentResponse])
def list_document_fragments(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    query_service: DocumentQueryService = Depends(get_document_query_service),
) -> list[DocumentFragmentResponse]:
    """List fragments for one registered technical document."""

    _ensure_role(current_user, DOCUMENT_QUERY_ROLES)
    try:
        return [_fragment_to_response(fragment) for fragment in query_service.list_fragments(document_id)]
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc


def _ensure_role(user: User, allowed_roles: set[Role]) -> None:
    if user.role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _document_to_response(document: TechnicalDocument) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        title=document.title,
        format=document.format.value,
        crop_tags=document.crop_tags,
        size_bytes=document.size_bytes,
        status=document.status.value,
        fragments=[_fragment_to_response(fragment) for fragment in document.fragments],
    )


def _fragment_to_response(fragment: DocumentFragment) -> DocumentFragmentResponse:
    return DocumentFragmentResponse(
        id=fragment.id,
        document_id=fragment.document_id,
        text=fragment.text,
        page_ref=fragment.page_ref,
        crop_tags=fragment.crop_tags,
        token_count=fragment.token_count,
    )


def _search_result_to_response(result: DocumentSearchResult) -> DocumentFragmentSearchResponse:
    return DocumentFragmentSearchResponse(
        document_id=result.document_id,
        fragment_id=result.fragment_id,
        text=result.text,
        page_ref=result.page_ref,
        crop_tags=result.crop_tags,
        score=result.score,
    )
