"""HTTP LLM drafting adapter for Recommendation infrastructure."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib import error, request

from via.bounded_contexts.recommendation.application.ports import IRecommendationDraftingProvider, RecommendationDraftContext

MIN_GEMINI_DRAFT_CHARS = 120
GEMINI_REQUIRED_SECTIONS = (
    "resumen ejecutivo",
    "justificacion de viabilidad",
    "brechas y factores limitantes",
    "acciones recomendadas",
    "advertencias",
)
GEMINI_FORBIDDEN_OUTPUT_PHRASES = (
    "i should",
    "the prompt says",
    "ensure",
    "do not calculate",
    "based on provided data",
    "as an ai",
    "the instructions",
    "instruction",
    "prompt",
)


class LlmDraftingError(RuntimeError):
    """Raised when the LLM drafting adapter cannot return valid text."""


@dataclass(frozen=True)
class LocalHttpLlmConfig:
    """Configuration for a local HTTP LLM server."""

    endpoint: str
    model: str
    timeout_seconds: int
    max_prompt_chars: int


@dataclass(frozen=True)
class VertexGemmaConfig:
    """Configuration for a Vertex AI Gemma endpoint."""

    project_id: str
    location: str
    endpoint_id: str
    model: str
    timeout_seconds: int
    max_prompt_chars: int


@dataclass(frozen=True)
class GeminiApiConfig:
    """Configuration for the Gemini REST generateContent API."""

    api_key: str
    model: str
    base_url: str
    timeout_seconds: int
    max_prompt_chars: int
    max_output_tokens: int


HttpPost = Callable[[str, dict[str, Any], int], dict[str, Any]]
GeminiPost = Callable[[str, dict[str, Any], int, str], dict[str, Any]]


class VertexGemmaClient(Protocol):
    """Client protocol used to invoke Vertex AI endpoints."""

    def predict(self, endpoint_path: str, instances: list[dict[str, Any]], parameters: dict[str, Any], timeout: int) -> Any:
        """Return a Vertex prediction response."""


class LocalHttpLlmDraftingProvider(IRecommendationDraftingProvider):
    """Draft recommendations through a local HTTP LLM compatible with Gemma-style servers."""

    def __init__(self, config: LocalHttpLlmConfig, http_post: HttpPost | None = None) -> None:
        """Create the adapter with injectable HTTP transport for tests."""

        self._config = config
        self._http_post = http_post or _urllib_post_json

    def draft(self, context: RecommendationDraftContext) -> str:
        """Send precomputed evaluation context to the LLM and return drafted text."""

        prompt = build_recommendation_prompt(context)
        if len(prompt) > self._config.max_prompt_chars:
            raise LlmDraftingError("LLM prompt exceeds configured maximum length")

        response = self._http_post(
            self._config.endpoint,
            {
                "model": self._config.model,
                "prompt": prompt,
                "stream": False,
            },
            self._config.timeout_seconds,
        )
        text = _extract_text(response)
        if not text.strip():
            raise LlmDraftingError("LLM response text is empty")
        return text.strip()


class VertexGemmaDraftingProvider(IRecommendationDraftingProvider):
    """Draft recommendations through a configured Vertex AI Gemma endpoint."""

    def __init__(self, config: VertexGemmaConfig, client: VertexGemmaClient | None = None) -> None:
        """Create the adapter with an injectable Vertex client for tests."""

        self._config = config
        self._client = client

    def draft(self, context: RecommendationDraftContext) -> str:
        """Invoke Vertex AI with a prompt built from precomputed recommendation context."""

        prompt = build_recommendation_prompt(context)
        if len(prompt) > self._config.max_prompt_chars:
            raise LlmDraftingError("LLM prompt exceeds configured maximum length")

        endpoint_path = _vertex_endpoint_path(self._config)
        instances = [
            {
                "prompt": prompt,
                "model": self._config.model,
            }
        ]
        parameters = {"temperature": 0.2, "maxOutputTokens": 1024}
        try:
            client = self._client or _create_vertex_prediction_client(self._config.location)
            response = client.predict(
                endpoint_path,
                instances,
                parameters,
                self._config.timeout_seconds,
            )
        except Exception as exc:
            raise LlmDraftingError(f"Vertex Gemma prediction failed: {exc.__class__.__name__}") from exc

        text = _extract_text(_response_to_mapping(response))
        if not text.strip():
            raise LlmDraftingError("Vertex Gemma response text is empty")
        return text.strip()


class GeminiApiDraftingProvider(IRecommendationDraftingProvider):
    """Draft recommendations through Gemini API generateContent."""

    def __init__(self, config: GeminiApiConfig, http_post: GeminiPost | None = None) -> None:
        """Create the adapter with injectable HTTP transport for tests."""

        self._config = config
        self._http_post = http_post or _urllib_post_json_with_api_key

    def draft(self, context: RecommendationDraftContext) -> str:
        """Send precomputed recommendation context to Gemini and return drafted text."""

        prompt = _build_gemini_recommendation_prompt(context)
        if len(prompt) > self._config.max_prompt_chars:
            raise LlmDraftingError("LLM prompt exceeds configured maximum length")

        endpoint = _gemini_generate_content_endpoint(self._config)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": self._config.max_output_tokens,
            },
        }
        try:
            response = self._http_post(
                endpoint,
                payload,
                self._config.timeout_seconds,
                self._config.api_key,
            )
        except LlmDraftingError:
            raise
        except Exception as exc:
            raise LlmDraftingError(f"Gemini API request failed: {exc.__class__.__name__}") from exc

        text = _extract_gemini_text(response).strip()
        _validate_gemini_recommendation_text(text)
        return text


def build_recommendation_prompt(context: RecommendationDraftContext) -> str:
    """Build a prompt that asks only for prose over already-computed data."""

    result = context.crop_result
    gaps = "\n".join(
        (
            f"- criterio={gap.criterion_id}; fase={gap.phase_id}; periodo={gap.most_limiting_period}; "
            f"observado={gap.observed_value}; optimo={gap.optimal_limit}; brecha={gap.gap_value}"
        )
        for gap in result.gaps
    ) or "- Sin brechas agronomicas calculadas."
    limiting_factors = "\n".join(
        (
            f"- criterio={factor.criterion_id}; fase={factor.phase_id}; politica={factor.policy}; "
            f"penalty_factor={factor.penalty_factor}; observado={factor.observed_value}; "
            f"optimo={factor.optimal_limit}; membership={factor.membership}; fuente={factor.doc_source}"
        )
        for factor in result.limiting_factors
    ) or "- Sin factores limitantes calculados."
    evidence = "\n".join(
        (
            f"- fragment_id={item.fragment_id}; document_id={item.document_id}; pagina={item.page_ref}; "
            f"score={item.score}; cultivos={','.join(item.crop_tags)}; texto={item.text}"
        )
        for item in context.evidence
    ) or "- No se encontro evidencia documental suficiente."

    return (
        "Redacta una recomendacion agricola sustentada en espanol.\n"
        "Usa exclusivamente los datos calculados y la evidencia listada. "
        "No calcules score, pesos, membresias, brechas, ranking, categoria ni decisiones nuevas.\n\n"
        "Estructura la respuesta con: 1) Resumen ejecutivo, 2) Justificacion con score, categoria y ranking "
        "ya calculados, 3) Brechas y factores limitantes, 4) Acciones recomendadas sustentadas en evidencia, "
        "5) Advertencias sobre evidencia insuficiente si corresponde.\n\n"
        f"evaluation_id: {context.evaluation_id}\n"
        f"crop_id: {result.crop_id}\n"
        f"score_calculado: {result.score}\n"
        f"rank_position_calculado: {result.rank_position}\n"
        f"calc_condition: {result.calc_condition}\n"
        f"viability_category_calculada: {result.viability_category}\n\n"
        "Brechas agronomicas ya calculadas:\n"
        f"{gaps}\n\n"
        "Factores limitantes ya calculados:\n"
        f"{limiting_factors}\n\n"
        "Evidencia documental recuperada:\n"
        f"{evidence}\n"
    )


def _build_gemini_recommendation_prompt(context: RecommendationDraftContext) -> str:
    return (
        build_recommendation_prompt(context)
        + "\n\nContrato de salida para Gemini:\n"
        + "- Responde solo con la recomendacion final, en espanol.\n"
        + "- No repitas estas instrucciones, el prompt, datos crudos ni metacomentarios del proceso.\n"
        + "- No uses ingles salvo nombres tecnicos inevitables.\n"
        + "- No inventes ni recalcules score, ranking, categoria, brechas, pesos o membresias.\n"
        + "- Mantente en los valores calculados y la evidencia recuperada.\n"
        + "- Usa exactamente estas secciones con esos titulos:\n"
        + "1. Resumen ejecutivo\n"
        + "2. Justificacion de viabilidad\n"
        + "3. Brechas y factores limitantes\n"
        + "4. Acciones recomendadas\n"
        + "5. Advertencias o limites de evidencia\n"
    )


def _extract_text(response: dict[str, Any]) -> str:
    for key in ("response", "text", "content"):
        value = response.get(key)
        if isinstance(value, str):
            return value
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            text = first.get("text")
            if isinstance(text, str):
                return text
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
    raise LlmDraftingError("LLM response does not contain text")


def _response_to_mapping(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    predictions = getattr(response, "predictions", None)
    if isinstance(predictions, list) and predictions:
        first = predictions[0]
        if isinstance(first, dict):
            return first
        if hasattr(first, "__iter__") and not isinstance(first, (str, bytes)):
            try:
                return dict(first)
            except (TypeError, ValueError):
                pass
    raise LlmDraftingError("Vertex Gemma response does not contain predictions")


def _extract_gemini_text(response: dict[str, Any]) -> str:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise LlmDraftingError("Gemini API response does not contain candidates")
    first = candidates[0]
    if not isinstance(first, dict):
        raise LlmDraftingError("Gemini API candidate must be an object")
    content = first.get("content")
    if not isinstance(content, dict):
        raise LlmDraftingError("Gemini API candidate does not contain content")
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise LlmDraftingError("Gemini API content does not contain parts")
    first_part = parts[0]
    if not isinstance(first_part, dict) or not isinstance(first_part.get("text"), str):
        raise LlmDraftingError("Gemini API response does not contain text")
    return first_part["text"]


def _validate_gemini_recommendation_text(text: str) -> None:
    normalized = text.strip()
    if not normalized:
        raise LlmDraftingError("Gemini API response text is empty")
    if len(normalized) < MIN_GEMINI_DRAFT_CHARS:
        raise LlmDraftingError("Gemini API response text is too short")
    lower = _normalize_for_contract(normalized)
    for phrase in GEMINI_FORBIDDEN_OUTPUT_PHRASES:
        if phrase in lower:
            raise LlmDraftingError("Gemini API response contains prompt instructions or metacommentary")
    missing_sections = [section for section in GEMINI_REQUIRED_SECTIONS if section not in lower]
    if missing_sections:
        raise LlmDraftingError("Gemini API response does not satisfy the recommendation section contract")
    if "score" not in lower or "brecha" not in lower:
        raise LlmDraftingError("Gemini API response must mention score and brecha")


def _vertex_endpoint_path(config: VertexGemmaConfig) -> str:
    return (
        f"projects/{config.project_id}/locations/{config.location}/"
        f"endpoints/{config.endpoint_id}"
    )


def _create_vertex_prediction_client(location: str) -> VertexGemmaClient:
    try:
        from google.cloud import aiplatform_v1
    except ImportError as exc:
        raise LlmDraftingError("google-cloud-aiplatform is required for vertex_gemma") from exc
    client_options = {"api_endpoint": f"{location}-aiplatform.googleapis.com"}
    return aiplatform_v1.PredictionServiceClient(client_options=client_options)


def _gemini_generate_content_endpoint(config: GeminiApiConfig) -> str:
    return f"{config.base_url.rstrip('/')}/models/{config.model}:generateContent"


def _urllib_post_json(endpoint: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except error.URLError as exc:
        raise LlmDraftingError(f"LLM HTTP request failed: {exc}") from exc
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LlmDraftingError("LLM HTTP response is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise LlmDraftingError("LLM HTTP response must be a JSON object")
    return decoded


def _urllib_post_json_with_api_key(
    endpoint: str,
    payload: dict[str, Any],
    timeout_seconds: int,
    api_key: str,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        raise LlmDraftingError(_format_gemini_http_error(exc, api_key)) from exc
    except error.URLError as exc:
        raise LlmDraftingError(f"Gemini API HTTP request failed: {exc.__class__.__name__}") from exc
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LlmDraftingError("Gemini API HTTP response is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise LlmDraftingError("Gemini API HTTP response must be a JSON object")
    return decoded


def _format_gemini_http_error(exc: error.HTTPError, api_key: str) -> str:
    raw_body = exc.read().decode("utf-8", errors="replace")
    status_code = getattr(exc, "code", None)
    reason = getattr(exc, "reason", None) or getattr(exc, "msg", "")
    details = _gemini_error_details(raw_body, api_key)
    status = details.get("status")
    message = details.get("message")

    parts = [f"HTTP {status_code}"]
    if status:
        parts.append(status)
    elif reason:
        parts.append(str(reason))
    if message:
        parts.append(message)
    return "Gemini API request failed: " + " - ".join(parts)


def _gemini_error_details(raw_body: str, api_key: str) -> dict[str, str]:
    try:
        decoded = json.loads(raw_body)
    except json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    error_payload = decoded.get("error")
    if not isinstance(error_payload, dict):
        return {}
    details: dict[str, str] = {}
    status = error_payload.get("status")
    message = error_payload.get("message")
    if isinstance(status, str):
        details["status"] = _sanitize_error_text(status, api_key)
    if isinstance(message, str):
        details["message"] = _sanitize_error_text(message, api_key)
    return details


def _sanitize_error_text(value: str, api_key: str) -> str:
    sanitized = value.replace("\r", " ").replace("\n", " ").strip()
    if api_key:
        sanitized = sanitized.replace(api_key, "[REDACTED]")
    return sanitized[:300]


def _normalize_for_contract(value: str) -> str:
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
    return without_accents.lower()
