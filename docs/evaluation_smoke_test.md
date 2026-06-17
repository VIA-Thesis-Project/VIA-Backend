# Smoke Test Demostrativo — Motor MCDA Difuso (DEMO-EVAL-1)

## Propósito

Demuestra el funcionamiento completo del motor de evaluación MCDA difuso de VIA
con datos controlados para dos cultivos candidatos, sin depender de GEE, LLM, RAG
ni ningún servicio externo. Está diseñado para ser ejecutado en cualquier entorno
sin credenciales ni conexiones externas.

## Ejecución

```bash
python scripts/evaluation_smoke_test.py
```

## Escenario controlado

**Parcela de ejemplo:** Lima, Perú (GeoJSON implícito — el motor no depende de geometría real).

**Ventana temporal:** 2026-Q1 y 2026-Q2 (dos períodos por fase fenológica).

**Cultivos evaluados:**

| Cultivo | Score esperado | Categoría | Rank |
|---|---|---|---|
| `maiz_amarillo_duro` | ≈ 0.871 | VIABLE | 1 |
| `papa` | ≈ 0.536 | CONDICIONAL | 2 |

## Criterios y datos controlados

### Maíz Amarillo Duro

| Criterio | Función (a,b,c,d) | w_AHP | Q1 | Q2 |
|---|---|---|---|---|
| temperatura | (18,22,30,35) °C | 0.6 | 25°C → μ=1.0 | 27°C → μ=1.0 |
| precipitacion | (400,600,900,1100) mm | 0.4 | 700mm → μ=1.0 | 500mm → μ=0.5 |

**Cálculo:**
- μ_temp = WGM(1.0^0.5 · 1.0^0.5) = 1.0
- μ_precip = WGM(1.0^0.5 · 0.5^0.5) = √0.5 ≈ 0.707
- score = WGM(1.0^0.6 · 0.707^0.4) ≈ **0.871 → VIABLE**
- Entropía: 2 períodos < min_series_length=3 → fallback a pesos AHP

**Brecha visible:** precipitación Q2 = 500mm, óptimo = 600mm, **gap = −100mm (déficit)**

### Papa

| Criterio | Función (a,b,c,d) | w_AHP | Q1 | Q2 |
|---|---|---|---|---|
| temperatura | (10,14,18,22) °C | 0.6 | 20°C → μ=0.5 | 21°C → μ=0.25 |
| precipitacion | (400,600,900,1100) mm | 0.4 | 700mm → μ=1.0 | 650mm → μ=1.0 |

**Cálculo:**
- μ_temp = WGM(0.5^0.5 · 0.25^0.5) = √0.5 · √0.25 ≈ 0.354
- μ_precip = WGM(1.0^0.5 · 1.0^0.5) = 1.0
- score = WGM(0.354^0.6 · 1.0^0.4) ≈ **0.536 → CONDICIONAL**
- Entropía: fallback a pesos AHP (igual que maíz)

**Brecha visible:** temperatura Q2 = 21°C, óptimo = 18°C (c), **gap = +3°C (exceso)**

## Salida JSON esperada

```json
{
  "evaluation_id": "00000000-0000-4000-8000-000000000001",
  "parcel_id": "00000000-0000-4000-8000-000000000002",
  "status": "COMPLETADA",
  "results": [
    {
      "crop_id": "maiz_amarillo_duro",
      "score": 0.870551,
      "rank_position": 1,
      "calc_condition": "DEFINITIVO",
      "viability_category": "VIABLE",
      "missing_criteria": [],
      "unrecognized_variables": [],
      "limiting_factors": [],
      "gaps": [
        {
          "criterion_id": "precipitacion",
          "phase_id": "vegetativo",
          "most_limiting_period": "2026-Q2",
          "observed_value": 500.0,
          "optimal_limit": 600.0,
          "gap_value": -100.0
        }
      ]
    },
    {
      "crop_id": "papa",
      "score": 0.535826,
      "rank_position": 2,
      "calc_condition": "DEFINITIVO",
      "viability_category": "CONDICIONAL",
      "missing_criteria": [],
      "unrecognized_variables": [],
      "limiting_factors": [],
      "gaps": [
        {
          "criterion_id": "temperatura",
          "phase_id": "vegetativo",
          "most_limiting_period": "2026-Q2",
          "observed_value": 21.0,
          "optimal_limit": 18.0,
          "gap_value": 3.0
        }
      ]
    }
  ]
}
```

## Flujo del motor MCDA ejecutado

El script invoca directamente `PureMcdaEvaluationEngine.evaluate()` que
encadena los siguientes servicios de dominio:

1. **Fuzificación trapezoidal** por criterio y período
2. **Agregación temporal** (Media Geométrica Ponderada) por fase
3. **Agregación por criterio** a través de fases
4. **Resolución de criterios faltantes** — ninguno faltante en este escenario
5. **Pesos por entropía de Shannon** — fallback a AHP (solo 2 períodos < mínimo 3)
6. **Pesos híbridos** w* = α·w_AHP + (1−α)·w_ENT = w_AHP (fallback)
7. **Agregación multicriterio** (MGP con pesos híbridos)
8. **Políticas críticas** — sin factores críticos en este escenario
9. **Clasificación de viabilidad** por umbrales (VIABLE≥0.70, CONDICIONAL≥0.40)
10. **Cálculo de brechas** usando el período más limitante por fase
11. **Ranking** por score descendente, desempate por crop_id ascendente

## Tests

```bash
pytest tests/unit/smoke_test/ -v
```

Los tests verifican:
- Ranking determinista: maíz rank=1 (VIABLE), papa rank=2 (CONDICIONAL)
- Brecha de maíz: precipitación Q2 −100mm
- Brecha de papa: temperatura Q2 +3°C
- Sin imports de GEE, LLM, SQLAlchemy ni FastAPI
- Estabilidad numérica (score ∈ [0,1], finito)
- Determinismo entre dos ejecuciones consecutivas

## Limitaciones del DEMO-EVAL-1

- Solo 1 fase fenológica y 2 períodos temporales (escenario simplificado).
- Con 2 períodos < min_series_length=3 la entropía hace fallback a pesos AHP.
  En producción, con períodos mensuales por varios meses, la entropía se activa.
- No hay criterios críticos (critical_policy=NO_VIABLE/PENALIZE) en este escenario;
  los tests de critical_policy están cubiertos en tests/unit/viability_evaluation/.
- Los datos de precipitación y temperatura son ilustrativos, no de una parcela real.

## Confirmación de restricciones

- ✅ Sin GEE real
- ✅ Sin LLM (Gemini, Vertex, local_http)
- ✅ Sin Recommendation ni RAG
- ✅ Sin SQLAlchemy ni psycopg2
- ✅ Sin FastAPI ni endpoints nuevos
- ✅ Sin Process Manager, Event Bus ni Outbox
- ✅ Sin asyncpg, AsyncSession ni Celery
- ✅ Sin cambios de arquitectura
- ✅ No duplica lógica MCDA — usa `PureMcdaEvaluationEngine` existente
- ✅ No rompe tests existentes
