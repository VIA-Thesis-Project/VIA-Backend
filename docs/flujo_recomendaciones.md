# Flujo de Recomendaciones en VIA

> Bounded Context: `recommendation`  
> Archivos principales: `application/gap_analysis.py`, `application/command_service.py`, `application/ports.py`, `infrastructure/openai_file_search_provider.py`

---

## Visión general

El proceso de recomendación toma los resultados ya calculados por el motor MCDA (scores, brechas, factores limitantes) y produce un documento técnico agrícola sustentado en evidencia documental recuperada de un vector store. **Ningún componente del pipeline recalcula resultados MCDA**: el LLM recibe los datos como solo-lectura.

```
Evaluation Results (MCDA)
        │
        ▼
┌───────────────────┐
│  1. Gap Analysis  │  ← determinístico, sin LLM
└───────────────────┘
        │  GapAnalysisResult (grupos, clases, prioridades)
        ▼
┌─────────────────────────┐
│  2. Evidence Retrieval  │  ← OpenAI File Search / RAG
└─────────────────────────┘
        │  list[EvidenceData]
        ▼
┌──────────────────────────────┐
│  3. LLM Drafting (provider)  │  ← genera JSON estructurado
└──────────────────────────────┘
        │  structured_output (dict)
        ▼
┌──────────────────────────────────┐
│  4. Quality Control (QC)         │  ← determinístico, sin LLM
│     · detección de sospechosos   │
│     · validación de evidencia    │
│     · reescrituras de seguridad  │
└──────────────────────────────────┘
        │  structured_output limpio
        ▼
┌──────────────────────┐
│  5. Text Rendering   │  ← produce el texto visible final
└──────────────────────┘
        │  text (markdown)
        ▼
┌──────────────────────────────┐
│  6. Recommendation Aggregate │  ← dominio: save + eventos
└──────────────────────────────┘
```

---

## Paso 0 — Disparo del comando

El flujo se inicia cuando llega un mensaje `GenerarRecomendacionSolicitada` al `RecommendationMessageCommandService`. El mensaje trae:

| Campo | Descripción |
|---|---|
| `evaluation_id` | UUID de la evaluación MCDA ya completada |
| `crop_id` | Cultivo específico (opcional; si hay ranking usa rank=1) |
| `max_fragments` | Máximo de fragmentos de evidencia a recuperar |

El servicio verifica idempotencia (tabla `processed_messages`) antes de procesar, y envuelve todo en una transacción unitaria.

---

## Paso 1 — Análisis de brechas (`gap_analysis.py`)

### 1.1 Lectura de resultados de evaluación

`RecommendationCommandService.generate()` llama al puerto `IEvaluationResultsPort.get_results_for_recommendation(evaluation_id)` y obtiene un `EvaluationRecommendationData` que contiene uno o más `CropEvaluationResultData`:

```python
@dataclass(frozen=True)
class CropEvaluationResultData:
    crop_id: str
    score: float | None
    rank_position: int | None
    calc_condition: str          # e.g. "VIABLE", "CONDICIONAL"
    viability_category: str      # e.g. "VIABLE", "CONDICIONAL", "NO_VIABLE"
    gaps: list[GapData]          # brechas por criterio × fase
    limiting_factors: list[LimitingFactorData]
```

Cada `GapData` representa **una brecha en una fase fenológica**:

```python
@dataclass(frozen=True)
class GapData:
    criterion_id: str
    phase_id: str
    most_limiting_period: str
    observed_value: float        # valor real de la parcela
    optimal_limit: float         # límite del rulebook
    gap_value: float             # magnitud de la brecha
    gap_direction: str | None    # "below_optimum" | "above_optimum"
    severity: str | None         # "baja" | "media" | "alta"
    criterion_name: str | None
    criterion_label: str | None
    criterion_group: str | None  # "suelo", "clima", "riego", "topografia"...
    unit: str | None
    phase_name: str | None
    recommendation_topic: str | None
```

