"""Unit tests for the configurable Recommendation LLM adapter."""

from __future__ import annotations

import ast
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from via.bounded_contexts.recommendation.infrastructure import llm_adapter
from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    EvidenceData,
    GapData,
    LimitingFactorData,
    RecommendationDraftContext,
)
from via.bounded_contexts.recommendation.infrastructure.llm_adapter import (
    GeminiApiConfig,
    GeminiApiDraftingProvider,
    LlmDraftingError,
    LocalHttpLlmConfig,
    LocalHttpLlmDraftingProvider,
    VertexGemmaConfig,
    VertexGemmaDraftingProvider,
    build_recommendation_prompt,
)


ROOT = Path(__file__).resolve().parents[3]


def test_local_http_adapter_sends_prompt_with_precomputed_data_and_evidence() -> None:
    transport = RecordingTransport({"response": "Texto redactado desde datos precalculados."})
    provider = LocalHttpLlmDraftingProvider(_config(), http_post=transport.post)
    context = _context()

    text = provider.draft(context)

    assert text == "Texto redactado desde datos precalculados."
    assert transport.calls == 1
    assert transport.payload["model"] == "gemma:2b"
    assert "score_calculado: 0.82" in transport.payload["prompt"]
    assert "viability_category_calculada: VIABLE" in transport.payload["prompt"]
    assert "brecha=-4.0" in transport.payload["prompt"]
    assert "Manual tecnico cacao" in transport.payload["prompt"]
    assert transport.timeout_seconds == 7


def test_prompt_explicitly_forbids_llm_calculations() -> None:
    prompt = build_recommendation_prompt(_context())

    assert "No calcules score" in prompt
    assert "pesos" in prompt
    assert "membresias" in prompt
    assert "ranking" in prompt
    assert "Brechas agronomicas ya calculadas" in prompt


def test_adapter_does_not_calculate_score_ranking_or_gaps() -> None:
    source = (ROOT / "via" / "bounded_contexts" / "recommendation" / "infrastructure" / "llm_adapter.py").read_text(
        encoding="utf-8"
    )

    forbidden_terms = ["rank_crops", "calculate_score", "GapCalculation", "Fuzzification", "EntropyWeights"]
    assert not any(term in source for term in forbidden_terms)


def test_http_error_is_propagated_as_technical_error() -> None:
    def failing_post(endpoint, payload, timeout_seconds):
        raise LlmDraftingError("timeout")

    provider = LocalHttpLlmDraftingProvider(_config(), http_post=failing_post)

    with pytest.raises(LlmDraftingError, match="timeout"):
        provider.draft(_context())


@pytest.mark.parametrize("response", [{}, {"response": ""}, {"choices": []}, {"choices": [{"message": {}}]}])
def test_invalid_response_is_rejected(response: dict) -> None:
    provider = LocalHttpLlmDraftingProvider(_config(), http_post=lambda endpoint, payload, timeout: response)

    with pytest.raises(LlmDraftingError):
        provider.draft(_context())


def test_prompt_size_limit_is_enforced_before_http_call() -> None:
    transport = RecordingTransport({"response": "no deberia llamarse"})
    provider = LocalHttpLlmDraftingProvider(
        LocalHttpLlmConfig(
            endpoint="http://localhost:11434/api/generate",
            model="gemma:2b",
            timeout_seconds=7,
            max_prompt_chars=10,
        ),
        http_post=transport.post,
    )

    with pytest.raises(LlmDraftingError, match="exceeds"):
        provider.draft(_context())

    assert transport.calls == 0


def test_vertex_gemma_builds_request_with_endpoint_and_prompt() -> None:
    client = RecordingVertexClient({"response": "Texto Vertex redactado."})
    provider = VertexGemmaDraftingProvider(_vertex_config(), client=client)

    text = provider.draft(_context())

    assert text == "Texto Vertex redactado."
    assert client.calls == 1
    assert client.endpoint_path == "projects/via-project/locations/us-central1/endpoints/123456789"
    assert client.instances[0]["model"] == "gemma-2-9b-it"
    assert "score_calculado: 0.82" in client.instances[0]["prompt"]
    assert "brecha=-4.0" in client.instances[0]["prompt"]
    assert client.parameters == {"temperature": 0.2, "maxOutputTokens": 1024}
    assert client.timeout == 11


