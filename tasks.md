# Tasks Document — VIA: Viabilidad Inteligente Agrícola

## 1. Foundation

* [ ] 1.1 Crear la estructura base del monolito modular

  * Objetivo: Crear el esqueleto de carpetas del monolito FastAPI con los 7 bounded contexts aprobados y las capas de Clean Architecture por contexto.
  * Archivos: `via/`, `via/main.py`, `via/shared/`, `via/bounded_contexts/{iam,parcel_management,rulebook_management,document_management,agroenv_extraction,viability_evaluation,recommendation}/`.
  * Depende de: Ninguna.
  * Criterio de aceptacion: La estructura contiene exactamente los 7 bounded contexts aprobados, cada uno con `domain`, `application`, `infrastructure` e `interfaces`; no se crean bounded contexts adicionales ni microservicios.
  * Prueba: Validacion manual.

* [ ] 1.2 Definir paquetes Python e imports permitidos

  * Objetivo: Inicializar `__init__.py` y fijar la regla de dependencias hacia adentro para evitar que dominio importe FastAPI, SQLAlchemy, Event Bus o adaptadores externos.
  * Archivos: `via/**/__init__.py`, `tests/static/test_domain_dependencies.py`.
  * Depende de: 1.1.
  * Criterio de aceptacion: Los modulos de dominio no tienen imports directos ni transitivos hacia infraestructura, interfaces, FastAPI, SQLAlchemy ni bus.
  * Prueba: Unit test.

* [ ] 1.3 Configurar punto de entrada FastAPI del monolito

  * Objetivo: Crear la aplicacion FastAPI unica y preparar el registro de routers sin implementar casos de uso todavia.
  * Archivos: `via/main.py`.
  * Depende de: 1.1.
  * Criterio de aceptacion: Existe una unica app FastAPI para el monolito modular; no se crean procesos HTTP separados por bounded context.
  * Prueba: Validacion manual.

## 2. Configuration

* [ ] 2.1 Implementar configuracion centralizada por variables de entorno

  * Objetivo: Definir settings para nombre de aplicacion, base de datos, JWT, GEE, LLM, embeddings, RAG, outbox, relay worker, MCDA, parcelas y rulebooks.
  * Archivos: `via/config.py`, `.env.example`.
  * Depende de: 1.1.
  * Criterio de aceptacion: Existe `APP_NAME=VIA - Viabilidad Inteligente Agrícola`; `DATABASE_URL` usa el esquema `postgresql+psycopg2://`; existen `DB_SCHEMA_TRANSACTIONAL=transactional` y `DB_SCHEMA_DOCUMENTAL=documental`; no aparecen `asyncpg` ni `AsyncSession`.
  * Prueba: Unit test.

* [ ] 2.2 Validar parametros criticos de configuracion

  * Objetivo: Rechazar configuraciones invalidas para `MCDA_ALPHA`, umbrales MCDA, tolerancia de rulebooks, intervalo del relay y maximos de RAG.
  * Archivos: `via/config.py`, `tests/unit/test_config.py`.
  * Depende de: 2.1.
  * Criterio de aceptacion: La aplicacion falla al iniciar si `MCDA_ALPHA` no esta en `[0,1]`, si `RELAY_WORKER_POLL_INTERVAL_SECONDS` supera 60 o si la URL de base de datos no usa `psycopg2`.
  * Prueba: Unit test.

## 3. Database and Infrastructure

* [ ] 3.1 Configurar SQLAlchemy sincrono con psycopg2

  * Objetivo: Crear `Engine`, `SessionFactory` sincrono y base declarativa compartida.
  * Archivos: `via/shared/database/session.py`, `via/shared/database/base.py`.
  * Depende de: 2.1.
  * Criterio de aceptacion: La sesion expuesta es `sqlalchemy.orm.Session`; no existe uso de `AsyncSession`, `create_async_engine` ni `asyncpg`.
  * Prueba: Unit test.

* [ ] 3.2 Declarar esquemas PostgreSQL aislados

  * Objetivo: Centralizar constantes de esquemas `transactional` y `documental` para todos los modelos ORM.
  * Archivos: `via/shared/database/base.py`.
  * Depende de: 3.1.
  * Criterio de aceptacion: Los modelos transaccionales declaran `schema="transactional"` y los documentales `schema="documental"`.
  * Prueba: Integration test.

* [ ] 3.3 Crear unidad de trabajo sincrona

  * Objetivo: Proveer una abstraccion simple de transaccion para application services, process manager, outbox y consumidores.
  * Archivos: `via/shared/database/unit_of_work.py`.
  * Depende de: 3.1.
  * Criterio de aceptacion: Commit y rollback se ejecutan sobre una sesion SQLAlchemy sincrona y pueden compartirse con el Outbox Writer en la misma transaccion.
  * Prueba: Unit test.

## 4. Initial Migrations

* [ ] 4.1 Crear modelos ORM mínimos y metadata compartida

  * Objetivo: Declarar modelos ORM mínimos por BC y componentes compartidos antes de generar migraciones, conectados a la metadata compartida de SQLAlchemy.
  * Archivos: `via/bounded_contexts/**/infrastructure/orm_models.py`, `via/shared/outbox/models.py`, `via/shared/orchestration/evaluation_process_manager/saga_orm.py`, `via/shared/database/base.py`.
  * Depende de: 3.1.
  * Criterio de aceptacion: Los ORM declaran los esquemas `transactional` o `documental` correctos; parcelas usan `GEOMETRY(MULTIPOLYGON, 4326)`; outbox incluye `correlation_id`; resultados incluyen `rank_position`; ORM y nombres de columnas esperados quedan en metadata compartida.
  * Prueba: Integration test.

* [ ] 4.2 Inicializar Alembic para el monolito

  * Objetivo: Configurar migraciones para todos los modelos del monolito sincrono usando metadata compartida.
  * Archivos: `alembic.ini`, `migrations/env.py`, `migrations/versions/`.
  * Depende de: 4.1.
  * Criterio de aceptacion: Alembic importa metadata compartida, usa `DATABASE_URL` con `psycopg2`, y autogenerate detecta los modelos ORM mínimos sin desconectarse de ellos.
  * Prueba: Validacion manual.

* [ ] 4.3 Crear migracion de esquemas y extensiones

  * Objetivo: Crear los esquemas `transactional` y `documental`, y habilitar extensiones requeridas como `pgcrypto`, PostGIS y pgvector segun aplique.
  * Archivos: `migrations/versions/*_create_schemas_and_extensions.py`.
  * Depende de: 4.2.
  * Criterio de aceptacion: La migracion crea ambos esquemas y mantiene aisladas las tablas transaccionales y documentales.
  * Prueba: Integration test.