### 1.2 Selección del cultivo objetivo

Si `crop_id` fue indicado en el comando, se selecciona ese resultado directamente. Si no, se toma el resultado con `rank_position = 1`. Si existen múltiples resultados y ninguna de las condiciones se cumple, se lanza `RecommendationDomainError`.

### 1.3 `analyse_gaps()` — corazón del análisis

La función `analyse_gaps(crop_result)` en `gap_analysis.py` recibe el `CropEvaluationResultData` y produce un `GapAnalysisResult` completamente determinístico.

#### Agrupación por criterio

Las brechas (que pueden repetirse para varias fases del mismo criterio) se agrupan por `criterion_id`. Cada grupo produce un `GapGroup`:

```python
@dataclass(frozen=True)
class GapGroup:
    criterion_id: str
    gap_class: GapClass          # clasificación de intervención
    correctability: Correctability
    occurrences: list[GapOccurrence]  # una por fase
    representative_observed: float
    representative_optimal: float
    representative_gap: float
    representative_severity: str | None   # la peor fase
    recurrence: int              # cuántas fases presentan brecha
    priority_score: float        # puntaje de priorización
    rulebook_review_required: bool
    data_quality_flags: list[str]
```

#### Clasificación `GapClass`

Cada criterio se clasifica en una de cuatro clases según su **factibilidad de intervención**:

| `GapClass` | Significado | Ejemplos de criterios |
|---|---|---|
| `STRUCTURAL_NOT_CORRECTABLE` | No se puede corregir agronómicamente | `aptitud_altitudinal`, `cobertura_actual_auxiliar`, grupo `topografia` |
| `MITIGABLE` | Se puede reducir el impacto, no eliminar | `aptitud_termica`, `riesgo_frio`, `riesgo_calor`, grupo `clima` |
| `CORRECTABLE` | Se puede corregir con manejo | `reaccion_suelo_ph`, `carbono_organico_suelo`, grupo `suelo`, `riego` |
| `DATA_QUALITY_REVIEW` | Los datos son sospechosos antes de clasificar | Ver detección de flags abajo |

La regla de prioridad es: `criterion_name` explícito > `criterion_group` > fallback a `MITIGABLE` (conservador).

#### Detección de calidad de datos (`_detect_data_quality_flags`)

Antes de clasificar, se inspeccionan los valores en busca de anomalías. Los flags se adjuntan al `GapGroup.data_quality_flags` y fuerzan la clase a `DATA_QUALITY_REVIEW`:

| Condición | Flag generado |
|---|---|
| `criterion_name` y `criterion_group` ambos ausentes | Criterio completamente desconocido |
| `observed_value = 0.0` para `carbono_organico_suelo` o `reaccion_suelo_ph` | Valor físicamente imposible |
| Todos los periodos con `observed_value = 0.0` | Posible fallo de extracción o capa ausente |
| `deficit_hidrico` con valores en rango de altitud (800–4500 msnm) | Posible confusión criterion_id con `aptitud_altitudinal` |
| Valor idéntico en todas las fases para variable temporal | Posible extracción con valor único en vez de media por periodo |
| Inconsistencia de signo en `gap_value` vs `observed - optimal` | Error en fórmula de brecha del motor de evaluación |

#### Correctability

Mapa directo desde `GapClass`, con una excepción: criterios estructurales con **alta severidad dominante** (≥2 fases con severidad "alta") escalan a `requiere_revision_rulebook`.

| `GapClass` | `Correctability` |
|---|---|
| `CORRECTABLE` | `corregible` |
| `MITIGABLE` | `mitigable` |
| `STRUCTURAL_NOT_CORRECTABLE` | `no_corregible` (o `requiere_revision_rulebook`) |
| `DATA_QUALITY_REVIEW` | `requiere_validacion` |

#### Representante del grupo

