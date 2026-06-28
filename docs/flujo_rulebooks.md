# Flujo de Rulebooks en VIA

> Bounded Context: `rulebook_management`  
> Archivos principales: `domain/rulebook.py`, `domain/phase_requirement.py`, `domain/value_objects.py`, `application/command_service.py`, `application/query_service.py`, `infrastructure/rulebook_repository.py`

---

## Visión general

Un **rulebook** es el documento agronómico versionado que define *qué medir*, *cómo medir* y *cuánto vale* cada condición ambiental para evaluar la viabilidad de un cultivo en una parcela. Contiene los criterios ecofisiológicos ponderados, las fases fenológicas del ciclo productivo, las funciones de membresía fuzzy que traducen valores físicos a grados de aptitud, y los enlaces a los datasets de extracción GEE.

Sin un rulebook activo para un cultivo, el sistema no puede ni extraer variables ni evaluar viabilidad — es la pieza central que une extracción, evaluación y recomendación.

```
Agronómo/Admin
      │  POST /rulebooks   (crear DRAFT)
      │  POST /rulebooks/{id}/publish  (activar)
      ▼
┌──────────────────────────────┐
│  RulebookCommandService      │
│  · validate() aggregate      │
│  · deactivate anterior       │
│  · publish() nuevo           │
└──────────────────────────────┘
        │ ACTIVE rulebook en BD
        │
        ├──► Process Manager → RequiredExtractionSpec → agroenv_extraction
        │         (qué variables extraer × fase × cultivo)
        │
        └──► Viability Engine → EvaluationCriterionSpec → MCDA
                  (funciones membresía + pesos AHP + políticas críticas)
```

---

## Modelo de dominio

### Aggregate root: `Rulebook`

```python
@dataclass
class Rulebook:
    id: UUID
    crop_id: str               # e.g. "maiz_amarillo_duro"
    version: int               # incremental por cultivo (1, 2, 3...)
    status: RulebookStatus     # DRAFT | ACTIVE | INACTIVE
    criteria: list[Criterion]
    phases: list[PhenologicalPhase]
    phase_requirements: list[PhaseRequirement]
```

Un único cultivo puede tener múltiples versiones, pero solo **una puede estar ACTIVE** en un momento dado. Esto se garantiza en la publicación de forma atómica.

### `Criterion` — Criterio ecofisiológico

```python
@dataclass(frozen=True)
class Criterion:
    id: UUID
    name: str                        # e.g. "aptitud_termica"
    is_critical: bool
    critical_policy: CriticalPolicy | None   # NO_VIABLE | PENALIZE
    penalty_factor: float | None             # [0,1] si policy=PENALIZE
    ahp_weight: float                        # peso AHP global [0,1]
    doc_source: str | None                   # fuente documental
    technical_notes: str | None
```

Los criterios definen *qué variable* se evalúa y *cuánto peso* tiene en el score global. **La función de membresía no vive en el criterio** — vive en `PhaseRequirement`, porque el mismo criterio puede tener rangos óptimos distintos en cada fase fenológica.

### `PhenologicalPhase` — Fase fenológica

```python
@dataclass(frozen=True)
class PhenologicalPhase:
    id: UUID
    name: str             # e.g. "espigamiento_floracion"
    duration_days: int    # duración en días (>0)
    sequence_order: int   # orden en el ciclo (>0)
```

Las fases modelan el ciclo productivo del cultivo. Los pesos de fase reflejan la sensibilidad relativa de cada etapa a las condiciones ambientales: la fase de floración, por ejemplo, concentra el mayor peso en todos los cultivos de producción.

### `PhaseRequirement` — Requisito por criterio × fase

Esta es la entidad central que conecta todo:

```python
@dataclass(frozen=True)
class PhaseRequirement:
    id: UUID
    criterion_id: UUID
    phase_id: UUID
    membership_fn: MembershipFunction   # función trapecial (a, b, c, d)
    phase_weight: float                 # peso de esta fase para el criterio [0,1]
    temporal_periods: list[TemporalPeriod]   # periodos con sus pesos
    extraction_binding: ExtractionBinding    # enlace al dataset GEE
```

Por cada combinación `(criterio × fase)` hay exactamente un `PhaseRequirement`. Un rulebook con 12 criterios y 7 fases tiene hasta 84 `PhaseRequirement`.

### `MembershipFunction` — Función de membresía trapezoidal