* [ ] 4.4 Crear y validar migracion inicial de tablas principales

  * Objetivo: Crear tablas de usuarios, parcelas, rulebooks, vectores agroambientales, resultados, documentos, sagas, outbox e idempotencia.
  * Archivos: `migrations/versions/*_initial_tables.py`.
  * Depende de: 4.3.
  * Criterio de aceptacion: La migracion se genera o valida contra metadata compartida; ORM y DDL coinciden; `outbox_messages.id` es el `message_id` semantico y `outbox_messages` incluye `correlation_id`; `evaluation_results` incluye `rank_position`; `agronomy_gaps` incluye `most_limiting_period`; `evaluation_criterion_details` incluye `entropy_fallback_reason`; `rulebook_phase_requirements` contiene `membership_fn`; `rulebook_criteria` no contiene `membership_fn`; tablas transaccionales y documentales respetan sus esquemas.
  * Prueba: Integration test.

## 5. Internal Event Bus

* [ ] 5.1 Definir contrato y modelo base de mensajes

  * Objetivo: Crear el puerto del bus y la estructura comun para comandos y eventos.
  * Archivos: `via/shared/event_bus/message.py`, `via/shared/event_bus/event_bus_interface.py`.
  * Depende de: 1.1.
  * Criterio de aceptacion: Todo mensaje tiene `id`, `type`, `kind`, `payload`, `created_at` y `correlation_id` opcional; `kind` distingue `COMMAND` y `EVENT`.
  * Prueba: Unit test.

* [ ] 5.2 Implementar Event Bus interno en memoria

  * Objetivo: Permitir publicar mensajes y registrar handlers sin infraestructura externa.
  * Archivos: `via/shared/event_bus/in_memory_event_bus.py`.
  * Depende de: 5.1.
  * Criterio de aceptacion: El bus enruta comandos y eventos a handlers registrados en memoria, de forma sincrona.
  * Prueba: Unit test.

## 6. Transactional Outbox

* [ ] 6.1 Crear modelo ORM de outbox

  * Objetivo: Persistir comandos y eventos en la base transaccional antes de publicarlos al bus.
  * Archivos: `via/shared/outbox/models.py`, migracion correspondiente.
  * Depende de: 4.4, 5.1.
  * Criterio de aceptacion: `outbox_messages` vive en `transactional`; `id` es el `message_id` semantico del mensaje y no se crea una segunda columna `message_id`; guarda `correlation_id UUID NULL`, payload JSON, tipo, kind, estado `PENDING|DISPATCHED|PERMANENT_FAILURE`, reintentos, error y timestamps; para la saga de evaluacion `correlation_id = evaluation_id`.
  * Prueba: Integration test.

* [ ] 6.2 Implementar Outbox Writer transaccional

  * Objetivo: Escribir mensajes en outbox dentro de la misma transaccion que el cambio de estado de dominio o saga.
  * Archivos: `via/shared/outbox/outbox_writer.py`.
  * Depende de: 6.1, 3.3.
  * Criterio de aceptacion: El writer no hace commit propio; usa la sesion activa para garantizar atomicidad; persiste `correlation_id` y preserva `outbox_messages.id` como `message_id` semantico del mensaje.
  * Prueba: Integration test.

## 7. Synchronous Relay Worker

* [ ] 7.1 Implementar relay worker sincrono

  * Objetivo: Leer mensajes `PENDING` de outbox y publicarlos al Event Bus con semantica at-least-once.
  * Archivos: `via/shared/outbox/relay_worker.py`.
  * Depende de: 5.2, 6.2.
  * Criterio de aceptacion: Usa `threading.Thread`, `time.sleep`, `Session` sincrona, ordena por `created_at` e `id`, publica mensajes preservando `correlation_id`, y no usa `asyncio`, `AsyncSession` ni `asyncpg`.
  * Prueba: Integration test.

* [ ] 7.2 Manejar reintentos y fallo permanente

  * Objetivo: Registrar errores de publicacion y marcar fallo permanente tras el maximo configurado.
  * Archivos: `via/shared/outbox/relay_worker.py`, `via/shared/outbox/models.py`.
  * Depende de: 7.1.
  * Criterio de aceptacion: Tras 5 fallos consecutivos por defecto, el mensaje queda como `PERMANENT_FAILURE` con `last_error` y timestamp del ultimo intento.
  * Prueba: Integration test.

## 8. Consumer Idempotency

* [ ] 8.1 Crear tabla de mensajes procesados

  * Objetivo: Registrar mensajes consumidos por consumidor para absorber duplicados.
  * Archivos: `via/shared/idempotency/processed_message_store.py`, migracion correspondiente.
  * Depende de: 4.4.
  * Criterio de aceptacion: La tabla `transactional.processed_message_ids` usa clave primaria compuesta `(message_id, consumer)`.
  * Prueba: Integration test.

* [ ] 8.2 Implementar mixin o servicio de consumidor idempotente

  * Objetivo: Proveer `is_already_processed` y `mark_as_processed` para process manager y consumidores de BCs.
  * Archivos: `via/shared/idempotency/processed_message_store.py`.
  * Depende de: 8.1.
  * Criterio de aceptacion: Un mensaje duplicado se descarta sin ejecutar efectos secundarios y cada consumidor puede procesar independientemente el mismo `message_id`.
  * Prueba: Unit test.

## 9. Process Manager and Saga State

* [ ] 9.1 Crear modelos y repositorio de saga

  * Objetivo: Persistir estado de evaluacion y transiciones auditables.
  * Archivos: `via/shared/orchestration/evaluation_process_manager/saga_orm.py`, `via/shared/orchestration/evaluation_process_manager/saga_repository.py`.
  * Depende de: 4.4, 3.3.
  * Criterio de aceptacion: Existen `evaluation_sagas` y `saga_transitions` con estado actual, historial, `triggered_by`, causa de fallo y timestamps.
  * Prueba: Integration test.

* [ ] 9.2 Definir comandos, eventos y puerto de read model de rulebooks

  * Objetivo: Crear contratos de saga, incluyendo `IRulebookReadModelPort.get_required_extraction_spec(...) -> RequiredExtractionSpec`.
  * Archivos: `via/shared/orchestration/evaluation_process_manager/commands.py`, `via/shared/orchestration/evaluation_process_manager/events.py`, `via/shared/orchestration/evaluation_process_manager/ports.py`.
  * Depende de: 5.1.
  * Criterio de aceptacion: `RequiredExtractionSpec` incluye por variable `variable_name`, `criterion_id`, `crop_id`, `phase_id`, `dataset_key`, `band`, `unit`, `temporal_resolution`, `spatial_resolution` o `scale`, `reducer`, `aggregation_method`, `temporal_window`, `temporal_periods`, `quality_mask` y `fallback_allowed`; el Process Manager no interpreta rulebooks, criterios, fases, datasets, bandas ni funciones de membresia.
  * Prueba: Unit test.