Se elige la **ocurrencia más severa** como representante del grupo, desempatando por `abs(gap_value)` descendente.

#### Puntaje de prioridad

```
priority_score = severity_weight × (recurrence / 7) × class_multiplier
```

| Factor | Valores |
|---|---|
| `severity_weight` | alta=3.0, media=2.0, baja=1.0 |
| `recurrence` | número de fases con brecha (cap 7) |
| `class_multiplier` | CORRECTABLE=1.0, DATA_QUALITY=0.9, MITIGABLE=0.7, STRUCTURAL=0.4 |

Los grupos se ordenan descendentemente por `priority_score` antes de pasarse al LLM.

#### Barreras dominantes

Son los criterios con `gap_class = STRUCTURAL_NOT_CORRECTABLE` y `representative_severity = "alta"`. Se listan en `ruling_structural_barriers` y condicionan las instrucciones de redacción.

#### Interpretación de viabilidad

Se asigna una instrucción semántica según la categoría:

| `viability_category` | Interpretación |
|---|---|
| `VIABLE` | Generar recomendación técnica directa con plan de manejo estándar |
| `CONDICIONAL` | Plan priorizado diferenciando acciones inmediatas, validaciones, manejo, restricciones y riesgos |
| `NO_VIABLE` | Solo explicación técnica del descarte, brechas dominantes y condiciones mínimas para reconsiderar |

---

## Paso 2 — Recuperación de evidencia (`IDocumentEvidencePort`)

El puerto `IDocumentEvidencePort.search_evidence(crop_id, gaps, max_fragments)` devuelve fragmentos de documentos técnicos relevantes como `list[EvidenceData]`.

En producción, la implementación delega a la OpenAI Responses API con **File Search**, pero esta búsqueda ocurre dentro del Paso 3 (el provider hace RAG internamente). El resultado se extrae luego del trace del provider.

```python
@dataclass(frozen=True)
class EvidenceData:
    fragment_id: UUID
    document_id: UUID
    text: str               # fragmento recuperado
    crop_tags: list[str]
    score: float | None     # relevance score del vector store
    source_filename: str | None   # e.g. "suelo.md", "clima_fenologia.md"
    source_file_id: str | None    # OpenAI file ID
    page_ref: int | None
```

---

## Paso 3 — Borrador LLM (`OpenAIFileSearchDraftingProvider`)

### 3.1 Contexto enviado

El `RecommendationDraftContext` agrupa todo lo que el LLM necesita:

```python
@dataclass(frozen=True)
class RecommendationDraftContext:
    evaluation_id: UUID
    crop_result: CropEvaluationResultData
    evidence: list[EvidenceData]
    gap_analysis: GapAnalysisResult | None
```

### 3.2 Resolución del vector store

Cada cultivo tiene su propio vector store en OpenAI, configurado mediante variables de entorno (`VIA_VECTOR_STORE_MAIZ_AMARILLO_DURO_ID`, etc.). Si no hay vector store para el cultivo, se lanza `OpenAIFileSearchError`.

Cultivos soportados: `maiz_amarillo_duro`, `palta_hass`, `mandarina_murcott`, `maracuya_criolla_amarilla`, `uva_de_mesa_sweet_globe`.

### 3.3 System prompt

El system prompt tiene tres bloques fijos:

1. **Rol**: "Eres un asistente agrícola técnico. Tu única función es redactar en español una recomendación agrícola técnica sustentada en la evidencia documental recuperada por File Search."

2. **Prohibiciones absolutas** (`PROMPT_FORBIDDEN_BEHAVIORS`): 14+ reglas explícitas, entre ellas:
   - No recalcular scores, pesos, membresías, rankings ni categorías de viabilidad
   - No inventar rangos óptimos, dosis, productos ni citas no sustentadas en evidencia
   - No recomendar riego como acción principal para temperatura baja
   - No usar ventana de siembra para cultivos perennes
   - No usar fases de otro cultivo (e.g., "panojamiento" en mandarina)
   - No interpretar `riesgo_calor/below_optimum` como exceso de calor