```python
@dataclass(frozen=True)
class MembershipFunction:
    a: float   # límite inferior (membresía empieza a crecer)
    b: float   # inicio de meseta (membresía = 1.0)
    c: float   # fin de meseta
    d: float   # límite superior (membresía cae a 0)
    function_type: str = "TRAPEZOIDAL"
```

Traduce un valor físico observado a un grado de aptitud en `[0, 1]`:

```
μ(x) = 0                    si x < a o x > d
μ(x) = (x - a) / (b - a)   si a ≤ x < b   (rampa ascendente)
μ(x) = 1.0                  si b ≤ x ≤ c   (meseta óptima)
μ(x) = (d - x) / (d - c)   si c < x ≤ d   (rampa descendente)
```

**Invariante**: `a ≤ b ≤ c ≤ d` siempre. Si `b = c`, la función degenera a triangular. Si `a = b`, la rampa ascendente desaparece (óptimo desde el inicio).

**Trapecios invertidos** (caso especial producción): Para `riesgo_frio` durante `induccion_floral` en mandarina Murcott y `reposo_vegetativo` en uva Sweet Globe, el valor óptimo es *bajo* (temperaturas frías nocturnas son deseables). En lugar de invertir el signo, el trapecio simplemente usa un rango numérico bajo como meseta óptima — la función fuzzy estándar captura esto naturalmente sin código especial.

### `TemporalPeriod` — Periodo temporal con peso

```python
@dataclass(frozen=True)
class TemporalPeriod:
    period_key: str        # e.g. "espigamiento_floracion_2024"
    temporal_weight: float # peso relativo del periodo [0,1]
    start_day: int | None
    end_day: int | None
```

Permite ponderar distintos sub-periodos dentro de una fase. Los `period_key` luego mapean con las entradas del `AgroenvVector` para saber qué valor GEE usar en cada periodo.

### `ExtractionBinding` — Enlace al dataset GEE

```python
@dataclass(frozen=True)
class ExtractionBinding:
    variable_name: str       # e.g. "temperatura_media_c"
    dataset_key: str         # e.g. "ECMWF/ERA5_LAND/MONTHLY_AGGR"
    band: str                # e.g. "temperature_2m"
    unit: str                # e.g. "celsius"
    temporal_resolution: str # "monthly" | "daily" | "static" | "derived"
    scale: float | None      # metros (11132 ERA5, 30 SRTM, 250 OLM)
    reducer: str | None      # "mean" | "median"
    aggregation_method: str | None  # "mean" | "sum"
    quality_mask: dict | None
    fallback_allowed: bool   # si True, valor None es aceptable
```

El `ExtractionBinding` es el contrato técnico que le dice al sistema de extracción exactamente qué consultar en GEE para satisfacer este requisito de criterio-fase.

---

## Ciclo de vida del rulebook

```
                  create_rulebook()
                       │
                       ▼
                    DRAFT  ──── validate() en construcción
                       │
              publish_rulebook()
                       │
                 (atomico: deactivate anterior)
                       │
                       ▼
                    ACTIVE  ──── único por crop_id
                       │
              nueva versión publicada
                       │
                       ▼
                  INACTIVE  ──── historial preservado
```

Solo el estado `ACTIVE` es visible para el process manager y el motor de evaluación. Los estados `DRAFT` e `INACTIVE` no participan en ningún flujo de evaluación.

---

## Reglas de validación (`Rulebook.validate()`)

La validación se ejecuta en `create_rulebook()` antes de persistir. Es exhaustiva e interdependiente:

### 1. Estructura mínima
- Al menos 1 criterio, 1 fase y 1 `PhaseRequirement`

### 2. Suma de pesos AHP = 1.0 ± tolerance

```
Σ(criterion.ahp_weight) ≈ 1.0
```

### 3. Suma de pesos de fase por criterio = 1.0

Para cada criterio, la suma de `phase_weight` de todos sus `PhaseRequirement` debe ser ≈ 1.0:

```
∀ criterion_id: Σ(requirement.phase_weight) ≈ 1.0
```

### 4. Suma de pesos temporales por PhaseRequirement = 1.0

```
∀ requirement: Σ(period.temporal_weight) ≈ 1.0
```

### 5. Referencias cruzadas
- Todo `requirement.criterion_id` debe existir entre los criterios del rulebook
- Todo `requirement.phase_id` debe existir entre las fases del rulebook
- Todo criterio debe tener al menos un `PhaseRequirement`

### 6. Función de membresía
- `a ≤ b ≤ c ≤ d` (invariante del trapecio)
- Solo `function_type = "TRAPEZOIDAL"` aceptado

