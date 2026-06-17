# Demo Técnica: E2E Parcial MCDA sobre PostgreSQL Real

**VIA — Viabilidad Inteligente Agrícola**
Lote 25C — Documentación reproducible del flujo E2E parcial MCDA sobre PostgreSQL real

---

## Resumen ejecutivo

Este documento describe cómo reproducir la demostración técnica del flujo de evaluación MCDA de VIA
sobre infraestructura PostgreSQL real. El flujo es un **E2E parcial controlado**: ejerce
infraestructura real (PostgreSQL, Alembic, Outbox, RelayWorker, motor MCDA), pero usa puertos
controlados para aislar dependencias externas (GEE, LLM) que aún no forman parte del flujo de tests.

---

## Flujo técnico validado

```
POST /evaluaciones
  │
  ▼
EvaluationProcessManager
  → IniciarExtraccionAgroambiental (escrito en transactional.outbox_messages — PostgreSQL real)
  │
  ▼ RelayWorker real (WITH FOR UPDATE SKIP LOCKED — PostgreSQL native row locking)
  │
  ▼
AgroenvExtractionConsumer
  → ControlledExtractionClient (valores deterministas; no llama a GEE)
  → AgroenvVector persistido en transactional.agroenv_vectors (PostgreSQL real)
  → VectorAgroambientalGenerado (Outbox PostgreSQL real)
  │
  ▼ RelayWorker real (segunda ola)
  │
  ▼
EvaluationProcessManager
  → Transición INICIADA → EXTRACCION_COMPLETADA (PostgreSQL real)
  → EjecutarEvaluacionViabilidad (Outbox PostgreSQL real)
  │
  ▼ RelayWorker real (tercera ola)
  │
  ▼
ViabilityEvaluationConsumer
  → Motor MCDA difuso real (fuzzificación, pesos AHP-entropía, MGP, brechas agronómicas)
  → Resultados persistidos en transactional.evaluation_results (PostgreSQL real)
  → EvaluacionViabilidadCompletada (Outbox PostgreSQL real)
  │
  ▼ RelayWorker real (cuarta ola)
  │
  ▼
EvaluationProcessManager
  → Transición EXTRACCION_COMPLETADA → EVALUACION_COMPLETADA (PostgreSQL real)
  │
  ▼
GET /evaluaciones/{id}/estado        → EVALUACION_COMPLETADA (leído de PostgreSQL real)
GET /evaluaciones/{id}/resultado-mcda → ranking + gaps (leído de PostgreSQL real)
```

---

## 1. Requisitos previos

| Requisito | Versión |
|---|---|
| Docker y Docker Compose | ≥ 20.10 |
| Python | 3.11 |
| psycopg2-binary | instalado en entorno virtual |
| pytest | ≥ 9.0 |

---

## 2. Levantar PostgreSQL con Docker

El archivo `docker-compose.postgres.yml` en la raíz del proyecto inicia un PostgreSQL 15 con
PostGIS y pgvector usando credenciales locales de desarrollo:

```bash
docker compose -f docker-compose.postgres.yml up -d
```

El contenedor expone el puerto `5433` en localhost. Para verificar que está listo:

```bash
docker compose -f docker-compose.postgres.yml ps
```

Para detenerlo:

```bash
docker compose -f docker-compose.postgres.yml down
```

---

## 3. Configurar variables de entorno

Estas variables son necesarias para que VIA se conecte a la base de datos local de desarrollo.
Las credenciales corresponden a la configuración de `docker-compose.postgres.yml` (no son
credenciales de producción):

```bash
export DATABASE_URL=postgresql+psycopg2://via_user:via_password@localhost:5433/via_test
export DB_SCHEMA_TRANSACTIONAL=transactional
export DB_SCHEMA_DOCUMENTAL=documental
```

En Windows (PowerShell):

```powershell
$env:DATABASE_URL="postgresql+psycopg2://via_user:via_password@localhost:5433/via_test"
$env:DB_SCHEMA_TRANSACTIONAL="transactional"
$env:DB_SCHEMA_DOCUMENTAL="documental"
```

> **Nota:** Las variables `JWT_SECRET_KEY`, `GEE_SERVICE_ACCOUNT`, `LLM_API_KEY` y
> `EMBEDDING_API_KEY` no se requieren para ejecutar los tests E2E de este lote porque
> los puertos correspondientes están controlados (ver sección 5).

---

## 4. Ejecutar los tests

### 4.1 Tests estáticos (sin base de datos, sin servicios externos)

Verifican restricciones arquitectónicas y existencia de documentación:

```bash
pytest tests/static -q
```

Salida esperada (≥ 220 tests passing):

```
221 passed, 1 warning in 4.16s
```

### 4.2 Tests de integración PostgreSQL (22A + 22B + 25B)

Requieren PostgreSQL activo y `DATABASE_URL` configurado:

```bash
pytest tests/integration/postgres/ -q
```

