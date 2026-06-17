# Requirements Document

## Introduction

VIA — Viabilidad Inteligente Agrícola es un sistema de evaluación de viabilidad agrícola por parcela que evalúa la aptitud de diversos cultivos para una parcela geoespacial delimitada. El sistema combina un motor de decisión multicriterio con lógica difusa (MCDA difuso), recuperación documental aumentada (RAG) y un modelo de lenguaje externo (LLM) para calcular índices de viabilidad, rankings de cultivos, brechas agronómicas y generar recomendaciones explicables sustentadas en documentación técnica oficial (por ejemplo, INIA).

La arquitectura es un **monolito modular** (Python / FastAPI / SQLAlchemy / PostgreSQL) organizado en **7 Bounded Contexts** bajo principios de **Domain-Driven Design** y **Clean Architecture**. La evaluación completa se ejecuta como una saga asincrónica coordinada por un **Process Manager** centralizado en `shared/orchestration/evaluation_process_manager`. La fiabilidad de mensajería se garantiza mediante el patrón **Transactional Outbox** con relay worker y consumidores idempotentes bajo semántica **at-least-once**.

---

## Glossary

- **Parcela**: Unidad geoespacial delimitada como `Polygon` o `MultiPolygon` GeoJSON sobre la cual se solicita una evaluación agrícola. En el MVP no se aceptan puntos; un `Polygon` simple se normaliza internamente a `MultiPolygon` para persistencia.
- **Cultivo**: Especie vegetal candidata a ser evaluada para una parcela.
- **Rulebook Ecofisiológico**: Documento estructurado que contiene criterios, fases fenológicas, rangos óptimos/tolerables, funciones de membresía difusa, pesos base Fuzzy AHP precalculados y metadatos de fuente documental para un cultivo específico.
- **Vector Agroambiental**: Conjunto de variables climáticas, edáficas, topográficas y de teledetección extraídas para una parcela desde fuentes externas (GEE u otras), organizadas por fase fenológica y período temporal.
- **RequiredExtractionSpec**: Especificación de extracción generada por el BC Rulebooks y reenviada por el Process Manager al BC Extracción. Contiene, por variable requerida: `variable_name`, `criterion_id`, `crop_id`, `phase_id`, `dataset_key`, `band`, `unit`, `temporal_resolution`, `spatial_resolution` o `scale`, `reducer`, `aggregation_method`, `temporal_window`, `temporal_periods`, `quality_mask` y `fallback_allowed`. El Process Manager no interpreta este contenido; solo lo reenvía.
- **MCDA Difuso**: Motor de decisión multicriterio con lógica difusa que ejecuta fuzificación por fase fenológica, calcula pesos híbridos, agrega temporalmente y multicriterio mediante Media Geométrica Ponderada, aplica penalizaciones por factores limitantes, y produce un score de viabilidad trazable.
- **Fuzzy AHP**: Proceso Analítico Jerárquico difuso utilizado para derivar los pesos base de importancia relativa de los criterios ecofisiológicos a partir del juicio experto. Los pesos resultantes son precalculados y almacenados en el Rulebook; el flujo principal de evaluación los consume directamente sin reconstruir las matrices de comparación.
- **Peso Objetivo por Entropía**: Peso calculado a partir de la serie temporal de membresías de un criterio. Mide la divergencia informativa, concentración o dispersión temporal de la aptitud del criterio a lo largo del ciclo evaluado. Un criterio con membresías distribuidas de forma relativamente uniforme a lo largo de los períodos evaluados tenderá a presentar mayor entropía. En cambio, un criterio cuya aptitud se concentra en pocos períodos o presenta fases claramente limitantes tenderá a presentar menor entropía y mayor divergencia informativa. Esta medida no refleja incertidumbre de medición satelital ni error de sensor; solo describe la distribución temporal de la aptitud observada. No reemplaza el peso agronómico definido por Fuzzy AHP, sino que lo ajusta mediante combinación convexa cuando existe serie temporal de longitud suficiente.
- **Peso Híbrido**: Combinación convexa de peso base Fuzzy AHP y peso objetivo por entropía: `w*_j = α · w_AHP_j + (1 − α) · w_ENT_j`, donde `α ∈ (0, 1)` es un parámetro configurable. Esta combinación garantiza que ningún criterio biológicamente importante pueda recibir peso cero por efecto del componente objetivo.
- **Fuzificación**: Proceso de transformar un valor observado en un grado de membresía difusa en el rango [0.0, 1.0] según las funciones de membresía definidas en el Rulebook para cada criterio, cultivo y fase fenológica.
- **Agregación Temporal**: Combinación de los grados de membresía de múltiples períodos dentro de una fase fenológica mediante Media Geométrica Ponderada, produciendo una membresía agregada por criterio y fase.
- **Agregación Multicriterio**: Combinación de las membresías agregadas por criterio mediante Media Geométrica Ponderada usando los pesos híbridos, produciendo el Score de Viabilidad final del cultivo.
- **Factor Limitante**: Criterio cuya membresía agregada es igual a 0.0, indicando una condición agronómica incompatible con el cultivo. Si el criterio es crítico, el comportamiento del sistema depende de la `critical_policy` definida en el Rulebook.
- **critical_policy**: Campo del Rulebook que define el comportamiento del motor cuando un criterio crítico alcanza membresía 0.0. Valores posibles: `NO_VIABLE` (se asigna categoría de viabilidad `NO_VIABLE` al cultivo y se excluye del Ranking principal) o `PENALIZE` (se aplica un `penalty_factor` al score; la categoría de viabilidad resultante es determinada por el score penalizado). La `critical_policy` opera sobre la **categoría de viabilidad**, no sobre la condición del cálculo (`DEFINITIVO`, `PARCIAL`, `NO_CONCLUYENTE`).
- **penalty_factor**: Valor numérico en el rango [0.0, 1.0] definido en el Rulebook para un criterio con `critical_policy = PENALIZE`. El Score de Viabilidad calculado se multiplica por este factor cuando el criterio actúa como factor limitante.
- **Score de Viabilidad**: Valor numérico en el rango [0.0, 1.0] que representa la aptitud global de un cultivo para una parcela dada. Tiene dos atributos diferenciados: (1) **Condición del cálculo**: refleja la completitud de los datos usados — `DEFINITIVO` (todos los criterios disponibles), `PARCIAL` (uno o más criterios no críticos faltantes), `NO_CONCLUYENTE` (al menos un criterio crítico faltante sin regla alternativa). (2) **Categoría de viabilidad**: refleja el resultado agronómico — `VIABLE`, `CONDICIONAL` o `NO_VIABLE`; la categoría `NO_VIABLE` es asignada por la `critical_policy` cuando un criterio crítico presenta membresía 0.0 y no tiene relación con la condición del cálculo.
- **Brecha Agronómica**: Diferencia con signo entre el valor observado de una variable y el límite óptimo más cercano del rango definido en el Rulebook, calculada por criterio y fase fenológica: (valor_observado − límite_óptimo). Negativo indica déficit; positivo indica exceso.
- **Ranking de Cultivos**: Ordenamiento descendente de cultivos candidatos según su Score de Viabilidad. Solo se incluyen cultivos cuya condición del cálculo es `DEFINITIVO` o `PARCIAL` y cuya categoría de viabilidad no es `NO_VIABLE`. Los empates se resuelven por orden alfanumérico ascendente del identificador de cultivo.
- **Recomendación Sustentada**: Texto explicativo generado por el LLM a partir de la evidencia técnica recuperada y los resultados del MCDA Difuso. El LLM no calcula viabilidad, membresías, pesos, scores ni brechas; solo redacta explicaciones y recomendaciones sustentadas en los resultados precalculados.
- **RAG (Retrieval-Augmented Generation)**: Técnica que combina recuperación de fragmentos documentales relevantes con generación de texto por un LLM. RAG reduce el riesgo de respuestas no sustentadas al restringir la generación a brechas calculadas y evidencia documental recuperada; no elimina este riesgo por completo.
- **Process Manager**: Componente ubicado en `shared/orchestration/evaluation_process_manager` que coordina las fases de la saga de evaluación sin implementar lógica de dominio.
- **Comando (mensajería)**: Instrucción publicada por el Process Manager hacia el Event Bus para iniciar una acción en un Bounded Context. Ejemplos: `IniciarExtraccionAgroambiental`, `EjecutarEvaluacionViabilidad`, `GenerarRecomendacionSustentada`.
- **Evento (mensajería)**: Notificación emitida por un Bounded Context al concluir una acción o al producirse un fallo. Ejemplos: `VectorAgroambientalGenerado`, `EvaluacionCompletada`, `VectorBrechasGenerado`, `RecomendacionValidada`, `ExtraccionFallida`, `EvaluacionFallida`, `RecomendacionFallida`.
- **Saga de Evaluación**: Flujo asincrónico de fases coordinadas por el Process Manager: extracción agroambiental → evaluación MCDA difuso → recomendación sustentada.
- **Transactional Outbox**: Patrón de persistencia donde los mensajes de dominio —tanto comandos publicados por el Process Manager (`IniciarExtraccionAgroambiental`, `EjecutarEvaluacionViabilidad`, `GenerarRecomendacionSustentada`) como eventos emitidos por los Bounded Contexts (`VectorAgroambientalGenerado`, `EvaluacionCompletada`, `VectorBrechasGenerado`, `RecomendacionValidada`, `ExtraccionFallida`, `EvaluacionFallida`, `RecomendacionFallida`)— se escriben atómicamente junto con los cambios de estado antes de ser despachados al Event Bus. El Outbox no se limita a eventos; aplica a cualquier mensaje que deba publicarse con garantía de persistencia atómica.
- **Relay Worker**: Proceso que lee el Outbox y publica los mensajes pendientes (comandos y eventos) en el Event Bus interno con semántica at-least-once.
- **Event Bus**: Componente en memoria (MVP) que enruta comandos y eventos entre el Process Manager y los Bounded Contexts.
- **Idempotent Consumer**: Consumidor que detecta y descarta mensajes duplicados enviados por el Relay Worker sin ejecutar efectos secundarios, haciendo tolerante la semántica at-least-once.
- **Anti-Corruption Layer (ACL)**: Adaptador que traduce modelos y estructuras de fuentes externas al lenguaje ubicuo interno.
- **CQRS Ligero**: Separación de Command Services (escritura) y Query Services (lectura) dentro de cada Bounded Context.
- **IAM**: Bounded Context de Gestión de Usuarios y Accesos.
- **GEE**: Google Earth Engine, fuente de datos agroambientales externos.
- **DTO**: Data Transfer Object, estructura de datos usada en la capa de Interfaces.
- **LLM**: Modelo de Lenguaje de Gran Escala externo usado exclusivamente para redactar recomendaciones y explicaciones; no participa en ningún cálculo de viabilidad.
- **Estado de Evaluación**: Estado persistido del Process Manager para una evaluación en curso: `INICIADA`, `EXTRACCION_COMPLETADA`, `EVALUACION_COMPLETADA`, `RECOMENDACION_COMPLETADA`, `FALLIDA`.
- **Criterio Faltante**: Variable del Vector Agroambiental no disponible o fuera del rango de datos para una parcela dada; marcada como `CRITERIO_FALTANTE`.
- **Variable No Reconocida**: Variable presente en el Vector Agroambiental que no existe en el Rulebook del cultivo evaluado; marcada como `VARIABLE_NO_RECONOCIDA` e ignorada en el cálculo.
- **Base Transaccional**: Esquema PostgreSQL `transactional` que almacena entidades de dominio, estado de sagas y tabla Outbox.
- **Base Documental**: Esquema PostgreSQL `documental` con extensión vectorial (pgvector) que almacena fragmentos e índices para RAG.
- **Criterio Crítico**: Criterio del Rulebook declarado explícitamente como imprescindible; su ausencia o membresía igual a 0.0 tiene consecuencias severas sobre el resultado.
- **Ventana Temporal de Análisis**: Período de tiempo definido por fecha de siembra tentativa o rango de fechas, usado para alinear cada fase fenológica del cultivo con los períodos de extracción geoespacial correspondientes.