### 7. Criterios críticos
- Si `is_critical = True` → `critical_policy` requerido
- Si `critical_policy = PENALIZE` → `penalty_factor ∈ [0, 1]` requerido
- Si `critical_policy = NO_VIABLE` → `penalty_factor` no se usa

La tolerancia de validación de pesos es `0.001` por defecto (configurable en el servicio).

---

## Flujo de creación (command service)

### `create_rulebook()`

```
Admin POST /rulebooks
        │
        ▼
RulebookCommandService.create_rulebook(
    crop_id, criteria, phases, phase_requirements
)
        │
        ├─ repository.next_version_for_crop(crop_id)
        │    └─ SELECT MAX(version) WHERE crop_id → +1
        │
        ├─ Rulebook(id=uuid4(), crop_id, version, DRAFT, ...)
        │
        ├─ rulebook.validate(weight_tolerance=0.001)
        │    ├─ coherencia estructural
        │    ├─ pesos AHP
        │    ├─ pesos fase × criterio
        │    └─ pesos temporales
        │
        ├─ repository.add(rulebook)
        │    ├─ INSERT RulebookModel + FLUSH (FK parent)
        │    ├─ INSERT CriterionModel × N + FLUSH (FK children)
        │    ├─ INSERT RulebookPhaseModel × M + FLUSH
        │    └─ INSERT PhaseRequirementModel × (N×M)
        │         └─ membership_fn, temporal_periods, extraction_binding → JSONB
        │
        └─ retorna Rulebook DRAFT
```

El repositorio realiza **tres flushes** en orden estricto para satisfacer las restricciones de FK:
1. `RulebookModel` (padre)
2. `CriterionModel` + `RulebookPhaseModel` (hijos directos)
3. `PhaseRequirementModel` (referencia a criterios y fases)

### `publish_rulebook()`

```
Admin POST /rulebooks/{id}/publish
        │
        ▼
RulebookCommandService.publish_rulebook(rulebook_id)
        │
        ├─ repository.get_by_id(rulebook_id)
        │
        ├─ repository.deactivate_active_for_crop(crop_id)
        │    └─ UPDATE status='INACTIVE' WHERE crop_id AND status='ACTIVE'
        │
        ├─ rulebook.publish()
        │    └─ status = ACTIVE
        │
        ├─ repository.save(rulebook)
        │    └─ UPDATE RulebookModel SET status='ACTIVE'
        │
        └─ (todo en la misma transacción — nunca dos ACTIVE simultáneos)
```

La desactivación y activación son atómicas — si falla cualquier parte, toda la transacción hace rollback y el rulebook anterior sigue activo.

---

## Flujo de consulta (query service)

### `get_active_rulebook(crop_id)`

Lee el rulebook activo completo: criterios, fases y phase_requirements reconstruidos desde ORM. Lo consume el motor de evaluación a través del `RulebookAclAdapter`.

### `get_required_extraction_spec(crop_candidates, temporal_window)`

Este es el método que conecta rulebooks con extracción. Para cada cultivo candidato:

1. Carga el rulebook activo
2. Itera todos los `PhaseRequirement`
3. Por cada uno genera un `RequiredVariableForEvaluation`:

```python
RequiredVariableForEvaluation(
    variable_name=binding.variable_name,   # "temperatura_media_c"
    criterion_id=str(criterion.id),
    crop_id=rulebook.crop_id,
    phase_id=str(requirement.phase_id),
    dataset_key=binding.dataset_key,       # "ECMWF/ERA5_LAND/MONTHLY_AGGR"
    band=binding.band,
    unit=binding.unit,
    temporal_resolution=binding.temporal_resolution,
    scale=binding.scale,
    reducer=binding.reducer,
    aggregation_method=binding.aggregation_method,
    temporal_window=temporal_window,
    temporal_periods=requirement.temporal_period_payload(),
    quality_mask=binding.quality_mask,
    fallback_allowed=binding.fallback_allowed,
)
```

El resultado es un `RequiredExtractionSpec` que el process manager incluye en el payload del comando `IniciarExtraccionAgroambiental`. La clave: **el rulebook no interpreta los datos, solo proyecta lo que hay que extraer**.

---

## API HTTP

`GET /rulebooks` — lista todas las versiones de todos los cultivos  
`POST /rulebooks` — crea una versión DRAFT  
`POST /rulebooks/{rulebook_id}/publish` — activa la versión DRAFT  
`GET /rulebooks/{crop_id}/active` — retorna el rulebook activo con detalle completo

Los roles permitidos son:
- **Lectura**: `ADMINISTRADOR`, `ESPECIALISTA_TECNICO`
- **Escritura/Publicación**: solo `ADMINISTRADOR`