* [ ] 9.3 Implementar maquina de estados de la saga

  * Objetivo: Coordinar extraccion, evaluacion y recomendacion sin logica de dominio.
  * Archivos: `via/shared/orchestration/evaluation_process_manager/process_manager.py`, `via/shared/orchestration/evaluation_process_manager/handlers.py`.
  * Depende de: 6.2, 8.2, 9.1, 9.2.
  * Criterio de aceptacion: Las transiciones `INICIADA -> EXTRACCION_COMPLETADA -> EVALUACION_COMPLETADA -> RECOMENDACION_COMPLETADA` y `FALLIDA` escriben estado y mensaje outbox en una misma transaccion; los mensajes de la saga usan `correlation_id = evaluation_id`.
  * Prueba: Integration test.

* [ ] 9.4 Iniciar evaluacion desde endpoint de solicitud

  * Objetivo: Crear la solicitud de evaluacion y emitir `IniciarExtraccionAgroambiental` con `required_extraction_spec` ya consultado.
  * Archivos: `via/shared/orchestration/evaluation_process_manager/process_manager.py`, `via/bounded_contexts/viability_evaluation/interfaces/evaluation_router.py`.
  * Depende de: 9.3, 13.2.
  * Criterio de aceptacion: El payload contiene `parcel_id`, `temporal_window`, `crop_candidates` y `required_extraction_spec`; no contiene interpretacion interna del rulebook por parte del Process Manager.
  * Prueba: Integration test.

## 10. IAM

* [ ] 10.1 Modelar usuario, rol y reglas simples de IAM

  * Objetivo: Crear dominio IAM con `User`, `Role` y reglas simples de jerarquia/autorizacion, sin dependencias de JWT, hashing ni infraestructura.
  * Archivos: `via/bounded_contexts/iam/domain/user.py`, `via/bounded_contexts/iam/domain/role.py`.
  * Depende de: 1.1.
  * Criterio de aceptacion: Los roles son `ADMINISTRADOR`, `ESPECIALISTA_TECNICO` y `USUARIO_AGRICOLA`; no existe `TokenService`, `PasswordHasher`, hashing casero ni dependencia a librerias externas en dominio.
  * Prueba: Unit test.

* [ ] 10.2 Implementar puertos y servicios de aplicacion IAM

  * Objetivo: Autenticar usuarios, auditar intentos fallidos y validar jerarquia de roles.
  * Archivos: `via/bounded_contexts/iam/application/ports.py`, `via/bounded_contexts/iam/application/command_service.py`, `via/bounded_contexts/iam/application/query_service.py`.
  * Depende de: 10.1.
  * Criterio de aceptacion: `ITokenService` e `IPasswordHasher` viven en application ports y se implementan en infraestructura; el servicio de aplicacion usa `IPasswordHasher.verify(...)`; credenciales invalidas retornan error generico.
  * Prueba: Unit test.

* [ ] 10.3 Implementar repositorio, password hasher, JWT adapter y rutas IAM

  * Objetivo: Persistir usuarios, verificar passwords con una libreria segura y exponer login/refresh usando JWT.
  * Archivos: `via/bounded_contexts/iam/infrastructure/user_repository.py`, `via/bounded_contexts/iam/infrastructure/password_hasher.py`, `via/bounded_contexts/iam/infrastructure/jwt_adapter.py`, `via/bounded_contexts/iam/infrastructure/orm_models.py`, `via/bounded_contexts/iam/interfaces/auth_router.py`.
  * Depende de: 10.2, 4.4.
  * Criterio de aceptacion: `password_hasher.py` implementa `IPasswordHasher` con una libreria segura como bcrypt/passlib y no hashing casero; el adaptador JWT implementa `ITokenService` en infraestructura y respeta expiracion configurable.
  * Prueba: Integration test.

## 11. Parcel Management

* [ ] 11.1 Modelar parcela y validacion GeoJSON

  * Objetivo: Crear aggregate de parcela, value objects y validaciones de geometria WGS-84 para `Polygon` y `MultiPolygon`.
  * Archivos: `via/bounded_contexts/parcel_management/domain/parcel.py`, `via/bounded_contexts/parcel_management/domain/geometry_validator.py`, `via/bounded_contexts/parcel_management/domain/value_objects.py`.
  * Depende de: 1.1, 2.1.
  * Criterio de aceptacion: Solo se aceptan `Polygon` y `MultiPolygon`; un `Polygon` se normaliza a `MultiPolygon`; se detectan poligonos no cerrados, coordenadas fuera de rango, anillos con menos de 4 puntos, autointersecciones y area mayor a `PARCEL_MAX_AREA_HA` por poligono y total.
  * Prueba: Unit test.

* [ ] 11.2 Implementar comandos, queries y repositorio de parcelas

  * Objetivo: Registrar, actualizar, listar y consultar parcelas con historial de versiones.
  * Archivos: `via/bounded_contexts/parcel_management/application/*.py`, `via/bounded_contexts/parcel_management/infrastructure/*.py`.
  * Depende de: 11.1, 4.4.
  * Criterio de aceptacion: Las consultas solo retornan parcelas del propietario autenticado; los accesos a parcelas ajenas devuelven 403 sin revelar existencia; la persistencia usa preferentemente `GEOMETRY(MULTIPOLYGON, 4326)`.
  * Prueba: Integration test.

* [ ] 11.3 Exponer API de parcelas

  * Objetivo: Crear rutas protegidas para operaciones de parcela.
  * Archivos: `via/bounded_contexts/parcel_management/interfaces/parcel_router.py`, `via/bounded_contexts/parcel_management/interfaces/resources.py`.
  * Depende de: 10.3, 11.2.
  * Criterio de aceptacion: Las rutas aplican roles `ESPECIALISTA_TECNICO` o `ADMINISTRADOR` y devuelven codigos 201, 403, 404 o 422 segun corresponda.
  * Prueba: Integration test.

## 12. Ecophysiological Rulebook Management