---

## Requirements

---

### Requirement 1: Autenticación y Control de Acceso (IAM)

**User Story:** Como usuario del sistema, quiero autenticarme y que el sistema valide mis permisos, para que solo los usuarios autorizados puedan solicitar evaluaciones, administrar parcelas y gestionar rulebooks.

#### Acceptance Criteria

1. WHEN un usuario envía credenciales válidas, THE IAM_Service SHALL generar un token de sesión JWT firmado con tiempo de expiración configurable y retornarlo en la respuesta con código HTTP 200.
2. IF un usuario envía credenciales inválidas (usuario inexistente o contraseña incorrecta), THEN THE IAM_Service SHALL rechazar la solicitud con código HTTP 401 y un mensaje genérico que no revele si el usuario existe en el sistema.
3. IF un request llega a cualquier endpoint protegido sin token de autenticación, THEN THE IAM_Service SHALL rechazar la solicitud con código HTTP 401 indicando que se requiere autenticación.
4. WHEN un token de sesión expirado es recibido en cualquier endpoint protegido, THE IAM_Service SHALL rechazar la solicitud con código HTTP 401 e indicar que la sesión ha expirado.
5. THE IAM_Service SHALL controlar el acceso por roles; los roles definidos son `ADMINISTRADOR`, `ESPECIALISTA_TECNICO` y `USUARIO_AGRICOLA`, con la jerarquía: `ADMINISTRADOR` > `ESPECIALISTA_TECNICO` > `USUARIO_AGRICOLA`.
6. WHEN un usuario con rol `USUARIO_AGRICOLA` intenta ejecutar una operación restringida a `ESPECIALISTA_TECNICO` o `ADMINISTRADOR`, THE IAM_Service SHALL rechazar la solicitud con código HTTP 403 y un mensaje que indique insuficiencia de permisos sin revelar los roles requeridos.
7. WHEN un usuario con rol `ESPECIALISTA_TECNICO` intenta ejecutar una operación restringida a `ADMINISTRADOR`, THE IAM_Service SHALL rechazar la solicitud con código HTTP 403.
8. THE IAM_Service SHALL registrar cada intento de autenticación fallido con marca de tiempo ISO-8601, identificador de usuario intentado y dirección IP de origen.

