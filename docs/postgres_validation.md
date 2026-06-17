# Validación PostgreSQL — VIA

Documentación de los lotes de validación contra PostgreSQL real.

---

## Lote 22A — Conexión, Extensiones, Esquemas y Migraciones

**Archivo:** `tests/integration/postgres/test_postgres_connection.py`, `test_postgres_extensions.py`, `test_postgres_schemas.py`, `test_postgres_migrations.py`, `test_postgres_tables.py`, `test_postgres_columns.py`, `test_postgres_no_async.py`

**Objetivo:** Verificar que la base de datos PostgreSQL real cumple todos los requisitos de infraestructura del monolito VIA.

**Cobertura:**
- Conexión real mediante `postgresql+psycopg2://`
- Extensiones: `pgcrypto`, `postgis`, `vector`
- Esquemas: `transactional`, `documental`
- Migraciones Alembic: `downgrade base → upgrade head`
- 21 tablas en esquema `transactional`, 2 en `documental`
- Columnas críticas: `GEOMETRY(MULTIPOLYGON, 4326)` en `parcels`, `VECTOR(1536)` en fragmentos, `JSONB` en `outbox_messages.payload_json`
- Ningún `async`, `asyncpg`, `AsyncSession` ni `SQLite`

**Requisitos:** `DATABASE_URL=postgresql+psycopg2://via_user:via_password@localhost:5433/via_test`

---

## Lote 22B — Transactional Outbox, Relay Worker e Idempotencia

**Archivo:** `tests/integration/postgres/test_outbox_relay_idempotency.py`

**Objetivo:** Verificar la implementación real del patrón Transactional Outbox sobre PostgreSQL, incluyendo locking optimista y deduplicación idempotente.

**Cobertura:**
- `OutboxWriter` persiste mensajes con PK semántico (`message_id = message.id`)
- `RelayWorker.process_batch()` usa `WITH FOR UPDATE SKIP LOCKED` (semántica PostgreSQL nativa)
- Flujo PENDING → DISPATCHED en ciclo de relay real
- Todos los campos de envelope preservados: `correlation_id`, `aggregate_type`, `aggregate_id`, `message_type`, `message_kind`, `payload_json`
- Fallo de handler: `retry_count += 1`, `last_error` poblado
- `PERMANENT_FAILURE` tras `retry_count >= max_retries`
- Idempotencia DB: `(message_id, consumer)` en `processed_message_ids` → `IntegrityError` en duplicado
- Idempotencia consumidor: `IdempotentConsumerMixin` descarta duplicados real en PostgreSQL
- Segundo ciclo de relay: 0 mensajes procesados (ya DISPATCHED)

**Semántica at-least-once documentada:** Si el proceso cae entre `bus.publish()` y `session.commit()`, el mensaje queda `PENDING` y se republicará. `processed_message_ids` provee idempotencia de consumidor para semántica exactly-once.

---

## Lote 25B — E2E parcial MCDA sobre PostgreSQL real

**Archivo:** `tests/integration/postgres/test_postgres_e2e_mcda.py`

**Objetivo:** Verificar el flujo completo de evaluación MCDA (sin GEE ni LLM) usando infraestructura PostgreSQL real: Outbox real, RelayWorker real con `FOR UPDATE SKIP LOCKED`, persistencia real de resultados y consulta HTTP desde la base de datos real.

### Flujo validado

```
POST /evaluaciones
  → EvaluationProcessManager
  → IniciarExtraccionAgroambiental (Outbox → PostgreSQL)
  → RelayWorker.process_batch() [ola 1: extracción]
  → ControlledExtractionClient (no GEE)
  → VectorAgroambientalGenerado (Outbox → PostgreSQL)
  → RelayWorker.process_batch() [ola 2: PM recibe vector]
  → EjecutarEvaluacionViabilidad (Outbox → PostgreSQL)
  → RelayWorker.process_batch() [ola 3: evaluación MCDA]
  → ViabilityEvaluationConsumer (MCDA real, resultados → PostgreSQL)
  → EvaluacionViabilidadCompletada (Outbox → PostgreSQL)
  → RelayWorker.process_batch() [ola 4: PM marca EVALUACION_COMPLETADA]
  → GET /evaluaciones/{id}/estado → EVALUACION_COMPLETADA (desde PostgreSQL)
  → GET /evaluaciones/{id}/resultado-mcda → ranking + gaps (desde PostgreSQL)
```

### Infraestructura real usada

| Componente | Implementación |
|---|---|
| Base de datos | PostgreSQL 15 (garapadev/postgres-postgis-pgvector:15-slim) |
| Migraciones | Alembic `upgrade head` (via `pg_migrated`) |
| Relay Worker | `RelayWorker` real con `WITH FOR UPDATE SKIP LOCKED` |
| Event Bus | `InMemoryEventBus` real, sincrónico |
| Outbox | `transactional.outbox_messages` en PostgreSQL |
| Agroenv vectors | `transactional.agroenv_vectors` en PostgreSQL |
| Evaluación MCDA | Motor MCDA difuso real del dominio |
| Resultados | `transactional.evaluation_results` en PostgreSQL |
| Gaps | `transactional.agronomy_gaps` en PostgreSQL |
| Query endpoint | Lee de PostgreSQL, no de objetos en memoria |

### Puertos controlados (para evitar servicios externos)