* [ ] 12.1 Modelar rulebooks, criterios, fases y requisitos por fase

  * Objetivo: Crear dominio de rulebooks con pesos AHP precalculados y funciones de membresia por fase.
  * Archivos: `via/bounded_contexts/rulebook_management/domain/rulebook.py`, `via/bounded_contexts/rulebook_management/domain/criterion.py`, `via/bounded_contexts/rulebook_management/domain/phase_requirement.py`, `via/bounded_contexts/rulebook_management/domain/phenological_phase.py`, `via/bounded_contexts/rulebook_management/domain/membership_function.py`, `via/bounded_contexts/rulebook_management/domain/value_objects.py`.
  * Depende de: 1.1.
  * Criterio de aceptacion: `membership_fn` pertenece a `PhaseRequirement`, no a `Criterion`; el flujo consume pesos Fuzzy AHP ya construidos y no reconstruye matrices AHP.
  * Prueba: Unit test.

* [ ] 12.2 Validar pesos, rangos y politicas criticas

  * Objetivo: Implementar reglas de consistencia de rulebook antes de persistir.
  * Archivos: `via/bounded_contexts/rulebook_management/domain/weight_validator.py`, `via/bounded_contexts/rulebook_management/domain/membership_function.py`.
  * Depende de: 12.1, 2.1.
  * Criterio de aceptacion: Pesos AHP, pesos de fase y pesos temporales suman 1.0 dentro de tolerancia configurable; rangos y trapecios son validos.
  * Prueba: Unit test.

* [ ] 12.3 Implementar persistencia, versionado y publicacion atomica

  * Objetivo: Guardar versiones, publicar una version activa por cultivo y mantener historial.
  * Archivos: `via/bounded_contexts/rulebook_management/application/*.py`, `via/bounded_contexts/rulebook_management/infrastructure/*.py`.
  * Depende de: 12.2, 4.4.
  * Criterio de aceptacion: Publicar una version activa desactiva la anterior en la misma transaccion; consultar cultivo sin version activa devuelve 404.
  * Prueba: Integration test.

* [ ] 12.4 Exponer API de rulebooks

  * Objetivo: Crear endpoints para crear, publicar y consultar rulebooks.
  * Archivos: `via/bounded_contexts/rulebook_management/interfaces/rulebook_router.py`, `via/bounded_contexts/rulebook_management/interfaces/resources.py`.
  * Depende de: 10.3, 12.3.
  * Criterio de aceptacion: Crear y publicar requiere `ADMINISTRADOR`; consultar permite `ADMINISTRADOR` y `ESPECIALISTA_TECNICO`.
  * Prueba: Integration test.

## 13. Read Model RequiredExtractionSpec

* [ ] 13.1 Implementar read model de especificacion de extraccion

  * Objetivo: Proveer `RequiredExtractionSpec` desde el BC Rulebooks para la saga.
  * Archivos: `via/bounded_contexts/rulebook_management/application/query_service.py`, `via/bounded_contexts/rulebook_management/application/read_models.py`.
  * Depende de: 12.3.
  * Criterio de aceptacion: Dado un conjunto de cultivos y ventana temporal, retorna una especificacion por variable con `variable_name`, `criterion_id`, `crop_id`, `phase_id`, `dataset_key`, `band`, `unit`, `temporal_resolution`, `spatial_resolution` o `scale`, `reducer`, `aggregation_method`, `temporal_window`, `temporal_periods`, `quality_mask` y `fallback_allowed`, sin exponer ORM.
  * Prueba: Unit test.

* [ ] 13.2 Crear adaptador del puerto del Process Manager hacia Rulebooks

  * Objetivo: Implementar `IRulebookReadModelPort.get_required_extraction_spec(...)` usando el Query Service de rulebooks.
  * Archivos: `via/shared/orchestration/evaluation_process_manager/rulebook_read_model_adapter.py`.
  * Depende de: 9.2, 13.1.
  * Criterio de aceptacion: El Process Manager solo invoca `get_required_extraction_spec(...)` y reenvia `required_extraction_spec`; no interpreta rulebooks, criterios, fases, datasets, bandas ni mascaras.
  * Prueba: Integration test.

## 14. Agroenvironmental Extraction

* [ ] 14.1 Modelar vector agroambiental

  * Objetivo: Crear aggregate y entradas de variables con estados `OK` y `CRITERIO_FALTANTE`.
  * Archivos: `via/bounded_contexts/agroenv_extraction/domain/agroenv_vector.py`, `via/bounded_contexts/agroenv_extraction/domain/variable_entry.py`, `via/bounded_contexts/agroenv_extraction/domain/value_objects.py`.
  * Depende de: 1.1.
  * Criterio de aceptacion: El vector representa variables por periodo, criterio, cultivo, fase, fuente y ventana temporal sin conocer rulebooks.
  * Prueba: Unit test.

* [ ] 14.2 Implementar ACL y cliente externo de extraccion

  * Objetivo: Traducir respuestas externas de GEE al modelo interno de extraccion.
  * Archivos: `via/bounded_contexts/agroenv_extraction/infrastructure/gee_client.py`, `via/bounded_contexts/agroenv_extraction/infrastructure/extraction_acl.py`.
  * Depende de: 14.1, 2.1.
  * Criterio de aceptacion: La ACL produce `AgroenvVector` usando `required_extraction_spec`; variables no disponibles quedan como `CRITERIO_FALTANTE` cuando `fallback_allowed` lo permite; Extraccion no importa ni conoce el modelo interno del Rulebook.
  * Prueba: Unit test.

* [ ] 14.3 Consumir comando de extraccion y emitir eventos

  * Objetivo: Procesar `IniciarExtraccionAgroambiental`, persistir vector y publicar resultado o fallo via outbox.
  * Archivos: `via/bounded_contexts/agroenv_extraction/application/command_service.py`, `via/bounded_contexts/agroenv_extraction/infrastructure/extraction_repository.py`, `via/bounded_contexts/agroenv_extraction/interfaces/extraction_consumer.py`.
  * Depende de: 6.2, 8.2, 14.2.
  * Criterio de aceptacion: Exito emite `VectorAgroambientalGenerado`; fallo emite `ExtraccionFallida`; ambos via Transactional Outbox.
  * Prueba: Integration test.

## 15. Agricultural Viability Evaluation

* [ ] 15.1 Modelar aggregate de evaluacion y resultados por cultivo

  * Objetivo: Crear entidades de evaluacion, resultado por cultivo, detalles, brechas y factores limitantes.
  * Archivos: `via/bounded_contexts/viability_evaluation/domain/evaluation.py`, `via/bounded_contexts/viability_evaluation/domain/crop_result.py`, `via/bounded_contexts/viability_evaluation/domain/criterion_detail.py`, `via/bounded_contexts/viability_evaluation/domain/agronomy_gap.py`, `via/bounded_contexts/viability_evaluation/domain/limiting_factor.py`, `via/bounded_contexts/viability_evaluation/domain/value_objects.py`.
  * Depende de: 1.1.
  * Criterio de aceptacion: `CropResult` contiene `rank_position`; `CriterionDetail` contiene `entropy_fallback_reason`; `AgronomyGap` contiene `most_limiting_period`.
  * Prueba: Unit test.

