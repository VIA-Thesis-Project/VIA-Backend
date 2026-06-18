"""Seed simulated demo rulebooks for VIA technical testing.

Usage (PowerShell):
    $env:DATABASE_URL="postgresql+psycopg2://via_user:via_password@localhost:5433/via_test"
    python scripts/seed_demo_rulebooks.py

These rulebooks are synthetic fixtures for exercising the evaluation pipeline.
They are not agronomic recommendations and do not represent INIA data.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from via.bounded_contexts.rulebook_management.application.command_service import RulebookCommandService
from via.bounded_contexts.rulebook_management.domain.criterion import Criterion
from via.bounded_contexts.rulebook_management.domain.phase_requirement import ExtractionBinding, PhaseRequirement
from via.bounded_contexts.rulebook_management.domain.phenological_phase import PhenologicalPhase
from via.bounded_contexts.rulebook_management.domain.rulebook import Rulebook
from via.bounded_contexts.rulebook_management.domain.value_objects import MembershipFunction, TemporalPeriod
from via.bounded_contexts.rulebook_management.infrastructure.rulebook_repository import SqlAlchemyRulebookRepository


DEMO_CROPS: dict[str, str] = {
    "demo_papa": "Papa demo",
    "demo_maiz": "Maiz demo",
    "demo_quinua": "Quinua demo",
    "demo_palta": "Palta demo",
    "demo_arandano": "Arandano demo",
}

DEMO_CRITERIA = (
    "vegetacion_vigor",
    "humedad_superficial",
    "estres_hidrico",
    "estabilidad_fenologica",
    "aptitud_general",
)

DEMO_PHASES = (
    ("establecimiento", 30),
    ("desarrollo", 45),
    ("floracion", 35),
    ("maduracion", 40),
)

DEMO_VERSION_NOTE = "version demo simulada"
DEMO_DOC_SOURCE = "Synthetic demo fixture - not agronomic guidance and not INIA data"

# The current real GEE demo supports Sentinel-2 B8 through this binding.  The
# five criteria below intentionally reuse the same extraction variable so the
# full evaluation flow can run today; criterion labels are simulated fixtures.
DEMO_EXTRACTION_BINDING = ExtractionBinding(
    variable_name="nir_reflectancia",
    dataset_key="COPERNICUS/S2_SR_HARMONIZED",
    band="B8",
    unit="reflectance_scaled",
    temporal_resolution="monthly",
    spatial_resolution=None,
    scale=30.0,
    reducer="mean",
    aggregation_method="mean",
    quality_mask=None,
    fallback_allowed=True,
)


@dataclass(frozen=True)
class SeededRulebook:
    """Summary of one seeded demo rulebook."""

    crop_id: str
    display_name: str
    rulebook_id: UUID
    version: int
    status: str


class RulebookRepositoryLike(Protocol):
    """Subset of the rulebook repository used by the demo seed."""

    def next_version_for_crop(self, crop_id: str) -> int:
        """Return the next version number for a crop."""

    def add(self, rulebook: Rulebook) -> None:
        """Persist a rulebook."""

    def get_by_id(self, rulebook_id: UUID) -> Rulebook | None:
        """Return a rulebook by id."""

    def deactivate_active_for_crop(self, crop_id: str) -> None:
        """Deactivate active versions for a crop."""

    def save(self, rulebook: Rulebook) -> None:
        """Persist rulebook state changes."""


def require_database_url() -> str:
    """Return DATABASE_URL from the environment or exit with a clear error."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("ERROR: DATABASE_URL is required but not set.", file=sys.stderr)
        sys.exit(1)
    if not database_url.startswith("postgresql+psycopg2://"):
        print("ERROR: DATABASE_URL must use postgresql+psycopg2://", file=sys.stderr)
        sys.exit(1)
    return database_url


def seed_demo_rulebooks(
    session_factory: sessionmaker[Session],
    cleanup_func: Callable[[Session], None] | None = None,
    repository_factory: Callable[[Session], RulebookRepositoryLike] | None = None,
) -> list[SeededRulebook]:
    """Replace existing demo rulebooks and publish one active version per crop."""

    session = session_factory()
    try:
        resolved_cleanup = cleanup_func or remove_existing_demo_rulebooks
        resolved_repository_factory = repository_factory or SqlAlchemyRulebookRepository
        resolved_cleanup(session)
        seeded = create_and_publish_demo_rulebooks(resolved_repository_factory(session))
        session.commit()
        return seeded
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_and_publish_demo_rulebooks(repository: RulebookRepositoryLike) -> list[SeededRulebook]:
    """Create and publish the five demo rulebooks through the application service."""

    service = RulebookCommandService(repository=repository)
    seeded: list[SeededRulebook] = []
    for crop_id, display_name in DEMO_CROPS.items():
        criteria, phases, requirements = build_demo_rulebook_parts(crop_id)
        rulebook = service.create_rulebook(
            crop_id=crop_id,
            criteria=criteria,
            phases=phases,
            phase_requirements=requirements,
        )
        service.publish_rulebook(rulebook.id)
        seeded.append(_summary(rulebook, display_name))
    return seeded


