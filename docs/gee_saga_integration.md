# Lote 27A — GEE Real Integration in the Extraction Saga

## Overview

Lote 27A extends the 25B MCDA E2E saga to use `GeeExtractionClient` (real Google Earth Engine)
instead of `ControlledExtractionClient`. The tests are **opt-in**: they skip automatically in
`pytest -q` unless the `GEE_TEST_RUN_REAL` environment variable is set.

## Saga flow

```
POST /evaluaciones
  → EvaluationProcessManager
      GeeRealRulebookReadModelPort  →  COPERNICUS/S2_SR_HARMONIZED, band B8
      GeeRealParcelGeometryPort     →  Polygon near Lima, Peru
  → outbox_messages (PostgreSQL)
  → RelayWorker (FOR UPDATE SKIP LOCKED)
  → GeeExtractionClient.extract_variable()
      dataset: COPERNICUS/S2_SR_HARMONIZED
      band:    B8 (NIR, scaled reflectance 0–10 000 DN)
      reducer: mean, scale: 30 m
  → agroenv_vectors (PostgreSQL)
  → outbox_messages (PostgreSQL)
  → RelayWorker (second wave)
  → ViabilityEvaluationConsumer (MCDA, wide TRAPEZOIDAL membership)
  → evaluation_results (PostgreSQL)
  → saga status: EVALUACION_COMPLETADA
```

## Infrastructure

| Component | Description |
|-----------|-------------|
| `GeeExtractionClient` | Real GEE adapter — initialized via `ee.ServiceAccountCredentials` |
| `GeeRealRulebookReadModelPort` | Returns extraction spec for `COPERNICUS/S2_SR_HARMONIZED` B8 |
| `GeeRealParcelGeometryPort` | Returns small Lima-area polygon (~100 m × 100 m) |
| `GeeRealRulebookEvaluationPort` | Wide TRAPEZOIDAL membership; accepts any valid NIR DN value |
| `RelayWorker` | Real outbox relay with PostgreSQL row-level locking |
| `pg_migrated` | Alembic-managed test database (no manual DDL) |

## GEE dataset details

- **Collection**: `COPERNICUS/S2_SR_HUMANIZED` (Sentinel-2 Surface Reflectance Harmonized)
- **Band**: `B8` (Near-Infrared), DN values scaled to 0–10 000
- **Reducer**: `mean`
- **Scale**: 30 m (native Sentinel-2 spatial resolution is 10 m for B8; 30 m used for speed)
- **Periods**: `2024-Q2` (Jun–Jul 2024), `2024-Q3` (Aug 2024)
- **Test polygon**: small area near Lima, Peru (coastal semi-arid zone)

## MCDA membership function

The 27A rulebook uses a deliberately wide TRAPEZOIDAL function to accept any valid S2 NIR value:

```
TRAPEZOIDAL(a=0, b=100, c=9900, d=10001)
```

- Any value in `[100, 9900]` → membership = 1.0 → category VIABLE
- `fallback_allowed=True` → if GEE returns `None` (no valid pixels), saga continues gracefully

## Running the tests

### Opt-in GEE real tests

```bash
# Set credentials — never hardcode these values in source files
export GEE_PROJECT=your-gcp-project-id
export GEE_SERVICE_ACCOUNT=your-service-account@project.iam.gserviceaccount.com
export GEE_PRIVATE_KEY_FILE=/path/to/your/keyfile.json
export DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/via_test

# Enable real GEE tests
export GEE_TEST_RUN_REAL=1

pytest tests/integration/postgres/test_postgres_e2e_gee_real.py -v
```

### Normal pytest run (without GEE)

```bash
pytest -q
# GEE real tests are skipped automatically — no failures
```

### Static architecture tests (always run)

```bash
pytest tests/static/test_lote27a_gee_real_architecture.py -v
```

## Credential security

| Rule | Detail |
|------|--------|
| No hardcoded credentials | All GEE config comes from environment variables |
| No key file content | The JSON key file is never read or embedded in source |
| No user-specific paths | Key file path provided via `GEE_PRIVATE_KEY_FILE` env var |
| No printed secrets | `GeeExtractionClient` does not log credential values |
| Skip, not fail | Missing env vars → `pytest.skip` (not error) |

## Test functions

| Test | Guard |
|------|-------|
| `test_gee_real_credentials_are_required_for_real_run` | Standalone — skips if not opt-in |
| `test_postgres_e2e_gee_real_saga_reaches_evaluacion_completada` | `gee_real_skip_check` |
| `test_postgres_e2e_gee_real_resultado_mcda_returns_200` | `gee_real_skip_check` |
| `test_postgres_e2e_gee_real_result_persisted_in_postgresql` | `gee_real_skip_check` |
| `test_gee_real_client_extracts_single_variable` | `gee_real_skip_check` |
| `test_postgres_e2e_gee_real_does_not_use_controlled_extraction` | `gee_real_skip_check` |
| `test_postgres_e2e_gee_real_does_not_use_lockfree_relay` | `gee_real_skip_check` |
| `test_postgres_e2e_gee_real_outbox_dispatched_for_evaluation` | `gee_real_skip_check` |
| `test_postgres_e2e_gee_real_does_not_call_llm_or_recommendation` | `gee_real_skip_check` |

## What is NOT included

- No LLM, Gemini, Vertex, local_http provider
- No Recommendation consumer (saga stops at `EVALUACION_COMPLETADA`)
- No new endpoints, no new MCDA logic, no domain changes
- No SQLite, manual DDL, or `LockFreeRelayWorker`
- No asyncpg, AsyncSession, Celery, Kafka, RabbitMQ, or Redis
