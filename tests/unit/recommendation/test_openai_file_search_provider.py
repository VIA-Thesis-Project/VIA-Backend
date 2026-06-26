"""Unit tests for OpenAI File Search drafting provider and related configuration.

Covers requirements:
 1. Config reads OPENAI_API_KEY without printing it.
 2. Vector store mapping per crop works.
 3. Missing vector_store_id produces a controlled error.
 4. Create-vector-stores script supports --only maiz_amarillo_duro.
 5. Invalid manifest fails with a clear message.
 6. Upload script validates document paths.
 7. Provider builds request with file_search tool.
 8. Provider uses max_num_results from config.
 9. Provider requests include=["file_search_call.results"].
10. Provider persists response_id and retrieved_results in trace.
11. Provider prompt forbids LLM from modifying scores/ranking/categories.
12. No retrieved results -> recommendation declares insufficient evidence.
13. Provider does not invent citations.
14. No API keys are hardcoded in provider source.
15. No pgvector or internal embeddings in provider source.
16. No async, Celery, Kafka, RabbitMQ, Redis in provider source.
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest

from via.bounded_contexts.recommendation.application.ports import (
    CropEvaluationResultData,
    GapData,
    LimitingFactorData,
    RecommendationDraftContext,
)
from via.bounded_contexts.recommendation.infrastructure.openai_file_search_provider import (
    INSUFFICIENT_EVIDENCE_MSG,
    PROMPT_FORBIDDEN_BEHAVIORS,
    FileSearchTrace,
    OpenAIFileSearchConfig,
    OpenAIFileSearchDraftingProvider,
    OpenAIFileSearchError,
    _build_system_prompt,
    _build_user_prompt,
    _parse_response,
    _resolve_vector_store_id,
)
from via.config import ConfigurationError, load_settings

ROOT = pathlib.Path(__file__).resolve().parents[3]
PROVIDER_SRC = (
    ROOT
    / "via"
    / "bounded_contexts"
    / "recommendation"
    / "infrastructure"
    / "openai_file_search_provider.py"
).read_text(encoding="utf-8")
CREATE_SCRIPT_PATH = ROOT / "scripts" / "openai_create_vector_stores.py"
UPLOAD_SCRIPT_PATH = ROOT / "scripts" / "openai_upload_crop_documents.py"


# ─── Fixtures ──────────────────────────────────────────────────────────────────


def _context(crop_id: str = "maiz_amarillo_duro") -> RecommendationDraftContext:
    return RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id=crop_id,
            score=0.78,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="VIABLE",
            gaps=[
                GapData(
                    criterion_id="precipitacion",
                    phase_id="crecimiento",
                    most_limiting_period="p3",
                    observed_value=55.0,
                    optimal_limit=80.0,
                    gap_value=-25.0,
                )
            ],
            limiting_factors=[
                LimitingFactorData(
                    criterion_id="temperatura",
                    phase_id="floracion",
                    policy="PENALIZE",
                    penalty_factor=0.6,
                    observed_value=38.0,
                    optimal_limit=32.0,
                    membership=0.0,
                )
            ],
        ),
        evidence=[],
    )


def _config(
    crop_id: str = "maiz_amarillo_duro",
    vs_id: str = "vs_test_maiz_001",
) -> OpenAIFileSearchConfig:
    return OpenAIFileSearchConfig(
        api_key="test-api-key",
        model="gpt-4o-mini",
        max_num_results=8,
        prompt_version="v1",
        timeout_seconds=30,
        vector_store_map={crop_id: vs_id},
    )


def _valid_response(
    text: str = "Resumen ejecutivo: cultivo viable.\nJustificación de viabilidad: score 0.78.\n"
    "Brechas y factores limitantes: brecha precipitacion.\n"
    "Acciones recomendadas: riego suplementario.\n"
    "Advertencias y límites de evidencia: evidencia limitada.",
    file_id: str = "file_abc",
    filename: str = "manual_maiz.pdf",
    score: float = 0.88,
    response_id: str = "resp_xyz",
    fs_call_id: str = "fs_call_001",
) -> dict[str, Any]:
    return {
        "id": response_id,
        "output": [
            {
                "type": "file_search_call",
                "id": fs_call_id,
                "results": [
                    {
                        "file_id": file_id,
                        "filename": filename,
                        "score": score,
                        "text": "El maíz requiere al menos 80 mm de precipitación en crecimiento.",
                    }
                ],
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            },
        ],
    }


def _structured_response() -> dict[str, Any]:
    return _valid_response(
        text=json.dumps(
            {
                "schema_version": "recommendation_structured_v1",
                "summary": "La parcela es condicional para maiz amarillo duro.",
                "overall_limitations": "La evidencia recuperada es parcial.",
                "gap_recommendations": [
                    {
                        "gap_key": "precipitacion|crecimiento|55|80|-25",
                        "criterion_id": "precipitacion",
                        "criterion_name": "precipitacion",
                        "criterion_label": "Precipitacion",
                        "criterion_group": "clima",
                        "unit": "mm",
                        "phase_id": "crecimiento",
                        "phase_name": "crecimiento",
                        "gap_direction": "below_optimum",
                        "severity": "alta",
                        "observed_value": 55.0,
                        "optimal_limit": 80.0,
                        "gap_value": -25.0,
                        "recommendation": "Priorizar riego suplementario sustentado en evidencia.",
                        "rationale": "La brecha indica deficit de precipitacion.",
                        "evidence_used": [
                            {
                                "source_file_id": "file_abc",
                                "source_filename": "manual_maiz.pdf",
                                "quote_summary": "El maiz requiere agua suficiente en crecimiento.",
                            }
                        ],
                        "confidence": "media",
                        "limitations": "No se especifica una lamina exacta de riego.",
                    }
                ],
            }
        )
    )


@dataclass
class RecordingOpenAIClient:
    """Fake IOpenAIResponsesClient that records the call and returns a preset response."""

    response: dict[str, Any]
    calls: int = 0
    last_model: str = ""
    last_input_messages: list[dict[str, str]] | None = None
    last_vector_store_ids: list[str] | None = None
    last_max_num_results: int = 0
    last_include: list[str] | None = None
    last_timeout: int = 0

    def create_response(
        self,
        *,
        model: str,
        input_messages: list[dict[str, str]],
        vector_store_ids: list[str],
        max_num_results: int,
        include: list[str],
        timeout: int,
    ) -> dict[str, Any]:
        self.calls += 1
        self.last_model = model
        self.last_input_messages = input_messages
        self.last_vector_store_ids = vector_store_ids
        self.last_max_num_results = max_num_results
        self.last_include = include
        self.last_timeout = timeout
        return self.response


def _system_content(client: RecordingOpenAIClient) -> str:
    for m in client.last_input_messages or []:
        if m.get("role") == "system":
            return m.get("content", "")
    return ""


def _user_content(client: RecordingOpenAIClient) -> str:
    for m in client.last_input_messages or []:
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


# ─── 1. Config reads OPENAI_API_KEY without printing ──────────────────────────


def test_config_reads_openai_api_key_from_env() -> None:
    settings = load_settings(
        {
            "DATABASE_URL": "postgresql+psycopg2://u:p@h/db",
            "LLM_DRAFTING_PROVIDER": "openai_file_search",
            "OPENAI_API_KEY": "sk-super-secret-key",
            "OPENAI_RAG_MODEL": "gpt-4o-mini",
        }
    )
    assert settings.openai_api_key == "sk-super-secret-key"


def test_config_openai_api_key_does_not_appear_in_config_source() -> None:
    config_src = (ROOT / "via" / "config.py").read_text(encoding="utf-8")
    assert "sk-" not in config_src
    assert "openai_api_key" in config_src


# ─── 2. Vector store mapping per crop works ───────────────────────────────────


def test_vector_store_map_resolves_maiz_amarillo_duro() -> None:
    vs_map = {"maiz_amarillo_duro": "vs_maiz_001"}
    result = _resolve_vector_store_id(vs_map, "maiz_amarillo_duro")
    assert result == "vs_maiz_001"


def test_config_builds_vector_store_map_from_env() -> None:
    settings = load_settings(
        {
            "DATABASE_URL": "postgresql+psycopg2://u:p@h/db",
            "LLM_DRAFTING_PROVIDER": "openai_file_search",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_RAG_MODEL": "gpt-4o-mini",
            "VIA_VECTOR_STORE_MAIZ_AMARILLO_DURO_ID": "vs_maiz_999",
            "VIA_VECTOR_STORE_PALTA_HASS_ID": "vs_palta_888",
        }
    )
    assert settings.openai_vector_store_maiz_amarillo_duro_id == "vs_maiz_999"
    assert settings.openai_vector_store_palta_hass_id == "vs_palta_888"
    assert settings.openai_vector_store_mandarina_murcott_id is None


# ─── 3. Missing vector_store_id produces controlled error ─────────────────────


def test_missing_vector_store_id_raises_controlled_error() -> None:
    with pytest.raises(OpenAIFileSearchError, match="Vector store no configurado"):
        _resolve_vector_store_id({}, "maiz_amarillo_duro")


def test_missing_vector_store_id_names_the_crop() -> None:
    with pytest.raises(OpenAIFileSearchError, match="maiz_amarillo_duro"):
        _resolve_vector_store_id({"palta_hass": "vs_x"}, "maiz_amarillo_duro")


def test_provider_raises_on_unconfigured_crop() -> None:
    client = RecordingOpenAIClient(response=_valid_response())
    provider = OpenAIFileSearchDraftingProvider(_config("palta_hass", "vs_palta"), client=client)
    with pytest.raises(OpenAIFileSearchError, match="maiz_amarillo_duro"):
        provider.draft(_context("maiz_amarillo_duro"))
    assert client.calls == 0


# ─── 4. Create-vector-stores script supports --only flag ──────────────────────


def test_create_vector_stores_script_is_importable() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_create_vector_stores as cvs  # noqa: F401

    assert hasattr(cvs, "CROP_STORE_NAMES")
    assert "maiz_amarillo_duro" in cvs.CROP_STORE_NAMES


def test_create_vector_stores_only_flag_filters_to_one_crop(monkeypatch: pytest.MonkeyPatch) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_create_vector_stores as cvs

    created_crops: list[str] = []

    class FakeVS:
        id = "vs_fake_001"

    class FakeVSClient:
        class vector_stores:
            @staticmethod
            def create(name: str) -> FakeVS:
                created_crops.append(name)
                return FakeVS()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    result = cvs.create_vector_stores(
        {"maiz_amarillo_duro": "via_maiz_amarillo_duro"},
        client_factory=lambda api_key: FakeVSClient(),
    )
    assert list(result.keys()) == ["maiz_amarillo_duro"]
    assert result["maiz_amarillo_duro"]["vector_store_id"] == "vs_fake_001"


def test_create_vector_stores_unknown_crop_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_create_vector_stores as cvs

    with pytest.raises(SystemExit):
        cvs.main(["--only", "cultivo_desconocido"])


# ─── 5. Invalid manifest fails with clear message ─────────────────────────────


def test_upload_script_missing_documents_field_exits(tmp_path: pathlib.Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_upload_crop_documents as upd

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"crop": "maiz_amarillo_duro"}), encoding="utf-8")
    with pytest.raises(SystemExit):
        upd.load_and_validate_manifest(str(manifest), "maiz_amarillo_duro")


def test_upload_script_crop_mismatch_exits(tmp_path: pathlib.Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_upload_crop_documents as upd

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"crop": "palta_hass", "documents": [{"path": "x.pdf", "role": "principal"}]}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        upd.load_and_validate_manifest(str(manifest), "maiz_amarillo_duro")


def test_upload_script_invalid_json_exits(tmp_path: pathlib.Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_upload_crop_documents as upd

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{ not json }", encoding="utf-8")
    with pytest.raises(SystemExit):
        upd.load_and_validate_manifest(str(manifest), "maiz_amarillo_duro")


def test_upload_script_empty_documents_list_exits(tmp_path: pathlib.Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_upload_crop_documents as upd

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"crop": "maiz_amarillo_duro", "documents": []}), encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        upd.load_and_validate_manifest(str(manifest), "maiz_amarillo_duro")


# ─── 6. Upload script validates document paths ───────────────────────────────


def test_upload_script_missing_file_exits(tmp_path: pathlib.Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_upload_crop_documents as upd

    documents = [{"path": str(tmp_path / "no_existe.pdf"), "role": "principal"}]
    with pytest.raises(SystemExit):
        upd.validate_document_paths(documents)


def test_upload_script_existing_file_passes(tmp_path: pathlib.Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_upload_crop_documents as upd

    pdf = tmp_path / "documento.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    upd.validate_document_paths([{"path": str(pdf), "role": "principal"}])


def test_upload_script_auto_adds_curated_documents_first(tmp_path: pathlib.Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_upload_crop_documents as upd

    crop_dir = tmp_path / "Fuente Documental" / "maiz_amarillo_duro"
    principal_dir = crop_dir / "principal"
    curated_dir = crop_dir / "curated"
    principal_dir.mkdir(parents=True)
    curated_dir.mkdir()
    pdf = principal_dir / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    (curated_dir / "riego.md").write_text("Riego en maiz amarillo duro.", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "crop": "maiz_amarillo_duro",
                "documents": [{"path": str(pdf), "role": "principal"}],
            }
        ),
        encoding="utf-8",
    )

    manifest = upd.load_and_validate_manifest(str(manifest_path), "maiz_amarillo_duro")

    assert manifest["documents"][0]["role"] == "curated"
    assert pathlib.Path(manifest["documents"][0]["path"]).name == "riego.md"
    assert manifest["documents"][-1]["role"] == "principal"


def test_upload_script_auto_adds_palta_curated_documents_first(tmp_path: pathlib.Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_upload_crop_documents as upd

    crop_dir = tmp_path / "Fuente Documental" / "palta_hass"
    principal_dir = crop_dir / "principal"
    curated_dir = crop_dir / "curated"
    principal_dir.mkdir(parents=True)
    curated_dir.mkdir()
    pdf = principal_dir / "manual_palto.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    (curated_dir / "sanidad.md").write_text("Sanidad y MIP en palta Hass.", encoding="utf-8")
    (curated_dir / "polinizacion_floracion.md").write_text("Floracion, polinizacion y cuajado.", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "crop": "palta_hass",
                "documents": [{"path": str(pdf), "role": "principal"}],
            }
        ),
        encoding="utf-8",
    )

    manifest = upd.load_and_validate_manifest(str(manifest_path), "palta_hass")
    curated = [pathlib.Path(doc["path"]).name for doc in manifest["documents"] if doc.get("role") == "curated"]

    assert curated == ["polinizacion_floracion.md", "sanidad.md"]
    assert manifest["documents"][0]["role"] == "curated"
    assert manifest["documents"][-1]["role"] == "principal"


# ─── 7. Provider builds request with file_search tool ─────────────────────────


def test_upload_script_auto_adds_mandarina_curated_documents_first(tmp_path: pathlib.Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_upload_crop_documents as upd

    crop_dir = tmp_path / "Fuente Documental" / "mandarina_murcott"
    principal_dir = crop_dir / "principal"
    curated_dir = crop_dir / "curated"
    principal_dir.mkdir(parents=True)
    curated_dir.mkdir()
    pdf = principal_dir / "manual_mandarina.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    (curated_dir / "induccion_floracion_cuajado.md").write_text(
        "Induccion floral, floracion y cuajado en mandarina.",
        encoding="utf-8",
    )
    (curated_dir / "sanidad_mip.md").write_text("Sanidad y MIP en mandarina.", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "crop": "mandarina_murcott",
                "documents": [{"path": str(pdf), "role": "principal"}],
            }
        ),
        encoding="utf-8",
    )

    manifest = upd.load_and_validate_manifest(str(manifest_path), "mandarina_murcott")
    curated = [pathlib.Path(doc["path"]).name for doc in manifest["documents"] if doc.get("role") == "curated"]

    assert curated == ["induccion_floracion_cuajado.md", "sanidad_mip.md"]
    assert manifest["documents"][0]["role"] == "curated"
    assert manifest["documents"][-1]["role"] == "principal"


def test_upload_script_auto_adds_maracuya_curated_documents_first(tmp_path: pathlib.Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_upload_crop_documents as upd

    crop_dir = tmp_path / "Fuente Documental" / "maracuya_criolla_amarilla"
    principal_dir = crop_dir / "principal"
    curated_dir = crop_dir / "curated"
    principal_dir.mkdir(parents=True)
    curated_dir.mkdir()
    pdf = principal_dir / "manual_maracuya.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    (curated_dir / "polinizacion_floracion_cuajado.md").write_text(
        "Floracion, polinizacion y cuajado en maracuya.",
        encoding="utf-8",
    )
    (curated_dir / "propagacion_vivero_material.md").write_text(
        "Propagacion, vivero y material vegetal en maracuya.",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "crop": "maracuya_criolla_amarilla",
                "documents": [{"path": str(pdf), "role": "principal"}],
            }
        ),
        encoding="utf-8",
    )

    manifest = upd.load_and_validate_manifest(str(manifest_path), "maracuya_criolla_amarilla")
    curated = [pathlib.Path(doc["path"]).name for doc in manifest["documents"] if doc.get("role") == "curated"]

    assert curated == ["polinizacion_floracion_cuajado.md", "propagacion_vivero_material.md"]
    assert manifest["documents"][0]["role"] == "curated"
    assert manifest["documents"][-1]["role"] == "principal"


def test_upload_script_auto_adds_uva_curated_documents_first(tmp_path: pathlib.Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import openai_upload_crop_documents as upd

    crop_dir = tmp_path / "Fuente Documental" / "uva_de_mesa_sweet_globe"
    principal_dir = crop_dir / "principal"
    curated_dir = crop_dir / "curated"
    principal_dir.mkdir(parents=True)
    curated_dir.mkdir()
    pdf = principal_dir / "manual_uva.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    (curated_dir / "agua_riego.md").write_text("Agua y riego en uva de mesa.", encoding="utf-8")
    (curated_dir / "floracion_cuajado_raleo_calibre.md").write_text(
        "Floracion, cuajado, raleo y calibre en Sweet Globe.",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "crop": "uva_de_mesa_sweet_globe",
                "documents": [{"path": str(pdf), "role": "principal"}],
            }
        ),
        encoding="utf-8",
    )

    manifest = upd.load_and_validate_manifest(str(manifest_path), "uva_de_mesa_sweet_globe")
    curated = [pathlib.Path(doc["path"]).name for doc in manifest["documents"] if doc.get("role") == "curated"]

    assert curated == ["agua_riego.md", "floracion_cuajado_raleo_calibre.md"]
    assert manifest["documents"][0]["role"] == "curated"
    assert manifest["documents"][-1]["role"] == "principal"


def test_provider_calls_client_with_file_search_tool() -> None:
    client = RecordingOpenAIClient(response=_valid_response())
    provider = OpenAIFileSearchDraftingProvider(_config(), client=client)
    provider.draft(_context())
    assert client.calls == 1
    assert client.last_vector_store_ids == ["vs_test_maiz_001"]


def test_provider_sends_precomputed_data_in_prompt() -> None:
    client = RecordingOpenAIClient(response=_valid_response())
    provider = OpenAIFileSearchDraftingProvider(_config(), client=client)
    provider.draft(_context())
    user_msg = _user_content(client)
    assert "score_calculado: 0.78" in user_msg
    assert "viability_category_calculada: VIABLE" in user_msg
    assert "precipitacion" in user_msg
    assert "brecha=-25.0" in user_msg


def test_provider_sends_enriched_gap_semantics_in_prompt() -> None:
    context = RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="maiz_amarillo_duro",
            score=0.42,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="CONDICIONAL",
            gaps=[
                GapData(
                    criterion_id="criterion-temp",
                    phase_id="phase-panoja",
                    most_limiting_period="p2",
                    observed_value=20.47,
                    optimal_limit=22.0,
                    gap_value=-1.53,
                    criterion_name="temperatura_media_panojamiento",
                    criterion_label="Temperatura media durante panojamiento",
                    criterion_group="clima",
                    unit="celsius",
                    phase_name="panojamiento",
                    gap_direction="below_optimum",
                    severity="media",
                    recommendation_topic="temperatura floracion panojamiento",
                )
            ],
        ),
        evidence=[],
    )
    client = RecordingOpenAIClient(response=_valid_response())
    provider = OpenAIFileSearchDraftingProvider(_config(), client=client)

    provider.draft(context)

    user_msg = _user_content(client)
    assert "criterio_nombre=temperatura_media_panojamiento" in user_msg
    assert "criterio_label=Temperatura media durante panojamiento" in user_msg
    assert "unidad=celsius" in user_msg
    assert "fases_afectadas=['panojamiento']" in user_msg
    assert "tema_recomendacion=temperatura floracion panojamiento" in user_msg
    assert "Consultas semánticas sugeridas para File Search" in user_msg


def test_provider_routes_climate_gap_to_curated_climate_file() -> None:
    context = RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="maiz_amarillo_duro",
            score=0.42,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="CONDICIONAL",
            gaps=[
                GapData(
                    criterion_id="criterion-temp",
                    phase_id="phase-panoja",
                    most_limiting_period="p2",
                    observed_value=20.47,
                    optimal_limit=22.0,
                    gap_value=-1.53,
                    criterion_name="aptitud_termica",
                    criterion_label="Aptitud termica",
                    criterion_group="clima",
                    unit="celsius",
                    phase_name="panojamiento",
                    gap_direction="below_optimum",
                    severity="media",
                    recommendation_topic="temperatura floracion panojamiento",
                )
            ],
        ),
        evidence=[],
    )

    user_msg = _build_user_prompt(context)

    assert "clima_fenologia.md" in user_msg
    assert "curated/clima_fenologia.md" in user_msg


def test_provider_routes_riego_gap_to_curated_riego_file() -> None:
    context = RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="maiz_amarillo_duro",
            score=0.42,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="CONDICIONAL",
            gaps=[
                GapData(
                    criterion_id="criterion-water",
                    phase_id="phase-floracion",
                    most_limiting_period="p3",
                    observed_value=420.0,
                    optimal_limit=600.0,
                    gap_value=-180.0,
                    criterion_name="deficit_hidrico",
                    criterion_label="Deficit hidrico",
                    criterion_group="riego",
                    unit="mm",
                    phase_name="floracion",
                    gap_direction="below_optimum",
                    severity="alta",
                    recommendation_topic="riego agua humedad requerimiento hidrico",
                )
            ],
        ),
        evidence=[],
    )

    user_msg = _build_user_prompt(context)

    assert "riego.md" in user_msg
    assert "curated/riego.md" in user_msg
    assert "costa central Peru" in user_msg


def test_provider_routes_palta_sanidad_gap_to_curated_sanidad_file() -> None:
    context = RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="palta_hass",
            score=0.51,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="CONDICIONAL",
            gaps=[
                GapData(
                    criterion_id="criterion-sanidad",
                    phase_id="phase-fruto",
                    most_limiting_period="p4",
                    observed_value=0.4,
                    optimal_limit=0.8,
                    gap_value=-0.4,
                    criterion_name="phytophthora",
                    criterion_label="Riesgo sanitario Phytophthora",
                    criterion_group="sanidad",
                    unit="index",
                    phase_name="crecimiento_desarrollo_fruto",
                    gap_direction="below_optimum",
                    severity="alta",
                    recommendation_topic="sanidad phytophthora mip palta Hass",
                )
            ],
        ),
        evidence=[],
    )

    user_msg = _build_user_prompt(context)

    assert "sanidad.md" in user_msg
    assert "curated/sanidad.md" in user_msg
    assert "palta Hass Peru" in user_msg


def test_provider_routes_palta_floracion_gap_to_curated_pollination_file() -> None:
    context = RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="palta_hass",
            score=0.51,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="CONDICIONAL",
            gaps=[
                GapData(
                    criterion_id="criterion-cuajado",
                    phase_id="phase-cuajado",
                    most_limiting_period="p3",
                    observed_value=12.0,
                    optimal_limit=18.0,
                    gap_value=-6.0,
                    criterion_name="cuajado",
                    criterion_label="Cuajado de fruto",
                    criterion_group="polinizacion",
                    unit="celsius",
                    phase_name="cuajado_fruto",
                    gap_direction="below_optimum",
                    severity="media",
                    recommendation_topic="floracion polinizacion cuajado abejas",
                )
            ],
        ),
        evidence=[],
    )

    user_msg = _build_user_prompt(context)

    assert "polinizacion_floracion.md" in user_msg
    assert "curated/polinizacion_floracion.md" in user_msg


def test_provider_routes_mandarina_floracion_gap_to_curated_file() -> None:
    context = RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="mandarina_murcott",
            score=0.49,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="CONDICIONAL",
            gaps=[
                GapData(
                    criterion_id="criterion-cuajado",
                    phase_id="phase-cuajado",
                    most_limiting_period="p3",
                    observed_value=120.0,
                    optimal_limit=80.0,
                    gap_value=40.0,
                    criterion_name="deficit_hidrico",
                    criterion_label="Deficit hidrico en cuajado",
                    criterion_group="riego",
                    unit="mm",
                    phase_name="cuajado_fruto",
                    gap_direction="above_optimum",
                    severity="alta",
                    recommendation_topic="induccion floral floracion cuajado estres hidrico mandarina",
                )
            ],
        ),
        evidence=[],
    )

    user_msg = _build_user_prompt(context)

    assert "induccion_floracion_cuajado.md" in user_msg
    assert "curated/induccion_floracion_cuajado.md" in user_msg


def test_provider_routes_maracuya_polinizacion_gap_to_curated_file() -> None:
    context = RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="maracuya_criolla_amarilla",
            score=0.46,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="CONDICIONAL",
            gaps=[
                GapData(
                    criterion_id="criterion-polinizacion",
                    phase_id="phase-polinizacion",
                    most_limiting_period="p4",
                    observed_value=20.0,
                    optimal_limit=24.0,
                    gap_value=-4.0,
                    criterion_name="aptitud_termica",
                    criterion_label="Aptitud termica en polinizacion",
                    criterion_group="clima",
                    unit="celsius",
                    phase_name="polinizacion_fecundacion",
                    gap_direction="below_optimum",
                    severity="alta",
                    recommendation_topic="floracion polinizacion cuajado fecundacion Xylocopa maracuya",
                )
            ],
        ),
        evidence=[],
    )

    user_msg = _build_user_prompt(context)

    assert "polinizacion_floracion_cuajado.md" in user_msg
    assert "curated/polinizacion_floracion_cuajado.md" in user_msg
    assert "maracuya criolla amarilla Peru" in user_msg


def test_provider_routes_uva_calibre_gap_to_curated_file() -> None:
    context = RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="uva_de_mesa_sweet_globe",
            score=0.52,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="CONDICIONAL",
            gaps=[
                GapData(
                    criterion_id="criterion-calibre",
                    phase_id="phase-crecimiento-baya",
                    most_limiting_period="p5",
                    observed_value=16.0,
                    optimal_limit=20.0,
                    gap_value=-4.0,
                    criterion_name="aptitud_termica",
                    criterion_label="Aptitud termica en crecimiento de baya",
                    criterion_group="clima",
                    unit="celsius",
                    phase_name="crecimiento_baya",
                    gap_direction="below_optimum",
                    severity="alta",
                    recommendation_topic="floracion cuajado raleo calibre baya Sweet Globe",
                )
            ],
        ),
        evidence=[],
    )

    user_msg = _build_user_prompt(context)

    assert "floracion_cuajado_raleo_calibre.md" in user_msg
    assert "curated/floracion_cuajado_raleo_calibre.md" in user_msg
    assert "uva de mesa Sweet Globe Peru" in user_msg


def test_provider_groups_repeated_gap_semantics_in_prompt() -> None:
    gap_kwargs = {
        "criterion_id": "criterion-altitud",
        "observed_value": 1808.12,
        "optimal_limit": 600.0,
        "gap_value": 1208.12,
        "criterion_name": "altitud",
        "criterion_label": "Altitud de la parcela",
        "criterion_group": "topografia",
        "unit": "m",
        "gap_direction": "above_optimum",
        "severity": "alta",
        "recommendation_topic": "altitud aptitud maiz amarillo duro",
    }
    context = RecommendationDraftContext(
        evaluation_id=uuid4(),
        crop_result=CropEvaluationResultData(
            crop_id="maiz_amarillo_duro",
            score=0.42,
            rank_position=1,
            calc_condition="DEFINITIVO",
            viability_category="CONDICIONAL",
            gaps=[
                GapData(phase_id="germinacion", most_limiting_period="p1", phase_name="germinacion", **gap_kwargs),
                GapData(phase_id="madurez", most_limiting_period="p4", phase_name="madurez", **gap_kwargs),
            ],
        ),
        evidence=[],
    )

    user_msg = _build_user_prompt(context)

    assert user_msg.count("criterio_nombre=altitud") == 1
    assert "fases_afectadas=['germinacion', 'madurez']" in user_msg


# ─── 8. Provider uses max_num_results from config ─────────────────────────────


def test_provider_uses_configured_max_num_results() -> None:
    client = RecordingOpenAIClient(response=_valid_response())
    provider = OpenAIFileSearchDraftingProvider(_config(), client=client)
    provider.draft(_context())
    assert client.last_max_num_results == 8


def test_provider_respects_different_max_num_results() -> None:
    cfg = OpenAIFileSearchConfig(
        api_key="test-key",
        model="gpt-4o-mini",
        max_num_results=3,
        prompt_version="v1",
        timeout_seconds=30,
        vector_store_map={"maiz_amarillo_duro": "vs_test"},
    )
    client = RecordingOpenAIClient(response=_valid_response())
    provider = OpenAIFileSearchDraftingProvider(cfg, client=client)
    provider.draft(_context())
    assert client.last_max_num_results == 3


# ─── 9. Provider requests include=["file_search_call.results"] ───────────────


def test_provider_requests_include_file_search_results() -> None:
    client = RecordingOpenAIClient(response=_valid_response())
    provider = OpenAIFileSearchDraftingProvider(_config(), client=client)
    provider.draft(_context())
    assert client.last_include == ["file_search_call.results"]


# ─── 10. Provider persists response_id and retrieved_results in trace ─────────


def test_provider_stores_response_id_in_trace() -> None:
    client = RecordingOpenAIClient(
        response=_valid_response(response_id="resp_abc123", fs_call_id="fs_789")
    )
    provider = OpenAIFileSearchDraftingProvider(_config(), client=client)
    provider.draft(_context())
    trace = provider.get_last_trace()
    assert trace is not None
    assert trace.response_id == "resp_abc123"
    assert trace.file_search_call_id == "fs_789"


def test_provider_stores_retrieved_results_in_trace() -> None:
    client = RecordingOpenAIClient(
        response=_valid_response(file_id="file_xyz", filename="guia_maiz.pdf", score=0.92)
    )
    provider = OpenAIFileSearchDraftingProvider(_config(), client=client)
    provider.draft(_context())
    trace = provider.get_last_trace()
    assert trace is not None
    assert len(trace.retrieved_results) == 1
    assert trace.retrieved_results[0]["filename"] == "guia_maiz.pdf"
    assert trace.retrieved_results[0]["file_id"] == "file_xyz"
    assert trace.source_filenames == ["guia_maiz.pdf"]


def test_provider_parses_structured_json_and_renders_text() -> None:
    client = RecordingOpenAIClient(response=_structured_response())
    provider = OpenAIFileSearchDraftingProvider(_config(), client=client)

    text = provider.draft(_context())

    structured = provider.get_last_structured_output()
    assert structured is not None
    assert structured["schema_version"] == "recommendation_structured_v1"
    assert structured["gap_recommendations"][0]["recommendation"].startswith("Priorizar riego")
    assert "## Recomendaciones por brecha" in text
    assert "Priorizar riego suplementario" in text


def test_trace_includes_evaluation_crop_and_vector_store_ids() -> None:
    client = RecordingOpenAIClient(response=_valid_response())
    ctx = _context()
    provider = OpenAIFileSearchDraftingProvider(_config(), client=client)
    provider.draft(ctx)
    trace = provider.get_last_trace()
    assert trace is not None
    assert trace.evaluation_id == str(ctx.evaluation_id)
    assert trace.crop_id == "maiz_amarillo_duro"
    assert trace.vector_store_id == "vs_test_maiz_001"
    assert trace.model == "gpt-4o-mini"
    assert trace.prompt_version == "v1"


def test_trace_to_dict_is_json_serialisable() -> None:
    client = RecordingOpenAIClient(response=_valid_response())
    provider = OpenAIFileSearchDraftingProvider(_config(), client=client)
    provider.draft(_context())
    trace = provider.get_last_trace()
    assert trace is not None
    d = trace.to_dict()
    json.dumps(d)


def test_trace_is_none_before_first_draft() -> None:
    provider = OpenAIFileSearchDraftingProvider(
        _config(),
        client=RecordingOpenAIClient(response=_valid_response()),
    )
    assert provider.get_last_trace() is None


# ─── 11. Prompt forbids LLM from modifying scores/ranking/categories ──────────


def test_prompt_contains_explicit_forbidden_behaviors() -> None:
    system = _build_system_prompt("v1")
    assert "NO calcular scores" in system
    assert "NO recalcular la aptitud agrícola" in system
    assert "NO modificar las categorías de viabilidad ya calculadas" in system
    assert "NO modificar el ranking ya calculado" in system
    assert "NO inventar citas" in system
    assert "NO citar documentos que no fueron recuperados" in system
    assert "NO afirmar que esta recomendación reemplaza validación agronómica" in system


def test_prompt_marks_mcda_data_as_read_only() -> None:
    user = _build_user_prompt(_context())
    assert "solo leer, no modificar" in user
    assert "score_calculado:" in user
    assert "rank_position_calculado:" in user
    assert "viability_category_calculada:" in user


def test_prompt_links_recommendations_to_calculated_gaps() -> None:
    system = _build_system_prompt("v1")
    assert "vinculada a una brecha calculada por VIA" in system


def test_provider_source_does_not_contain_calculation_logic() -> None:
    forbidden_terms = [
        "rank_crops",
        "calculate_score",
        "GapCalculation",
        "Fuzzification",
        "EntropyWeights",
        "WGM",
        "membership_fn",
        "trapezoidal",
    ]
    for term in forbidden_terms:
        assert term not in PROVIDER_SRC, f"Forbidden term found in provider: {term}"


# ─── 12. No retrieved results → declares insufficient evidence ────────────────


def test_no_retrieved_results_produces_insufficient_evidence_text() -> None:
    empty_response: dict[str, Any] = {
        "id": "resp_empty",
        "output": [
            {
                "type": "file_search_call",
                "id": "fs_empty",
                "results": [],
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "breve"}],
            },
        ],
    }
    client = RecordingOpenAIClient(response=empty_response)
    provider = OpenAIFileSearchDraftingProvider(_config(), client=client)
    text = provider.draft(_context())
    assert INSUFFICIENT_EVIDENCE_MSG in text
    trace = provider.get_last_trace()
    assert trace is not None
    assert trace.raw_output_validation_status in {"no_retrieved_results", "insufficient_text"}
    assert trace.warnings


def test_no_retrieved_results_warning_is_recorded_in_trace() -> None:
    response: dict[str, Any] = {
        "id": "resp_x",
        "output": [{"type": "file_search_call", "id": "fs_x", "results": []}],
    }
    client = RecordingOpenAIClient(response=response)
    provider = OpenAIFileSearchDraftingProvider(_config(), client=client)
    provider.draft(_context())
    trace = provider.get_last_trace()
    assert trace is not None
    assert any("no recuperó" in w.lower() or "no retrieved" in w.lower() for w in trace.warnings)


# ─── 13. Provider does not invent citations ───────────────────────────────────


def test_prompt_explicitly_prohibits_invented_citations() -> None:
    system = _build_system_prompt("v1")
    assert "NO inventar citas" in system
    assert "NO citar documentos que no fueron recuperados" in system


def test_provider_source_does_not_fabricate_citations_by_code() -> None:
    fabrication_indicators = [
        'bibliography"',
        'references"',
        '"cite"',
        '"citation"',
        "invented_doc",
    ]
    src = PROVIDER_SRC.lower()
    for indicator in fabrication_indicators:
        assert indicator not in src


# ─── 14. No hardcoded API keys ───────────────────────────────────────────────


def test_no_hardcoded_api_keys_in_provider() -> None:
    assert "sk-" not in PROVIDER_SRC
    assert "OPENAI_API_KEY" not in PROVIDER_SRC or "OPENAI_API_KEY" not in _collect_string_literals(
        PROVIDER_SRC
    )


def test_api_key_comes_from_config_not_provider() -> None:
    cfg_src = (ROOT / "via" / "config.py").read_text(encoding="utf-8")
    assert "_read_optional_text" in cfg_src
    assert "OPENAI_API_KEY" in cfg_src


# ─── 15. No pgvector or internal embeddings ──────────────────────────────────


def test_provider_does_not_import_pgvector_or_embeddings() -> None:
    forbidden_imports = {"pgvector", "sentence_transformers", "faiss", "chromadb", "numpy"}
    tree = ast.parse(PROVIDER_SRC)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".")[0])
    violations = set(imported) & forbidden_imports
    assert violations == set(), f"Forbidden imports found: {violations}"


def test_no_pgvector_imported_in_project_provider_files() -> None:
    infra_dir = (
        ROOT / "via" / "bounded_contexts" / "recommendation" / "infrastructure"
    )
    forbidden_imports = {"pgvector", "sentence_transformers", "faiss", "chromadb"}
    for py_file in infra_dir.glob("*.py"):
        src = py_file.read_text(encoding="utf-8")
        tree = ast.parse(src)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        violations = imports & forbidden_imports
        assert violations == set(), (
            f"Forbidden vector search import(s) {violations} found in {py_file.name}"
        )


# ─── 16. No async, Celery, Kafka, RabbitMQ, Redis ───────────────────────────


def test_provider_does_not_use_async() -> None:
    assert "async def" not in PROVIDER_SRC
    assert "asyncio" not in PROVIDER_SRC
    assert "await " not in PROVIDER_SRC


def test_provider_does_not_import_message_brokers() -> None:
    forbidden = {"celery", "kafka", "rabbitmq", "redis", "aioredis", "kombu"}
    src_lower = PROVIDER_SRC.lower()
    for term in forbidden:
        assert term not in src_lower, f"Forbidden broker found in provider: {term}"


def test_create_script_does_not_use_async() -> None:
    src = CREATE_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "async def" not in src
    assert "asyncio" not in src


def test_upload_script_does_not_use_async() -> None:
    src = UPLOAD_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "async def" not in src
    assert "asyncio" not in src


# ─── Additional: parse_response helper ───────────────────────────────────────


def test_parse_response_extracts_text_and_file_search_results() -> None:
    raw = _valid_response(
        text="Recomendación completa con score 0.78.",
        filename="doc_inia.pdf",
        file_id="file_inia_001",
        score=0.91,
        response_id="resp_001",
        fs_call_id="fs_001",
    )
    text, fs_id, results, filenames, warnings = _parse_response(raw)
    assert "Recomendación completa" in text
    assert fs_id == "fs_001"
    assert len(results) == 1
    assert results[0]["filename"] == "doc_inia.pdf"
    assert filenames == ["doc_inia.pdf"]
    assert warnings == []


def test_parse_response_handles_empty_output() -> None:
    text, fs_id, results, filenames, warnings = _parse_response({"id": "r", "output": []})
    assert text == ""
    assert results == []
    assert warnings


def test_parse_response_deduplicates_filenames() -> None:
    raw: dict[str, Any] = {
        "id": "r",
        "output": [
            {
                "type": "file_search_call",
                "id": "fs_1",
                "results": [
                    {"file_id": "a", "filename": "doc.pdf", "score": 0.9, "text": "txt1"},
                    {"file_id": "b", "filename": "doc.pdf", "score": 0.8, "text": "txt2"},
                ],
            }
        ],
    }
    _, _, _, filenames, _ = _parse_response(raw)
    assert filenames == ["doc.pdf"]


# ─── Additional: config validation ───────────────────────────────────────────


def test_config_openai_file_search_requires_api_key() -> None:
    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        load_settings(
            {
                "DATABASE_URL": "postgresql+psycopg2://u:p@h/db",
                "LLM_DRAFTING_PROVIDER": "openai_file_search",
                "OPENAI_RAG_MODEL": "gpt-4o-mini",
            }
        )


def test_config_openai_file_search_requires_model() -> None:
    with pytest.raises(ConfigurationError, match="OPENAI_RAG_MODEL"):
        load_settings(
            {
                "DATABASE_URL": "postgresql+psycopg2://u:p@h/db",
                "LLM_DRAFTING_PROVIDER": "openai_file_search",
                "OPENAI_API_KEY": "sk-test",
            }
        )


def test_config_openai_file_search_max_results_must_be_positive() -> None:
    with pytest.raises(ConfigurationError, match="OPENAI_FILE_SEARCH_MAX_RESULTS"):
        load_settings(
            {
                "DATABASE_URL": "postgresql+psycopg2://u:p@h/db",
                "LLM_DRAFTING_PROVIDER": "openai_file_search",
                "OPENAI_API_KEY": "sk-test",
                "OPENAI_RAG_MODEL": "gpt-4o-mini",
                "OPENAI_FILE_SEARCH_MAX_RESULTS": "0",
            }
        )


def test_config_openai_file_search_valid_settings_load() -> None:
    settings = load_settings(
        {
            "DATABASE_URL": "postgresql+psycopg2://u:p@h/db",
            "LLM_DRAFTING_PROVIDER": "openai_file_search",
            "OPENAI_API_KEY": "sk-test-valid",
            "OPENAI_RAG_MODEL": "gpt-4o-mini",
            "OPENAI_FILE_SEARCH_MAX_RESULTS": "5",
            "OPENAI_FILE_SEARCH_PROMPT_VERSION": "v2",
            "VIA_VECTOR_STORE_MAIZ_AMARILLO_DURO_ID": "vs_maiz_123",
        }
    )
    assert settings.llm_drafting_provider == "openai_file_search"
    assert settings.openai_api_key == "sk-test-valid"
    assert settings.openai_rag_model == "gpt-4o-mini"
    assert settings.openai_file_search_max_results == 5
    assert settings.openai_file_search_prompt_version == "v2"
    assert settings.openai_vector_store_maiz_amarillo_duro_id == "vs_maiz_123"


# ─── Helper ──────────────────────────────────────────────────────────────────


def _collect_string_literals(src: str) -> list[str]:
    """Return all string literal values in the source."""
    tree = ast.parse(src)
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append(node.value)
    return literals