---

## Persistencia (ORM)

Cuatro tablas en el schema `transactional`:

| Tabla | PK | Relaciones |
|---|---|---|
| `rulebooks` | `id` (UUID) | — |
| `rulebook_criteria` | `id` (UUID) | FK → `rulebooks.id` |
| `rulebook_phases` | `id` (UUID) | FK → `rulebooks.id` |
| `rulebook_phase_requirements` | `id` (UUID) | FK → `rulebook_criteria.id`, `rulebook_phases.id` |

Restricción única: `(crop_id, version)` en `rulebooks`. Restricción única: `(criterion_id, phase_id)` en `rulebook_phase_requirements`.

Los campos `membership_fn`, `temporal_periods` y `extraction_binding` se almacenan como **JSONB** en `rulebook_phase_requirements`, lo que permite evolucionar su estructura sin migraciones de columnas. Los pesos (`ahp_weight`, `phase_weight`, `penalty_factor`) se persisten como `Numeric(6,5)` y `Numeric(4,3)` para evitar pérdida de precisión float → Decimal → float en la conversión.

---

## Integración con `viability_evaluation` (ACL)

El motor MCDA no conoce los modelos ORM de `rulebook_management`. Consume el rulebook a través del `RulebookAclAdapter`, que transforma el aggregate de dominio en DTOs planos de evaluación:

```python
RulebookAclAdapter.get_active_rulebook(crop_id) → RulebookEvaluationData(
    crop_id=...,
    rulebook_id=...,
    version=...,
    criteria=[
        EvaluationCriterionSpec(
            criterion_id=str(criterion.id),
            crop_id=...,
            phase_id=str(requirement.phase_id),
            variable_name=binding.variable_name,
            w_ahp=criterion.ahp_weight,
            phase_weight=requirement.phase_weight,
            temporal_periods=[...],
            membership_fn={"type": "TRAPEZOIDAL", "a": ..., "b": ..., "c": ..., "d": ...},
            critical_policy=criterion.critical_policy,
            penalty_factor=criterion.penalty_factor,
            doc_source=criterion.doc_source,
        )
        for requirement in rulebook.phase_requirements
        for criterion in [find_criterion(requirement.criterion_id)]
    ]
)
```

El motor MCDA usa estos DTOs para:
1. Recuperar el valor observado de la parcela del `AgroenvVector` por `(variable_name, phase_id, period_key)`
2. Aplicar `MembershipFunction` → grado de membresía μ ∈ [0, 1]
3. Ponderar por `phase_weight` × `temporal_weight`
4. Ponderar por `w_ahp`
5. Aplicar política crítica si μ < umbral

---

## Rulebooks de producción: cultivos reales

Los rulebooks de producción (`seed_prod_rulebooks.py`) implementan 5 cultivos con umbrales derivados de bibliografía oficial peruana (SENASA, MIDAGRI, SENAMHI, INIA). Todos comparten la misma estructura de **12 criterios**:

### Criterios comunes (12) y sus bindings GEE

| Criterio | Variable GEE | Dataset | Peso típico |
|---|---|---|---|
| `aptitud_termica` | `temperatura_media_c` | ERA5-Land MONTHLY | 0.13–0.16 |
| `riesgo_frio` | `temperatura_minima_c` | ERA5-Land MONTHLY | 0.06–0.11 |
| `riesgo_calor` | `temperatura_maxima_c` | ERA5-Land MONTHLY | 0.08–0.12 |
| `disponibilidad_hidrica` | `precipitacion_acumulada_mm` | CHIRPS DAILY | 0.09–0.13 |
| `deficit_hidrico` | `deficit_hidrico_mm` | ERA5 derivado | 0.10–0.11 |
| `aptitud_altitudinal` | `elevacion_m` | SRTM 30m | 0.07–0.13 |
| `aptitud_topografica` | `pendiente_grados` | SRTM 30m | 0.06–0.10 |
| `reaccion_suelo_ph` | `ph_suelo` | OpenLandMap SOL_PH | 0.06–0.09 |
| `contenido_arcilla` | `arcilla_pct` | OpenLandMap SOL_CLAY | 0.07–0.09 |
| `contenido_arena` | `arena_pct` | OpenLandMap SOL_SAND | 0.05–0.07 |
| `carbono_organico_suelo` | `carbono_organico_suelo` | OpenLandMap SOL_OC | 0.03–0.06 |
| `cobertura_actual_auxiliar` | `ndvi` | Sentinel-2 SR | 0.02 |