---

### Requirement 2: Gestión de Parcelas

**User Story:** Como especialista técnico, quiero registrar y mantener parcelas geoespaciales, para que el sistema pueda asociarlas a evaluaciones agrícolas y extraer variables agroambientales de su área.

#### Acceptance Criteria

1. WHEN un especialista técnico envía los datos de una nueva parcela con geometría GeoJSON válida de tipo `Polygon` o `MultiPolygon` y metadatos requeridos (nombre, descripción, sistema de referencia), THE Parcela_Service SHALL normalizar un `Polygon` simple a `MultiPolygon`, persistir la parcela y retornar su identificador único con código HTTP 201.
2. IF la geometría enviada no es `Polygon` ni `MultiPolygon`, o es inválida por alguna de las siguientes condiciones en cualquiera de sus polígonos: anillo no cerrado, coordenadas fuera de rango WGS-84, anillo exterior con menos de 4 puntos, o intersecciones propias, THEN THE Parcela_Service SHALL rechazar el registro con código HTTP 422 y retornar un mensaje de error que identifique la condición de invalidez específica.
3. IF la geometría total de la parcela supera el área máxima configurada por el sistema, THEN THE Parcela_Service SHALL rechazar el registro con código HTTP 422 y retornar el área enviada y el área máxima permitida.
4. WHEN un especialista técnico solicita la lista de parcelas, THE Parcela_Service SHALL retornar únicamente las parcelas cuyo propietario coincide con el identificador del usuario autenticado.
5. WHEN un especialista técnico solicita los detalles de una parcela por su identificador, THE Parcela_Service SHALL retornar la geometría GeoJSON, los metadatos y el historial de evaluaciones asociadas (identificadores y estados).
6. IF se intenta acceder a una parcela cuyo identificador no existe en el sistema, THEN THE Parcela_Service SHALL retornar código HTTP 404.
7. IF un usuario intenta acceder o modificar una parcela que pertenece a otro usuario, THEN THE Parcela_Service SHALL retornar código HTTP 403 sin revelar la existencia de la parcela.
8. WHEN un especialista técnico actualiza los metadatos de una parcela existente que le pertenece, THE Parcela_Service SHALL persistir los nuevos metadatos y registrar los metadatos anteriores con marca de tiempo ISO-8601 en el historial de versiones.
9. WHEN un especialista técnico actualiza la geometría de una parcela existente, THE Parcela_Service SHALL aceptar solo `Polygon` o `MultiPolygon`, normalizar `Polygon` a `MultiPolygon`, y aplicar las mismas validaciones de cierre, WGS-84, mínimo de puntos, autointersecciones y área máxima por polígono y total antes de persistir el cambio.

---

### Requirement 3: Gestión de Rulebooks Ecofisiológicos

**User Story:** Como administrador, quiero construir, versionar y publicar rulebooks ecofisiológicos por cultivo, para que el motor MCDA Difuso disponga de criterios, rangos, pesos base Fuzzy AHP y funciones de membresía actualizados y auditables.

#### Acceptance Criteria

