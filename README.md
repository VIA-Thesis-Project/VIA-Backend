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
$env:JWT_SECRET_KEY="cambia-esto-por-una-clave-local-de-32-bytes-minimo"

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

## Crear usuario admin inicial

Antes de usar `/auth/login` es necesario insertar al menos un usuario con rol `ADMINISTRADOR`. El script `scripts/seed_admin_user.py` es idempotente: crea el usuario si no existe o actualiza su contraseña y rol si ya existe.

```powershell
$env:DATABASE_URL="postgresql+psycopg2://via_user:via_password@localhost:5433/via_test"
$env:SEED_ADMIN_EMAIL="admin@via.local"
$env:SEED_ADMIN_PASSWORD="Admin123456"
$env:SEED_ADMIN_NAME="Administrador VIA"   # opcional

python scripts/seed_admin_user.py
```

## Sembrar rulebooks diagnósticos

Antes de ejecutar la demo es necesario tener rulebooks activos en la base de datos. El script es idempotente.

```powershell
$env:DATABASE_URL="postgresql+psycopg2://via_user:via_password@localhost:5433/via_test"

python scripts/seed_diagnostic_rulebooks.py
```

Esto crea rulebooks sintéticos para 5 cultivos de demo: `demo_papa`, `demo_maiz`, `demo_quinua`, `demo_palta`, `demo_arandano`.

> **Advertencia:** estos rulebooks son fixtures diagnósticos para validación funcional. No corresponden a datos INIA ni constituyen guía agronómica real.

## Ejecutar demo E2E trazable

La demo registra una parcela desde un archivo GeoJSON, inicia una evaluación, procesa el Outbox con GEE real, calcula el MCDA y genera un reporte completo de trazabilidad en `artifacts/demo_runs/`.

Primero configurar las variables de entorno adicionales:

```powershell
$env:VIA_API_BASE_URL="http://127.0.0.1:8000"
$env:VIA_ADMIN_EMAIL="admin@via.local"
$env:VIA_ADMIN_PASSWORD="Admin123456"
```

Luego ejecutar la demo (el servidor FastAPI debe estar corriendo):

```powershell
python scripts/run_traceable_e2e_demo.py `
  --geojson-file examples/parcels/parcela_humalla.geojson `
  --start-date 2025-01-01 `
  --end-date 2025-12-31 `
  --max-rounds 10 `
  --pause-seconds 1 `
  --until-completed
```

Parcelas de ejemplo disponibles en `examples/parcels/`:

* `parcela_humalla.geojson` — valle costero, zona Huaura-Sayán
* `parcela_oyon.geojson` — sierra, distrito de Oyón

Cada ejecución genera un directorio en `artifacts/demo_runs/<timestamp>_<evaluation_id>/` con 15 archivos JSON de trazabilidad y un `trace_report.md` legible.

## Login

```http
POST /auth/login
Content-Type: application/json

{
  "email": "admin@via.local",
  "password": "Admin123456"
}
```

Responde `200` con `access_token` (JWT Bearer) si las credenciales son válidas, o `401` si no lo son.

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
* Despliegue productivo
