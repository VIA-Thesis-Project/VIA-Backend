# Deploy en Render

Esta guia resume la configuracion necesaria para desplegar VIA en Render usando el blueprint `render.yaml`.

## Blueprint

El servicio `via-api` ejecuta:

1. Instalacion de dependencias con `requirements.txt` y restricciones de `requirements.lock`.
2. Migraciones de base de datos con Alembic.
3. Creacion o actualizacion del usuario administrador inicial.
4. Carga idempotente de los cinco rulebooks productivos.
5. Arranque de FastAPI con Uvicorn sobre el puerto asignado por Render.

La base de datos `via-postgres` se crea desde el mismo blueprint y su `DATABASE_URL` se inyecta automaticamente.

## Variables obligatorias

Estas variables deben configurarse en Render antes del primer deploy productivo:

| Variable | Uso |
| --- | --- |
| `SEED_ADMIN_EMAIL` | Correo del usuario administrador inicial. |
| `SEED_ADMIN_PASSWORD` | Password inicial del administrador. |
| `CORS_ALLOWED_ORIGINS` | Origenes permitidos del frontend, separados por coma y sin slash final. |
| `OPENAI_API_KEY` | Generacion de recomendaciones con el proveedor `tavily_rag`. |
| `TAVILY_API_KEY` | Recuperacion documental del proveedor `tavily_rag`. |
| `GEE_PROJECT` | Proyecto de Google Earth Engine. |
| `GEE_SERVICE_ACCOUNT` | Cuenta de servicio usada por Earth Engine. |
| `GEE_PRIVATE_KEY_JSON` | Credencial JSON completa de la cuenta de servicio. |

`JWT_SECRET_KEY` se genera automaticamente por Render. Si se despliega fuera del blueprint, debe configurarse manualmente y no debe usarse el valor de desarrollo.

## Variables ya fijadas por el blueprint

| Variable | Valor |
| --- | --- |
| `PYTHON_VERSION` | `3.11.9` |
| `GEE_ENABLED` | `true` |
| `LLM_DRAFTING_PROVIDER` | `tavily_rag` |
| `OPENAI_RAG_MODEL` | `gpt-4o-mini` |
| `TAVILY_SEARCH_DEPTH` | `basic` |
| `JINA_READER_ENABLED` | `false` |
| `RELAY_WORKER_POLL_INTERVAL_SECONDS` | `1` |

## Checks antes del commit

Comandos recomendados:

```bash
python -m compileall -q via scripts
pytest -q tests/unit/test_config.py tests/unit/shared/test_application_runtime.py tests/unit/shared/test_relay_worker.py --tb=short
```

Si se desea validar con PostgreSQL local, levantar la base configurada en `DATABASE_URL` y ejecutar los tests de integracion correspondientes.

## Riesgos de despliegue

- Con `GEE_ENABLED=true`, la aplicacion intenta inicializar Earth Engine al arrancar. Credenciales ausentes o invalidas hacen fallar el deploy.
- Con `LLM_DRAFTING_PROVIDER=tavily_rag`, faltas de `OPENAI_API_KEY`, `OPENAI_RAG_MODEL` o `TAVILY_API_KEY` detienen el arranque por validacion de configuracion.
- El seeder de admin es intencionalmente obligatorio: si faltan `SEED_ADMIN_EMAIL` o `SEED_ADMIN_PASSWORD`, el deploy se detiene para evitar una instancia sin acceso administrativo.
- El seeder de rulebooks es idempotente, pero recrea los rulebooks productivos en cada arranque.
