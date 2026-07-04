# Design Document — VIA: Viabilidad Inteligente Agrícola

## 1. Visión general de la arquitectura

VIA — Viabilidad Inteligente Agrícola es el nombre oficial del sistema. VIA se implementa como un **monolito modular** desplegado como una única unidad Python/FastAPI. La separación lógica es estricta: cada Bounded Context (BC) es un módulo Python independiente con sus propias capas internas. Los módulos no se importan entre sí directamente; toda comunicación entre BCs ocurre a través del Event Bus interno o de contratos de puerto explícitos.

**Principios rectores:**

- **DDD**: 7 BCs con lenguaje ubicuo propio, aggregates, entidades y servicios de dominio.
- **Clean Architecture por BC**: dependencias apuntan hacia adentro (Interfaces → Application → Domain ← Infrastructure). El dominio no importa frameworks, SQLAlchemy ni FastAPI.
- **CQRS ligero**: `CommandApplicationService` y `QueryApplicationService` separados en cada BC.
- **Transactional Outbox**: todo mensaje (comando o evento) se persiste atómicamente con el cambio de estado antes de ser despachado.
- **Semántica at-least-once + Consumidores idempotentes**: el Relay Worker puede entregar duplicados; los consumidores los absorben por `(message_id, consumer)`.
- **Dos esquemas PostgreSQL lógicamente aislados**: `transactional` para dominio/saga/outbox y `documental` para fragmentos/embeddings (pgvector).
- **SQLAlchemy síncrono con `psycopg2`**: el MVP usa sesiones síncronas en todos los repositorios, el Relay Worker y los Application Services. No se usa `asyncpg`, `AsyncSession` ni `create_async_engine`. El Relay Worker corre como hilo de fondo (`threading.Thread`) dentro del proceso FastAPI, no como corutina `async`.

---

## 2. Estructura de carpetas del proyecto

```
via/
├── main.py                          # Punto de entrada FastAPI
├── config.py                        # Configuración centralizada (env vars)
├── pyproject.toml
│
├── shared/
│   ├── __init__.py
│   ├── event_bus/
│   │   ├── __init__.py
│   │   ├── in_memory_event_bus.py   # Implementación en memoria (MVP)
│   │   ├── event_bus_interface.py   # Puerto abstracto del bus
│   │   └── message.py               # Dataclass base Message(id, type, kind, payload, correlation_id)
│   ├── outbox/
│   │   ├── __init__.py
│   │   ├── outbox_writer.py         # Escribe mensajes en tabla outbox_messages
│   │   ├── relay_worker.py          # Loop de polling y publicación
│   │   └── models.py                # ORM model OutboxMessage
│   ├── orchestration/
│   │   ├── __init__.py
│   │   └── evaluation_process_manager/
│   │       ├── __init__.py
│   │       ├── process_manager.py   # Máquina de estados de la saga
│   │       ├── saga_repository.py   # Puerto del repositorio de saga
│   │       ├── saga_orm.py          # Modelos ORM EvaluationSaga, SagaTransition
│   │       ├── commands.py          # IniciarExtraccionAgroambiental, EjecutarEvaluacionViabilidad, GenerarRecomendacionSustentada
│   │       ├── ports.py             # IRulebookReadModelPort → get_required_extraction_spec() → RequiredExtractionSpec
│   │       └── handlers.py          # Handlers de eventos entrantes al Process Manager
│   ├── idempotency/
│   │   ├── __init__.py
│   │   └── processed_message_store.py  # Registro de message_ids procesados
│   └── database/
│       ├── __init__.py
│       ├── session.py               # SessionFactory SQLAlchemy
│       └── base.py                  # Base declarativa + esquemas
│
├── bounded_contexts/
│   │
│   ├── iam/                         # BC: Gestión de Usuarios y Accesos
│   │   ├── interfaces/
│   │   │   ├── auth_router.py       # POST /auth/login, POST /auth/refresh
│   │   │   └── resources.py         # LoginRequest, TokenResponse (DTOs)
│   │   ├── application/
│   │   │   ├── command_service.py   # AuthenticateUserCommand
│   │   │   ├── query_service.py     # GetUserProfileQuery
│   │   │   └── ports.py             # IUserRepository, IPasswordHasher, ITokenService
│   │   ├── domain/
│   │   │   ├── user.py              # Aggregate User (id, email, role, hashed_password)
│   │   │   └── role.py              # Enum Role: ADMINISTRADOR, ESPECIALISTA_TECNICO, USUARIO_AGRICOLA
│   │   └── infrastructure/
│   │       ├── user_repository.py   # SQLAlchemy UserRepository
│   │       ├── password_hasher.py   # Implementa IPasswordHasher usando bcrypt/passlib u otra librería segura
│   │       ├── jwt_adapter.py       # Implementa ITokenService usando librería JWT + secreto + algoritmo + expiración
│   │       └── orm_models.py        # ORM UserModel
│   │
│   ├── parcel_management/           # BC: Gestión de Parcelas
│   │   ├── interfaces/
│   │   │   ├── parcel_router.py     # GET/POST/PATCH /parcelas
│   │   │   └── resources.py         # ParcelRequest, ParcelResponse (DTOs GeoJSON)
│   │   ├── application/
│   │   │   ├── command_service.py   # RegisterParcelCommand, UpdateParcelCommand
│   │   │   ├── query_service.py     # GetParcelQuery, ListParcelsQuery
│   │   │   └── ports.py             # IParcelRepository
│   │   ├── domain/
│   │   │   ├── parcel.py            # Aggregate Parcel (id, owner_id, geometry, metadata)
│   │   │   ├── geometry_validator.py # Domain service: validaciones GeoJSON WGS-84
│   │   │   └── value_objects.py     # GeoJSONGeometry (Polygon/MultiPolygon), ParcelMetadata
│   │   └── infrastructure/
│   │       ├── parcel_repository.py # SQLAlchemy + PostGIS
│   │       └── orm_models.py        # ORM ParcelModel, ParcelVersionModel
│   │
│   ├── rulebook_management/         # BC: Gestión de Rulebooks Ecofisiológicos
│   │   ├── interfaces/
│   │   │   ├── rulebook_router.py   # GET/POST/PATCH /rulebooks
│   │   │   └── resources.py         # RulebookRequest, RulebookResponse (DTOs)
│   │   ├── application/
│   │   │   ├── command_service.py   # CreateRulebookCommand, PublishRulebookCommand
│   │   │   ├── query_service.py     # GetActiveRulebookQuery, GetRulebookVersionQuery
│   │   │   └── ports.py             # IRulebookRepository
│   │   ├── domain/
│   │   │   ├── rulebook.py          # Aggregate Rulebook
│   │   │   ├── criterion.py         # Entity Criterion (id, name, is_critical, critical_policy, penalty_factor, ahp_weight, phase_requirements[], doc_source)
│   │   │   ├── phase_requirement.py # Entity PhaseRequirement (id, criterion_id, phase_id, membership_fn, phase_weight, temporal_periods[])
│   │   │   ├── phenological_phase.py # Entity PhenologicalPhase (id, name, duration_days, sequence_order)
│   │   │   ├── membership_function.py # Value Object: trapezoidal(a,b,c,d), validación a≤b≤c≤d — definida por fase
│   │   │   ├── weight_validator.py  # Domain service: validar sumas de pesos por nivel
│   │   │   └── value_objects.py     # CriticalPolicy enum, RulebookVersion
│   │   └── infrastructure/
│   │       ├── rulebook_repository.py
│   │       └── orm_models.py        # RulebookModel, CriterionModel, PhaseRequirementModel, PhaseModel
│   │
│   ├── document_management/         # BC: Gestión Documental Técnica
│   │   ├── interfaces/
│   │   │   ├── document_router.py   # POST/DELETE /documentos
│   │   │   └── resources.py         # DocumentUploadRequest, FragmentResponse
│   │   ├── application/
│   │   │   ├── command_service.py   # UploadDocumentCommand, DeleteDocumentCommand
│   │   │   ├── query_service.py     # SearchFragmentsQuery
│   │   │   └── ports.py             # IDocumentRepository, IEmbeddingService
│   │   ├── domain/
│   │   │   ├── document.py          # Aggregate Document (id, title, crop_tags, fragments)
│   │   │   ├── fragment.py          # Entity Fragment (id, text, page_ref, embedding)
│   │   │   └── chunker.py           # Domain service: fragmentación 200-1000 tokens
│   │   └── infrastructure/
│   │       ├── document_repository.py  # Escribe en esquema documental
│   │       ├── embedding_adapter.py    # Llama API de embeddings externa
│   │       └── orm_models.py           # ORM DocumentModel, FragmentModel (vector column)
│   │
│   ├── agroenv_extraction/          # BC: Extracción Agroambiental de Parcela
│   │   ├── interfaces/
│   │   │   └── extraction_consumer.py  # Consume comando IniciarExtraccionAgroambiental del Event Bus
│   │   ├── application/
│   │   │   ├── command_service.py   # StartExtractionCommand
│   │   │   ├── query_service.py     # GetExtractionStatusQuery
│   │   │   └── ports.py             # IGEEClient, IExtractionRepository, IOutboxWriter
│   │   ├── domain/
│   │   │   ├── agroenv_vector.py    # Aggregate AgroenvVector (parcela_id, variables[], periodo)
│   │   │   ├── variable_entry.py    # Entity VariableEntry (name, value, source, date, status: OK|CRITERIO_FALTANTE)
│   │   │   └── value_objects.py     # TemporalWindow, VariableStatus
│   │   └── infrastructure/
│   │       ├── gee_client.py        # Adaptador Google Earth Engine API
│   │       ├── extraction_acl.py    # ACL: traduce respuesta GEE → AgroenvVector dominio
│   │       ├── extraction_repository.py
│   │       └── orm_models.py
│   │
│   ├── viability_evaluation/        # BC: Evaluación de Viabilidad Agrícola (Core Domain)
│   │   ├── interfaces/
│   │   │   ├── evaluation_consumer.py   # Consume comando EjecutarEvaluacionViabilidad
│   │   │   ├── evaluation_router.py     # GET /evaluaciones/{id}/resultado
│   │   │   ├── resources.py             # EvaluationResultResponse, GapResponse (DTOs)
│   │   │   └── transformers.py          # Resources ↔ Commands/Queries
│   │   ├── application/
│   │   │   ├── command_service.py       # ExecuteEvaluationCommand
│   │   │   ├── query_service.py         # GetEvaluationResultQuery
│   │   │   └── ports.py                 # IEvaluationRepository, IRulebookACL, IAgroenvACL, IOutboxWriter, IUnitOfWork
│   │   ├── domain/
│   │   │   ├── evaluation.py            # Aggregate Evaluation
│   │   │   ├── crop_result.py           # Entity CropResult (score, calc_condition, viability_category, gaps, limiting_factors)
│   │   │   ├── criterion_detail.py      # Entity CriterionDetail (memberships_by_phase, aggregated_membership, w_ahp, w_entropy, w_hybrid, entropy_fallback_reason)
│   │   │   ├── agronomy_gap.py          # Entity AgronomyGap (criterion_id, phase_id, most_limiting_period, observed, optimal_limit, gap_value)
│   │   │   ├── limiting_factor.py       # Entity LimitingFactor (criterion_id, phase_id, policy, penalty_factor, doc_source)
│   │   │   ├── value_objects.py         # CalcCondition, ViabilityCategory, CriticalPolicy enums
│   │   │   └── services/
│   │   │       ├── phenological_alignment_service.py  # Mapea ventana temporal + fases Rulebook → períodos vector
│   │   │       ├── fuzzification_service.py           # Aplica funciones de membresía trapezoidales
│   │   │       ├── temporal_aggregation_service.py    # MGP temporal por fase
│   │   │       ├── criterion_aggregation_service.py   # MGP por criterio a través de fases
│   │   │       ├── missing_criteria_service.py        # Excluye faltantes no críticos y decide NO_CONCLUYENTE
│   │   │       ├── entropy_weights_service.py         # Calcula w_ENT por entropía de Shannon
│   │   │       ├── hybrid_weights_service.py          # Combina w_AHP y w_ENT → w_hybrid
│   │   │       ├── multicriteria_aggregation_service.py # MGP multicriterio final
│   │   │       ├── critical_policy_service.py         # Aplica NO_VIABLE o PENALIZE
│   │   │       ├── viability_classifier_service.py    # Asigna CalcCondition y ViabilityCategory
│   │   │       └── gap_calculation_service.py         # Calcula brechas con signo
│   │   └── infrastructure/
│   │       ├── evaluation_repository.py               # SQLAlchemy, escribe en esquema transactional
│   │       ├── rulebook_acl_adapter.py                # ACL: RulebookDTO (de rulebook_management) → RulebookDomainModel
│   │       ├── agroenv_acl_adapter.py                 # ACL: AgroenvVectorDTO → VectorDomainModel
│   │       ├── outbox_adapter.py                      # Implementa IOutboxWriter usando OutboxWriter shared
│   │       ├── event_bus_adapter.py                   # Implementa publicación en InMemoryEventBus
│   │       └── orm_models.py                          # EvaluationModel, CropResultModel, CriterionDetailModel, GapModel
│   │
│   └── recommendation/              # BC: Recomendación Sustentada
│       ├── interfaces/
│       │   └── recommendation_consumer.py  # Consume comando GenerarRecomendacionSustentada
│       ├── application/
│       │   ├── command_service.py    # GenerateRecommendationCommand
│       │   ├── query_service.py      # GetRecommendationQuery
│       │   └── ports.py              # IDocumentSearchPort, ILLMPort, IRecommendationRepository, IOutboxWriter
│       ├── domain/
│       │   ├── recommendation.py     # Aggregate Recommendation (id, evaluation_id, text, fragment_ids)
│       │   └── prompt_builder.py     # Domain service: construye prompt para LLM con scores/brechas/fragmentos
│       └── infrastructure/
│           ├── recommendation_repository.py
│           ├── llm_adapter.py        # ACL hacia API LLM externa (reintentos, validación respuesta)
│           ├── document_search_adapter.py  # Llama al QueryService de document_management
│           └── orm_models.py
│
└── tests/
    ├── unit/
    │   └── viability_evaluation/
    │       ├── test_fuzzification_service.py
    │       ├── test_temporal_aggregation_service.py
    │       ├── test_entropy_weights_service.py
    │       ├── test_hybrid_weights_service.py
    │       ├── test_missing_criteria_service.py
    │       ├── test_multicriteria_aggregation_service.py
    │       ├── test_critical_policy_service.py
    │       ├── test_viability_classifier_service.py
    │       └── test_gap_calculation_service.py
    ├── integration/
    │   ├── test_outbox_relay_worker.py
    │   ├── test_evaluation_repository.py
    │   └── test_rulebook_acl_adapter.py
    └── property_based/
        └── test_mcda_invariants.py   # Hypothesis: score∈[0,1], pesos suman 1.0, membresías∈[0,1]
```