* [ ] 15.2 Crear puertos ACL hacia rulebooks y vectores agroambientales

  * Objetivo: Evitar imports directos entre bounded contexts mediante adaptadores.
  * Archivos: `via/bounded_contexts/viability_evaluation/application/ports.py`, `via/bounded_contexts/viability_evaluation/infrastructure/rulebook_acl_adapter.py`, `via/bounded_contexts/viability_evaluation/infrastructure/agroenv_acl_adapter.py`.
  * Depende de: 12.3, 14.3, 15.1.
  * Criterio de aceptacion: El BC de evaluacion recibe DTOs traducidos a su modelo interno; no importa ORM ni dominio de otros BCs.
  * Prueba: Integration test.

* [ ] 15.3 Implementar servicio de aplicacion para ejecutar evaluacion

  * Objetivo: Orquestar el caso de uso `ExecuteEvaluationCommand`, cargando datos por ACL, invocando el MCDA difuso puro para cada cultivo candidato y delegando la persistencia/emision de salida a la tarea 17.2.
  * Archivos: `via/bounded_contexts/viability_evaluation/application/command_service.py`, `via/bounded_contexts/viability_evaluation/interfaces/evaluation_consumer.py`.
  * Depende de: 15.2, 16.10, 17.1.
  * Criterio de aceptacion: Consume `EjecutarEvaluacionViabilidad`, ejecuta calculo sin LLM y produce el resultado de aplicacion para persistencia; no construye ni emite directamente `EvaluacionCompletada` ni `VectorBrechasGenerado`.
  * Prueba: Integration test.

## 16. Fuzzy MCDA Services

* [ ] 16.1 Implementar alineacion fenologica

  * Objetivo: Mapear ventana temporal y duracion de fases del rulebook a periodos del vector agroambiental.
  * Archivos: `via/bounded_contexts/viability_evaluation/domain/services/phenological_alignment_service.py`.
  * Depende de: 15.1.
  * Criterio de aceptacion: Si no hay datos temporales suficientes, la fase queda no alineada y sus criterios se tratan como `CRITERIO_FALTANTE`.
  * Prueba: Unit test.

* [ ] 16.2 Implementar fuzificacion trapezoidal por criterio y fase

  * Objetivo: Calcular membresias en `[0,1]` usando `membership_fn` de `PhaseRequirement`.
  * Archivos: `via/bounded_contexts/viability_evaluation/domain/services/fuzzification_service.py`.
  * Depende de: 16.1.
  * Criterio de aceptacion: Soporta trapecios, triangulares y casos degenerados sin division por cero; nunca lee `membership_fn` desde `Criterion`.
  * Prueba: Unit test.

* [ ] 16.3 Implementar agregacion temporal

  * Objetivo: Agregar membresias por periodo dentro de una fase mediante Media Geometrica Ponderada.
  * Archivos: `via/bounded_contexts/viability_evaluation/domain/services/temporal_aggregation_service.py`.
  * Depende de: 16.2.
  * Criterio de aceptacion: Con membresia 0.0 retorna 0.0; con pesos normalizados retorna valor en `[0,1]`.
  * Prueba: Unit test.

* [ ] 16.4 Implementar agregacion por criterio

  * Objetivo: Combinar membresias agregadas por fase para cada criterio mediante Media Geometrica Ponderada.
  * Archivos: `via/bounded_contexts/viability_evaluation/domain/services/criterion_aggregation_service.py`.
  * Depende de: 16.3.
  * Criterio de aceptacion: Usa pesos de fase del rulebook y produce una membresia agregada por criterio.
  * Prueba: Unit test.

* [ ] 16.4.1 Implementar resolucion de criterios faltantes antes de agregacion multicriterio

  * Objetivo: Excluir criterios no criticos faltantes y detener el calculo ranking para criterios criticos faltantes sin regla alternativa antes de la agregacion multicriterio final.
  * Archivos: `via/bounded_contexts/viability_evaluation/domain/services/missing_criteria_service.py`.
  * Depende de: 16.4.
  * Criterio de aceptacion: Criterio critico faltante sin regla alternativa produce `NO_CONCLUYENTE` y no entra al ranking; criterio no critico faltante se excluye del calculo, se registra en `missing_criteria`, renormaliza una sola vez los pesos restantes a suma 1.0 y marca resultado `PARCIAL`; faltantes no criticos no se tratan como membresia 0.0.
  * Prueba: Unit test.

* [ ] 16.5 Implementar pesos por entropia con fallback total

  * Objetivo: Calcular pesos objetivos solo si la serie temporal es completa y suficiente.
  * Archivos: `via/bounded_contexts/viability_evaluation/domain/services/entropy_weights_service.py`.
  * Depende de: 16.4.1, 2.1.
  * Criterio de aceptacion: Si una serie es insuficiente, incompleta o tiene divergencia total menor al minimo, no se generan pesos parciales; se usa fallback total a AHP y se registra `entropy_fallback_reason`.
  * Prueba: Unit test.

* [ ] 16.6 Implementar combinacion convexa de pesos

  * Objetivo: Combinar pesos AHP precalculados y pesos por entropia con `w*_j = alpha*w_AHP_j + (1-alpha)*w_ENT_j`.
  * Archivos: `via/bounded_contexts/viability_evaluation/domain/services/hybrid_weights_service.py`.
  * Depende de: 16.5.
  * Criterio de aceptacion: Si no hay pesos de entropia, `w_hybrid = w_AHP`; los pesos finales suman 1.0 y ningun criterio con `w_AHP > 0` queda en cero cuando `alpha` esta en `(0,1)`.
  * Prueba: Unit test.

* [ ] 16.7 Implementar agregacion multicriterio por Media Geometrica Ponderada

  * Objetivo: Calcular score final por cultivo con membresias por criterio y pesos hibridos, aplicando el piso `MCDA_PENALIZE_EPSILON` antes de la MGP para criterios criticos con `critical_policy = PENALIZE` y membresia agregada `0.0`.
  * Archivos: `via/bounded_contexts/viability_evaluation/domain/services/multicriteria_aggregation_service.py`.
  * Depende de: 16.6, 2.1.
  * Criterio de aceptacion: Score siempre cae en `[0,1]`; si todas las membresias son 1.0, el score es 1.0; si un criterio critico `PENALIZE` tiene membresia agregada `0.0`, la MGP usa `MCDA_PENALIZE_EPSILON` para ese criterio antes de aplicar `penalty_factor`.
  * Prueba: Unit test.