def remove_existing_demo_rulebooks(session: Session) -> None:
    """Delete only existing demo rulebooks so seeding remains idempotent."""

    crop_ids = list(DEMO_CROPS)
    session.execute(
        text(
            """
            DELETE FROM transactional.rulebook_phase_requirements
            WHERE criterion_id IN (
                SELECT c.id
                FROM transactional.rulebook_criteria c
                JOIN transactional.rulebooks r ON r.id = c.rulebook_id
                WHERE r.crop_id IN :crop_ids
            )
            OR phase_id IN (
                SELECT p.id
                FROM transactional.rulebook_phases p
                JOIN transactional.rulebooks r ON r.id = p.rulebook_id
                WHERE r.crop_id IN :crop_ids
            )
            """
        ).bindparams(bindparam("crop_ids", expanding=True)),
        {"crop_ids": crop_ids},
    )
    session.execute(
        text(
            """
            DELETE FROM transactional.rulebook_phases
            WHERE rulebook_id IN (
                SELECT id FROM transactional.rulebooks WHERE crop_id IN :crop_ids
            )
            """
        ).bindparams(bindparam("crop_ids", expanding=True)),
        {"crop_ids": crop_ids},
    )
    session.execute(
        text(
            """
            DELETE FROM transactional.rulebook_criteria
            WHERE rulebook_id IN (
                SELECT id FROM transactional.rulebooks WHERE crop_id IN :crop_ids
            )
            """
        ).bindparams(bindparam("crop_ids", expanding=True)),
        {"crop_ids": crop_ids},
    )
    session.execute(
        text("DELETE FROM transactional.rulebooks WHERE crop_id IN :crop_ids").bindparams(
            bindparam("crop_ids", expanding=True)
        ),
        {"crop_ids": crop_ids},
    )


def build_demo_rulebook_parts(
    crop_id: str,
) -> tuple[list[Criterion], list[PhenologicalPhase], list[PhaseRequirement]]:
    """Build a complete synthetic rulebook graph for one demo crop."""

    if crop_id not in DEMO_CROPS:
        raise ValueError(f"Unknown demo crop: {crop_id}")

    criteria = [
        Criterion(
            id=_stable_id(crop_id, "criterion", criterion_name),
            name=criterion_name,
            is_critical=False,
            critical_policy=None,
            penalty_factor=None,
            ahp_weight=1.0 / len(DEMO_CRITERIA),
            doc_source=DEMO_DOC_SOURCE,
            technical_notes=(
                f"{DEMO_VERSION_NOTE}. Simulated criterion mapped to "
                f"{DEMO_EXTRACTION_BINDING.variable_name}; not real agronomic data."
            ),
        )
        for criterion_name in DEMO_CRITERIA
    ]
    phases = [
        PhenologicalPhase(
            id=_stable_id(crop_id, "phase", phase_name),
            name=phase_name,
            duration_days=duration_days,
            sequence_order=index,
        )
        for index, (phase_name, duration_days) in enumerate(DEMO_PHASES, start=1)
    ]
    requirements = [
        PhaseRequirement(
            id=_stable_id(crop_id, "requirement", criterion.name, phase.name),
            criterion_id=criterion.id,
            phase_id=phase.id,
            membership_fn=_membership_for_phase(phase.sequence_order),
            phase_weight=1.0 / len(DEMO_PHASES),
            temporal_periods=[TemporalPeriod(period_key=f"{phase.name}_demo", temporal_weight=1.0)],
            extraction_binding=DEMO_EXTRACTION_BINDING,
        )
        for criterion in criteria
        for phase in phases
    ]
    return criteria, phases, requirements


def main() -> None:
    """Run the seed from DATABASE_URL and print a concise summary."""

    database_url = require_database_url()
    engine = create_engine(database_url, future=True)
    try:
        session_factory = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)
        seeded = seed_demo_rulebooks(session_factory)
    finally:
        engine.dispose()

    print("Seeded synthetic demo rulebooks:")
    for item in seeded:
        print(f"- {item.crop_id} ({item.display_name}): {item.status} v{item.version} {item.rulebook_id}")
    print("These are simulated technical fixtures, not INIA data and not agronomic guidance.")


def _membership_for_phase(sequence_order: int) -> MembershipFunction:
    # Broad synthetic trapezoids over Sentinel-2 B8 scaled values. These ranges
    # are intentionally demo-only and are not crop-specific agronomic thresholds.
    offset = float(sequence_order - 1) * 50.0
    return MembershipFunction(a=0.0 + offset, b=100.0 + offset, c=9900.0 - offset, d=10001.0 - offset)


def _stable_id(crop_id: str, *parts: str) -> UUID:
    return uuid5(NAMESPACE_URL, ":".join(("via-demo-rulebook", crop_id, *parts)))


def _summary(rulebook: Rulebook, display_name: str) -> SeededRulebook:
    return SeededRulebook(
        crop_id=rulebook.crop_id,
        display_name=display_name,
        rulebook_id=rulebook.id,
        version=rulebook.version,
        status=rulebook.status.value,
    )


if __name__ == "__main__":
    main()