`cobertura_actual_auxiliar` (NDVI) es intencionalmente un auxiliar de contexto con el peso mínimo (0.02). No puede determinar viabilidad por sí solo — solo aporta información sobre el estado actual de cobertura.

---

### Maíz Amarillo Duro (`maiz_amarillo_duro`)

**Fuentes**: SENASA BPA 2020, MIDAGRI FT-09, SENAMHI Costa Central, INIA-605/609/619

**Fases** (7, ciclo de 140 días — valles costeros Lima):

| Fase | Duración | Peso | Escala Fenológica |
|---|---|---|---|
| `germinacion_emergencia` | 15 d | 0.08 | VE |
| `desarrollo_vegetativo` | 45 d | 0.22 | V1-Vn |
| `panojamiento` | 12 d | 0.15 | VT |
| `espigamiento_floracion` | 12 d | **0.28** | R1 ← crítica |
| `llenado_grano_lechoso` | 20 d | 0.15 | R3 |
| `llenado_grano_pastoso` | 15 d | 0.08 | R4 |
| `madurez_cosecha` | 21 d | 0.04 | R6 |

**Trapecios destacados**:

| Criterio | Fase crítica | Trapecio (a, b, c, d) | Nota |
|---|---|---|---|
| `aptitud_termica` | `espigamiento_floracion` | (14, 18, 28, 34) °C | "Al menos 18°C" SENASA |
| `riesgo_frio` | `espigamiento_floracion` | (12, 16, 22, 26) °C | 18°C mínimo real |
| `riesgo_calor` | `espigamiento_floracion` | (16, 22, 28, 34) °C | Polén sensible |
| `aptitud_altitudinal` | todas | (0, 0, 600, 900) m | Valles costeros 0-600m |
| `reaccion_suelo_ph` | todas | (4.5, 5.5, 7.2, 8.0) | Conflicto SENASA/MIDAGRI → unión |

**Política crítica**: `aptitud_altitudinal` → `PENALIZE 0.65` (fuera de 0-600 msnm, cultivo costero, MIDAGRI)

---

### Mandarina Murcott (`mandarina_murcott`)

**Fuentes**: SENASA BPA 2020, MIDAGRI/AgroRural, estudio W. Murcott Irrigación Santa Rosa, Sayán, Lima

**Fases** (8, ciclo productivo anual de 315 días — frutal perenne):

| Fase | Duración | Peso | Particularidad |
|---|---|---|---|
| `instalacion_establecimiento` | 30 d | 0.05 | |
| `brotacion_desarrollo_vegetativo` | 45 d | 0.12 | |
| `induccion_floral` | 30 d | **0.20** | Necesita noches frías |
| `floracion` | 25 d | **0.22** | ← fase más crítica |
| `cuajado_fruto` | 30 d | 0.18 | Estrés = reducción cuajado |
| `crecimiento_llenado_fruto` | 90 d | 0.13 | |
| `maduracion_cosecha` | 45 d | 0.08 | |
| `postcosecha` | 20 d | 0.02 | |

**Novedad clave — trapecio invertido en `riesgo_frio` × `induccion_floral`**:

Las noches frías (8–15°C) son **deseables** para inducir la floración en cítricos. El trapecio tiene su meseta óptima en el rango bajo:

```
riesgo_frio / induccion_floral: (4, 8, 15, 22) °C
```

Esto contrasta con todas las demás fases donde el trapecio de `riesgo_frio` tiene la meseta en valores más altos (protegiendo de heladas). El motor MCDA trata este criterio igual que cualquier otro — la diferencia agronómica está capturada en los parámetros del trapecio.

**Novedad en `deficit_hidrico`** — doble rol del déficit:

| Fase | Trapecio déficit | Razonamiento |
|---|---|---|
| `induccion_floral` | **(50, 100, 400, 700) mm** | Déficit moderado **activa** inducción (Sayán: 17 días de estrés) |
| `floracion` | (0, 0, 200, 600) mm | Mínimo déficit; irrigar fuerte |
| `cuajado_fruto` | (0, 0, 200, 600) mm | Igual; crítico para cuajado |

**Política crítica**: `aptitud_altitudinal` → `PENALIZE 0.65` (>1200 msnm; valles costeros Lima 0-800 msnm)

---

### Maracuya Criolla Amarilla (`maracuya_criolla_amarilla`)

**Fuentes**: Gerencia Regional Agraria La Libertad, INIA/MIDAGRI Folleto 2010

**Fases** (10, ciclo productivo ~350 días):

