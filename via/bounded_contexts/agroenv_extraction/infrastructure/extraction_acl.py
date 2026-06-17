"""Anti-corruption layer for external extraction responses."""

from __future__ import annotations

from datetime import date
from typing import Any

from via.bounded_contexts.agroenv_extraction.application.ports import (
    ExtractionRequest,
    IExtractionClient,
    StartExtractionCommand,
)
from via.bounded_contexts.agroenv_extraction.domain.agroenv_vector import AgroenvVector
from via.bounded_contexts.agroenv_extraction.domain.value_objects import AgroenvExtractionError, TemporalWindow, VariableStatus
from via.bounded_contexts.agroenv_extraction.domain.variable_entry import VariableEntry


class ExtractionAcl:
    """Translate command specs and external results into domain vectors."""

    def build_vector(self, command: StartExtractionCommand, extraction_client: IExtractionClient) -> AgroenvVector:
        """Build an agroenvironmental vector from required_extraction_spec only."""

        entries: list[VariableEntry] = []
        for raw_variable in command.required_extraction_spec.get("variables", []):
            entries.extend(self._extract_variable_periods(command, raw_variable, extraction_client))

        return AgroenvVector(
            evaluation_id=command.evaluation_id,
            parcel_id=command.parcel_id,
            temporal_window=TemporalWindow(command.temporal_window),
            variables=entries,
        )

    def _extract_variable_periods(
        self,
        command: StartExtractionCommand,
        raw_variable: dict[str, Any],
        extraction_client: IExtractionClient,
    ) -> list[VariableEntry]:
        periods = raw_variable.get("temporal_periods") or [{"period_key": "default"}]
        entries: list[VariableEntry] = []
        for raw_period in periods:
            request = _request_from_spec(command, raw_variable, raw_period)
            result = extraction_client.extract_variable(request)
            if result is None:
                if not request.fallback_allowed:
                    raise AgroenvExtractionError(f"Variable unavailable without fallback: {request.variable_name}")
                entries.append(_missing_entry_from_request(request))
            else:
                entries.append(_ok_entry_from_request(request, result.value, result.source, result.extraction_date))
        return entries


def _request_from_spec(command: StartExtractionCommand, raw_variable: dict[str, Any], raw_period: dict[str, Any]) -> ExtractionRequest:
    return ExtractionRequest(
        parcel_id=command.parcel_id,
        parcel_geometry=command.parcel_geometry,
        temporal_window=command.temporal_window,
        variable_name=str(raw_variable["variable_name"]),
        criterion_id=str(raw_variable["criterion_id"]),
        crop_id=str(raw_variable["crop_id"]),
        phase_id=str(raw_variable["phase_id"]),
        dataset_key=str(raw_variable["dataset_key"]),
        band=str(raw_variable["band"]),
        unit=str(raw_variable["unit"]),
        temporal_resolution=str(raw_variable["temporal_resolution"]),
        spatial_resolution=raw_variable.get("spatial_resolution"),
        scale=float(raw_variable["scale"]) if raw_variable.get("scale") is not None else None,
        reducer=str(raw_variable.get("reducer") or "mean"),
        aggregation_method=str(raw_variable.get("aggregation_method") or "mean"),
        quality_mask=raw_variable.get("quality_mask"),
        fallback_allowed=bool(raw_variable.get("fallback_allowed", False)),
        period_key=str(raw_period.get("period_key") or "default"),
        period_start=_period_bound(raw_period, "start"),
        period_end=_period_bound(raw_period, "end"),
    )


def _period_bound(raw_period: dict[str, Any], bound: str) -> str | None:
    return raw_period.get(bound) or raw_period.get(f"{bound}_date")


def _ok_entry_from_request(request: ExtractionRequest, value: float | None, source: str, extraction_date: date) -> VariableEntry:
    return VariableEntry(
        variable_name=request.variable_name,
        criterion_id=request.criterion_id,
        crop_id=request.crop_id,
        phase_id=request.phase_id,
        dataset_key=request.dataset_key,
        band=request.band,
        unit=request.unit,
        temporal_resolution=request.temporal_resolution,
        spatial_resolution=request.spatial_resolution,
        scale=request.scale,
        reducer=request.reducer,
        aggregation_method=request.aggregation_method,
        quality_mask=request.quality_mask,
        fallback_allowed=request.fallback_allowed,
        value=value,
        source=source,
        extraction_date=extraction_date,
        period_key=request.period_key,
        status=VariableStatus.OK,
    )


def _missing_entry_from_request(request: ExtractionRequest) -> VariableEntry:
    return VariableEntry(
        variable_name=request.variable_name,
        criterion_id=request.criterion_id,
        crop_id=request.crop_id,
        phase_id=request.phase_id,
        dataset_key=request.dataset_key,
        band=request.band,
        unit=request.unit,
        temporal_resolution=request.temporal_resolution,
        spatial_resolution=request.spatial_resolution,
        scale=request.scale,
        reducer=request.reducer,
        aggregation_method=request.aggregation_method,
        quality_mask=request.quality_mask,
        fallback_allowed=request.fallback_allowed,
        value=None,
        source="unavailable",
        extraction_date=date.today(),
        period_key=request.period_key,
        status=VariableStatus.CRITERIO_FALTANTE,
    )