1. WHEN un administrador envía un rulebook con criterios, fases fenológicas, rangos óptimos, funciones de membresía, pesos base Fuzzy AHP precalculados, indicadores de criterio crítico y metadatos de fuente documental por parámetro válidos, THE Rulebook_Service SHALL persistir el rulebook con un número de versión incremental (entero positivo, iniciando en 1 para el primer rulebook de cada cultivo).
2. IF un rulebook enviado contiene criterios cuyos pesos base Fuzzy AHP no suman 1.0 (con tolerancia configurable, por defecto ±0.001) dentro del bloque evaluativo correspondiente, THEN THE Rulebook_Service SHALL rechazar el rulebook con código HTTP 422 y retornar un mensaje que indique el valor de la suma calculada, el bloque evaluativo afectado y los identificadores de los criterios involucrados.
3. IF un rulebook enviado contiene un criterio con múltiples fases fenológicas ponderadas cuyos pesos de fase no suman 1.0 (con la misma tolerancia configurable), THEN THE Rulebook_Service SHALL rechazar el rulebook con código HTTP 422 e indicar el criterio afectado y los pesos de fase que no cierran correctamente.
4. IF un rulebook enviado contiene una fase fenológica con múltiples períodos temporales ponderados cuyos pesos temporales no suman 1.0 (con la misma tolerancia configurable), THEN THE Rulebook_Service SHALL rechazar el rulebook con código HTTP 422 e indicar la fase y el criterio afectados y los pesos temporales que no cierran correctamente.
5. IF un rulebook enviado contiene rangos donde el valor mínimo es mayor o igual que el valor máximo, THEN THE Rulebook_Service SHALL rechazar el rulebook con código HTTP 422 y retornar un mensaje que identifique el criterio específico con el rango inválido.
6. WHEN un administrador publica una versión de rulebook para un cultivo que ya tiene una versión activa, THE Rulebook_Service SHALL marcar la nueva versión como activa y marcar la versión anteriormente activa como inactiva, de forma atómica.
7. WHEN un administrador publica la primera versión de un rulebook para un cultivo (sin versión activa previa), THE Rulebook_Service SHALL marcar esa versión como activa directamente.
8. THE Rulebook_Service SHALL mantener el historial completo de versiones de cada rulebook, de modo que cualquier versión pasada pueda ser consultada por su número de versión.
9. IF se solicita una versión de rulebook por número de versión y ese número no existe para el cultivo indicado, THEN THE Rulebook_Service SHALL retornar código HTTP 404.
10. WHEN el Evaluation_Engine solicita el rulebook activo para un cultivo, THE Rulebook_Service SHALL retornar la versión marcada como activa con todos sus criterios, fases, pesos base Fuzzy AHP, pesos de fase, pesos temporales, indicadores de criterio crítico, política de criterio crítico (`critical_policy`), factores de penalización (`penalty_factor`) y metadatos de fuente documental.
11. IF el Evaluation_Engine solicita el rulebook activo para un cultivo que no tiene ninguna versión activa publicada, THEN THE Rulebook_Service SHALL retornar código HTTP 404 con un mensaje que indique que no existe rulebook activo para ese cultivo.
12. WHERE el campo de notas técnicas está presente en un criterio y su longitud no supera los 2000 caracteres, THE Rulebook_Service SHALL persistir dicho campo junto con el criterio sin modificarlo.

---

### Requirement 4: Gestión Documental Técnica

**User Story:** Como administrador, quiero cargar documentos técnicos oficiales (manuales INIA, fichas de cultivo), para que el sistema los fragmente, indexe y los disponga para recuperación en la generación de recomendaciones.

#### Acceptance Criteria

1. WHEN un administrador carga un documento técnico en formato PDF o texto plano con tamaño máximo de 50 MB y metadatos válidos (incluyendo al menos una etiqueta de cultivo), THE Document_Service SHALL validar el formato, fragmentar el contenido en fragmentos de entre 200 y 1000 tokens, y persistir los fragmentos con sus metadatos en la Base Documental.
2. IF el documento cargado no corresponde a formato PDF ni texto plano, THEN THE Document_Service SHALL rechazar la carga con código HTTP 415 y retornar la lista de formatos aceptados.
3. IF el documento cargado supera los 50 MB, THEN THE Document_Service SHALL rechazar la carga con código HTTP 413 e indicar el tamaño máximo permitido.
4. IF el documento cargado no contiene metadatos con al menos una etiqueta de cultivo válida, THEN THE Document_Service SHALL rechazar la carga con código HTTP 422 e indicar que se requiere al menos una etiqueta de cultivo.
5. WHEN los fragmentos de un documento son persistidos en la Base Documental, THE Document_Service SHALL generar y almacenar el embedding vectorial de cada fragmento para permitir búsqueda semántica.
6. WHEN los fragmentos de un documento son persistidos, THE Document_Service SHALL asociar cada fragmento con su documento de origen, número de página de referencia y las etiquetas de cultivo declaradas en los metadatos del documento.
7. WHEN el Recommendation_Service solicita fragmentos relevantes para un cultivo y un conjunto de brechas agronómicas, THE Document_Service SHALL retornar hasta un máximo de 10 fragmentos con mayor similitud semántica, ordenados por score de relevancia descendente.
8. IF el Document_Service no encuentra fragmentos con similitud semántica superior al umbral mínimo configurado (valor en el rango [0.0, 1.0], con valor por defecto 0.5), THEN THE Document_Service SHALL retornar una lista vacía e indicar en la respuesta que no se encontró evidencia suficiente.
9. WHEN un administrador elimina un documento, THE Document_Service SHALL eliminar todos sus fragmentos y embeddings asociados de la Base Documental de forma atómica.

---

### Requirement 5: Extracción Agroambiental de Parcela

**User Story:** Como sistema, quiero obtener automáticamente las variables climáticas, edáficas, topográficas y de teledetección de una parcela, organizadas por fase fenológica y período temporal, para que el motor de evaluación disponga de datos observados actualizados y alineados con el cultivo.

#### Acceptance Criteria

1. WHEN el Process_Manager publica el comando `IniciarExtraccionAgroambiental` con un identificador de parcela, un conjunto de cultivos candidatos, una ventana temporal de análisis y `required_extraction_spec: RequiredExtractionSpec` válidos, THE Extraction_Service SHALL iniciar la consulta a GEE para esa parcela en un plazo máximo de 5 segundos desde la recepción del comando.
2. WHEN la consulta a GEE retorna valores no nulos dentro de rangos físicamente plausibles para todas las variables definidas en `required_extraction_spec`, THE Extraction_ACL SHALL traducir las estructuras de datos de GEE al modelo de dominio interno, y THE Extraction_Service SHALL construir el Vector Agroambiental organizado por variable, criterio, cultivo, fase y período temporal, y emitir el evento `VectorAgroambientalGenerado` vía Transactional Outbox.
3. IF GEE retorna un error HTTP o el tiempo de espera supera los 60 segundos después de hasta 3 reintentos, THEN THE Extraction_Service SHALL registrar el fallo con marca de tiempo y causa, y emitir el evento `ExtraccionFallida` vía Transactional Outbox.
4. IF una o más variables definidas en `required_extraction_spec` no están disponibles en GEE para la parcela y período solicitados, THEN THE Extraction_Service SHALL marcar dichas variables como `CRITERIO_FALTANTE` en el Vector Agroambiental y continuar la construcción con las variables disponibles cuando `fallback_allowed` lo permita.
5. THE Extraction_Service SHALL incluir en cada entrada del Vector Agroambiental la fuente de datos, `dataset_key`, `band`, unidad, resolución temporal, resolución espacial o escala, método de reducción, método de agregación, máscara de calidad aplicada, fecha de extracción ISO-8601 y período de análisis de la variable.
6. THE Extraction_Service SHALL usar `required_extraction_spec` solo como contrato de entrada, y SHALL NOT importar, interpretar ni depender del modelo interno del Rulebook.
7. WHILE una extracción está en curso para una parcela y período determinados, IF el Process_Manager publica un nuevo comando `IniciarExtraccionAgroambiental` para la misma parcela y período, THEN THE Extraction_Service SHALL descartar el comando duplicado, emitir el evento `ExtraccionDuplicadaRechazada` vía Transactional Outbox y no iniciar una nueva consulta a GEE.