Incluye:
- **22A**: conexión real, extensiones (pgcrypto, postgis, vector), esquemas, migraciones Alembic
- **22B**: Transactional Outbox, RelayWorker, idempotencia con `FOR UPDATE SKIP LOCKED`
- **25B**: flujo E2E parcial MCDA completo

### 4.3 E2E MCDA PostgreSQL (solo 25B)

```bash
pytest tests/integration/postgres/test_postgres_e2e_mcda.py -q
```

Los 20 tests del lote 25B cubren: estado de saga, resultado MCDA, ranking, brechas, outbox
dispatched, relay real, ausencia de GEE/LLM, endpoint HTTP.

### 4.4 Suite completa

```bash
pytest -q
```

Salida esperada (con PostgreSQL activo):

```
694 passed, 1 warning, 95 errors in ...s
```

> Los 95 errores y 1 fallo son **pre-existentes** y no pertenecen al lote 25C:
> - 95 errores: `test_postgres_tables.py` — falla de fixture de sesión en orden de colección
> - 1 fallo: `test_database_name_contains_test` — nombre de DB `via_test` en fixture de conexión

---

## 5. Qué está validado (infraestructura y lógica real)

| Componente | Estado | Detalle |
|---|---|---|
| PostgreSQL 15 | **Real** | garapadev/postgres-postgis-pgvector:15-slim |
| Migraciones Alembic | **Real** | `downgrade base → upgrade head` por fixture `pg_migrated` |
| Esquema `transactional` | **Real** | evaluation_sagas, outbox_messages, agroenv_vectors, evaluation_results, agronomy_gaps |
| Esquema `documental` | **Real** | creado por migración; no se inserta contenido en este lote |
| PostGIS | **Real** | extensión activa en la instancia PostgreSQL |
| pgvector | **Real** | extensión activa; columna VECTOR(1536) en document_fragments |
| Transactional Outbox | **Real** | `transactional.outbox_messages` con `FOR UPDATE SKIP LOCKED` |
| RelayWorker | **Real** | `via.shared.outbox.relay_worker.RelayWorker` (no `LockFreeRelayWorker`) |
| InMemoryEventBus | **Real** | sincrónico, despacha a handlers registrados |
| Consumidores idempotentes | **Real** | `processed_message_ids` con clave compuesta `(message_id, consumer)` |
| Motor MCDA difuso | **Real** | fuzzificación trapezoidal, pesos híbridos AHP-entropía, MGP, política crítica |
| Ranking de cultivos | **Real** | score DESC, crop_id ASC; rank_position NULL para NO_CONCLUYENTE / NO_VIABLE |
| Brechas agronómicas | **Real** | `agronomy_gaps` con `most_limiting_period`, `observed_value`, `gap_value` |
| Endpoint `resultado-mcda` | **Real** | lee de `evaluation_results` en PostgreSQL, no de objetos en memoria |
| Endpoint `estado` | **Real** | lee de `evaluation_sagas` en PostgreSQL |

---

## 6. Qué está controlado/simulado

| Puerto | Reemplazo | Motivo |
|---|---|---|
| `IGEEClient` | `ControlledExtractionClient` | Evita llamadas a Google Earth Engine (servicio externo) |
| `IParcelGeometryPort` | `ControlledParcelGeometryPort` | Evita insertar geometría PostGIS en `parcels` (complejidad WKB/WKT en fixture) |
| `IRulebookReadModelPort` | `ControlledRulebookReadModelPort` | Evita insertar cadena completa de FK: rulebooks→criteria→phases→phase_requirements |
| `IRulebookEvaluationPort` | `ControlledRulebookEvaluationPort` | Evita insertar rulebooks con criterios y fases en PostgreSQL |
| Recommendation BC | No registrado en bus | La saga se detiene en EVALUACION_COMPLETADA; no se invoca LLM ni RAG |

Los puertos controlados devuelven datos deterministas que ejercen el motor MCDA real sin depender
de servicios externos. El motor difuso procesa esos datos igual que lo haría con datos reales de GEE.

---

## 7. Qué NO está validado aún en este flujo

Los siguientes componentes **no forman parte** del E2E parcial controlado de los lotes 25A/25B/25C.
Se listan explícitamente para evitar malentendidos en la presentación:

| Componente | Estado | Comentario |
|---|---|---|
| GEE real en la saga | **No validado** | `ControlledExtractionClient` reemplaza la llamada a Google Earth Engine |
| Recommendation en E2E PostgreSQL | **No validado** | El handler de `GenerarRecomendacionSustentada` no está registrado en el bus de tests |
| LLM externo | **No validado** | No se llama a ninguna API de lenguaje en el flujo de tests |
| RAG documental real | **No validado** | El esquema `documental` existe pero no se insertan fragmentos ni embeddings en este lote |
| Despliegue productivo | **No validado** | El flujo corre en entorno local de desarrollo con Docker |
| Seguridad completa (IAM) | **No validado** | Los tests usan `TestClient` con `dependency_override` para IAM |

---

## 8. Datos de entrada del E2E

Los tests 25B usan datos deterministas para los dos cultivos candidatos:

| Cultivo | Variable | Q1 (2026) | Q2 (2026) |
|---|---|---|---|
| `maiz_amarillo_duro` | temperatura_media | 26.0 °C | 28.0 °C |
| `maiz_amarillo_duro` | precipitacion_acumulada | 800.0 mm | 480.0 mm |
| `papa` | temperatura_media | 20.0 °C | 21.0 °C |
| `papa` | precipitacion_acumulada | 750.0 mm | 650.0 mm |

Rulebook controlado (sin FK en BD):

- Temperatura: trapezoidal (18, 22, 30, 35 °C); peso AHP = 0.6
- Precipitación: trapezoidal (400, 600, 900, 1100 mm); peso AHP = 0.4
- Sin criterios críticos en el rulebook controlado (sin `critical_policy` activa)

---

## 9. Resultados esperados

### 9.1 Estado de saga

```
GET /evaluaciones/{evaluation_id}/estado
→ HTTP 200
→ { "status": "EVALUACION_COMPLETADA", ... }
```

### 9.2 Ejemplo de respuesta de `GET /evaluaciones/{id}/resultado-mcda`

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

**Interpretación:**
- `maiz_amarillo_duro` es VIABLE (score ~0.793, rank 1). La brecha de precipitación en Q2 es
  déficit de -120 mm respecto al óptimo de 600 mm.
- `papa` es CONDICIONAL (score ~0.536, rank 2). La temperatura en Q2 es 21 °C cuando el óptimo
  máximo del rango es 18 °C (exceso de +3 °C).

---

## 10. Limitaciones actuales

1. **Saga parcial**: El flujo termina en `EVALUACION_COMPLETADA`. La fase de recomendación
   (`RECOMENDACION_COMPLETADA`) no está ejercida porque el handler de
   `GenerarRecomendacionSustentada` no se registra en los tests (requeriría LLM o stub).

2. **Geometría de parcela no persistida en PostGIS**: `ControlledParcelGeometryPort` evita
   insertar geometría en la tabla `transactional.parcels`. La dirección de la parcela es un
   identificador UUID de fixture; la geometría real requeriría encoding WKB/WKT.

3. **Rulebooks no persistidos en BD**: Los rulebooks se construyen en memoria via
   `ControlledRulebookEvaluationPort`. La cadena completa de FK
   (`rulebooks → rulebook_criteria → rulebook_phases → rulebook_phase_requirements`) se omite
   para simplificar el fixture.

4. **GEE no integrado en la saga de tests**: La extracción de datos agroambientales usa datos
   deterministas controlados. GEE real requiere credenciales de servicio y latencia de red que
   hacen impracticable su uso en tests automatizados.

5. **IAM sin JWT real**: Los endpoints se llaman via `TestClient` con `dependency_override` para
   el usuario autenticado. La validación JWT completa no se ejerce en este lote.

---

## 11. Cómo presentar esto al asesor

VIA ya valida el núcleo del sistema de evaluación de viabilidad agrícola sobre infraestructura
real de PostgreSQL 15. El flujo demostrado cubre desde la solicitud HTTP hasta la consulta de
resultados MCDA, ejerciendo el patrón Transactional Outbox con `FOR UPDATE SKIP LOCKED`,
el Relay Worker sincrónico, el motor MCDA difuso completo (fuzzificación trapezoidal, pesos
híbridos AHP-entropía, Media Geométrica Ponderada, ranking de cultivos y brechas agronómicas),
y la persistencia de resultados en PostgreSQL con Alembic. La extracción agroambiental usa
puertos controlados para aislar la dependencia de Google Earth Engine, cuya integración real
se validará en una fase posterior. Esto constituye un E2E parcial controlado que demuestra
la viabilidad técnica del diseño sobre infraestructura real, separando claramente los módulos
ya validados de los que aún dependen de servicios externos.

---

## 12. Referencia de archivos

| Archivo | Propósito |
|---|---|
| `docker-compose.postgres.yml` | Levanta PostgreSQL 15 + PostGIS + pgvector local |
| `migrations/` | Migraciones Alembic del monolito |
| `tests/integration/postgres/test_postgres_e2e_mcda.py` | 20 tests del E2E parcial MCDA (lote 25B) |
| `tests/integration/postgres/conftest.py` | Fixtures: `pg_migrated`, `pg25b_cleanup`, `pg_engine` |
| `tests/static/test_lote25b_postgres_e2e_architecture.py` | 24 tests estáticos de arquitectura del lote 25B |
| `tests/static/test_lote25c_demo_documentation.py` | Tests estáticos de esta documentación (lote 25C) |
| `docs/postgres_validation.md` | Historial técnico de los lotes 22A, 22B y 25B |
| `docs/e2e_postgres_mcda_demo.md` | Este archivo |
| `via/shared/outbox/relay_worker.py` | RelayWorker real con `FOR UPDATE SKIP LOCKED` |
| `via/bounded_contexts/viability_evaluation/` | BC de evaluación MCDA (Core Domain) |