def test_vertex_gemma_accepts_prediction_response_object() -> None:
    class Response:
        predictions = [{"content": "Texto desde predictions."}]

    provider = VertexGemmaDraftingProvider(_vertex_config(), client=RecordingVertexClient(Response()))

    assert provider.draft(_context()) == "Texto desde predictions."


@pytest.mark.parametrize("response", [{}, {"predictions": []}, {"predictions": [{"unknown": "x"}]}])
def test_vertex_gemma_invalid_response_is_rejected(response: dict) -> None:
    provider = VertexGemmaDraftingProvider(_vertex_config(), client=RecordingVertexClient(response))

    with pytest.raises(LlmDraftingError):
        provider.draft(_context())


def test_vertex_gemma_technical_error_is_propagated_without_credentials() -> None:
    provider = VertexGemmaDraftingProvider(
        _vertex_config(),
        client=FailingVertexClient("service-account-json-secret"),
    )

    with pytest.raises(LlmDraftingError) as exc_info:
        provider.draft(_context())

    assert "RuntimeError" in str(exc_info.value)
    assert "service-account-json-secret" not in str(exc_info.value)


def test_gemini_api_builds_generate_content_request_with_key_and_prompt() -> None:
    draft = _valid_gemini_draft()
    transport = RecordingGeminiTransport(
        {"candidates": [{"content": {"parts": [{"text": draft}]}}]}
    )
    provider = GeminiApiDraftingProvider(_gemini_config(), http_post=transport.post)

    text = provider.draft(_context())

    assert text == draft
    assert transport.calls == 1
    assert transport.endpoint == "https://generativelanguage.googleapis.com/v1beta/models/gemma-3-27b-it:generateContent"
    assert transport.api_key == "gemini-secret"
    prompt = transport.payload["contents"][0]["parts"][0]["text"]
    assert prompt.startswith("Redacta una recomendacion agricola")
    assert "Responde solo con la recomendacion final, en espanol" in prompt
    assert "No repitas estas instrucciones" in prompt
    assert "score_calculado: 0.82" in prompt
    assert "brecha=-4.0" in prompt
    assert transport.payload["generationConfig"] == {"temperature": 0.2, "maxOutputTokens": 1800}
    assert transport.timeout_seconds == 13


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"candidates": []},
        {"candidates": [{}]},
        {"candidates": [{"content": {"parts": []}}]},
        {"candidates": [{"content": {"parts": [{"text": ""}]}}]},
        {"candidates": [{"content": {"parts": [{"text": "Muy corto"}]}}]},
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    "Resumen ejecutivo: El prompt says que debo responder. "
                                    "Justificacion de viabilidad: I should ensure que no calcule. "
                                    "Brechas y factores limitantes: score 0.82 y brecha -4. "
                                    "Acciones recomendadas: ejecutar acciones. "
                                    "Advertencias: texto con metacomentario."
                                )
                            }
                        ]
                    }
                }
            ]
        },
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    "Resumen ejecutivo: score 0.82. "
                                    "Justificacion de viabilidad: cultivo viable. "
                                    "Brechas y factores limitantes: brecha hidrica. "
                                    "Acciones recomendadas: manejar cobertura."
                                )
                            }
                        ]
                    }
                }
            ]
        },
    ],
)
def test_gemini_api_invalid_response_is_rejected(response: dict) -> None:
    provider = GeminiApiDraftingProvider(_gemini_config(), http_post=RecordingGeminiTransport(response).post)

    with pytest.raises(LlmDraftingError):
        provider.draft(_context())


def test_gemini_api_technical_error_is_propagated_without_api_key() -> None:
    provider = GeminiApiDraftingProvider(
        _gemini_config(),
        http_post=FailingGeminiTransport("gemini-secret").post,
    )

    with pytest.raises(LlmDraftingError) as exc_info:
        provider.draft(_context())

    assert "RuntimeError" in str(exc_info.value)
    assert "gemini-secret" not in str(exc_info.value)