| Fase | Duración | Peso | Particularidad |
|---|---|---|---|
| `vivero_propagacion` | 60 d | 0.05 | |
| `trasplante_establecimiento` | 30 d | 0.06 | |
| `crecimiento_conduccion` | 60 d | 0.10 | |
| `formacion_poda` | 30 d | 0.08 | |
| `floracion` | 30 d | **0.22** | 24-28°C; flores 13-18h |
| `polinizacion_fecundacion` | 20 d | **0.20** | Xylocopa, no riego aspersión |
| `crecimiento_fruto` | 55 d | 0.15 | 50-60 días post-antesis |
| `maduracion_cosecha` | 20 d | 0.08 | |
| `postcosecha_comercializacion` | 15 d | 0.03 | |
| `renovacion_mantenimiento` | 30 d | 0.03 | |

**Novedades**:

- **Temperatura más estrecha** que otros cultivos: óptimo 24-28°C, trapecio `(18, 22, 26, 30)` en floración. >28°C restringe flores y reduce botones (fuente La Libertad).
- **pH explícito**: 5.5-7.0 por fuente documentada (Gerencia La Libertad), trapecio `(4.5, 5.5, 7.0, 7.8)` — más ajustado que maíz/mandarina donde la fuente es menos específica.
- **Fusariosis por arcilla pesada**: `contenido_arcilla` tiene `PENALIZE 0.70` (política más severa que otros cultivos). Suelos con >45% arcilla → fusariosis y podredumbre radical.
- **Noches cálidas para Xylocopa**: `riesgo_frio` × `polinizacion_fecundacion` tiene el rango más alto del sistema para esta fase — el polinizador nativo requiere temperaturas nocturnas altas para estar activo.

**Políticas críticas**:
- `aptitud_altitudinal` → `PENALIZE 0.65` (flavicarpa 0-1000 msnm; tolera hasta 1300 msnm)
- `contenido_arcilla` → `PENALIZE 0.70` (fusariosis — la penalización más alta del sistema)

---

### Palta Hass (`palta_hass`)

**Fuentes**: SENAMHI Ficha Agroclimática Palto Hass (2021), INIA Folleto Cultivo de Palto, MIDAGRI/AgroRural Manual BPA Palto

**Fases** (9, ciclo productivo anual de 375 días):

| Fase | Duración | Peso | Particularidad |
|---|---|---|---|
| `instalacion_establecimiento` | 60 d | 0.06 | |
| `brotacion_foliacion` | 45 d | 0.08 | |
| `induccion_floral` | 30 d | 0.17 | T baja + déficit leve activan inducción |
| `floracion` | 25 d | **0.24** | ← fase más crítica; 20-25°C, 10°C noche |
| `cuajado_fruto` | 30 d | **0.20** | Solo 0.1% flores → fruto; sin estrés |
| `crecimiento_desarrollo_fruto` | 90 d | 0.14 | |
| `maduracion_cosecha` | 45 d | 0.06 | |
| `postcosecha` | 20 d | 0.02 | |
| `renovacion_mantenimiento` | 30 d | 0.03 | |

**Novedades**:

- **Altitud sin política crítica**: SENAMHI reconoce aptitud 0-2700 msnm. Es el único cultivo sin penalización por altitud — la altitud se trata como criterio contextual. Trapecio amplio `(0, 0, 2000, 2700)`.
- **pH con conflicto documental**: tres fuentes dan rangos distintos (SENAMHI 6.5-7.5 / MIDAGRI 6.5-7.0 / INIA 5.5-6.8). El rulebook usa la **unión conservadora** `(5.0, 5.5, 7.5, 8.0)` y lo documenta en `technical_notes` — VIA no inventa conciliaciones no documentadas.
- **Temperatura de floración muy estrecha**: 20-25°C (SENAMHI fecundación), trapecio `(16, 20, 25, 30)`. >35°C daña floración/fructificación.
- **Déficit hídrico en floración/cuajado crítico**: umbral `(0, 0, 150, 500)` mm — el más bajo del sistema. El aguacate tiene el cuajado más sensible al estrés: solo 0.1% de flores llegan a fruto.
- **Inducción floral con temperatura baja y déficit leve** (similar a mandarina pero más suave; no inversión total de trapecios): `deficit_hidrico` × `induccion_floral` → `(30, 80, 350, 700)`.

**Política crítica**: `contenido_arcilla` → `PENALIZE 0.65` (arcilla pesada → mal drenaje → asfixia radical → *Phytophthora cinnamomi*)

---