---

## 3. Bounded Contexts — responsabilidades y límites

### 3.1 IAM — Gestión de Usuarios y Accesos

**Responsabilidad**: autenticar usuarios y emitir tokens JWT; validar permisos por rol en cada request.

**Lenguaje ubicuo**: Usuario, Rol, Token, Credenciales, Sesión.

**Capa de dominio**: Aggregate `User` (id, email, hashed_password, role); Value Object `Role` (ADMINISTRADOR, ESPECIALISTA_TECNICO, USUARIO_AGRICOLA); reglas simples de dominio para jerarquía/autorización por rol. El dominio no contiene servicios de password, hashing casero, secretos, algoritmos, librerías de hashing ni librerías JWT.

**Puertos de aplicación** (`ports.py`): `IUserRepository`; `IPasswordHasher` (puerto abstracto que define `verify(plain_password, hashed_password) → bool` y, cuando aplique, `hash(plain_password) → str`); `ITokenService` (puerto abstracto que define `generate_token(user_id, role) → str` y `verify_token(token) → TokenClaims`). El Application Service depende de estas abstracciones, nunca de implementaciones concretas.

**CQRS**:
- `AuthenticateUserCommand(email, password)` → verifica credenciales via `IPasswordHasher` (puerto de aplicación) y genera token via `ITokenService` (puerto), retorna `TokenPair`.
- `GetUserProfileQuery(user_id)` → retorna perfil sin datos sensibles.

**Interfaces**: `POST /auth/login`, `POST /auth/refresh`. Middleware FastAPI verifica token en cada request protegido (usando `ITokenService`) y adjunta el contexto de usuario al request.

**Infraestructura**: `UserRepository` (SQLAlchemy, esquema `transactional`); `PasswordHasher` — implementa `IPasswordHasher` usando una librería segura como `bcrypt`/`passlib`, sin hashing casero; `JWTAdapter` — implementa `ITokenService` usando la librería JWT elegida (ej. `python-jose` o `PyJWT`), secreto, algoritmo y tiempos de expiración configurados vía variables de entorno. Ningún detalle de estas implementaciones pertenece ni es visible desde el dominio.

---

### 3.2 Gestión de Parcelas

**Responsabilidad**: registrar, validar y mantener parcelas geoespaciales con historial de cambios.

**Lenguaje ubicuo**: Parcela, Geometría, Propietario, Historial de Versiones.

**Capa de dominio**: Aggregate `Parcel` (id, owner_id, geometry: GeoJSONGeometry, metadata, created_at); `GeoJSONGeometry` acepta únicamente `Polygon` o `MultiPolygon`. Un `Polygon` simple se normaliza a `MultiPolygon` antes de persistir. Domain Service `GeometryValidator` valida cierre, WGS-84, mínimo de 4 puntos por anillo exterior, ausencia de autointersecciones y área máxima para cada polígono y para la geometría total. El MVP no acepta puntos.

**CQRS**:
- `RegisterParcelCommand(owner_id, geometry, metadata)` → valida y persiste.
- `UpdateParcelCommand(parcel_id, user_id, geometry?, metadata?)` → revalida y versiona.
- `GetParcelQuery(parcel_id, user_id)` → retorna parcela con historial de evaluaciones.
- `ListParcelsQuery(owner_id)` → retorna sólo parcelas del usuario.

