# Lote 28A — Prueba MVP: Leaflet → GEE Real → Resultado MCDA

## Objetivo

Validar el flujo mínimo funcional que un frontend Leaflet usaría para solicitar una
evaluación agroambiental completa:

1. El usuario dibuja una parcela en Leaflet → se genera un GeoJSON Polygon en `[lng, lat]`
2. El frontend llama `POST /parcelas` → la parcela queda registrada con ID en PostgreSQL
3. El frontend llama `POST /evaluaciones` → inicia la saga asincrónica
4. La saga extrae datos reales de Google Earth Engine para la geometría de la parcela
5. El MCDA difuso genera un ranking de cultivos y brechas agronómicas
6. El frontend consulta `GET /evaluaciones/{id}/resultado-mcda` → ranking + brechas

> **MVP técnico**: Este flujo valida la plomería real (PostgreSQL + GEE + MCDA) de extremo a
> extremo. No incluye Recommendation, LLM, RAG, ni UI Leaflet real.

---

## Advertencia crítica: Leaflet vs GeoJSON

Leaflet usa el formato `[lat, lng]` (latitud primero) en sus callbacks.
El estándar GeoJSON usa `[lng, lat]` (longitud primero).

**El error más común en integración Leaflet→VIA** es enviar coordenadas invertidas:

```javascript
// ❌ Incorrecto — Leaflet [lat, lng]
const bounds = layer.getBounds();
const coords = [[bounds.getSouth(), bounds.getWest()], ...]; // INCORRECTO

// ✅ Correcto — GeoJSON [lng, lat]
const latlngs = layer.getLatLngs()[0];
const coords = latlngs.map(p => [p.lng, p.lat]);  // lng primero
coords.push(coords[0]);  // cerrar el anillo
const geojson = { type: "Polygon", coordinates: [coords] };
```

VIA acepta ambos `Polygon` y `MultiPolygon` en formato WGS-84 `[lng, lat]`.
Un `Polygon` de entrada se normaliza internamente a `MultiPolygon` para persistencia.

---

## Prerequisitos

| Componente | Requisito |
|-----------|-----------|
| Python | ≥ 3.11 |
| PostgreSQL | ≥ 15 con extensiones `postgis`, `pgcrypto`, `vector` |
| Extensión GEE | Service account con acceso a Earth Engine |
| Google Cloud | Proyecto habilitado para Earth Engine API |

---

## Variables de entorno

```bash
# PostgreSQL (obligatorio)
export DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/via_test

# GEE (obligatorio solo para prueba real)
export GEE_PROJECT=tu-proyecto-gcp
export GEE_SERVICE_ACCOUNT=tu-cuenta@proyecto.iam.gserviceaccount.com
export GEE_PRIVATE_KEY_FILE=/ruta/a/keyfile.json   # no incluir en código fuente

# VIA app (opcionales — defaults usables)
export GEE_ENABLED=true
export GEE_TIMEOUT_SECONDS=60
export GEE_MAX_RETRIES=3

# Para activar la prueba opt-in
export GEE_TEST_RUN_REAL=1
```

**Seguridad:**
- No hardcodear credenciales en código fuente
- No incluir el archivo JSON de service account en el repositorio
- Agregar `*.json` al `.gitignore` si el key file está en el proyecto

---

## PostgreSQL con Docker

```bash
docker run --name via_postgres \
  -e POSTGRES_USER=via \
  -e POSTGRES_PASSWORD=via_password \
  -e POSTGRES_DB=via_test \
  -p 5432:5432 \
  -d postgis/postgis:15-3.4

# Instalar extensiones adicionales
docker exec -it via_postgres psql -U via -d via_test -c "
  CREATE EXTENSION IF NOT EXISTS pgcrypto;
  CREATE EXTENSION IF NOT EXISTS vector;
"
```

Luego ejecutar las migraciones:

```bash
export DATABASE_URL=postgresql+psycopg2://via:via_password@localhost:5432/via_test
alembic downgrade base && alembic upgrade head
```