3. **Formato de salida obligatorio**: JSON estructurado con schema `recommendation_structured_v1`.

### 3.4 User prompt

Se construye dinámicamente con:

- **Header MCDA**: `evaluation_id`, `crop_id`, `score`, `rank_position`, `calc_condition`, `viability_category` (read-only)
- **Sección de brechas**: si hay `GapAnalysisResult`, se formatea con grupos priorizados, clases, correctabilidad, ocurrencias y flags de calidad de datos. Si no, se usan las brechas agrupadas semánticamente.
- **Instrucción de redacción** adaptada a la `viability_category` (VIABLE / CONDICIONAL / NO_VIABLE)
- **Factores limitantes** con política, penalty, membership y dirección
- **Consultas semánticas sugeridas**: generadas automáticamente desde `criterion_label`, `recommendation_topic` y fases afectadas, con contexto geográfico del cultivo
- **Ruteo documental preferido**: mapa de brecha → archivo curado preferido en el vector store (e.g., `suelo.md`, `clima_fenologia.md`, `induccion_floracion_cuajado.md`)

#### Ruteo documental por cultivo

Cada cultivo tiene un conjunto de archivos curados (`CURATED_FILES_BY_CROP`). El provider intenta dirigir al LLM hacia el archivo más relevante según el `criterion_group`/`criterion_name` de cada brecha:

| Cultivo | Archivos curados disponibles (ejemplos) |
|---|---|
| `maiz_amarillo_duro` | `clima_fenologia.md`, `riego.md`, `suelo.md`, `fertilizacion.md`, `siembra_manejo.md`... |
| `palta_hass` | `clima_fenologia.md`, `riego.md`, `suelo.md`, `instalacion_material_vegetal.md`, `sanidad.md`... |
| `mandarina_murcott` | `induccion_floracion_cuajado.md`, `sanidad_mip.md`, `cosecha_postcosecha_calidad.md`... |
| `uva_de_mesa_sweet_globe` | `agua_riego.md`, `floracion_cuajado_raleo_calibre.md`, `sanidad_mip_bpa.md`, `fitosanitario_exportacion_trazabilidad.md`... |

### 3.5 Llamada a OpenAI Responses API

```python
raw = client.create_response(
    model=config.model,
    input_messages=[system_prompt, user_prompt],
    vector_store_ids=[vector_store_id],
    max_num_results=config.max_num_results,
    include=["file_search_call.results"],
    timeout=config.timeout_seconds,
)
```

OpenAI ejecuta File Search, recupera fragmentos del vector store y el modelo genera la recomendación.

### 3.6 Parsing de la respuesta

`_parse_response()` extrae del objeto raw:
- `text`: el texto generado por el LLM
- `fs_call_id`: ID del tool call de File Search
- `results`: lista de `{file_id, filename, score, text}` de los fragmentos recuperados
- `filenames`: nombres de archivos fuente únicos

Si el modelo devolvió JSON válido con `schema_version = "recommendation_structured_v1"`, se parsea como structured output. Si no, se usa como texto legacy con advertencia.

Un `FileSearchTrace` registra toda la trazabilidad de la llamada (evaluation_id, crop_id, vector_store_id, model, prompt_version, response_id, retrieved_results, etc.).

---

## Paso 4 — Control de calidad (`_quality_control_structured_output`)

Luego del LLM, **el QC es 100% determinístico**. Recibe el `structured_output` del LLM y lo transforma aplicando una serie de guardas en orden:

### 4.1 Por cada ítem de `gap_recommendations`

1. **Normalización de `limitations`**: convierte strings `"None"/"null"/"-"` a `None`.

