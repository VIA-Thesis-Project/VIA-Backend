# VIA — Viabilidad Inteligente Agrícola

Backend de VIA, sistema para evaluar viabilidad agrícola de parcelas usando rulebooks agronómicos, extracción agroambiental con Google Earth Engine y evaluación MCDA.

## Estado actual

Este backend permite ejecutar el flujo mínimo:

1. Registrar una parcela en formato GeoJSON.
2. Registrar/publicar un rulebook.
3. Ejecutar una evaluación.
4. Extraer datos agroambientales con Google Earth Engine.
5. Calcular resultado MCDA.
6. Consultar ranking, score, categoría y brechas agronómicas.

La integración con Recommendation, LLM externo y RAG puede quedar para una fase posterior.

## Requisitos

* Python 3.11+
* Docker Desktop
* PostgreSQL con PostGIS y pgvector mediante Docker Compose
* Credenciales de Google Earth Engine en archivo JSON local

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

## Levantar PostgreSQL local

```bash
docker compose -f docker-compose.postgres.yml up -d
```

## Variables de entorno

En PowerShell:

```powershell
$env:DATABASE_URL="postgresql+psycopg2://via_user:via_password@localhost:5433/via_test"
$env:DB_SCHEMA_TRANSACTIONAL="transactional"
$env:DB_SCHEMA_DOCUMENTAL="documental"

$env:GEE_ENABLED="True"
$env:GEE_PROJECT="TU_PROJECT_ID"
$env:GEE_SERVICE_ACCOUNT="TU_SERVICE_ACCOUNT"
$env:GEE_PRIVATE_KEY_FILE="RUTA_LOCAL_AL_JSON"
$env:GEE_TEST_RUN_REAL="1"

$env:LLM_DRAFTING_PROVIDER="template"
```

No subir el archivo JSON de Google Earth Engine al repositorio.

## Migraciones

```bash
alembic upgrade head
```

## Ejecutar tests normales

```bash
pytest -q
```

## Ejecutar demo Leaflet → GEE → MCDA

```bash
python scripts/leaflet_to_gee_mcda_demo.py
```

La demo registra una parcela tipo Leaflet, crea/publica un rulebook, ejecuta la saga con GEE real y consulta el resultado MCDA.

## Endpoints principales

### Crear parcela

```http
POST /parcelas
```

La geometría debe enviarse como GeoJSON estándar. Importante: Leaflet usa coordenadas `[lat, lng]`, pero GeoJSON usa `[lng, lat]`.

### Ejecutar evaluación

```http
POST /evaluaciones
```

### Consultar estado

```http
GET /evaluaciones/{evaluation_id}/estado
```

### Consultar resultado MCDA

```http
GET /evaluaciones/{evaluation_id}/resultado-mcda
```

## Respuesta esperada del resultado MCDA

El endpoint devuelve:

* `evaluation_id`
* `status`
* `results`
* `crop_id`
* `score`
* `rank_position`
* `viability_category`
* `calc_condition`
* `gaps`
* `limiting_factors`
* `missing_criteria`
* `unrecognized_variables`

## Nota para frontend

El frontend debe convertir correctamente la geometría dibujada en Leaflet:

* Leaflet: `[lat, lng]`
* GeoJSON esperado por backend: `[lng, lat]`

Si el orden se envía mal, Google Earth Engine consultará una ubicación incorrecta.

## Alcance actual

Validado:

* PostgreSQL real
* PostGIS
* pgvector
* Alembic
* Transactional Outbox
* RelayWorker
* Google Earth Engine real
* Evaluación MCDA
* Ranking y resultado por endpoint

Pendiente o posterior:

* Recommendation final en frontend
* LLM externo
* RAG documental
* despliegue productivo