---

## Configurar GEE

1. Crear un proyecto en Google Cloud Console
2. Habilitar la API de Google Earth Engine
3. Crear una service account con rol de lector en Earth Engine
4. Descargar el archivo JSON de credenciales
5. Registrar la service account en Earth Engine en:
   `https://code.earthengine.google.com/register`

```bash
export GEE_PROJECT=via-tp
export GEE_SERVICE_ACCOUNT=tu-extractor@tu-proyecto.iam.gserviceaccount.com
export GEE_PRIVATE_KEY_FILE=/ruta/segura/al/keyfile.json
```

---

## GeoJSON correcto `[lng, lat]`

Polígono de ejemplo cerca de Lima, Perú (~100 m × 100 m):

```json
{
  "type": "Polygon",
  "coordinates": [
    [
      [-76.010, -12.010],
      [-76.010, -12.011],
      [-76.009, -12.011],
      [-76.009, -12.010],
      [-76.010, -12.010]
    ]
  ]
}
```

> **Nota**: El primer y último punto deben ser idénticos (anillo cerrado).
> VIA valida esto y rechaza polígonos no cerrados con HTTP 422.

---

## Ejemplo: `POST /parcelas`

Requiere JWT con rol `ESPECIALISTA_TECNICO` o `ADMINISTRADOR`.

```http
POST /parcelas
Authorization: Bearer {token}
Content-Type: application/json

{
  "geometry": {
    "type": "Polygon",
    "coordinates": [
      [
        [-76.010, -12.010],
        [-76.010, -12.011],
        [-76.009, -12.011],
        [-76.009, -12.010],
        [-76.010, -12.010]
      ]
    ]
  },
  "metadata": {
    "name": "Parcela Leaflet Demo",
    "description": "Parcela de prueba para integración GEE real",
    "crs": "EPSG:4326"
  }
}
```

**Respuesta (201 Created):**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "owner_id": "...",
  "geometry": {
    "type": "MultiPolygon",
    "coordinates": [[[ [-76.010, -12.010], [-76.010, -12.011], ... ]]]
  },
  "metadata": {
    "name": "Parcela Leaflet Demo",
    "description": "Parcela de prueba para integración GEE real",
    "crs": "EPSG:4326"
  }
}
```

> La geometría se **normaliza automáticamente** de `Polygon` → `MultiPolygon` al persistir.

---

## Ejemplo: `POST /rulebooks`

Requiere JWT con rol `ADMINISTRADOR`. Crea un rulebook mínimo con un criterio de NIR (B8 Sentinel-2).

```http
POST /rulebooks
Authorization: Bearer {admin_token}
Content-Type: application/json

{
  "crop_id": "maiz_gee_test",
  "criteria": [
    {
      "id": "00000001-0000-4000-8000-000000000028",
      "name": "vigor_nir",
      "is_critical": false,
      "critical_policy": null,
      "penalty_factor": null,
      "ahp_weight": 1.0,
      "doc_source": "Sentinel-2 NIR B8 — reflectancia superficial"
    }
  ],
  "phases": [
    {
      "id": "00000002-0000-4000-8000-000000000028",
      "name": "desarrollo",
      "duration_days": 90,
      "sequence_order": 1
    }
  ],
  "phase_requirements": [
    {
      "id": "00000003-0000-4000-8000-000000000028",
      "criterion_id": "00000001-0000-4000-8000-000000000028",
      "phase_id": "00000002-0000-4000-8000-000000000028",
      "membership_fn": {
        "type": "TRAPEZOIDAL",
        "a": 0.0,
        "b": 100.0,
        "c": 9900.0,
        "d": 10001.0
      },
      "phase_weight": 1.0,
      "temporal_periods": [
        { "period_key": "2024-Q2", "temporal_weight": 0.6 },
        { "period_key": "2024-Q3", "temporal_weight": 0.4 }
      ],
      "extraction": {
        "variable_name": "nir_reflectancia",
        "dataset_key": "COPERNICUS/S2_SR_HARMONIZED",
        "band": "B8",
        "unit": "reflectance_scaled",
        "temporal_resolution": "monthly",
        "scale": 30.0,
        "reducer": "mean",
        "aggregation_method": "mean",
        "fallback_allowed": true
      }
    }
  ]
}
```

**Respuesta (201 Created):**

```json
{
  "id": "rulebook-uuid",
  "crop_id": "maiz_gee_test",
  "version": 1,
  "status": "DRAFT"
}
```

---

## Ejemplo: publicar el rulebook

```http
POST /rulebooks/{rulebook_id}/publish
Authorization: Bearer {admin_token}
```

**Respuesta (200 OK):**

```json
{
  "id": "rulebook-uuid",
  "crop_id": "maiz_gee_test",
  "version": 1,
  "status": "ACTIVE"
}
```

---

## Ejemplo: `POST /evaluaciones`

No requiere token para el endpoint de inicio de evaluación.

```http
POST /evaluaciones
Content-Type: application/json