2. **Guardas de seguridad en reescrituras**:

   | Guarda | Condición | Acción |
   |---|---|---|
   | `_rewrite_unsafe_clay_recommendation` | Criterio de arcilla + recomienda "aumentar" arcilla | Reescribe hacia mejora de estructura y MO |
   | `_rewrite_unsafe_thermal_recommendation` | `aptitud_termica/below_optimum` + recomienda riego como acción principal | Reescribe hacia ajuste de ventana de siembra (anuales) o manejo fenológico (perennes) |
   | `_sanitize_perennial_annual_language` | Cultivo perenne + lenguaje de "ventana de siembra" o "campaña" | Reemplaza por "manejo fenológico" |
   | `_sanitize_maiz_huerto_language` | `maiz_amarillo_duro` + lenguaje de "huerto" | Reemplaza por "lote" |
   | `_rewrite_unsafe_arena_recommendation` | `contenido_arena` + recomienda modificar textura directamente | Reescribe hacia análisis físico y mejora de estructura |
   | `_guard_mandarina_controlled_hydric_stress` | `deficit_hidrico` + "estrés hídrico controlado" en fase que no es inducción/floración/cuajado | Elimina recomendación, evidencia insuficiente |

3. **Detección de sospechosos de mapeo** (marcan `criterion_mapping_suspect = True`):

   | Sospechoso | Condición |
   |---|---|
   | `_has_invalid_crop_phase` | Fase fenológica de otro cultivo (e.g., "panojamiento" en mandarina_murcott) |
   | `_has_suspect_heat_mapping` | `riesgo_calor/below_optimum` — la dirección es incompatible con el nombre del criterio |
   | `_has_suspect_mandarina_cold_mapping` | `riesgo_frio/above_optimum` en inducción floral de mandarina — posible insuficiencia de frío inductivo |
   | `_has_suspect_hydric_as_altitude` | `deficit_hidrico` con valores en rango 800–4500 msnm — probable confusión con altitud |
   | `_has_suspect_hydric_mapping` | `deficit_hidrico/above_optimum` con observed > optimal — dirección incompatible |

   Los ítems sospechosos se anulan (recommendation=None, evidence=[], confidence=baja) y se mueven a `pending_methodological_validation`.

4. **Validación de compatibilidad de evidencia**:

   Para ítems no sospechosos, se verifica que cada referencia de `evidence_used` del LLM apunte a un fragmento real recuperado por File Search y que ese fragmento sea semánticamente compatible con el criterio/grupo del ítem.

   La compatibilidad se determina por grupo:
   - `clima`: acepta fragmentos que mencionen temperatura, precipitación, climatología; rechaza plaguicidas/LMR
   - `suelo`: acepta fragmentos de textura, arcilla, pH, MO; rechaza `clima_fenologia.md`
   - `riego`: acepta fragmentos de agua, humedad, requerimiento hídrico, floración/cuajado (por déficit inductivo)
   - `topografia`: acepta pendiente, erosión, escorrentía; rechaza cualquier otro
   - Para otros grupos: matching semántico por tokens ≥5 caracteres de criterion_name/label/phase/recommendation

   Si no hay evidencia compatible: `evidence_status = "insuficiente"`, recommendation=None.

   Si hay evidencia pero es solo indirecta para suelo físico: `evidence_status = "compatible_indirecta"`, confidence→baja.

5. **Downgrade de confianza**: si `confidence = "alta"` pero menos de 2 referencias compatibles → baja a `"media"`.

### 4.2 A nivel del structured_output completo

- Se separan los ítems en `gap_recommendations` (accionables) y `pending_methodological_validation` (sospechosos, deduplicados por criterion_name)
- Se ordenan los ítems accionables por prioridad: (1) no sospechoso, (2) severidad desc, (3) evidencia desc
- Se calculan `visible_gap_keys`: los primeros 5 accionables (máximo visible en texto final)
- Si hay sospechosos, el summary es generado determinísticamente (`_generate_qc_summary`), no del LLM
- Se agrega metadato `schema_version`, `quality_control`, `llm_raw_output` para trazabilidad