* [ ] 16.8 Implementar aplicacion de `critical_policy`

  * Objetivo: Aplicar `NO_VIABLE` o `PENALIZE` cuando un criterio critico tiene membresia 0.0, despues de que la agregacion multicriterio haya usado `MCDA_PENALIZE_EPSILON` para evitar que `PENALIZE` quede anulado por un score 0 previo.
  * Archivos: `via/bounded_contexts/viability_evaluation/domain/services/critical_policy_service.py`.
  * Depende de: 16.7.
  * Criterio de aceptacion: `NO_VIABLE` asigna categoria `NO_VIABLE` y excluye ranking; `PENALIZE` multiplica el score calculado con epsilon por `penalty_factor`; ambas registran factor limitante; existe un test unitario que demuestra que `PENALIZE` no queda anulado por score 0 previo.
  * Prueba: Unit test.

* [ ] 16.9 Implementar clasificacion de condicion y categoria

  * Objetivo: Determinar `DEFINITIVO`, `PARCIAL`, `NO_CONCLUYENTE` y categoria `VIABLE`, `CONDICIONAL`, `NO_VIABLE`.
  * Archivos: `via/bounded_contexts/viability_evaluation/domain/services/viability_classifier_service.py`.
  * Depende de: 16.8, 2.1.
  * Criterio de aceptacion: La condicion de calculo no se confunde con la categoria de viabilidad; `NO_VIABLE` por politica critica no se sobrescribe por score.
  * Prueba: Unit test.

* [ ] 16.10 Implementar calculo de brechas usando el periodo mas limitante

  * Objetivo: Calcular brecha agronomica por criterio y fase usando el periodo con menor membresia.
  * Archivos: `via/bounded_contexts/viability_evaluation/domain/services/gap_calculation_service.py`.
  * Depende de: 16.4.
  * Criterio de aceptacion: Cada brecha guarda `most_limiting_period`, `observed_value`, `optimal_limit` y `gap_value`; el periodo elegido es `argmin` de membresias de la fase.
  * Prueba: Unit test.

## 17. Persistence of Results, Gaps, Limiting Factors and Traceability

* [ ] 17.1 Implementar repositorio de resultados de evaluacion

  * Objetivo: Persistir resultados, detalles por criterio, brechas, factores limitantes y trazabilidad completa.
  * Archivos: `via/bounded_contexts/viability_evaluation/infrastructure/evaluation_repository.py`, `via/bounded_contexts/viability_evaluation/infrastructure/orm_models.py`.
  * Depende de: 4.4, 15.1.
  * Criterio de aceptacion: Escribe solo en `transactional`; `evaluation_results.rank_position`, `evaluation_criterion_details.entropy_fallback_reason` y `agronomy_gaps.most_limiting_period` se persisten correctamente.
  * Prueba: Integration test.

* [ ] 17.2 Persistir ranking y eventos de evaluacion

  * Objetivo: Construir y persistir el ranking una sola vez, excluir `NO_CONCLUYENTE` y categoria `NO_VIABLE`, y crear los mensajes `EvaluacionCompletada` y `VectorBrechasGenerado` una sola vez.
  * Archivos: `via/bounded_contexts/viability_evaluation/application/command_service.py`, `via/bounded_contexts/viability_evaluation/infrastructure/outbox_adapter.py`.
  * Depende de: 17.1, 6.2.
  * Criterio de aceptacion: Ranking ordena por `score DESC` y desempata por `crop_id ASC`; solo cultivos incluidos reciben `rank_position`; cultivos `NO_CONCLUYENTE` o `NO_VIABLE` persisten `rank_position = NULL`; `EvaluacionCompletada` y `VectorBrechasGenerado` se crean via Transactional Outbox con `correlation_id = evaluation_id` solo en esta tarea y no se duplican desde 15.3.
  * Prueba: Integration test.

## 18. Technical Document Management

* [ ] 18.1 Modelar documentos y fragmentos

  * Objetivo: Crear aggregate documental con fragmentos, etiquetas de cultivo y metadatos.
  * Archivos: `via/bounded_contexts/document_management/domain/document.py`, `via/bounded_contexts/document_management/domain/fragment.py`, `via/bounded_contexts/document_management/domain/chunker.py`.
  * Depende de: 1.1.
  * Criterio de aceptacion: El chunker genera fragmentos trazables con conteo de tokens y referencia de pagina cuando aplique.
  * Prueba: Unit test.

* [ ] 18.2 Implementar repositorio documental aislado

  * Objetivo: Persistir documentos, fragmentos y embeddings en el esquema `documental`.
  * Archivos: `via/bounded_contexts/document_management/infrastructure/document_repository.py`, `via/bounded_contexts/document_management/infrastructure/embedding_adapter.py`, `via/bounded_contexts/document_management/infrastructure/orm_models.py`.
  * Depende de: 4.4, 18.1.
  * Criterio de aceptacion: Las consultas RAG usan solo tablas de `documental` y no hacen JOINs ni subconsultas hacia `transactional`.
  * Prueba: Integration test.

* [ ] 18.3 Exponer API de gestion documental

  * Objetivo: Permitir carga, eliminacion y busqueda de fragmentos tecnicos.
  * Archivos: `via/bounded_contexts/document_management/application/*.py`, `via/bounded_contexts/document_management/interfaces/document_router.py`, `via/bounded_contexts/document_management/interfaces/resources.py`.
  * Depende de: 10.3, 18.2.
  * Criterio de aceptacion: Carga y eliminacion requieren `ADMINISTRADOR`; busqueda devuelve fragmentos relevantes por umbral y maximo configurados.
  * Prueba: Integration test.

## 19. Supported Recommendation with RAG/LLM

* [ ] 19.1 Modelar recomendacion y prompt builder

  * Objetivo: Construir prompts con resultados MCDA precalculados y evidencia documental.
  * Archivos: `via/bounded_contexts/recommendation/domain/recommendation.py`, `via/bounded_contexts/recommendation/domain/prompt_builder.py`.
  * Depende de: 17.2, 18.3.
  * Criterio de aceptacion: El prompt incluye score, ranking, brechas y fragmentos; no solicita al LLM calcular viabilidad, membresias, pesos, scores ni brechas.
  * Prueba: Unit test.