---

### Requirement 6: Evaluación de Viabilidad Agrícola — Inicialización, Alineación Fenológica y Orquestación de Saga

**User Story:** Como especialista técnico, quiero solicitar una evaluación de viabilidad agrícola para una parcela y un conjunto de cultivos candidatos indicando una ventana temporal de análisis, para que el sistema alinee las fases fenológicas con los datos extraídos, inicie de forma confiable el flujo asincrónico de evaluación y me permita consultar su estado.

#### Acceptance Criteria

1. WHEN un especialista técnico envía una solicitud de evaluación con un identificador de parcela válido, al menos un cultivo candidato y una ventana temporal de análisis (fecha de siembra tentativa o rango de fechas), THE Process_Manager SHALL crear un registro de evaluación con estado `INICIADA`, asignar un identificador único de evaluación y retornarlo al solicitante con código HTTP 202.
2. WHEN el registro de evaluación es creado con estado `INICIADA`, THE Process_Manager SHALL invocar `IRulebookReadModelPort.get_required_extraction_spec(crop_candidates, temporal_window)` y publicar el comando `IniciarExtraccionAgroambiental` vía Transactional Outbox dentro de la misma transacción atómica, incluyendo `required_extraction_spec` en el payload.
3. IF la parcela referenciada en la solicitud de evaluación no existe en el sistema, THEN THE Process_Manager SHALL rechazar la solicitud con código HTTP 404.
4. IF la solicitud de evaluación no incluye una ventana temporal de análisis (ni fecha de siembra tentativa ni rango de fechas), THEN THE Process_Manager SHALL rechazar la solicitud con código HTTP 422 e indicar que no es posible alinear las fases fenológicas con los datos temporales requeridos sin una ventana temporal definida.
5. IF el especialista técnico envía una solicitud de evaluación para una parcela que ya tiene una evaluación en estado `INICIADA` o `EXTRACCION_COMPLETADA`, THEN THE Process_Manager SHALL rechazar la nueva solicitud con código HTTP 409 y retornar el identificador de la evaluación en curso.
6. WHEN un usuario consulta el estado de una evaluación en curso por su identificador, THE Process_Manager SHALL retornar código HTTP 202 con el estado actual y la marca de tiempo ISO-8601 de la última transición de estado.
7. WHEN un usuario consulta el estado de una evaluación con estado `RECOMENDACION_COMPLETADA` o `FALLIDA`, THE Process_Manager SHALL retornar código HTTP 200 con el estado final y la marca de tiempo de la última transición.
8. THE Process_Manager SHALL NOT interpretar rulebooks, criterios, fases, datasets, bandas, máscaras de calidad ni funciones de membresía; solo SHALL reenviar `required_extraction_spec` al BC Extracción.

---

### Requirement 7: Evaluación de Viabilidad Agrícola — Motor MCDA Difuso

**User Story:** Como sistema, quiero ejecutar el cálculo de viabilidad con el motor MCDA Difuso al recibir el Vector Agroambiental, para que se produzcan scores, rankings y brechas agronómicas trazables y auditables considerando la estructura fenológica del cultivo, pesos híbridos y penalizaciones por factores limitantes.

#### Acceptance Criteria

1. WHEN el Process_Manager publica el comando `EjecutarEvaluacionViabilidad` con un Vector Agroambiental, una ventana temporal de análisis y el conjunto de Rulebooks activos para los cultivos candidatos, THE Evaluation_Engine SHALL ejecutar el cálculo MCDA Difuso completo para cada cultivo candidato.

2. WHEN el Evaluation_Engine procesa un cultivo, THE Evaluation_Engine SHALL alinear fenológicamente la evaluación: usar la ventana temporal de análisis y la duración de cada fase fenológica definida en el Rulebook para mapear cada fase con los períodos del Vector Agroambiental; IF no es posible realizar esta alineación por ausencia de datos temporales suficientes para alguna fase, THEN THE Evaluation_Engine SHALL registrar la fase como no alineada y tratarla como `CRITERIO_FALTANTE` para todos sus criterios.

3. WHEN el Evaluation_Engine ejecuta el MCDA Difuso para un cultivo, THE Evaluation_Engine SHALL fuzificar cada variable observada por cultivo, fase fenológica y criterio, aplicando las funciones de membresía definidas en el Rulebook activo, produciendo un grado de membresía en [0.0, 1.0] por (criterio, período temporal).

4. WHEN los grados de membresía por período temporal han sido calculados para un criterio y fase fenológica, THE Evaluation_Engine SHALL agregar temporalmente dichos grados mediante Media Geométrica Ponderada usando los pesos temporales definidos en el Rulebook, produciendo una membresía agregada por (criterio, fase).

5. WHEN las membresías agregadas por fase han sido calculadas, THE Evaluation_Engine SHALL combinar las membresías de todas las fases de un criterio mediante Media Geométrica Ponderada usando los pesos de fase definidos en el Rulebook, produciendo una membresía agregada por criterio.