**Infraestructura**: `ParcelRepository` (SQLAlchemy + PostGIS para geometrías, persistiendo preferentemente `GEOMETRY(MULTIPOLYGON, 4326)`), `ParcelVersionModel`.

---

### 3.3 Gestión de Rulebooks Ecofisiológicos

**Responsabilidad**: construir, versionar y publicar rulebooks que el motor MCDA consume. Los pesos base Fuzzy AHP son precalculados externamente y almacenados como datos.

**Lenguaje ubicuo**: Rulebook, Criterio, Fase Fenológica, Período Temporal, Peso AHP, Función de Membresía, Política de Criterio Crítico.

**Capa de dominio**: Aggregate `Rulebook` (id, crop_id, version, status: DRAFT|ACTIVE|INACTIVE, criteria[]); Entity `Criterion` (id, name, is_critical, critical_policy: NO_VIABLE|PENALIZE, penalty_factor, ahp_weight, phase_requirements[], doc_source) — **la función de membresía NO se define a nivel de criterio**; Entity `PhaseRequirement` (id, criterion_id, phase_id, membership_fn, phase_weight, temporal_periods[]) — **la función de membresía trapezoidal se define aquí, por criterio y fase**, permitiendo que un mismo criterio (p.ej. precipitación o temperatura) tenga rangos {a,b,c,d} distintos en establecimiento, desarrollo vegetativo, floración y maduración; Entity `PhenologicalPhase` (id, name, duration_days, sequence_order) — define la estructura temporal del ciclo del cultivo, independiente de los criterios; Value Object `MembershipFunction` (type: TRAPEZOIDAL, params: {a, b, c, d}, validación a≤b≤c≤d); Domain Service `WeightValidator`.

**CQRS**:
- `CreateRulebookCommand` → crea DRAFT con validaciones de pesos por nivel.
- `PublishRulebookCommand` → activa la versión y desactiva la anterior atómicamente.
- `GetActiveRulebookQuery(crop_id)` → retorna rulebook activo completo.
- `GetRulebookVersionQuery(crop_id, version)` → retorna versión histórica.

**Validación de pesos (WeightValidator)**:
- Suma de `ahp_weight` por bloque evaluativo = 1.0 ± tolerancia.
- Suma de `phase_weight` por criterio multifase = 1.0 ± tolerancia.
- Suma de pesos temporales por fase = 1.0 ± tolerancia.
- Si alguno falla → HTTP 422 indicando el nivel y grupo inválido.

---

### 3.4 Gestión Documental Técnica

**Responsabilidad**: fragmentar, vectorizar e indexar documentos técnicos; recuperar fragmentos relevantes para RAG.

**Lenguaje ubicuo**: Documento, Fragmento, Embedding, Etiqueta de Cultivo, Similitud Semántica.

**Capa de dominio**: Aggregate `Document` (id, title, crop_tags[], status); Entity `Fragment` (id, document_id, text, page_ref, crop_tags[], embedding_vector); Domain Service `Chunker` (fragmentación 200-1000 tokens respetando párrafos).

**CQRS**:
- `UploadDocumentCommand(file_bytes, format, metadata)` → valida formato/tamaño/tags, fragmenta, genera embeddings, persiste en esquema `documental`.
- `DeleteDocumentCommand(document_id)` → elimina fragmentos y embeddings atómicamente.
- `SearchFragmentsQuery(crop_id, gap_descriptions, top_k=10, threshold=0.5)` → búsqueda vectorial por coseno con pgvector.

**Infraestructura**: `DocumentRepository` (escribe **solo** en esquema `documental`), `EmbeddingAdapter` (API externa para generar embeddings).

---

### 3.5 Extracción Agroambiental de Parcela

**Responsabilidad**: obtener variables agroambientales desde GEE por período temporal, construir el Vector Agroambiental y emitir eventos al bus.

**Lenguaje ubicuo**: Vector Agroambiental, Variable, Criterio Faltante, Período de Análisis.

**Cómo el BC Extracción conoce qué consultar**: el Process Manager **no interpreta** los rulebooks ni deriva variables, datasets, bandas ni máscaras por sí mismo. En su lugar, antes de emitir el comando `IniciarExtraccionAgroambiental`, el Process Manager invoca el puerto `IRulebookReadModelPort.get_required_extraction_spec(crop_candidates, temporal_window) → RequiredExtractionSpec`. Este puerto es implementado en la infraestructura del Process Manager mediante una consulta de lectura al BC Rulebooks (a través de su `QueryService`), devolviendo un read model con especificaciones de extracción. Cada entrada incluye: `variable_name`, `criterion_id`, `crop_id`, `phase_id`, `dataset_key`, `band`, `unit`, `temporal_resolution`, `spatial_resolution` o `scale`, `reducer`, `aggregation_method`, `temporal_window`, `temporal_periods`, `quality_mask` y `fallback_allowed`. El Process Manager solo reenvía esa especificación en el payload del comando. El BC Extracción recibe la especificación técnica a ejecutar contra GEE y opera sin importar ni conocer el modelo interno de Rulebooks.

**Capa de dominio**: Aggregate `AgroenvVector` (evaluation_id, parcel_id, temporal_window, variable_entries[]); Entity `VariableEntry` (name, criterion_id, crop_id, phase_id, value, source, dataset_key, band, unit, extraction_date, period, status: OK|CRITERIO_FALTANTE); Value Object `TemporalWindow` (start_date, end_date).

**CQRS**:
- Consume: comando `IniciarExtraccionAgroambiental` desde Event Bus. El payload incluye: `evaluation_id`, `parcel_id`, `temporal_window`, `crop_candidates`, `required_extraction_spec: RequiredExtractionSpec` (especificación recopilada por el Process Manager via read model del BC Rulebooks, sin que el Process Manager interprete criterios, fases, datasets, bandas ni máscaras).
- `StartExtractionCommand` → consulta GEE con ACL usando `required_extraction_spec`, construye vector, persiste en esquema `transactional`, escribe `VectorAgroambientalGenerado` en Outbox.
- En fallo: escribe `ExtraccionFallida` en Outbox.
- En duplicado: descarta, escribe `ExtraccionDuplicadaRechazada` en Outbox.

**Infraestructura**: `GEEClient` (google-earth-engine SDK), `ExtractionACL` (traduce respuesta GEE → `AgroenvVector` dominio), `ExtractionRepository`.

---

### 3.6 Evaluación de Viabilidad Agrícola (Core Domain)

Diseño detallado en la sección 4.

---

### 3.7 Recomendación Sustentada

**Responsabilidad**: recuperar fragmentos documentales relevantes y usar el LLM exclusivamente para redactar la recomendación textual a partir de resultados precalculados.

**Lenguaje ubicuo**: Recomendación, Prompt, Fragmento de Evidencia, Score de Viabilidad (como entrada, no calculado aquí).

**Capa de dominio**: Aggregate `Recommendation` (id, evaluation_id, text, fragment_ids[], status); Domain Service `PromptBuilder` (construye el prompt estructurado con score, ranking, brechas y fragmentos; el LLM no calcula nada).

**CQRS**:
- Consume: comando `GenerarRecomendacionSustentada` desde Event Bus.
- `GenerateRecommendationCommand` → busca fragmentos (máx 5), construye prompt, llama LLM (máx 2 reintentos), valida respuesta, persiste, escribe `RecomendacionValidada` o `RecomendacionFallida` en Outbox.

**Infraestructura**: `LLMAdapter` (ACL hacia API LLM externa), `DocumentSearchAdapter` (llama `SearchFragmentsQuery` del BC Documental), `RecommendationRepository`.

---

## 4. Diseño del BC Evaluación de Viabilidad Agrícola (Core Domain)

### 4.1 Aggregate y entidades del dominio

```
Aggregate: Evaluation
  - id: UUID
  - parcel_id: UUID
  - requested_by: UUID
  - crop_candidates: List[str]
  - temporal_window: TemporalWindow
  - rulebook_version_map: Dict[crop_id, rulebook_version]
  - crop_results: List[CropResult]
  - status: EvaluationStatus
  - created_at: datetime

Entity: CropResult
  - crop_id: str
  - score: float  # [0.0, 1.0]
  - rank_position: int | None
  - calc_condition: CalcCondition  # DEFINITIVO | PARCIAL | NO_CONCLUYENTE
  - viability_category: ViabilityCategory  # VIABLE | CONDICIONAL | NO_VIABLE
  - criterion_details: List[CriterionDetail]
  - gaps: List[AgronomyGap]
  - limiting_factors: List[LimitingFactor]
  - missing_criteria: List[str]
  - unrecognized_variables: List[str]
  - entropy_series_sufficient: bool

Entity: CriterionDetail
  - criterion_id: str
  - memberships_by_period: Dict[period_key, float]   # per (phase, period)
  - aggregated_by_phase: Dict[phase_id, float]        # MGP temporal por fase
  - aggregated_membership: float                      # MGP a través de fases
  - w_ahp: float
  - w_entropy: float | None
  - w_hybrid: float
  - entropy_used: bool
  - entropy_fallback_reason: str | None

Entity: AgronomyGap
  - criterion_id: str
  - phase_id: str
  - most_limiting_period: str
  - observed_value: float
  - optimal_limit: float
  - gap_value: float    # observed - optimal_limit (signed)

Entity: LimitingFactor
  - criterion_id: str
  - phase_id: str
  - policy: CriticalPolicy
  - penalty_factor: float | None
  - observed_value: float
  - optimal_limit: float
  - membership: float   # = 0.0
  - doc_source: str
```