* [ ] 19.2 Implementar adaptadores RAG y LLM

  * Objetivo: Recuperar hasta 5 fragmentos y llamar al LLM con reintentos configurados.
  * Archivos: `via/bounded_contexts/recommendation/infrastructure/document_search_adapter.py`, `via/bounded_contexts/recommendation/infrastructure/llm_adapter.py`.
  * Depende de: 19.1, 2.1.
  * Criterio de aceptacion: Si no hay fragmentos, el texto indica ausencia de evidencia suficiente; si el LLM falla tras 2 reintentos, se prepara fallo sin recomendacion.
  * Prueba: Integration test.

* [ ] 19.3 Consumir comando y persistir recomendacion validada

  * Objetivo: Procesar `GenerarRecomendacionSustentada`, validar respuesta y emitir evento.
  * Archivos: `via/bounded_contexts/recommendation/application/command_service.py`, `via/bounded_contexts/recommendation/infrastructure/recommendation_repository.py`, `via/bounded_contexts/recommendation/interfaces/recommendation_consumer.py`.
  * Depende de: 6.2, 8.2, 19.2.
  * Criterio de aceptacion: La respuesta no vacia menciona score y al menos una brecha; exito emite `RecomendacionValidada`, fallo emite `RecomendacionFallida`, siempre via outbox.
  * Prueba: Integration test.

## 20. Status and Result Queries

* [ ] 20.1 Implementar consulta de estado de saga

  * Objetivo: Exponer estado actual y ultima transicion de una evaluacion.
  * Archivos: `via/shared/orchestration/evaluation_process_manager/saga_repository.py`, `via/bounded_contexts/viability_evaluation/interfaces/evaluation_router.py`.
  * Depende de: 9.3.
  * Criterio de aceptacion: `GET /evaluaciones/{id}/estado` devuelve estados en curso, completado o fallido sin exponer IDs de outbox ni stack traces.
  * Prueba: Integration test.

* [ ] 20.2 Implementar query service de resultados completos

  * Objetivo: Retornar ranking con `rank_position`, scores, brechas, factores limitantes y recomendacion cuando la saga esta finalizada.
  * Archivos: `via/bounded_contexts/viability_evaluation/application/query_service.py`, `via/bounded_contexts/viability_evaluation/interfaces/resources.py`, `via/bounded_contexts/viability_evaluation/interfaces/evaluation_router.py`.
  * Depende de: 17.2, 19.3.
  * Criterio de aceptacion: Si el estado es `RECOMENDACION_COMPLETADA`, retorna resultado completo con `rank_position` por cultivo (`NULL` cuando no entra al ranking); si esta en curso, retorna 202; si esta `FALLIDA`, retorna fase y causa; si no existe, 404.
  * Prueba: Integration test.

## 21. Unit Tests

* [ ] 21.1 Cubrir servicios de dominio IAM, parcelas, rulebooks y documentos

  * Objetivo: Verificar reglas puras sin base de datos, FastAPI ni Event Bus.
  * Archivos: `tests/unit/iam/`, `tests/unit/parcel_management/`, `tests/unit/rulebook_management/`, `tests/unit/document_management/`.
  * Depende de: 10.1, 11.1, 12.2, 18.1.
  * Criterio de aceptacion: Las reglas de roles, geometria, pesos, rangos, membresia por fase y fragmentacion tienen cobertura unitaria.
  * Prueba: Unit test.

* [ ] 21.2 Cubrir Process Manager, Event Bus, Outbox Writer e idempotencia

  * Objetivo: Verificar componentes compartidos sin infraestructura externa compleja.
  * Archivos: `tests/unit/shared/`.
  * Depende de: 5.2, 6.2, 8.2, 9.3.
  * Criterio de aceptacion: Se prueban rutas felices, duplicados, transiciones invalidas y escritura atomica delegada al Unit of Work.
  * Prueba: Unit test.

* [ ] 21.3 Cubrir servicios MCDA difuso

  * Objetivo: Probar todos los servicios del nucleo de evaluacion en aislamiento.
  * Archivos: `tests/unit/viability_evaluation/`.
  * Depende de: 16.10.
  * Criterio de aceptacion: Existen tests para alineacion, fuzificacion, agregaciones, resolucion de faltantes, renormalizacion de pesos restantes, exclusion de no criticos faltantes, `PARCIAL`, `NO_CONCLUYENTE`, entropia con fallback, pesos hibridos, politica critica, clasificacion y brechas.
  * Prueba: Unit test.

## 22. Integration Tests

* [ ] 22.1 Probar migraciones y aislamiento de esquemas

  * Objetivo: Validar que la base PostgreSQL contiene exactamente los esquemas y tablas esperadas.
  * Archivos: `tests/integration/test_database_schema.py`.
  * Depende de: 4.4.
  * Criterio de aceptacion: Tablas transaccionales estan en `transactional`, tablas RAG en `documental`; ORM y DDL coinciden para columnas criticas (`outbox_messages.id` como `message_id` semantico, `correlation_id`, `rank_position`, `most_limiting_period`, `entropy_fallback_reason`, `GEOMETRY(MULTIPOLYGON, 4326)`); no hay uso de `asyncpg` ni `AsyncSession`.
  * Prueba: Integration test.

* [ ] 22.2 Probar outbox, relay worker e idempotencia con base real

  * Objetivo: Verificar at-least-once seguro para consumidores.
  * Archivos: `tests/integration/test_outbox_relay_worker.py`, `tests/integration/test_idempotent_consumers.py`.
  * Depende de: 7.2, 8.2.
  * Criterio de aceptacion: Mensajes pendientes se publican preservando `correlation_id` y se marcan `DISPATCHED`; fallos llegan a `PERMANENT_FAILURE`; duplicados no repiten efectos de dominio.
  * Prueba: Integration test.

* [ ] 22.3 Probar APIs principales del monolito

  * Objetivo: Validar contratos HTTP de IAM, parcelas, rulebooks, documentos, evaluaciones y resultados.
  * Archivos: `tests/integration/test_api_*.py`.
  * Depende de: 10.3, 11.3, 12.4, 18.3, 20.2.
  * Criterio de aceptacion: Los endpoints cumplen codigos esperados, roles, DTOs y no exponen detalles internos.
  * Prueba: Integration test.

## 23. MCDA Property-Based Tests

* [ ] 23.1 Probar invariantes de fuzificacion

  * Objetivo: Verificar que toda funcion trapezoidal valida produce membresias en `[0,1]`.
  * Archivos: `tests/property/test_fuzzification_invariants.py`.
  * Depende de: 16.2.
  * Criterio de aceptacion: Para parametros `a <= b <= c <= d` y valores arbitrarios, la salida siempre esta en `[0,1]`.
  * Prueba: Property-based test.