### Uva de Mesa Sweet Globe (`uva_de_mesa_sweet_globe`)

**Fuentes**: SENAMHI Ficha Agroclimática Vid (2024), MIDAGRI, UNALM/ALICIA Pacanga-Chepén La Libertad, SENASA BPA Uva, Bloom Fresh/IFG TEN (override varietal)

**Fases** (13 — el cultivo con más fases del sistema, ciclo ~400 días):

| Fase | Duración | Peso | Particularidad |
|---|---|---|---|
| `instalacion_establecimiento` | 90 d | 0.04 | |
| `reposo_vegetativo` | 45 d | 0.04 | T baja DESEADA para dormancia |
| `poda_produccion` | 20 d | 0.06 | Define carga de yemas |
| `hinchazon_yemas` | 15 d | 0.04 | 8-12°C inicia brotación (SENAMHI) |
| `brotacion_desarrollo_brotes` | 30 d | 0.09 | |
| `aparicion_inflorescencias` | 20 d | 0.07 | |
| `floracion` | 15 d | **0.20** | ← crítica: 18-24°C muy estrecho |
| `cuajado_fruto` | 20 d | **0.16** | Déficit = aborto de bayas |
| `crecimiento_baya` | 60 d | 0.14 | Calibre 18-24mm Sweet Globe |
| `maduracion` | 30 d | 0.10 | 20°C día / 15°C noche, >16°Brix |
| `cosecha` | 15 d | 0.03 | |
| `postcosecha_exportacion` | 10 d | 0.02 | Hasta 90 días cadena frío |
| `renovacion_mantenimiento` | 30 d | 0.01 | |

**Novedades**:

- **`reposo_vegetativo` con temperatura baja deseada**: como la inducción floral en mandarina, pero por dormancia de vid. Trapecio `aptitud_termica`: `(4, 8, 16, 20)` °C. Trapecio `riesgo_frio`: rango bajo preferido.
- **`hinchazon_yemas`**: documentado por SENAMHI como etapa donde 8-12°C es el umbral de inicio de brotación. Trapecio ajustado.
- **Floración más estrecha del sistema**: 18-24°C óptimo, trapecio `(14, 18, 24, 30)`. <15.5°C o >30°C reducen drásticamente la floración (SENAMHI).
- **Mayor contenido de arena**: "arenoso / franco arenoso" (SENAMHI). El trapecio de arena `(25, 40, 70, 85)` refleja preferencia mayor que otros cultivos.
- **pH más amplio**: 5.5-8.5 (SENAMHI; rango más amplio del sistema). Se usa casi completo: `(5.0, 5.5, 8.0, 8.5)`.
- **Fuente local Sweet Globe de La Libertad** (Pacanga-Chepén), no de Lima costa. El `doc_source` incluye la advertencia explícita.

**Política crítica**: `contenido_arcilla` → `PENALIZE 0.65` (arcilla → mal drenaje → enfermedades fúngicas)

---

## Tabla resumen de políticas críticas

| Cultivo | Criterio crítico | Política | Factor | Fundamento |
|---|---|---|---|---|
| `maiz_amarillo_duro` | `aptitud_altitudinal` | PENALIZE | 0.65 | Valles costeros 0-600m (MIDAGRI) |
| `mandarina_murcott` | `aptitud_altitudinal` | PENALIZE | 0.65 | Costero 0-800 msnm (Sayán ~300m) |
| `maracuya_criolla_amarilla` | `aptitud_altitudinal` | PENALIZE | 0.65 | flavicarpa 0-1000 msnm |
| `maracuya_criolla_amarilla` | `contenido_arcilla` | PENALIZE | **0.70** | Fusariosis (La Libertad) |
| `palta_hass` | `contenido_arcilla` | PENALIZE | 0.65 | *Phytophthora cinnamomi* (INIA) |
| `uva_de_mesa_sweet_globe` | `contenido_arcilla` | PENALIZE | 0.65 | Hongos fúngicos (SENAMHI) |

`PENALIZE` multiplica el score MCDA cuando la membresía del criterio es 0. `NO_VIABLE` en cambio colapsa el score total a 0 independientemente de los demás criterios.

---

## Scripts de seed

| Script | Propósito | Cultivos |
|---|---|---|
| `seed_demo_rulebooks.py` | Rulebooks sintéticos básicos (testing) | demo_papa/maiz/quinua/palta/arandano |
| `seed_diagnostic_rulebooks.py` | Pesos diferenciados, scores variados para diagnóstico | demo (mismos) |
| `seed_multivariable_diagnostic_rulebooks.py` | Topografía + RS auxiliar, sin clima/suelo real | demo con 5 criterios |
| `seed_potential_viability_rulebooks.py` | 12 criterios completos, umbrales documentados | demo con valores reales |
| `seed_prod_rulebooks.py` | Cultivos reales INIA/SENASA/MIDAGRI | maiz, mandarina, maracuya, palta, uva |