| Puerto | Motivo |
|---|---|
| `ControlledExtractionClient` | Evita llamadas a GEE (Google Earth Engine) |
| `ControlledParcelGeometryPort` | Evita insertar geometría PostGIS en `parcels` |
| `ControlledRulebookReadModelPort` | Evita insertar cadena completa de FK de rulebooks |
| `ControlledRulebookEvaluationPort` | Evita insertar rulebooks con criterios y fases |

### Datos deterministas

Cultivos evaluados: `maiz_amarillo_duro`, `papa`

| Cultivo | Variable | Q1 | Q2 |
|---|---|---|---|
| maiz | temperatura_media | 26.0 °C | 28.0 °C |
| maiz | precipitacion_acumulada | 800.0 mm | 480.0 mm |
| papa | temperatura_media | 20.0 °C | 21.0 °C |
| papa | precipitacion_acumulada | 750.0 mm | 650.0 mm |

### Resultados esperados

| Cultivo | Score (aprox.) | Categoría | Rank |
|---|---|---|---|
| maiz_amarillo_duro | ~0.793 | VIABLE | 1 |
| papa | ~0.536 | CONDICIONAL | 2 |

Brechas esperadas:
- `maiz / precipitacion / Q2`: gap_value ≈ -120 mm (déficit)
- `papa / temperatura / Q2`: gap_value ≈ +3 °C (exceso)

### Ejemplo de respuesta `GET /evaluaciones/{id}/resultado-mcda`

```json
{
  "evaluation_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "EVALUACION_COMPLETADA",
  "results": [
    {
      "crop_id": "maiz_amarillo_duro",
      "score": 0.793,
      "rank_position": 1,
      "calc_condition": "DEFINITIVO",
      "viability_category": "VIABLE",
      "gaps": [
        {
          "criterion_id": "precipitacion",
          "phase_id": "vegetativo",
          "most_limiting_period": "2026-Q2",
          "observed_value": 480.0,
          "optimal_limit": 600.0,
          "gap_value": -120.0
        }
      ],
      "limiting_factors": [],
      "missing_criteria": [],
      "unrecognized_variables": []
    },
    {
      "crop_id": "papa",
      "score": 0.536,
      "rank_position": 2,
      "calc_condition": "DEFINITIVO",
      "viability_category": "CONDICIONAL",
      "gaps": [
        {
          "criterion_id": "temperatura",
          "phase_id": "vegetativo",
          "most_limiting_period": "2026-Q2",
          "observed_value": 21.0,
          "optimal_limit": 18.0,
          "gap_value": 3.0
        }
      ],
      "limiting_factors": [],
      "missing_criteria": [],
      "unrecognized_variables": []
    }
  ],
  "failure_reason": null
}
```

### Ejecutar los tests

```bash
# Levantar PostgreSQL con Docker
docker compose -f docker-compose.postgres.yml up -d

# Configurar DATABASE_URL
export DATABASE_URL=postgresql+psycopg2://via_user:via_password@localhost:5433/via_test

# Tests estáticos (sin DB)
pytest tests/static -q

# Tests de integración PostgreSQL (22A + 22B + 25B)
pytest tests/integration/postgres -q

# Suite completa
pytest -q
```

### Tests incluidos en 25B

| Test | Descripción |
|---|---|
| `test_postgres_e2e_evaluation_reaches_completed_state` | Saga llega a `EVALUACION_COMPLETADA` |
| `test_postgres_e2e_resultado_mcda_returns_persisted_results` | Resultados vienen de PostgreSQL real |
| `test_postgres_e2e_result_contains_ranking` | ≥2 cultivos con `rank_position` |
| `test_postgres_e2e_result_contains_agronomic_gaps` | ≥1 gap con `most_limiting_period` |
| `test_postgres_e2e_outbox_messages_are_dispatched` | Mensajes del outbox quedan `DISPATCHED` |
| `test_postgres_e2e_uses_real_relay_not_lockfree` | Relay usa `FOR UPDATE SKIP LOCKED` real |
| `test_postgres_e2e_does_not_call_gee_or_llm` | Ningún módulo GEE/LLM fue importado |
| `test_postgres_e2e_does_not_create_tables_manually` | Sin DDL manual en el archivo |
| + 10 adicionales | Score, ranking, gaps, estado HTTP, extracción controlada, campos requeridos |

### Confirmaciones

- PostgreSQL real: ✓ (usa `pg_migrated`, tablas creadas por Alembic)
- Alembic real: ✓ (`downgrade base → upgrade head`)
- RelayWorker real: ✓ (`FOR UPDATE SKIP LOCKED` verificado por inspección)
- Sin SQLite: ✓ (verificado por test estático y arquitectura)
- Sin DDL manual: ✓ (verificado por test estático)
- Sin LockFreeRelayWorker: ✓ (verificado por test estático y de comportamiento)
- Sin GEE ni LLM: ✓ (verificado por test de módulos importados)
- Solo lote 25B: ✓

### Limitaciones

- La geometría de la parcela proviene de un puerto controlado (no se inserta en `parcels`) para evitar la complejidad de codificación WKB/WKT de PostGIS en tests de fixture.
- Los rulebooks provienen de puertos controlados para evitar insertar la cadena completa de FK (`rulebooks → rulebook_criteria → rulebook_phases → rulebook_phase_requirements`).
- La saga se detiene en `EVALUACION_COMPLETADA` (no llega a `RECOMENDACION_COMPLETADA` porque no se registra handler para `GENERAR_RECOMENDACION_SOLICITADA`). El InMemoryEventBus simplemente ignora mensajes sin handler registrado.
- No se valida la recomendación LLM (fuera del alcance del lote 25B).