def test_gemini_api_http_503_reports_sanitized_status_and_message(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b'{"error":{"status":"UNAVAILABLE","message":"This model is currently experiencing high demand."}}'
    http_error = HTTPError(
        url="https://generativelanguage.googleapis.com/v1beta/models/gemma:generateContent",
        code=503,
        msg="Service Unavailable",
        hdrs={},
        fp=BytesIO(body),
    )
    monkeypatch.setattr(llm_adapter.request, "urlopen", lambda req, timeout: (_raise(http_error)))
    provider = GeminiApiDraftingProvider(_gemini_config())

    with pytest.raises(LlmDraftingError) as exc_info:
        provider.draft(_context())

    message = str(exc_info.value)
    assert message == (
        "Gemini API request failed: HTTP 503 - UNAVAILABLE - "
        "This model is currently experiencing high demand."
    )
    assert "gemini-secret" not in message


@pytest.mark.parametrize("status_code", [401, 403])
def test_gemini_api_auth_http_error_does_not_expose_api_key(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    body = b'{"error":{"status":"PERMISSION_DENIED","message":"key gemini-secret is not allowed"}}'
    http_error = HTTPError(
        url="https://generativelanguage.googleapis.com/v1beta/models/gemma:generateContent",
        code=status_code,
        msg="Forbidden",
        hdrs={},
        fp=BytesIO(body),
    )
    monkeypatch.setattr(llm_adapter.request, "urlopen", lambda req, timeout: (_raise(http_error)))
    provider = GeminiApiDraftingProvider(_gemini_config())

    with pytest.raises(LlmDraftingError) as exc_info:
        provider.draft(_context())

    message = str(exc_info.value)
    assert f"HTTP {status_code}" in message
    assert "PERMISSION_DENIED" in message
    assert "gemini-secret" not in message
    assert "[REDACTED]" in message


def test_gemini_api_invalid_json_response_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_adapter.request, "urlopen", lambda req, timeout: FakeHttpResponse(b"not-json"))
    provider = GeminiApiDraftingProvider(_gemini_config())

    with pytest.raises(LlmDraftingError, match="not valid JSON"):
        provider.draft(_context())


def test_gemini_api_prompt_size_limit_is_enforced_before_http_call() -> None:
    transport = RecordingGeminiTransport({"candidates": [{"content": {"parts": [{"text": "no"}]}}]})
    provider = GeminiApiDraftingProvider(
        GeminiApiConfig(
            api_key="gemini-secret",
            model="gemma-3-27b-it",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            timeout_seconds=13,
            max_prompt_chars=10,
            max_output_tokens=1800,
        ),
        http_post=transport.post,
    )

    with pytest.raises(LlmDraftingError, match="exceeds"):
        provider.draft(_context())

    assert transport.calls == 0


def test_recommendation_domain_does_not_import_http_or_infrastructure() -> None:
    domain = ROOT / "via" / "bounded_contexts" / "recommendation" / "domain"
    forbidden = {"urllib", "requests", "httpx", "sqlalchemy", "fastapi"}
    offenders: list[str] = []
    for path in domain.rglob("*.py"):
        imports = _imports_from(path)
        for imported in imports:
            if any(imported == item or imported.startswith(item + ".") for item in forbidden):
                offenders.append(f"{path.name}: {imported}")

    assert offenders == []


class RecordingTransport:
    """HTTP transport fake that records one request and never calls the network."""

    def __init__(self, response: dict) -> None:
        """Create a fake transport with a prepared response."""

        self.response = response
        self.calls = 0
        self.endpoint: str | None = None
        self.payload: dict | None = None
        self.timeout_seconds: int | None = None

    def post(self, endpoint: str, payload: dict, timeout_seconds: int) -> dict:
        """Record HTTP request data and return a fake response."""

        self.calls += 1
        self.endpoint = endpoint
        self.payload = payload
        self.timeout_seconds = timeout_seconds
        return self.response


class RecordingVertexClient:
    """Vertex client fake that records predict requests without Google Cloud calls."""

    def __init__(self, response) -> None:
        """Create a fake Vertex client with a prepared response."""

        self.response = response
        self.calls = 0
        self.endpoint_path = None
        self.instances = None
        self.parameters = None
        self.timeout = None

    def predict(self, endpoint_path: str, instances: list[dict], parameters: dict, timeout: int):
        """Record request data and return the fake response."""

        self.calls += 1
        self.endpoint_path = endpoint_path
        self.instances = instances
        self.parameters = parameters
        self.timeout = timeout
        return self.response


class FailingVertexClient:
    """Vertex client fake that raises a technical error."""

    def __init__(self, secret: str) -> None:
        """Create the fake with a secret that must not be leaked."""

        self.secret = secret

    def predict(self, endpoint_path: str, instances: list[dict], parameters: dict, timeout: int):
        """Raise a deterministic technical failure."""

        raise RuntimeError(self.secret)


class RecordingGeminiTransport:
    """Gemini HTTP transport fake that records one request without network calls."""

    def __init__(self, response: dict) -> None:
        """Create a fake Gemini transport with a prepared response."""

        self.response = response
        self.calls = 0
        self.endpoint: str | None = None
        self.payload: dict | None = None
        self.timeout_seconds: int | None = None
        self.api_key: str | None = None

    def post(self, endpoint: str, payload: dict, timeout_seconds: int, api_key: str) -> dict:
        """Record Gemini request data and return the fake response."""

        self.calls += 1
        self.endpoint = endpoint
        self.payload = payload
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key
        return self.response


class FailingGeminiTransport:
    """Gemini HTTP transport fake that raises a technical error."""

    def __init__(self, secret: str) -> None:
        """Create the fake with a secret that must not be leaked."""

        self.secret = secret

    def post(self, endpoint: str, payload: dict, timeout_seconds: int, api_key: str) -> dict:
        """Raise a deterministic technical failure."""

        raise RuntimeError(self.secret)


class FakeHttpResponse:
    """Context-manager fake for urllib responses."""

    def __init__(self, body: bytes) -> None:
        """Create the fake HTTP response."""

        self._body = body

    def __enter__(self) -> FakeHttpResponse:
        """Enter the response context manager."""

        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        """Exit the response context manager."""

    def read(self) -> bytes:
        """Return the fake response body."""

        return self._body


def _config() -> LocalHttpLlmConfig:
    return LocalHttpLlmConfig(
        endpoint="http://localhost:11434/api/generate",
        model="gemma:2b",
        timeout_seconds=7,
        max_prompt_chars=12000,
    )


def _vertex_config() -> VertexGemmaConfig:
    return VertexGemmaConfig(
        project_id="via-project",
        location="us-central1",
        endpoint_id="123456789",
        model="gemma-2-9b-it",
        timeout_seconds=11,
        max_prompt_chars=12000,
    )


def _gemini_config() -> GeminiApiConfig:
    return GeminiApiConfig(
        api_key="gemini-secret",
        model="gemma-3-27b-it",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds=13,
        max_prompt_chars=12000,
        max_output_tokens=1800,
    )


def _valid_gemini_draft() -> str:
    return (
        "Resumen ejecutivo: El cacao mantiene una condicion VIABLE con score 0.82 y ranking 1. "
        "La recomendacion se enfoca en sostener la aptitud calculada y reducir riesgos de manejo. "
        "Justificacion de viabilidad: El resultado ya calculado indica categoria VIABLE, con condicion DEFINITIVO, "
        "por lo que el texto conserva esos valores sin recalcularlos. "
        "Brechas y factores limitantes: La brecha principal es hidrica en floracion, con brecha -4.0, "
        "y se reporta temperatura como factor limitante penalizable. "
        "Acciones recomendadas: Priorizar cobertura, monitoreo de humedad, riego suplementario si esta disponible "
        "y sombra temporal para reducir estres termico. "
        "Advertencias o limites de evidencia: La recomendacion depende de la evidencia documental recuperada y de "
        "los resultados calculados disponibles."
    )


def _raise(exc: Exception):
    raise exc


def _context() -> RecommendationDraftContext:
    return RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="cacao",
            score=0.82,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="VIABLE",
            gaps=[
                GapData(
                    criterion_id="agua",
                    phase_id="floracion",
                    most_limiting_period="p2",
                    observed_value=18.0,
                    optimal_limit=22.0,
                    gap_value=-4.0,
                )
            ],
            limiting_factors=[
                LimitingFactorData(
                    criterion_id="temperatura",
                    phase_id="establecimiento",
                    policy="PENALIZE",
                    penalty_factor=0.5,
                    observed_value=35.0,
                    optimal_limit=30.0,
                    membership=0.0,
                    doc_source="Manual cacao",
                )
            ],
        ),
        evidence=[
            EvidenceData(
                fragment_id=uuid4(),
                document_id=uuid4(),
                text="Manual tecnico cacao",
                crop_tags=["cacao"],
                page_ref=3,
                score=0.91,
            )
        ],
    )


def _imports_from(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