Todos los seeds usan UUIDs determinísticos generados con `uuid5(NAMESPACE_URL, ...)` para garantizar idempotencia — re-ejecutar el seed no duplica datos.

---

## Diagrama de datos completo

```
Rulebook (aggregate root)
├── id, crop_id, version, status (DRAFT|ACTIVE|INACTIVE)
│
├── Criterion × N  (pesos AHP, política crítica)
│   ├── id, name ("aptitud_termica", "riesgo_frio", ...)
│   ├── ahp_weight [0,1]   → Σ = 1.0
│   ├── is_critical, critical_policy (NO_VIABLE | PENALIZE)
│   ├── penalty_factor [0,1]
│   └── doc_source, technical_notes
│
├── PhenologicalPhase × M  (ciclo fenológico)
│   ├── id, name ("floracion", "cuajado_fruto", ...)
│   ├── duration_days, sequence_order
│   └── (sin pesos aquí — el peso está en PhaseRequirement)
│
└── PhaseRequirement × (N×M)  (requisito criterio × fase)
    ├── criterion_id → Criterion.id
    ├── phase_id → PhenologicalPhase.id
    │
    ├── MembershipFunction  ← función trapezoidal JSONB
    │   ├── (a, b, c, d): define zona óptima del valor físico
    │   └── invertida cuando T baja es deseable (vid/mandarina)
    │
    ├── phase_weight [0,1]  → Σ por criterio = 1.0
    │
    ├── TemporalPeriod × K  ← pesos sub-periodos JSONB
    │   ├── period_key ("floracion_2024")
    │   ├── temporal_weight [0,1]  → Σ = 1.0
    │   └── start_day, end_day (opcional)
    │
    └── ExtractionBinding  ← enlace GEE JSONB
        ├── variable_name ("temperatura_media_c")
        ├── dataset_key ("ECMWF/ERA5_LAND/MONTHLY_AGGR")
        ├── band, unit, scale, reducer
        ├── temporal_resolution ("monthly"|"daily"|"static"|"derived")
        ├── quality_mask (SCL Sentinel-2, opcional)
        └── fallback_allowed

                    │
                    │ get_required_extraction_spec()
                    ▼
        RequiredExtractionSpec
        └── variables: RequiredVariableForEvaluation × (N×M×K)
                [→ IniciarExtraccionAgroambiental → GEE → AgroenvVector]

                    │
                    │ RulebookAclAdapter.get_active_rulebook()
                    ▼
        RulebookEvaluationData
        └── criteria: EvaluationCriterionSpec × (N×M)
                [→ MCDA: membresía + pesos + políticas críticas → score + categoría]
```

---

## Invariantes y restricciones clave

1. **Solo un ACTIVE por crop_id.** La publicación es atómica: desactiva el anterior y activa el nuevo en la misma transacción. Nunca puede haber dos versiones ACTIVE del mismo cultivo.

2. **La membresía vive en el PhaseRequirement, no en el Criterion.** El mismo criterio (e.g., `aptitud_termica`) puede tener trapecios completamente distintos para floración vs. maduración — esa flexibilidad es intencional y está modelada en el dominio.

3. **Suma de pesos ≠ 1.0 invalida el rulebook.** La validación rechaza el aggregate completo si cualquier nivel de pesos (AHP, fase, temporal) no suma 1.0 ± 0.001. No hay corrección automática.

4. **Los UUIDs de criterios y fases son estables entre versiones del mismo seed.** Se generan con `uuid5(NAMESPACE_URL, ...)` para garantizar idempotencia. Sin esto, cada re-ejecución del seed crearía versiones nuevas con nuevos IDs.

5. **El rulebook no interpreta los datos — solo define las reglas.** La aplicación de la función de membresía, el cálculo de scores y la categorización de viabilidad son responsabilidad exclusiva de `viability_evaluation`. El rulebook solo expone `(a, b, c, d)` y los pesos.

6. **Las fuentes documentales son trazables.** Cada `Criterion` tiene un `doc_source` que registra la bibliografía oficial que fundamenta sus umbrales. Cuando hay conflicto entre fuentes (como el pH de palta), el `technical_notes` documenta la decisión tomada y por qué.