6. WHEN las membresías por criterio han sido calculadas, THE Evaluation_Engine SHALL determinar los pesos a aplicar en la agregación multicriterio de la siguiente manera:
   - **Pesos base Fuzzy AHP**: leer directamente desde el Rulebook activo (precalculados por el Especialista Técnico); no reconstruir las matrices de comparación AHP en el flujo principal de evaluación.
   - **Pesos objetivos por entropía**: calcular únicamente si el Vector Agroambiental contiene una serie temporal de longitud suficiente para el criterio (mínimo configurable); la entropía mide la variabilidad, concentración o dispersión temporal de la aptitud del criterio, no la incertidumbre de la fuente satelital.
   - **Pesos híbridos**: combinar ambos mediante la fórmula convexa `w*_j = α · w_AHP_j + (1 − α) · w_ENT_j`, donde `α ∈ (0, 1)` es un parámetro configurable; esta combinación garantiza que ningún criterio biológicamente importante reciba peso cero.
   - IF la serie temporal no es suficiente para calcular pesos por entropía, THEN THE Evaluation_Engine SHALL usar los pesos base Fuzzy AHP directamente (equivalente a `α = 1.0`) y registrar esta condición en el detalle del cálculo.

7. WHEN los pesos híbridos han sido determinados para todos los criterios participantes y su suma es 1.0, THE Evaluation_Engine SHALL agregar multicriterio las membresías por criterio mediante Media Geométrica Ponderada usando los pesos híbridos, produciendo el Score de Viabilidad en el rango [0.0, 1.0].

8. WHEN la membresía agregada de un criterio calculada es igual a 0.0 y ese criterio es declarado crítico en el Rulebook, THE Evaluation_Engine SHALL aplicar la política definida por el campo `critical_policy` del Rulebook para ese criterio:
   - IF `critical_policy = NO_VIABLE`, THEN THE Evaluation_Engine SHALL asignar la categoría de viabilidad `NO_VIABLE` al cultivo, excluirlo del Ranking principal y registrar el criterio como factor limitante crítico. Esta asignación es independiente de la condición del cálculo (`DEFINITIVO`, `PARCIAL` o `NO_CONCLUYENTE`).
   - IF `critical_policy = PENALIZE`, THEN THE Evaluation_Engine SHALL multiplicar el Score de Viabilidad calculado por el `penalty_factor` definido en el Rulebook para ese criterio (valor en el rango [0.0, 1.0]) y registrar el criterio como factor limitante crítico; la categoría de viabilidad resultante se determina a partir del score penalizado.
   - En ambos casos, THE Evaluation_Engine SHALL registrar: identificador del criterio, fase fenológica afectada, valor observado, rango óptimo definido en el Rulebook, membresía resultante (0.0) y la fuente documental del parámetro según el Rulebook.

9. IF al menos un criterio declarado crítico en el Rulebook está marcado como `CRITERIO_FALTANTE` y el Rulebook no define una regla alternativa explícita para ese caso, THEN THE Evaluation_Engine SHALL marcar el Score de Viabilidad del cultivo como `NO_CONCLUYENTE` y no incluir ese cultivo en el Ranking.

10. IF un criterio no crítico está marcado como `CRITERIO_FALTANTE`, THEN THE Evaluation_Engine SHALL excluir ese criterio del cálculo antes de la agregación multicriterio final, registrar el criterio en `missing_criteria`, renormalizar una sola vez los pesos de los criterios restantes para que sumen 1.0, marcar el Score de Viabilidad resultante como `PARCIAL` y registrar el criterio faltante con una advertencia en el detalle del cálculo. THE Evaluation_Engine SHALL NOT tratar faltantes no críticos como membresía 0.0 ni aplicar una segunda normalización contradictoria.

11. WHEN el cálculo es completado para todos los cultivos candidatos, THE Evaluation_Engine SHALL construir el Ranking de Cultivos ordenando únicamente los cultivos cuya condición del cálculo es `DEFINITIVO` o `PARCIAL` y cuya categoría de viabilidad no es `NO_VIABLE`, por Score de Viabilidad en orden descendente; los empates se resolverán por orden alfanumérico ascendente del identificador de cultivo. Los cultivos incluidos en ranking SHALL persistir `rank_position`; los cultivos con condición `NO_CONCLUYENTE` o con categoría de viabilidad `NO_VIABLE` no se incluirán en el Ranking y SHALL persistir `rank_position = NULL`.

12. WHEN el cálculo es completado para todos los cultivos candidatos, THE Evaluation_Engine SHALL calcular la Brecha Agronómica para cada criterio y fase fenológica cuya membresía agregada sea inferior a 1.0, expresada como (valor_observado − límite_óptimo_más_cercano), con signo negativo para déficit y positivo para exceso respecto al rango óptimo del Rulebook.

13. WHEN el cálculo es completado para todos los cultivos candidatos, THE Evaluation_Engine SHALL emitir los eventos `EvaluacionCompletada` y `VectorBrechasGenerado` vía Transactional Outbox, incluyendo el Ranking, todos los Scores con su condición, y todas las Brechas Agronómicas por criterio y fase.

14. WHEN el Evaluation_Engine persiste el resultado de un cálculo, THE Evaluation_Engine SHALL registrar para cada evaluación los siguientes campos mínimos: identificador de evaluación, cultivo, versión del Rulebook utilizado, membresías por fase fenológica, membresía agregada por criterio, peso Fuzzy AHP por criterio, peso objetivo por entropía por criterio (o indicación de no calculado), peso híbrido por criterio, condición del cálculo (`DEFINITIVO` / `PARCIAL` / `NO_CONCLUYENTE`), categoría de viabilidad (`VIABLE` / `CONDICIONAL` / `NO_VIABLE`), criterios faltantes con advertencia, factores limitantes críticos, score final, `rank_position` y marca de tiempo del cálculo; de modo que dado el identificador de evaluación sea posible reconstruir el resultado completo.

15. IF el Vector Agroambiental contiene variables que no existen en el Rulebook del cultivo evaluado y no están marcadas como `CRITERIO_FALTANTE`, THEN THE Evaluation_Engine SHALL ignorar dichas variables en el cálculo y registrarlas como `VARIABLE_NO_RECONOCIDA` en el detalle del cálculo.