### 4.2 Value Objects y enums

```python
class CalcCondition(str, Enum):
    DEFINITIVO = "DEFINITIVO"
    PARCIAL = "PARCIAL"
    NO_CONCLUYENTE = "NO_CONCLUYENTE"

class ViabilityCategory(str, Enum):
    VIABLE = "VIABLE"
    CONDICIONAL = "CONDICIONAL"
    NO_VIABLE = "NO_VIABLE"

class CriticalPolicy(str, Enum):
    NO_VIABLE = "NO_VIABLE"
    PENALIZE = "PENALIZE"
```

### 4.3 Puertos de aplicación (interfaces)

```python
# ports.py
class IEvaluationRepository(ABC):
    def save(self, evaluation: Evaluation) -> None: ...
    def get_by_id(self, eval_id: UUID) -> Evaluation | None: ...

class IRulebookACL(ABC):
    def get_active_rulebook(self, crop_id: str) -> RulebookDomainModel: ...

class IAgroenvACL(ABC):
    def get_vector(self, evaluation_id: UUID) -> VectorDomainModel: ...

class IOutboxWriter(ABC):
    def write(self, message: OutboxMessage, session: Session) -> None: ...

class IUnitOfWork(ABC):
    def __enter__(self) -> Session: ...   # Session síncrona (psycopg2)
    def __exit__(self, *args) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

### 4.4 Command Application Service

```
ExecuteEvaluationCommandService.execute(command: ExecuteEvaluationCommand):
  1. Iniciar UoW (una sola transacción)
  2. Cargar rulebooks activos vía IRulebookACL para cada crop candidato
  3. Cargar AgroenvVector vía IAgroenvACL
  4. Para cada crop:
     a. PhenologicalAlignmentService.align(temporal_window, phases)
     b. FuzzificationService.fuzzify(vector, rulebook)
     c. TemporalAggregationService.aggregate(memberships_by_period, temporal_weights)
     d. CriterionAggregationService.aggregate(memberships_by_phase, phase_weights)
     e. MissingCriteriaService.resolve(aggregated_memberships, missing_criteria, rulebook)
     f. EntropyWeightsService.calculate(participating_memberships) si serie suficiente
     g. HybridWeightsService.combine(w_ahp, w_entropy, alpha)
     h. Renormalizar una sola vez pesos de criterios participantes si hubo exclusiones no críticas
     i. MulticriteriaAggregationService.aggregate(participating_memberships, w_hybrid)
     j. CriticalPolicyService.apply(crop_result, rulebook)
     k. ViabilityClassifierService.classify(crop_result, missing_criteria, rulebook)
     l. GapCalculationService.calculate(memberships, rulebook)
  5. Construir Evaluation aggregate con todos los CropResults
  6. IEvaluationRepository.save(evaluation) dentro de UoW
  7. IOutboxWriter.write(EvaluacionCompletada, session)
  8. IOutboxWriter.write(VectorBrechasGenerado, session)
  9. UoW.commit()
```

### 4.5 ACL Adapters

**RulebookACLAdapter**: recibe la respuesta JSON del `GetActiveRulebookQuery` del BC Rulebooks y la traduce al modelo de dominio `RulebookDomainModel` interno del BC Evaluación. Nunca expone el ORM del BC Rulebooks al dominio de evaluación.

**AgroenvACLAdapter**: recibe la respuesta del BC Extracción (`AgroenvVectorDTO`) y la traduce a `VectorDomainModel` usado internamente por los Domain Services de evaluación.

---

## 5. Algoritmo MCDA Difuso — diseño conceptual detallado

### Paso 1 — Alineación Fenológica

`PhenologicalAlignmentService.align(temporal_window, phases)` produce un mapa `phase_id → [period_keys]`.

```
temporal_window = (start_date, end_date)
Para cada fase f en rulebook.phases (ordenadas por secuencia):
  f.start = temporal_window.start + sum(duration_days de fases anteriores)
  f.end   = f.start + f.duration_days
  f.period_keys = [p.key for p in vector.periods if p.date in [f.start, f.end)]
  if f.period_keys vacío:
    marcar fase como NO_ALINEADA → todos sus criterios = CRITERIO_FALTANTE
```

### Paso 2 — Fuzificación (función trapezoidal)

`FuzzificationService.fuzzify(value, fn)` donde `fn = {a, b, c, d}`.

**Precondición validada en Rulebook**: `a ≤ b ≤ c ≤ d`.

```
Casos degenerados soportados:
  - Triangular: b = c (plateau de ancho cero)
  - Escalón izquierdo: a = b (rampa ascendente sin pendiente inicial)
  - Escalón derecho: c = d (rampa descendente sin pendiente final)
  - Escalón total: a = b y c = d (función rectangular)

Fórmula:
  if value < a or value > d:  return 0.0
  if b <= value <= c:          return 1.0
  if a <= value < b:
    if b == a: return 1.0      # caso degenerado: evitar división por cero
    return (value - a) / (b - a)
  if c < value <= d:
    if d == c: return 1.0      # caso degenerado: evitar división por cero
    return (d - value) / (d - c)
```

El resultado es siempre un valor en `[0.0, 1.0]`.

### Paso 3 — Agregación Temporal por Fase (MGP)

`TemporalAggregationService.aggregate(memberships: Dict[period_key, float], weights: Dict[period_key, float]) → float`

```
# Media Geométrica Ponderada
# Precondición: sum(weights.values()) ≈ 1.0 (validado en Rulebook)
result = product(m ** w for m, w in zip(memberships.values(), weights.values()))

# Caso especial: si algún membership = 0.0, resultado = 0.0 (por propiedad de la MGP)
# Caso especial: si memberships vacío (fase no alineada), retornar CRITERIO_FALTANTE
```

### Paso 4 — Agregación por Criterio a través de Fases (MGP)

`CriterionAggregationService.aggregate(memberships_by_phase: Dict[phase_id, float], phase_weights: Dict[phase_id, float]) → float`

```
result = product(m_phase ** w_phase for each phase)
# sum(phase_weights) ≈ 1.0 (validado en Rulebook)
```

### Paso 4.5 — Resolución explícita de criterios faltantes

`MissingCriteriaService.resolve(aggregated_memberships, missing_criteria, rulebook) → ParticipatingCriteria`

Esta etapa ocurre **después** de la agregación por criterio y **antes** del cálculo de pesos finales y de la agregación multicriterio. Su objetivo es evitar que criterios faltantes no críticos sean tratados como membresía 0.0.

```
critical_missing = [c for c in missing_criteria if rulebook.is_critical(c) and not rulebook.has_alternative_rule(c)]

if critical_missing:
  crop_result.calc_condition = CalcCondition.NO_CONCLUYENTE
  crop_result.missing_criteria = critical_missing
  crop_result.rank_position = None
  retornar sin agregación multicriterio final para ese cultivo

non_critical_missing = [c for c in missing_criteria if not rulebook.is_critical(c)]
participating_criteria = all_criteria - non_critical_missing

if non_critical_missing:
  crop_result.calc_condition = CalcCondition.PARCIAL
  crop_result.missing_criteria = non_critical_missing
  excluir esos criterios del cálculo
  renormalizar pesos de participating_criteria a suma 1.0 una sola vez
else:
  crop_result.calc_condition = CalcCondition.DEFINITIVO
```

Reglas:
- Un criterio crítico faltante sin regla alternativa produce `NO_CONCLUYENTE` y no entra al ranking.
- Un criterio no crítico faltante se excluye del cálculo, se registra en `missing_criteria` y el resultado queda `PARCIAL`.
- Los faltantes no críticos **no** se convierten en membresía 0.0.
- No se permite doble normalización: la normalización por exclusión de criterios se aplica una sola vez antes de la agregación multicriterio final.

### Paso 5 — Pesos Objetivos por Entropía de Shannon

`EntropyWeightsService.calculate(criterion_memberships: Dict[criterion_id, List[float]], min_series_length: int) → Dict[criterion_id, float] | None`

**Regla de aplicación completa o fallback total (MVP):**
La entropía se aplica **solo si todos los criterios participantes** tienen serie temporal válida y de longitud suficiente. Si al menos un criterio participante cumple cualquiera de las siguientes condiciones, el sistema hace **fallback completo a pesos Fuzzy AHP (α = 1.0) para todos los criterios**:
- Longitud de serie < `min_series_length`.
- Todas las membresías del criterio son 0.0.
- Serie vacía.

No se generan pesos por entropía parciales con criterios faltantes. La causa del fallback se registra en `CriterionDetail.entropy_used = False` con el campo `entropy_fallback_reason`, por ejemplo: `"entropy_fallback: incomplete_or_invalid_series"`.

```
# Validación previa: todos los criterios participantes deben tener serie válida
for criterion_id, memberships in criterion_memberships.items():
  n = len(memberships)
  if n < min_series_length:
    retornar None  # fallback completo; registrar entropy_fallback: incomplete_or_invalid_series
  if all(m == 0.0 for m in memberships):
    retornar None  # fallback completo; criterio con aptitud nula en todos los períodos