---

## Paso 5 — Renderizado de texto visible (`_render_visible_text`)

El structured_output limpio se convierte en markdown legible para el usuario. La función `_render_visible_text()` produce:

```markdown
# Recomendacion tecnica agricola

## Resumen
<summary del QC o del LLM>

## Recomendaciones priorizadas

1. Condicion fisica y organica del suelo (confianza: media)
   Brechas detectadas: Contenido de arcilla, pH del suelo.
   <recomendación integrada de suelo>
   Evidencia: suelo.md.

2. Aptitud térmica - Vegetativo (confianza: alta)
   <recomendación individual>
   Evidencia: clima_fenologia.md.

3. Criterios pendientes de validacion metodologica (confianza: baja)
   Criterios: Déficit hídrico.
   <nota de validación>

## Limites
<overall_limitations>
```

**Agrupación de brechas de suelo**: todos los ítems de grupo `suelo` se renderizan como un solo bloque integrado ("Condición física y orgánica del suelo") con una recomendación consolidada, en vez de ítems separados por criterio. Esto evita fragmentación en la narrativa al usuario.

**Ítems individuales**: cada ítem no-suelo genera su propio bloque numerado con título (criterion_label), texto de recomendación (máx. 120 palabras), evidencia y limitaciones.

**Sospechosos de mapeo**: se agrupan en un bloque al final indicando que requieren validación metodológica antes de generar recomendaciones.

**Fallback**: si no hay ítems accionables ni sospechosos y el structured_output fue generado por el fallback (`generated_by = "via_fallback"`), se retorna el texto legacy del LLM sin transformar.

---

## Paso 6 — Agregado de dominio `Recommendation`

Con el texto final y el structured_output limpio se construye el agregado:

```python
Recommendation(
    id=uuid4(),
    evaluation_id=command.evaluation_id,
    crop_id=crop_result.crop_id,
    text=text,                        # markdown visible
    sections=[                        # secciones estructuradas
        SUMMARY, VIABILITY_RESULT,
        AGRONOMIC_GAPS, LIMITING_FACTORS,
        DOCUMENTARY_EVIDENCE
    ],
    evidence=[DocumentaryEvidence(...)],  # fragmentos citados
    structured_output=structured_output,  # dict completo con QC
    status=RecommendationStatus.GENERATED,
)
```

Las secciones (tipo `RecommendationSection`) son registros estructurados con `section_type` (enum `RecommendationSectionType`) para facilitar consumo por APIs o UI.

---

## Paso 7 — Persistencia y eventos de dominio

### Persistencia

Si `command.persist = True` y hay repositorio configurado, se llama a `IRecommendationRepository.save(recommendation)` dentro de la misma transacción del `RecommendationMessageCommandService`.

### Eventos de outbox

Después de persistir, el `OutboxWriter` escribe un evento en la tabla de outbox (Transactional Outbox Pattern):

**Éxito** → `RecomendacionGenerada`:
```json
{
  "recommendation_id": "...",
  "evaluation_id": "...",
  "crop_id": "...",
  "fragment_ids": ["..."],
  "text": "..."
}
```

**Fallo** (`RecommendationDomainError`) → `RecomendacionFallida`:
```json
{
  "evaluation_id": "...",
  "failure_cause": "..."
}
```

Finalmente se marca el mensaje original como procesado (`mark_as_processed`) para garantizar idempotencia ante reentregas.

---

## Diagrama de datos completo