* [ ] 23.2 Probar invariantes de agregacion y pesos

  * Objetivo: Verificar rangos, normalizacion y estabilidad de MGP y pesos hibridos.
  * Archivos: `tests/property/test_mcda_invariants.py`.
  * Depende de: 16.7.
  * Criterio de aceptacion: Scores y membresias agregadas siempre estan en `[0,1]`; pesos hibridos suman 1.0 dentro de tolerancia.
  * Prueba: Property-based test.

* [ ] 23.3 Probar invariantes de ranking y brechas

  * Objetivo: Verificar ordenamiento determinista y seleccion del periodo mas limitante.
  * Archivos: `tests/property/test_ranking_and_gap_invariants.py`.
  * Depende de: 16.10, 17.2.
  * Criterio de aceptacion: Ranking ordena por `score DESC` y desempata por `crop_id ASC`; solo cultivos rankeados tienen `rank_position`; cultivos `NO_CONCLUYENTE` o `NO_VIABLE` tienen `rank_position = NULL`; toda brecha usa el periodo con menor membresia de la fase.
  * Prueba: Property-based test.

## 24. Application Composition and Runtime Wiring

* [ ] 24.1 Registrar routers del monolito en `main.py`

  * Objetivo: Ensamblar la aplicacion FastAPI unica usando `APP_NAME` como titulo y registrando los routers de IAM, parcelas, rulebooks, documentos, evaluaciones y consultas.
  * Archivos: `via/main.py`.
  * Depende de: 10.3, 11.3, 12.4, 18.3, 20.2.
  * Criterio de aceptacion: `main.py` usa `APP_NAME=VIA - Viabilidad Inteligente Agrícola` como titulo de FastAPI; todos los routers aprobados quedan montados en una sola app FastAPI; no se crean apps, procesos HTTP ni servicios separados por bounded context.
  * Prueba: Integration test.

* [ ] 24.2 Construir dependencias concretas de infraestructura

  * Objetivo: Instanciar y cablear repositorios, adapters, Unit of Work, OutboxWriter, Event Bus y servicios de aplicacion respetando Clean Architecture.
  * Archivos: `via/main.py`, `via/shared/runtime/container.py` o modulo equivalente de composicion.
  * Depende de: 3.3, 5.2, 6.2, 10.3, 11.2, 12.3, 14.3, 17.1, 18.2, 19.3.
  * Criterio de aceptacion: La composicion crea implementaciones concretas en el borde de infraestructura; los dominios no importan adaptadores, FastAPI, SQLAlchemy ni Event Bus.
  * Prueba: Integration test.

* [ ] 24.3 Registrar handlers y consumers en el Event Bus

  * Objetivo: Conectar Process Manager y consumidores de extraccion, evaluacion y recomendacion al Event Bus interno en memoria.
  * Archivos: `via/main.py`, `via/shared/runtime/event_bus_registration.py` o modulo equivalente.
  * Depende de: 9.3, 14.3, 15.3, 19.3, 24.2.
  * Criterio de aceptacion: El bus registra handlers para comandos y eventos de saga; los consumidores idempotentes se invocan con su nombre de consumidor y absorben duplicados por `(message_id, consumer)`.
  * Prueba: Integration test.

* [ ] 24.4 Iniciar y detener Relay Worker en lifespan de FastAPI

  * Objetivo: Gestionar el ciclo de vida del Relay Worker sincrono como hilo de fondo dentro del proceso FastAPI.
  * Archivos: `via/main.py`, `via/shared/outbox/relay_worker.py`.
  * Depende de: 7.2, 24.2, 24.3.
  * Criterio de aceptacion: El lifespan inicia `RelayWorker` con `threading.Thread` al arrancar y lo detiene limpiamente al cerrar; no usa `asyncio`, `AsyncSession` ni `asyncpg`.
  * Prueba: Integration test.

* [ ] 24.5 Verificar arranque monolitico completo

  * Objetivo: Confirmar que la aplicacion arranca como una sola unidad monolitica con base de datos, routers, dependencias, Event Bus y Relay Worker cableados.
  * Archivos: `tests/integration/test_application_startup.py`, `docs/manual_validation.md`.
  * Depende de: 24.4.
  * Criterio de aceptacion: El test de startup crea la app, resuelve dependencias principales, lista rutas esperadas y confirma que el Relay Worker queda gestionado por lifespan sin lanzar procesos externos.
  * Prueba: Integration test.

## 25. End-to-End Saga Validation

* [ ] 25.1 Preparar fixtures end-to-end

  * Objetivo: Crear datos minimos para usuario, parcela, rulebook activo, vector agroambiental, documentos y adaptadores externos simulados.
  * Archivos: `tests/e2e/fixtures/`, `tests/e2e/conftest.py`.
  * Depende de: 24.5.
  * Criterio de aceptacion: Los fixtures permiten ejecutar la saga completa despues de que `main.py`, routers, dependencias, Event Bus, consumers y Relay Worker esten cableados; usa stubs para GEE, embeddings y LLM.
  * Prueba: Integration test.

* [ ] 25.2 Validar saga completa exitosa

  * Objetivo: Ejecutar solicitud de evaluacion desde HTTP hasta recomendacion final.
  * Archivos: `tests/e2e/test_full_evaluation_saga.py`.
  * Depende de: 25.1.
  * Criterio de aceptacion: La saga transita `INICIADA`, `EXTRACCION_COMPLETADA`, `EVALUACION_COMPLETADA`, `RECOMENDACION_COMPLETADA`; persiste resultados, brechas, factores limitantes, recomendacion y trazabilidad.
  * Prueba: Integration test.

* [ ] 25.3 Validar saga con fallos y duplicados

  * Objetivo: Verificar recuperacion frente a fallos parciales, mensajes duplicados y transiciones invalidas.
  * Archivos: `tests/e2e/test_saga_failures_and_duplicates.py`.
  * Depende de: 25.2.
  * Criterio de aceptacion: Eventos `ExtraccionFallida`, `EvaluacionFallida` y `RecomendacionFallida` llevan la saga a `FALLIDA`; duplicados no repiten efectos; transiciones invalidas se registran sin cambiar estado.
  * Prueba: Integration test.

* [ ] 25.4 Validar manualmente el flujo operativo minimo

  * Objetivo: Confirmar que el monolito puede iniciarse, autenticar usuario, registrar parcela, publicar rulebook, cargar documento, solicitar evaluacion y consultar resultado.
  * Archivos: `docs/manual_validation.md` o checklist en el reporte de validacion.
  * Depende de: 25.3.
  * Criterio de aceptacion: El flujo manual confirma que RAG/LLM solo redacta recomendaciones y que el MCDA difuso realiza todos los calculos.
  * Prueba: Validacion manual.