# Si todos son válidos, proceder con el cálculo
Para cada criterio j con serie de membresías [m_1, ..., m_n]:
  total = sum(m_i) if sum(m_i) > 0 else 1.0
  p_i = m_i / total  para cada i

  # Entropía de Shannon normalizada (base e)
  H_j = -sum(p_i * ln(p_i) for p_i > 0) / ln(n)   # en [0, 1]

  # Divergencia
  d_j = 1.0 - H_j

# Caso especial: sum(d_k) = 0 — todos los criterios tienen distribución perfectamente uniforme
# No existe divergencia informativa diferenciada; no es posible calcular pesos con sentido
sum_d = sum(d_k for all k)
if sum_d == 0.0 or sum_d < MCDA_ENTROPY_MIN_DIVERGENCE:  # configurable via MCDA_ENTROPY_MIN_DIVERGENCE, default 1e-9
  retornar None  # fallback completo; registrar entropy_fallback: zero_divergence

# Pesos objetivos normalizados
w_ENT_j = d_j / sum_d
```

**Interpretación**: criterios con distribución temporal uniforme (mayor entropía → H_j alto) reciben d_j bajo y por tanto menor peso objetivo. Criterios cuya aptitud se concentra en pocos períodos (menor entropía → H_j bajo) reciben d_j alto y mayor peso objetivo.

### Paso 6 — Combinación Convexa (Pesos Híbridos)

`HybridWeightsService.combine(w_ahp, w_entropy, alpha) → Dict[criterion_id, float]`

```
Para cada criterio j:
  if w_entropy is not None:
    w_hybrid_j = alpha * w_ahp_j + (1 - alpha) * w_entropy_j
  else:
    w_hybrid_j = w_ahp_j   # fallback completo a AHP (α=1.0)

# Normalización final para garantizar sum = 1.0 (absorbe errores de punto flotante)
total = sum(w_hybrid.values())
w_hybrid_j = w_hybrid_j / total  para cada j
```

`alpha ∈ (0, 1)` es configurable via variable de entorno `MCDA_ALPHA` (default: 0.7).

### Paso 7 — Agregación Multicriterio Final (MGP)

`MulticriteriaAggregationService.aggregate(aggregated_memberships: Dict[criterion_id, float], w_hybrid: Dict[criterion_id, float], penalize_epsilon: float = MCDA_PENALIZE_EPSILON) → float`

**Regla de epsilon para criterios con `critical_policy = PENALIZE`:**
Antes de la agregación MGP, si un criterio es crítico con `critical_policy = PENALIZE` y su membresía agregada es 0.0, se sustituye temporalmente por `MCDA_PENALIZE_EPSILON` (configurable via `MCDA_PENALIZE_EPSILON`, default: `0.01`). Esto evita que la MGP anule completamente el score antes de que `CriticalPolicyService` aplique el `penalty_factor`. El score resultante de la MGP con epsilon es luego multiplicado por `penalty_factor` en el Paso 8.

Para criterios con `critical_policy = NO_VIABLE` y membresía 0.0: **no** se aplica epsilon; el score de la MGP puede llegar a 0.0 porque ese cultivo será descartado de todas formas en el Paso 8.

```
# Aplicar epsilon solo a criterios PENALIZE con membresía 0.0
effective_memberships = {}
for criterion_id, m in aggregated_memberships.items():
    criterion = rulebook.get_criterion(criterion_id)
    if m == 0.0 and criterion.is_critical and criterion.critical_policy == PENALIZE:
        effective_memberships[criterion_id] = penalize_epsilon  # piso mínimo para preservar el score
    else:
        effective_memberships[criterion_id] = m

score = product(effective_memberships[j] ** w_j for each criterion j)
# score ∈ (0.0, 1.0] cuando se aplica epsilon; = 0.0 solo si criterio NO_VIABLE
```

`penalize_epsilon` debe ser un valor pequeño pero no nulo (sugerido: 0.01) para que `penalty_factor` tenga efecto semántico real.

### Paso 8 — Aplicación de critical_policy

`CriticalPolicyService.apply(crop_result, rulebook)`:

```
Para cada criterio j declarado crítico en rulebook:
  if crop_result.criterion_details[j].aggregated_membership == 0.0:
    registrar LimitingFactor(criterion_id=j, phase, observed, optimal, membership=0.0, doc_source, policy)
    
    if criterion.critical_policy == NO_VIABLE:
      crop_result.viability_category = ViabilityCategory.NO_VIABLE
      # score numérico se mantiene como calculado, pero el cultivo se excluye del Ranking
      
    elif criterion.critical_policy == PENALIZE:
      crop_result.score = crop_result.score * criterion.penalty_factor
      # viability_category se determina en el paso siguiente por el score penalizado
```

### Paso 9 — Clasificación de Condición y Categoría

`ViabilityClassifierService.classify(crop_result, rulebook)`:

```
# La condición del cálculo ya fue resuelta por MissingCriteriaService.
# Este servicio no vuelve a excluir criterios ni renormalizar pesos.

# Categoría de viabilidad (resultado agronómico) — solo si no fue asignada NO_VIABLE por critical_policy
if crop_result.viability_category != ViabilityCategory.NO_VIABLE:
  score = crop_result.score
  if score >= VIABLE_THRESHOLD:        # configurable, default 0.70
    crop_result.viability_category = ViabilityCategory.VIABLE
  elif score >= CONDICIONAL_THRESHOLD: # configurable, default 0.40
    crop_result.viability_category = ViabilityCategory.CONDICIONAL
  else:
    crop_result.viability_category = ViabilityCategory.NO_VIABLE
```

### Paso 10 — Cálculo de Brechas

`GapCalculationService.calculate(memberships_by_period: Dict[(criterion_id, phase_id, period_key), float], rulebook, vector)`:

**Regla del valor representativo por fase**: cuando una fase contiene múltiples períodos temporales, el valor observado representativo para calcular la brecha es el valor del **período con menor membresía** dentro de esa fase. Esta elección hace que la brecha explique el punto más limitante de la fase, en lugar de ocultarlo mediante un promedio.

```
Para cada criterio j y fase f donde aggregated_membership(j, f) < 1.0:

  # Identificar el período con menor membresía dentro de la fase
  period_memberships = {p: memberships_by_period[(j, f, p)] for p in phase_periods(f)}
  most_limiting_period = argmin(period_memberships)   # período de menor membresía

  # Usar el valor observado de ese período como representante de la fase
  observed = vector.get_value(criterion=j, period=most_limiting_period)

  # Calcular brecha frente al límite óptimo más cercano de la función de membresía (j, f)
  optimal_limit = rulebook.get_nearest_optimal_limit(criterion=j, phase=f, observed=observed)
  gap = observed - optimal_limit   # negativo = déficit, positivo = exceso

  registrar AgronomyGap(criterion_id=j, phase_id=f,
                        most_limiting_period=most_limiting_period,
                        observed_value=observed,
                        optimal_limit=optimal_limit,
                        gap_value=gap)
```

### Paso 11 — Ranking persistido

`RankingService.assign_rank_positions(crop_results) → List[CropResult]`

```
ranked = filtrar crop_results donde:
  calc_condition in {DEFINITIVO, PARCIAL}
  viability_category != NO_VIABLE

ordenar ranked por score DESC, crop_id ASC

for index, crop_result in enumerate(ranked, start=1):
  crop_result.rank_position = index

for crop_result no incluido:
  crop_result.rank_position = None
```

Solo los cultivos incluidos en el ranking tienen `rank_position`. Los cultivos `NO_CONCLUYENTE` o `NO_VIABLE` persisten `rank_position = NULL`.

---

## 6. Flujo de mensajes — Process Manager, Event Bus y BCs

```
Cliente HTTP
  │
  ▼ POST /evaluaciones (parcela_id, crops, temporal_window)
API Gateway (FastAPI)
  │
  ▼ valida autenticación + roles
Process Manager.handle_create_evaluation()
  ├─ Crea EvaluationSaga (estado=INICIADA) en DB (esquema transactional)
  ├─ IRulebookReadModelPort.get_required_extraction_spec(crop_candidates, temporal_window)
  │     → retorna RequiredExtractionSpec con variable_name, criterion_id, crop_id, phase_id,
  │       dataset_key, band, unit, temporal/spatial resolution, reducer,
  │       aggregation_method, temporal_periods, quality_mask y fallback_allowed
  │     (el Process Manager NO interpreta rulebooks; solo recibe y reenvía el read model)
  ├─ outbox.write(COMMAND: IniciarExtraccionAgroambiental, correlation_id=evaluation_id,
  │               payload: {evaluation_id, parcel_id, temporal_window, crop_candidates,
  │                          required_extraction_spec: RequiredExtractionSpec}) en misma TX
  └─ Responde HTTP 202 {evaluation_id}

                   ┌───────────────────┐
Relay Worker ──────▶ Lee Outbox PENDING │
                   └───────────────────┘
                          │ publica en Event Bus
                          ▼