```
GapData (por criterio × fase)
    │
    ├── criterion_id, criterion_name, criterion_group
    ├── observed_value, optimal_limit, gap_value
    ├── gap_direction ("below_optimum" | "above_optimum")
    └── severity ("baja" | "media" | "alta")
            │
            ▼
    _build_groups()  ──────────────────────────────────────────┐
            │                                                   │
    GapGroup (por criterio)                         _detect_data_quality_flags()
    ├── gap_class (STRUCTURAL | MITIGABLE |          ├── valor imposible (0.0 en pH/MO)
    │             CORRECTABLE | DATA_QUALITY)        ├── altitud disfrazada de déficit hídrico
    ├── correctability                               ├── valor único en variable temporal
    ├── priority_score = f(severity, recurrence,    └── inconsistencia de signo en gap_value
    │                      class_multiplier)
    ├── ruling_structural_barriers (severidad alta)
    └── occurrences[GapOccurrence]
            │
            ▼
    GapAnalysisResult
    ├── viability_interpretation (instrucción para el LLM)
    ├── gap_groups (ordenados por priority_score DESC)
    ├── structural_count, correctable_count, mitigable_count, data_quality_count
    └── ruling_structural_barriers
            │
            ▼
    OpenAI Responses API (File Search)
    ├── system_prompt (rol + prohibiciones + formato JSON)
    ├── user_prompt (MCDA read-only + gap_analysis + LF + queries + routing)
    └── vector_store_id (por cultivo)
            │
            ▼
    structured_output (dict, schema_version=recommendation_structured_v1)
    └── gap_recommendations[]:
        ├── gap_key, criterion_id, criterion_name, criterion_group
        ├── phase_id, phase_name, gap_direction, severity
        ├── observed_value, optimal_limit, gap_value
        ├── recommendation, rationale
        ├── evidence_used[]: {source_file_id, source_filename, source_locator, quote_summary}
        ├── confidence ("baja" | "media" | "alta")
        └── limitations
            │
            ▼ Quality Control (determinístico)
            │
    ├── reescrituras de seguridad (arcilla, térmica, perenne/anual, arena, estrés hídrico)
    ├── detección de sospechosos (mapeo erróneo de criterios)
    ├── validación de compatibilidad de evidencia
    ├── downgrade de confianza sin respaldo suficiente
    └── separación: gap_recommendations (accionables) vs pending_methodological_validation
            │
            ▼
    _render_visible_text()
    ├── Bloque suelo agrupado (todos los ítems de suelo → 1 recomendación integrada)
    ├── Ítems individuales (otros criterios, máx. 5 visibles)
    └── Bloque de sospechosos (pendientes de validación metodológica)
            │
            ▼
    Recommendation (aggregate)
    ├── text (markdown visible)
    ├── sections (SUMMARY, VIABILITY_RESULT, AGRONOMIC_GAPS, LIMITING_FACTORS, DOCUMENTARY_EVIDENCE)
    ├── evidence[DocumentaryEvidence] (fragmentos citados)
    └── structured_output (dict completo con QC y metadatos de trazabilidad)
```

---

## Invariantes y restricciones clave

1. **El LLM nunca recalcula resultados MCDA.** Scores, rankings, membresías y categorías de viabilidad viajan como read-only al prompt.

2. **Todo cálculo de prioridad, clasificación y severidad es determinístico.** El análisis de brechas en `gap_analysis.py` no involucra modelos de lenguaje ni embeddings.

3. **El QC post-LLM puede anular recomendaciones completas.** Si la evidencia no es compatible o el criterio tiene sospecha de mapeo erróneo, `recommendation = None` y el ítem se mueve a validación pendiente.

4. **Los sospechosos de mapeo no se mezclan con recomendaciones de manejo.** Se exponen en `pending_methodological_validation` para que el equipo VIA corrija el rulebook antes de incluirlos en recomendaciones de campo.

5. **La trazabilidad es total.** `FileSearchTrace` almacena el response_id, los fragmentos recuperados con sus scores y filenames, y el validation_status de la salida del modelo.

6. **Idempotencia garantizada.** El `RecommendationMessageCommandService` usa `processed_message_store` para no procesar el mismo mensaje dos veces, aunque llegue duplicado por el broker.
