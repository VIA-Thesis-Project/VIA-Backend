"""Unit tests for viability-evaluation ACL ports and adapters."""

from __future__ import annotations

from uuid import uuid4

from via.bounded_contexts.viability_evaluation.application.ports import AgroenvVectorData, RulebookEvaluationData
from via.bounded_contexts.viability_evaluation.infrastructure.agroenv_acl_adapter import AgroenvVectorAclAdapter
from via.bounded_contexts.viability_evaluation.infrastructure.rulebook_acl_adapter import RulebookAclAdapter


def test_rulebook_acl_adapter_returns_evaluation_read_model() -> None:
    rulebook_id = uuid4()

    def read_source(crop_id: str) -> dict:
        return {
            "crop_id": crop_id,
            "rulebook_id": str(rulebook_id),
            "version": 3,
            "criteria": [
                {
                    "criterion_id": "rain",
                    "crop_id": crop_id,
                    "phase_id": "flowering",
                    "variable_name": "precipitation",
                    "w_ahp": 0.4,
                    "phase_weight": 0.5,
                    "temporal_periods": [{"period_key": "2026-W01", "weight": 1.0}],
                    "membership_fn": {"type": "trap", "a": 1, "b": 2, "c": 3, "d": 4},
                    "critical_policy": "PENALIZE",
                    "penalty_factor": 0.25,
                    "doc_source": "manual",
                }
            ],
        }

    data = RulebookAclAdapter(read_source).get_active_rulebook("cacao")

    assert isinstance(data, RulebookEvaluationData)
    assert data.rulebook_id == rulebook_id
    assert data.criteria[0].membership_fn["type"] == "trap"


def test_agroenv_acl_adapter_returns_evaluation_vector_model() -> None:
    evaluation_id = uuid4()
    parcel_id = uuid4()

    def read_source(_evaluation_id):
        return {
            "evaluation_id": str(evaluation_id),
            "parcel_id": str(parcel_id),
            "variables": [
                {
                    "variable_name": "precipitation",
                    "criterion_id": "rain",
                    "crop_id": "cacao",
                    "phase_id": "flowering",
                    "period_key": "2026-W01",
                    "value": 42.5,
                    "unit": "mm",
                    "status": "OK",
                    "dataset_key": "chirps",
                    "band": "precip",
                    "source": "stub",
                }
            ],
        }

    data = AgroenvVectorAclAdapter(read_source).get_vector_for_evaluation(evaluation_id)

    assert isinstance(data, AgroenvVectorData)
    assert data.parcel_id == parcel_id
    assert data.variables[0].dataset_key == "chirps"