BC Extracción [ExtractionConsumer.handle()]
  ├─ IdempotencyCheck(message_id) → descarta si ya procesado
  ├─ GEEClient.extract(parcel, temporal_window, required_extraction_spec)
  ├─ ExtractionACL.translate(gee_response) → AgroenvVector
  ├─ ExtractionRepository.save(vector) en misma TX
  ├─ outbox.write(EVENT: VectorAgroambientalGenerado, correlation_id=evaluation_id) en misma TX
  └─ TX commit

Relay Worker → Event Bus → Process Manager [EventHandler.on_vector_generated()]
  ├─ IdempotencyCheck(message_id)
  ├─ SagaRepository.transition(INICIADA → EXTRACCION_COMPLETADA) en misma TX
  ├─ outbox.write(COMMAND: EjecutarEvaluacionViabilidad, correlation_id=evaluation_id) en misma TX
  └─ TX commit

Relay Worker → Event Bus → BC Evaluación [EvaluationConsumer.handle()]
  ├─ IdempotencyCheck(message_id)
  ├─ RulebookACL.get_active_rulebooks(crops)
  ├─ AgroenvACL.get_vector(evaluation_id)
  ├─ MCDAEngine.execute(vector, rulebooks, temporal_window)  [pasos 1-10]
  ├─ EvaluationRepository.save(evaluation) en misma TX
  ├─ outbox.write(EVENT: EvaluacionCompletada, correlation_id=evaluation_id) en misma TX
  ├─ outbox.write(EVENT: VectorBrechasGenerado, correlation_id=evaluation_id) en misma TX
  └─ TX commit

Relay Worker → Event Bus → Process Manager [EventHandler.on_evaluation_completed()]
  ├─ SagaRepository.transition(EXTRACCION_COMPLETADA → EVALUACION_COMPLETADA) en misma TX
  ├─ outbox.write(COMMAND: GenerarRecomendacionSustentada, correlation_id=evaluation_id) en misma TX
  └─ TX commit

Relay Worker → Event Bus → BC Recomendación [RecommendationConsumer.handle()]
  ├─ IdempotencyCheck(message_id)
  ├─ DocumentSearchAdapter.search(crop_id, gaps, top_k=5)
  ├─ PromptBuilder.build(score, ranking, gaps, fragments)
  ├─ LLMAdapter.generate(prompt) [máx 2 reintentos]
  ├─ validar respuesta (no vacía, menciona score y brecha)
  ├─ RecommendationRepository.save(recommendation) en misma TX
  ├─ outbox.write(EVENT: RecomendacionValidada, correlation_id=evaluation_id) en misma TX
  └─ TX commit

Relay Worker → Event Bus → Process Manager [EventHandler.on_recommendation_validated()]
  ├─ SagaRepository.transition(EVALUACION_COMPLETADA → RECOMENDACION_COMPLETADA) en misma TX
  ├─ outbox.write(EVENT: EvaluacionFinalizada, correlation_id=evaluation_id) en misma TX
  └─ TX commit

Cliente HTTP
  ▼ GET /evaluaciones/{id}/estado → HTTP 200 {RECOMENDACION_COMPLETADA}
  ▼ GET /evaluaciones/{id}/resultado → EvaluationResultResponse completo
```

**Flujo de fallo** (cualquier fase):

```
BC emite evento ExtraccionFallida | EvaluacionFallida | RecomendacionFallida
  ▼
Process Manager.on_failure()
  ├─ SagaRepository.transition(estado_actual → FALLIDA, causa, fase, timestamp) en TX
  └─ TX commit
```

---

## 7. Diseño del Transactional Outbox y Relay Worker

### 7.1 Tabla `outbox_messages` (esquema `transactional`)

```sql
CREATE TABLE transactional.outbox_messages (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(), -- message_id semántico del mensaje
    correlation_id   UUID NULL,              -- para saga de evaluación: evaluation_id
    aggregate_type   VARCHAR(100) NOT NULL,   -- e.g. 'EvaluationSaga', 'AgroenvVector'
    aggregate_id     UUID NOT NULL,
    message_type     VARCHAR(150) NOT NULL,   -- e.g. 'IniciarExtraccionAgroambiental'
    message_kind     VARCHAR(10)  NOT NULL CHECK (message_kind IN ('COMMAND', 'EVENT')),
    payload_json     JSONB        NOT NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING', 'DISPATCHED', 'PERMANENT_FAILURE')),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    dispatched_at    TIMESTAMPTZ,
    retry_count      SMALLINT     NOT NULL DEFAULT 0,
    last_error       TEXT
);

CREATE INDEX idx_outbox_status_created ON transactional.outbox_messages (status, created_at)
    WHERE status = 'PENDING';
```

`outbox_messages.id` es el identificador semántico del mensaje (`message_id`) usado por el Event Bus, el Relay Worker y los consumidores idempotentes. No se crea una segunda columna `message_id`; el ORM `OutboxMessageModel.id` se mapea a `Message.id`.

### 7.2 Tabla `processed_message_ids` (esquema `transactional`)

```sql
CREATE TABLE transactional.processed_message_ids (
    message_id   UUID         NOT NULL,
    consumer     VARCHAR(100) NOT NULL,   -- e.g. 'ExtractionConsumer'
    processed_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, consumer)   -- clave compuesta: mismo message_id puede ser procesado por distintos consumidores
);
```

### 7.3 OutboxWriter

```python
class OutboxWriter:
    def write(self, session: Session, message: OutboxMessage) -> None:
        """
        Escribe el mensaje en outbox_messages dentro de la sesión activa.
        El commit lo realiza el Application Service (UoW), no el writer.
        """
        orm = OutboxMessageModel(
            aggregate_type=message.aggregate_type,
            aggregate_id=message.aggregate_id,
            correlation_id=message.correlation_id,
            message_type=message.message_type,
            message_kind=message.message_kind,  # COMMAND | EVENT
            payload_json=message.payload,
            status="PENDING",
        )
        session.add(orm)
```

### 7.4 RelayWorker — ciclo de polling

El Relay Worker corre como un **hilo de fondo síncrono** (`threading.Thread`) iniciado en el `lifespan` de FastAPI. Usa sesiones SQLAlchemy síncronas (`Session`) con `psycopg2`. No usa `asyncio` ni `AsyncSession`.

```python
class RelayWorker:
    """
    Hilo de fondo síncrono.
    Polling interval: configurable via RELAY_WORKER_POLL_INTERVAL_SECONDS (default: 5s).
    Max retries: configurable via RELAY_WORKER_MAX_RETRIES (default: 5).
    """
    def run(self) -> None:
        while not self._stop_event.is_set():
            self._process_batch()
            time.sleep(self.poll_interval)

    def _process_batch(self) -> None:
        with self.session_factory() as session:
            # SELECT FOR UPDATE SKIP LOCKED para evitar procesamiento doble
            messages = session.execute(
                select(OutboxMessageModel)
                .where(OutboxMessageModel.status == "PENDING")
                .order_by(OutboxMessageModel.created_at, OutboxMessageModel.id)
                .limit(self.batch_size)
                .with_for_update(skip_locked=True)
            ).scalars().all()

            for msg in messages:
                try:
                    self.event_bus.publish(msg.to_message())   # síncrono; preserva correlation_id
                    msg.status = "DISPATCHED"
                    msg.dispatched_at = datetime.utcnow()
                except Exception as e:
                    msg.retry_count += 1
                    msg.last_error = str(e)
                    if msg.retry_count >= self.max_retries:
                        msg.status = "PERMANENT_FAILURE"

            session.commit()
```

### 7.5 Idempotency check en consumidores

```python
class IdempotentConsumerMixin:
    def is_already_processed(self, session: Session, message_id: UUID, consumer_name: str) -> bool:
        # La PK compuesta (message_id, consumer) permite que distintos consumidores
        # procesen independientemente el mismo message_id sin interferencia.
        exists = session.get(ProcessedMessageIdModel, (message_id, consumer_name))
        return exists is not None

    def mark_as_processed(self, session: Session, message_id: UUID, consumer_name: str) -> None:
        session.add(ProcessedMessageIdModel(message_id=message_id, consumer=consumer_name))
        # El commit lo realiza el Application Service (UoW) al final del handler,
        # en la misma transacción que el efecto de dominio.
```

El ORM `ProcessedMessageIdModel` debe declarar la clave primaria compuesta:

```python
class ProcessedMessageIdModel(Base):
    __tablename__ = "processed_message_ids"
    __table_args__ = (
        PrimaryKeyConstraint("message_id", "consumer"),
        {"schema": "transactional"},
    )
    message_id   = Column(UUID(as_uuid=True), nullable=False)
    consumer     = Column(String(100), nullable=False)
    processed_at = Column(DateTime(timezone=True), server_default=func.now())
```

Cada consumidor llama `is_already_processed` al inicio. Si True, retorna sin ejecutar lógica de dominio. Si False, ejecuta y llama `mark_as_processed` en la misma transacción.

---

## 8. Modelo de datos — tablas principales

### Esquema `transactional`

```sql
-- Sagas del Process Manager
CREATE TABLE transactional.evaluation_sagas (
    id                  UUID PRIMARY KEY,
    parcel_id           UUID NOT NULL,
    requested_by        UUID NOT NULL,
    crop_candidates     JSONB NOT NULL,      -- array de crop_ids
    temporal_window     JSONB NOT NULL,      -- {start_date, end_date}
    status              VARCHAR(30) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE transactional.saga_transitions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    saga_id         UUID NOT NULL REFERENCES transactional.evaluation_sagas(id),
    from_status     VARCHAR(30),
    to_status       VARCHAR(30) NOT NULL,
    triggered_by    UUID,                   -- message_id que causó la transición
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    failure_cause   TEXT
);