16. THE Evaluation_Engine SHALL poder ejecutar el cálculo MCDA Difuso completo en un entorno de prueba sin instanciar adaptadores de base de datos, el framework HTTP ni el Event Bus, verificable mediante tests unitarios que no requieran infraestructura externa.

---

### Requirement 8: Evaluación de Viabilidad Agrícola — Transiciones de Estado de la Saga

**User Story:** Como sistema, quiero que el Process Manager transite el estado de la evaluación de forma confiable entre fases, para que la saga sea resistente a fallos parciales y los estados queden auditados.

#### Acceptance Criteria

1. WHEN el Process_Manager recibe el evento `VectorAgroambientalGenerado` y la evaluación está en estado `INICIADA`, THE Process_Manager SHALL transitar el estado a `EXTRACCION_COMPLETADA` y publicar el comando `EjecutarEvaluacionViabilidad` vía Transactional Outbox, ambas acciones dentro de la misma transacción atómica.
2. WHEN el Process_Manager recibe el evento `EvaluacionCompletada` y la evaluación está en estado `EXTRACCION_COMPLETADA`, THE Process_Manager SHALL transitar el estado a `EVALUACION_COMPLETADA` y publicar el comando `GenerarRecomendacionSustentada` vía Transactional Outbox, ambas acciones dentro de la misma transacción atómica.
3. WHEN el Process_Manager recibe el evento `RecomendacionValidada` y la evaluación está en estado `EVALUACION_COMPLETADA`, THE Process_Manager SHALL transitar el estado a `RECOMENDACION_COMPLETADA` y publicar el evento `EvaluacionFinalizada` vía Transactional Outbox, ambas acciones dentro de la misma transacción atómica.
4. WHEN el Process_Manager recibe cualquiera de los eventos `ExtraccionFallida`, `EvaluacionFallida` o `RecomendacionFallida`, THE Process_Manager SHALL transitar el estado de la evaluación a `FALLIDA` y registrar: la causa del fallo, la fase en que ocurrió y la marca de tiempo ISO-8601, dentro de la misma transacción atómica.
5. THE Process_Manager SHALL persistir cada transición de estado con los siguientes campos: identificador de evaluación, estado anterior, estado nuevo, identificador del mensaje recibido que motivó la transición, y marca de tiempo ISO-8601; el historial completo de transiciones debe ser recuperable por identificador de evaluación.
6. THE Process_Manager SHALL coordinar las fases de la saga sin implementar lógica de dominio ni acceder directamente a los repositorios de datos de los Bounded Contexts de extracción, evaluación o recomendación.
7. WHEN el Process_Manager recibe un mensaje cuyo identificador ya fue procesado previamente, THE Process_Manager SHALL descartar el mensaje sin re-transitar el estado de la evaluación ni ejecutar efectos secundarios.
8. IF el Process_Manager recibe un evento de transición para una evaluación en un estado desde el cual esa transición no es válida (por ejemplo, `EvaluacionCompletada` cuando el estado actual es `INICIADA`), THEN THE Process_Manager SHALL rechazar la transición, preservar el estado actual y registrar el mensaje inválido con su identificador, el estado actual y la marca de tiempo.

---

### Requirement 9: Recomendación Sustentada

**User Story:** Como especialista técnico o usuario agrícola, quiero recibir una recomendación textual explicable y sustentada en documentación técnica oficial, para que pueda comprender y justificar los resultados de viabilidad.

#### Acceptance Criteria

1. WHEN el Process_Manager publica el comando `GenerarRecomendacionSustentada` con el resultado de la evaluación MCDA y el identificador de cultivo, THE Recommendation_Service SHALL recuperar hasta un máximo de 5 fragmentos documentales relevantes desde la Base Documental.
2. WHEN los fragmentos documentales son recuperados, THE Recommendation_Service SHALL construir el prompt para el LLM incluyendo los resultados precalculados: Score de Viabilidad, Ranking, Brechas Agronómicas por criterio y fase, y los fragmentos documentales recuperados; el LLM no calculará viabilidad, membresías, pesos, scores ni brechas.
3. WHEN el LLM retorna una respuesta, THE Recommendation_Service SHALL validar que la respuesta no esté vacía y que mencione explícitamente el Score de Viabilidad y al menos una Brecha Agronómica antes de persistirla.
4. IF el LLM retorna un error o el tiempo de espera es superado, THE Recommendation_Service SHALL reintentar la llamada hasta 2 veces; IF el fallo persiste después de los 2 reintentos, THEN THE Recommendation_Service SHALL registrar el fallo y emitir el evento `RecomendacionFallida` vía Transactional Outbox sin generar texto de recomendación.
5. IF el Document_Service retorna una lista vacía de fragmentos relevantes, THEN THE Recommendation_Service SHALL generar la recomendación indicando explícitamente en el texto que no se encontró evidencia documental suficiente para sustentar las conclusiones; RAG reduce el riesgo de respuestas no sustentadas pero no lo elimina por completo.
6. THE Recommendation_Service SHALL garantizar que el LLM sea utilizado exclusivamente para redactar la explicación textual a partir de los resultados precalculados, y no para calcular scores, membresías, pesos ni brechas agronómicas.
7. WHEN la recomendación es validada, THE Recommendation_Service SHALL emitir el evento `RecomendacionValidada` vía Transactional Outbox incluyendo el texto generado, los identificadores de los fragmentos documentales usados y el identificador de evaluación.
8. THE Recommendation_Service SHALL persistir los identificadores de los fragmentos documentales utilizados junto con la recomendación, de modo que la evidencia sea trazable por identificador de evaluación.

---

### Requirement 10: Fiabilidad del Event Bus y Transactional Outbox

**User Story:** Como sistema, quiero que los mensajes de dominio —comandos y eventos— sean publicados con semántica at-least-once y procesados de forma idempotente, para que la saga de evaluación sea resistente a fallos de infraestructura sin prometer entrega exactly-once.

#### Acceptance Criteria