{
  "parcel_id": "550e8400-e29b-41d4-a716-446655440000",
  "requested_by": "dddddddd-eeee-4000-8000-ffffffffffff",
  "crop_candidates": ["maiz_gee_test"],
  "temporal_window": {
    "start": "2024-06-01",
    "end": "2024-08-31"
  }
}
```

**Respuesta (202 Accepted):**

```json
{
  "evaluation_id": "aaaaaaaa-bbbb-4000-8000-cccccccccccc",
  "status": "INICIADA"
}
```

---

## Consulta de estado

```http
GET /evaluaciones/{evaluation_id}/estado
```

**Respuesta — saga en curso (200):**

```json
{
  "evaluation_id": "aaaaaaaa-bbbb-4000-8000-cccccccccccc",
  "status": "EXTRACCION_COMPLETADA",
  "current_phase": "EXTRACCION_COMPLETADA",
  "last_transition": "2024-06-01T12:00:00Z",
  "failure_reason": null
}
```

Estados posibles: `INICIADA → EXTRACCION_COMPLETADA → EVALUACION_COMPLETADA → FALLIDA`.

---

## Ejemplo: `GET /resultado-mcda`

```http
GET /evaluaciones/{evaluation_id}/resultado-mcda
```

**Respuesta (200 OK) cuando EVALUACION_COMPLETADA:**

```json
{
  "evaluation_id": "aaaaaaaa-bbbb-4000-8000-cccccccccccc",
  "status": "EVALUACION_COMPLETADA",
  "results": [
    {
      "crop_id": "maiz_gee_test",
      "score": 0.95,
      "rank_position": 1,
      "calc_condition": "DEFINITIVO",
      "viability_category": "VIABLE",
      "gaps": [
        {
          "criterion_id": "vigor_nir_id",
          "phase_id": "desarrollo_id",
          "most_limiting_period": "2024-Q2",
          "observed_value": 2500.0,
          "optimal_limit": 9900.0,
          "gap_value": -7400.0
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

> Si GEE devolvió `None` para todos los períodos (sin píxeles válidos), la condición
> del cálculo será `PARCIAL` o `NO_CONCLUYENTE` y el resultado seguirá siendo válido
> gracias a `fallback_allowed: true` en el rulebook.

---

## Flujo completo en producción

```
Frontend Leaflet
  │ dibuja polígono → latlngs.map(p => [p.lng, p.lat])
  ▼
POST /parcelas          → parcel_id
  │
POST /rulebooks         → rulebook_id (admin)
POST /rulebooks/publish → status=ACTIVE
  │
POST /evaluaciones      → evaluation_id
  │
[saga asincrónica]
  │ RelayWorker (FOR UPDATE SKIP LOCKED)
  │ → AgroenvExtractionConsumer
  │     GeeExtractionClient → COPERNICUS/S2_SR_HARMONIZED, banda B8
  │ → ViabilityEvaluationConsumer (MCDA difuso)
  ▼
GET /evaluaciones/{id}/resultado-mcda → ranking + brechas
```

---

## Ejecutar la prueba real opt-in

```bash
# 1. Configurar entorno
export DATABASE_URL=postgresql+psycopg2://via:password@localhost:5432/via_test
export GEE_PROJECT=tu-proyecto
export GEE_SERVICE_ACCOUNT=tu-cuenta@proyecto.iam.gserviceaccount.com
export GEE_PRIVATE_KEY_FILE=/ruta/al/keyfile.json
export GEE_TEST_RUN_REAL=1

# 2. Asegurar que las migraciones están aplicadas
alembic downgrade base && alembic upgrade head

# 3. Ejecutar la prueba opt-in
pytest tests/integration/postgres/test_postgres_e2e_leaflet_gee_mcda.py -v

# 4. O ejecutar el script demostrativo
python scripts/leaflet_to_gee_mcda_demo.py
```

**Sin GEE real (test estáticos siempre corren):**

```bash
pytest tests/static -q   # siempre pasan, no requieren GEE ni DB
pytest -q                # GEE tests se saltan, 0 fallos
```

---

## Dataset GEE utilizado

| Parámetro | Valor |
|-----------|-------|
| Colección | `COPERNICUS/S2_SR_HARMONIZED` |
| Banda | `B8` (NIR, reflectancia superficial escalada) |
| Reducer | `mean` |
| Escala | 30 m |
| Período | Junio–Agosto 2024 |
| Polígono | Lima, Perú (~100 m × 100 m) |

Los valores de `B8` en Sentinel-2 SR Harmonized van de 0 a 10 000 DN.
La función de membresía usada en la demo acepta cualquier valor en [100, 9900] con
membresía 1.0, haciéndola robusta ante variaciones estacionales o de cobertura.

---

## Ranking y brechas

El resultado MCDA incluye:

- **rank_position**: posición en el ranking de cultivos (1 = más viable)
- **score**: índice de viabilidad [0.0, 1.0]
- **viability_category**: `VIABLE`, `CONDICIONAL`, o `NO_VIABLE`
- **calc_condition**: `DEFINITIVO` (todos los datos), `PARCIAL` (datos incompletos), `NO_CONCLUYENTE`
- **gaps**: diferencia entre valor observado y límite óptimo del rulebook
  - `gap_value < 0`: déficit (el valor está por debajo del rango óptimo)
  - `gap_value > 0`: exceso (el valor está por encima del rango óptimo)
- **limiting_factors**: criterios con membresía = 0.0 (condición crítica)

---

## Limitaciones de este MVP

- **Sin UI Leaflet**: el flujo se documenta y prueba a nivel de API; la integración real
  de Leaflet requiere un frontend web separado.
- **Sin Recommendation**: la saga se detiene en `EVALUACION_COMPLETADA`; la generación
  de texto recomendatorio (LLM) no está activada en este flujo.
- **Sin LLM / RAG**: no se llama a Gemini, Vertex, ni ningún modelo de lenguaje.
- **Sin producción completa**: el relay worker corre manualmente en tests; en producción
  correría como hilo de fondo o proceso separado.
- **Rulebook mínimo**: el rulebook de demo usa un solo criterio (NIR B8); un rulebook
  agrónomicamente completo tendría temperatura, precipitación, suelo, etc.
- **Temporal resolution simplificada**: ambos períodos (Q2 y Q3) usan el mismo rango
  de fechas (ventana temporal completa) porque el dominio de rulebooks no persiste
  fechas absolutas por período; solo pesos relativos.

## Qué queda fuera

- Recommendation (generación de texto con LLM)
- RAG (recuperación documental con embeddings)
- Gemini, Vertex, local_http
- Nuevos endpoints, nueva lógica MCDA, cambios de dominio
- Frontend Leaflet real
- Despliegue en producción