-- Parcelas
CREATE TABLE transactional.parcels (
    id              UUID PRIMARY KEY,
    owner_id        UUID NOT NULL,
    geometry        GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
    metadata        JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE transactional.parcel_version_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_id       UUID NOT NULL REFERENCES transactional.parcels(id),
    metadata_snapshot JSONB NOT NULL,
    geometry_snapshot GEOMETRY(MULTIPOLYGON, 4326),
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Rulebooks
CREATE TABLE transactional.rulebooks (
    id          UUID PRIMARY KEY,
    crop_id     VARCHAR(100) NOT NULL,
    version     INTEGER NOT NULL,
    status      VARCHAR(10) NOT NULL CHECK (status IN ('DRAFT', 'ACTIVE', 'INACTIVE')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(crop_id, version)
);

CREATE TABLE transactional.rulebook_criteria (
    id              UUID PRIMARY KEY,
    rulebook_id     UUID NOT NULL REFERENCES transactional.rulebooks(id),
    name            VARCHAR(150) NOT NULL,
    is_critical     BOOLEAN NOT NULL DEFAULT FALSE,
    critical_policy VARCHAR(20) CHECK (critical_policy IN ('NO_VIABLE', 'PENALIZE')),
    penalty_factor  NUMERIC(4,3),
    ahp_weight      NUMERIC(6,5) NOT NULL,
    -- membership_fn NO se define aquí: varía por fase fenológica (ver rulebook_phase_requirements)
    doc_source      TEXT,
    technical_notes TEXT
);

-- rulebook_phases se crea ANTES de rulebook_phase_requirements porque ésta la referencia
CREATE TABLE transactional.rulebook_phases (
    id              UUID PRIMARY KEY,
    rulebook_id     UUID NOT NULL REFERENCES transactional.rulebooks(id),
    name            VARCHAR(100) NOT NULL,
    duration_days   INTEGER NOT NULL,
    sequence_order  INTEGER NOT NULL          -- orden de las fases fenológicas
);

-- PhaseRequirement: une un criterio con una fase y define la función de membresía específica para esa combinación.
-- Esto permite que precipitación tenga {a,b,c,d} distintos en establecimiento vs. floración.
CREATE TABLE transactional.rulebook_phase_requirements (
    id               UUID PRIMARY KEY,
    criterion_id     UUID NOT NULL REFERENCES transactional.rulebook_criteria(id),
    phase_id         UUID NOT NULL REFERENCES transactional.rulebook_phases(id),
    membership_fn    JSONB NOT NULL,          -- {type: TRAPEZOIDAL, a, b, c, d} para este criterio+fase
    phase_weight     NUMERIC(6,5) NOT NULL,   -- peso de esta fase dentro del criterio
    temporal_periods JSONB NOT NULL,          -- [{period_key, temporal_weight}]
    UNIQUE(criterion_id, phase_id)
);

-- Vectores Agroambientales
CREATE TABLE transactional.agroenv_vectors (
    id              UUID PRIMARY KEY,
    evaluation_id   UUID NOT NULL,
    parcel_id       UUID NOT NULL,
    temporal_window JSONB NOT NULL,
    extracted_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE transactional.agroenv_variable_entries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vector_id       UUID NOT NULL REFERENCES transactional.agroenv_vectors(id),
    variable_name   VARCHAR(100) NOT NULL,
    criterion_id    VARCHAR(100) NOT NULL,
    crop_id         VARCHAR(100) NOT NULL,
    phase_id        VARCHAR(100) NOT NULL,
    dataset_key     VARCHAR(150) NOT NULL,
    band            VARCHAR(100) NOT NULL,
    unit            VARCHAR(50) NOT NULL,
    temporal_resolution VARCHAR(50) NOT NULL,
    spatial_resolution VARCHAR(50),
    scale           NUMERIC,
    reducer         VARCHAR(100) NOT NULL,
    aggregation_method VARCHAR(100) NOT NULL,
    quality_mask    JSONB,
    fallback_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    value           NUMERIC,
    source          VARCHAR(50) NOT NULL,
    extraction_date DATE NOT NULL,
    period_key      VARCHAR(50) NOT NULL,
    status          VARCHAR(20) NOT NULL CHECK (status IN ('OK', 'CRITERIO_FALTANTE'))
);

-- Resultados de Evaluación
CREATE TABLE transactional.evaluation_results (
    id              UUID PRIMARY KEY,
    evaluation_id   UUID NOT NULL REFERENCES transactional.evaluation_sagas(id),
    crop_id         VARCHAR(100) NOT NULL,
    score           NUMERIC(5,4),
    calc_condition  VARCHAR(20) NOT NULL,
    viability_category VARCHAR(15) NOT NULL,
    rank_position   INTEGER NULL,
    rulebook_version INTEGER NOT NULL,
    entropy_used    BOOLEAN NOT NULL DEFAULT FALSE,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE transactional.evaluation_criterion_details (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id               UUID NOT NULL REFERENCES transactional.evaluation_results(id),
    criterion_id            VARCHAR(100) NOT NULL,
    memberships_by_period   JSONB NOT NULL,
    aggregated_by_phase     JSONB NOT NULL,
    aggregated_membership   NUMERIC(5,4) NOT NULL,
    w_ahp                   NUMERIC(6,5) NOT NULL,
    w_entropy               NUMERIC(6,5),
    w_hybrid                NUMERIC(6,5) NOT NULL,
    entropy_series_used     BOOLEAN NOT NULL,
    entropy_fallback_reason TEXT NULL
);

CREATE TABLE transactional.agronomy_gaps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id       UUID NOT NULL REFERENCES transactional.evaluation_results(id),
    criterion_id    VARCHAR(100) NOT NULL,
    phase_id        VARCHAR(100) NOT NULL,
    most_limiting_period VARCHAR(50) NOT NULL,
    observed_value  NUMERIC NOT NULL,
    optimal_limit   NUMERIC NOT NULL,
    gap_value       NUMERIC NOT NULL
);

CREATE TABLE transactional.limiting_factors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id       UUID NOT NULL REFERENCES transactional.evaluation_results(id),
    criterion_id    VARCHAR(100) NOT NULL,
    phase_id        VARCHAR(100) NOT NULL,
    policy          VARCHAR(20) NOT NULL,
    penalty_factor  NUMERIC(4,3),
    observed_value  NUMERIC NOT NULL,
    optimal_limit   NUMERIC NOT NULL,
    membership      NUMERIC(5,4) NOT NULL,
    doc_source      TEXT
);

-- Recomendaciones
CREATE TABLE transactional.recommendations (
    id              UUID PRIMARY KEY,
    evaluation_id   UUID NOT NULL REFERENCES transactional.evaluation_sagas(id),
    crop_id         VARCHAR(100) NOT NULL,
    text            TEXT NOT NULL,
    fragment_ids    JSONB NOT NULL,         -- array de UUIDs
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Usuarios
CREATE TABLE transactional.users (
    id              UUID PRIMARY KEY,
    email           VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role            VARCHAR(30) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE transactional.auth_audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempted_user  VARCHAR(255),
    ip_address      VARCHAR(45),
    success         BOOLEAN NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Esquema `documental`

```sql
-- Requiere extensión pgvector
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documental.documents (
    id          UUID PRIMARY KEY,
    title       VARCHAR(500) NOT NULL,
    format      VARCHAR(10) NOT NULL,
    crop_tags   JSONB NOT NULL,
    size_bytes  BIGINT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status      VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
);

CREATE TABLE documental.document_fragments (
    id              UUID PRIMARY KEY,
    document_id     UUID NOT NULL REFERENCES documental.documents(id) ON DELETE CASCADE,
    text            TEXT NOT NULL,
    page_ref        INTEGER,
    crop_tags       JSONB NOT NULL,
    token_count     INTEGER NOT NULL,
    embedding       VECTOR(1536),            -- dimensión configurable
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Índice ANN para búsqueda vectorial eficiente
CREATE INDEX idx_fragments_embedding ON documental.document_fragments
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

---

## 9. API Gateway y routing

Todas las rutas pasan por el middleware de autenticación JWT. El API Gateway es el router principal de FastAPI que incluye los routers de cada BC.

| Método | Path | Roles | Descripción |
|--------|------|-------|-------------|
| POST | `/auth/login` | público | Autenticación, retorna JWT |
| POST | `/auth/refresh` | autenticado | Refresca token |
| GET | `/parcelas` | ESPECIALISTA_TECNICO, ADMINISTRADOR | Lista parcelas del usuario |
| POST | `/parcelas` | ESPECIALISTA_TECNICO, ADMINISTRADOR | Registra nueva parcela |
| GET | `/parcelas/{id}` | ESPECIALISTA_TECNICO, ADMINISTRADOR | Detalle + historial de evaluaciones |
| PATCH | `/parcelas/{id}` | ESPECIALISTA_TECNICO, ADMINISTRADOR | Actualiza metadatos/geometría |
| GET | `/rulebooks` | ADMINISTRADOR, ESPECIALISTA_TECNICO | Lista rulebooks |
| POST | `/rulebooks` | ADMINISTRADOR | Crea rulebook (DRAFT) |
| POST | `/rulebooks/{id}/publish` | ADMINISTRADOR | Publica versión activa |
| GET | `/rulebooks/{crop_id}/active` | ADMINISTRADOR, ESPECIALISTA_TECNICO | Rulebook activo para cultivo |
| POST | `/documentos` | ADMINISTRADOR | Carga documento técnico |
| DELETE | `/documentos/{id}` | ADMINISTRADOR | Elimina documento |
| POST | `/evaluaciones` | ESPECIALISTA_TECNICO, ADMINISTRADOR | Solicita evaluación (→ HTTP 202) |
| GET | `/evaluaciones/{id}/estado` | todos los roles | Consulta estado de saga (polling) |
| GET | `/evaluaciones/{id}/resultado` | todos los roles | Resultado completo cuando RECOMENDACION_COMPLETADA |

---

## 10. Configuración y variables de entorno

```bash
# Aplicación
APP_NAME=VIA - Viabilidad Inteligente Agrícola

# Base de datos — SQLAlchemy síncrono con psycopg2
# NO usar asyncpg; el MVP usa sesiones síncronas en repositorios, UoW y RelayWorker
DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/agri_viability
DB_SCHEMA_TRANSACTIONAL=transactional
DB_SCHEMA_DOCUMENTAL=documental

# JWT / IAM
JWT_SECRET_KEY=<secreto_largo>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Google Earth Engine
GEE_SERVICE_ACCOUNT=<email>
GEE_KEY_FILE_PATH=/secrets/gee_key.json
GEE_EXTRACTION_TIMEOUT_SECONDS=60
GEE_MAX_RETRIES=3

# LLM externo
LLM_API_URL=https://api.openai.com/v1/chat/completions
LLM_API_KEY=<api_key>
LLM_MODEL=gpt-4o
LLM_TIMEOUT_SECONDS=30
LLM_MAX_RETRIES=2

# Embeddings
EMBEDDING_API_URL=https://api.openai.com/v1/embeddings
EMBEDDING_API_KEY=<api_key>
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536

# RAG
RAG_SIMILARITY_THRESHOLD=0.5
RAG_MAX_FRAGMENTS=10
RAG_RECOMMENDATION_MAX_FRAGMENTS=8

# Outbox / Relay Worker
RELAY_WORKER_POLL_INTERVAL_SECONDS=5
RELAY_WORKER_BATCH_SIZE=20
RELAY_WORKER_MAX_RETRIES=5

# MCDA
MCDA_ALPHA=0.7                           # parámetro α para combinación convexa w_hybrid
MCDA_MIN_TEMPORAL_SERIES_LENGTH=3        # mínimo de períodos para calcular entropía
MCDA_VIABLE_THRESHOLD=0.70               # score >= umbral → VIABLE
MCDA_CONDICIONAL_THRESHOLD=0.40          # score >= umbral → CONDICIONAL, else NO_VIABLE
MCDA_PENALIZE_EPSILON=0.01               # piso mínimo de membresía para criterios PENALIZE antes de MGP
MCDA_ENTROPY_MIN_DIVERGENCE=1e-9         # umbral mínimo de sum(d_k) para aplicar pesos por entropía

# Parcelas
PARCEL_MAX_AREA_HA=50000                 # área máxima permitida en hectáreas

# Rulebooks
RULEBOOK_WEIGHT_TOLERANCE=0.001          # tolerancia para validación de sumas de pesos
```

---

## 11. Estrategia de testing

### 11.1 Tests unitarios — Domain Services (sin infraestructura)

Todos los tests del BC Evaluación corren sin instanciar SQLAlchemy, FastAPI ni el Event Bus. Las dependencias externas se inyectan como mocks o stubs simples.

**`test_fuzzification_service.py`**:
- Función trapezoidal retorna 0.0 fuera del soporte `[a, d]`.
- Retorna 1.0 en el plateau `[b, c]`.
- Interpolación lineal correcta en rampas.
- Casos degenerados: `b=a` (escalón izquierdo), `d=c` (escalón derecho), `b=c` (triangular) — sin división por cero.
- Retorna siempre un valor en `[0.0, 1.0]`.

**`test_temporal_aggregation_service.py`**:
- MGP con pesos unitarios retorna la media geométrica estándar.
- MGP con un membership = 0.0 retorna 0.0.
- Suma de pesos = 1.0 produce score en `[0.0, 1.0]`.

**`test_entropy_weights_service.py`**:
- Serie uniforme → mayor entropía → menor peso objetivo.
- Serie concentrada en un período → menor entropía → mayor peso objetivo.
- Serie con longitud < mínimo → retorna `None`.
- Pesos objetivos suman 1.0.

**`test_hybrid_weights_service.py`**:
- Con `w_entropy=None`: pesos híbridos = pesos AHP.
- Con `alpha=1.0`: pesos híbridos = pesos AHP.
- Con `alpha=0.0`: pesos híbridos = pesos entropía.
- Pesos híbridos siempre suman 1.0 tras normalización.
- Ningún criterio recibe peso cero cuando `alpha ∈ (0,1)` y `w_ahp > 0`.

**`test_missing_criteria_service.py`**:
- Criterio crítico faltante sin regla alternativa → `calc_condition = NO_CONCLUYENTE` y `rank_position = None`.
- Criterio no crítico faltante → se excluye del cálculo, se registra en `missing_criteria` y `calc_condition = PARCIAL`.
- Pesos de criterios restantes se renormalizan a suma 1.0 una sola vez.
- Faltantes no críticos no se tratan como membresía 0.0.

**`test_multicriteria_aggregation_service.py`**:
- Score ∈ `[0.0, 1.0]`.
- Con todas las membresías = 1.0 → score = 1.0.
- Con alguna membresía = 0.0 → score = 0.0 (propiedad MGP).

**`test_critical_policy_service.py`**:
- `NO_VIABLE` con membresía 0.0 → `viability_category = NO_VIABLE`.
- `PENALIZE` con `penalty_factor = 0.5` → score se reduce a la mitad.
- Sin factor limitante → sin cambio en score ni categoría.
- Registro correcto de `LimitingFactor` con todos sus campos.

**`test_viability_classifier_service.py`**:
- Criterio crítico faltante sin regla alternativa → `calc_condition = NO_CONCLUYENTE`.
- Criterio no crítico faltante → `calc_condition = PARCIAL`.
- Sin faltantes → `calc_condition = DEFINITIVO`.
- Score ≥ umbral VIABLE → `viability_category = VIABLE`.
- Score < umbral CONDICIONAL → `viability_category = NO_VIABLE`.
- `viability_category = NO_VIABLE` por `critical_policy` no se sobreescribe por score.

**`test_gap_calculation_service.py`**:
- Brecha negativa cuando `observed < optimal_lower_limit`.
- Brecha positiva cuando `observed > optimal_upper_limit`.
- Brecha = 0.0 cuando membresía = 1.0 (en plateau óptimo).

### 11.2 Tests de integración

**`test_outbox_relay_worker.py`**: verifica que el RelayWorker lee mensajes PENDING, los publica en el bus, los marca DISPATCHED y que tras 5 fallos marca PERMANENT_FAILURE.

**`test_evaluation_repository.py`**: verifica que `EvaluationRepository.save()` escribe solo en esquema `transactional` sin tocar el esquema `documental`.

**`test_rulebook_acl_adapter.py`**: verifica que `RulebookACLAdapter.get_active_rulebook()` traduce correctamente el DTO externo al `RulebookDomainModel` interno, sin exponer el ORM del BC Rulebooks.

### 11.3 Property-Based Tests (Hypothesis)

**`test_mcda_invariants.py`** — invariantes que deben mantenerse para cualquier entrada válida:

```python
@given(
    memberships=st.lists(st.floats(min_value=0.0, max_value=1.0), min_size=1, max_size=20),
    weights=...  # pesos aleatorios normalizados a 1.0
)
def test_mgp_score_in_range(memberships, weights):
    score = MulticriteriaAggregationService.aggregate(memberships, weights)
    assert 0.0 <= score <= 1.0

@given(params=st.tuples(
    st.floats(0, 100), st.floats(0, 100), st.floats(0, 100), st.floats(0, 100)
).filter(lambda p: p[0] <= p[1] <= p[2] <= p[3]))
def test_fuzzification_always_in_range(params):
    a, b, c, d = params
    value = st.floats(min_value=-10, max_value=110).example()
    result = FuzzificationService.fuzzify(value, MembershipFunction(a, b, c, d))
    assert 0.0 <= result <= 1.0

@given(w_ahp=..., alpha=st.floats(0.0, 1.0))
def test_hybrid_weights_sum_to_one(w_ahp, alpha):
    w_hybrid = HybridWeightsService.combine(w_ahp, w_entropy=None, alpha=alpha)
    assert abs(sum(w_hybrid.values()) - 1.0) < 1e-9
```