1. WHEN un Bounded Context emite un evento de dominio o el Process_Manager publica un comando, THE Outbox_Writer SHALL persistir ese mensaje (comando o evento) en la tabla Outbox de la Base Transaccional en la misma transacción atómica que el cambio de estado de dominio, de modo que ambas operaciones se confirmen o deshagan juntas. Cada mensaje SHALL tener `message_id` como identificador individual y `correlation_id UUID NULL`; para la saga de evaluación, `correlation_id = evaluation_id`. Los mensajes cubiertos por este criterio incluyen los comandos `IniciarExtraccionAgroambiental`, `EjecutarEvaluacionViabilidad` y `GenerarRecomendacionSustentada`, así como los eventos `VectorAgroambientalGenerado`, `EvaluacionCompletada`, `VectorBrechasGenerado`, `RecomendacionValidada`, `ExtraccionFallida`, `EvaluacionFallida` y `RecomendacionFallida`.
2. WHEN el Relay_Worker detecta mensajes en estado `PENDING` en la tabla Outbox, THE Relay_Worker SHALL publicar cada mensaje (comando o evento) en el Event Bus interno con semántica at-least-once; un mismo mensaje puede ser publicado más de una vez en caso de reintento, por lo que los consumidores deben ser idempotentes.
3. WHEN el Relay_Worker publica exitosamente un mensaje en el Event Bus, THE Relay_Worker SHALL marcar ese mensaje como `DISPATCHED` en la tabla Outbox en una operación separada posterior a la publicación.
4. IF el Relay_Worker falla antes de marcar un mensaje como `DISPATCHED`, THEN THE Relay_Worker SHALL reintentar la publicación del mismo mensaje en el siguiente ciclo de polling, que no debe superar los 60 segundos, de modo que ningún mensaje se pierda; este comportamiento puede resultar en entregas duplicadas que los consumidores idempotentes deben absorber.
5. WHEN un consumidor recibe un mensaje cuyo identificador ya fue procesado previamente, THE Idempotent_Consumer SHALL descartar el mensaje sin ejecutar ninguna acción de dominio ni efectos secundarios, garantizando que la semántica at-least-once del bus sea segura para el dominio.
6. THE Relay_Worker SHALL procesar mensajes del Outbox en orden ascendente de marca de tiempo de creación; los empates se resolverán por orden ascendente del identificador de mensaje, y SHALL preservar `correlation_id` al publicar en el Event Bus para permitir trazabilidad de toda la saga.
7. IF la publicación de un mensaje en el Event Bus falla después de 5 intentos consecutivos, THEN THE Relay_Worker SHALL marcar el mensaje como `PERMANENT_FAILURE` en la tabla Outbox y registrar un registro de error en un almacén de inspección operativa con: identificador de mensaje, marca de tiempo del último intento y causa del fallo.

---

### Requirement 11: Aislamiento de Bases Lógicas

**User Story:** Como arquitecto del sistema, quiero que las bases transaccional y documental sean esquemas PostgreSQL separados, para que la lógica de dominio y el índice vectorial no interfieran estructuralmente entre sí.

#### Acceptance Criteria

1. THE System SHALL mantener dos esquemas PostgreSQL distintos: un esquema `transactional` para entidades de dominio, estado de sagas y tabla Outbox, y un esquema `documental` para fragmentos de documentos técnicos y sus embeddings vectoriales.
2. WHEN una consulta de recuperación RAG es ejecutada, THE Document_Service SHALL acceder únicamente a tablas del esquema `documental`, sin utilizar JOINs, subconsultas ni referencias directas de tabla que involucren el esquema `transactional`.
3. WHEN el Evaluation_Engine persiste el resultado de una evaluación, THE Evaluation_Persistence_Adapter SHALL escribir únicamente en tablas del esquema `transactional`, sin utilizar JOINs, subconsultas ni referencias directas de tabla que involucren el esquema `documental`.
4. THE Domain_Model SHALL no contener dependencias de importación directas ni transitivas hacia los adaptadores de base de datos, el framework HTTP ni el Event Bus; esta condición es verificable mediante análisis estático de dependencias del módulo de dominio.

---

### Requirement 12: Consulta de Resultados de Evaluación

**User Story:** Como especialista técnico o usuario agrícola, quiero consultar los resultados completos de una evaluación finalizada, para que pueda revisar el ranking de cultivos, los scores, las brechas por criterio y fase, y la recomendación generada.

#### Acceptance Criteria

1. WHEN un usuario consulta el resultado de una evaluación con estado `RECOMENDACION_COMPLETADA` por su identificador, THE Evaluation_Query_Service SHALL retornar el Ranking de Cultivos con `rank_position`, todos los Scores de Viabilidad con su condición, todas las Brechas Agronómicas por criterio y fase fenológica, y la Recomendación Sustentada asociada.
2. WHEN el resultado es retornado, THE Evaluation_Query_Service SHALL incluir para cada cultivo: `rank_position` (`NULL` si el cultivo no entra al ranking), la condición del cálculo (`DEFINITIVO`, `PARCIAL` o `NO_CONCLUYENTE`), la categoría de viabilidad (`VIABLE`, `CONDICIONAL` o `NO_VIABLE`), la lista de identificadores de criterios faltantes que motivaron una condición `PARCIAL` o `NO_CONCLUYENTE`, y los factores limitantes críticos detectados. Para condición `DEFINITIVO` sin factores limitantes, la lista de criterios faltantes y factores limitantes será vacía.
3. IF una evaluación consultada tiene estado `FALLIDA`, THEN THE Evaluation_Query_Service SHALL retornar el estado `FALLIDA`, el nombre de la fase en que ocurrió el fallo y el mensaje de error registrado.
4. WHEN un usuario consulta un resultado, THE Evaluation_Query_Service SHALL retornar los datos sin exponer identificadores de eventos del Outbox, versiones internas de esquemas de base de datos ni trazas de stack de errores.
5. THE Evaluation_Query_Service SHALL ejecutar las consultas de resultados sin modificar el estado de ninguna entidad de dominio ni del Process Manager.
6. IF el identificador de evaluación consultado no existe en el sistema, THEN THE Evaluation_Query_Service SHALL retornar código HTTP 404.
7. IF el identificador de evaluación consultado existe pero la evaluación está en un estado en curso (`INICIADA`, `EXTRACCION_COMPLETADA` o `EVALUACION_COMPLETADA`), THEN THE Evaluation_Query_Service SHALL retornar código HTTP 202 con el estado actual y la marca de tiempo de la última transición, sin resultados parciales.
