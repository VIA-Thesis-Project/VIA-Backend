# Ponderación por entropía cross-cultivo (corrección metodológica)

> Bounded Context: `viability_evaluation`
> Archivos: `domain/entropy_weights.py`, `domain/hybrid_weights.py`,
> `application/command_service.py`, `config.py`
> Estado: implementado. Evidencia numérica reproducible con
> `scripts/entropy_before_after.py`.

---

## 1. El problema (bug de entropía temporal)

El método de entropía de Shannon en MCDA calcula, para cada criterio, un peso
**objetivo** proporcional a cuánto ese criterio **discrimina entre las
alternativas** de decisión. En VIA las alternativas son los **cultivos
candidatos**, así que la entropía debe medirse sobre la matriz de decisión
`cultivos × criterios`.

La implementación original medía la entropía sobre la **serie temporal de
membresías de un solo cultivo** (las membresías por fase/período). Esto es
matemáticamente válido pero agronómicamente incorrecto:

- Un criterio **estático de sitio** (textura de suelo, altitud, pendiente)
  tiene la **misma** membresía en todas las fases → su serie temporal es plana
  → su divergencia es 0 → recibía **peso de entropía ≈ 0**, incluso cuando ese
  criterio **discriminaba fuertemente entre los cultivos candidatos**.
- Resultado: transferencia sistemática de peso desde suelo/topografía hacia los
  criterios climáticos que varían en el tiempo. El sesgo era estructural, no un
  matiz: cada vez que la entropía se activaba, los criterios estáticos perdían
  hasta el `(1−α)` de su peso frente a la intención del AHP.

Además, "membresía uniformemente baja" ≠ "criterio sin información": esa
equivalencia solo es válida en la formulación clásica entre alternativas.

---

## 2. La corrección

La entropía ahora opera sobre la matriz de decisión `cultivos × criterios` de
**membresías agregadas** (una por cultivo por criterio). La matemática interna
(entropía de Shannon normalizada, divergencia = 1 − H, normalización a suma 1)
no cambia; solo cambia **qué vector entra**: la columna de un criterio a través
de los cultivos, en vez de la serie temporal de un cultivo.

Consecuencia clave: la fórmula correcta **distingue**
- "estático y no discrimina aquí" (p.ej. altitud a 300 m: todos los cultivos
  μ=1.0 → divergencia 0 → peso 0, **correctamente**), de
- "estático y sí discrimina" (p.ej. arcilla 42 %: los cultivos difieren →
  recibe peso).

La formulación vieja metía ambos casos en el mismo saco de peso 0.

---

## 3. Evidencia numérica (antes/después) — usada en la tesis

**Escenario:** parcela tipo Fundo Loreto — elevación 300 m, arcilla 42 %,
temperatura mensual con oscilación estacional real (13→24→13 °C sobre el ciclo).
Membresías agregadas por cultivo computadas con **los trapecios reales de los
seeds de producción** (`scripts/seed_prod_rulebooks.py`):

| criterio | maíz | mandarina | maracuyá | palta | uva |
|---|---|---|---|---|---|
| aptitud_termica (dinámico) | 0.847 | 0.632 | 0.000 | 0.938 | 0.899 |
| aptitud_altitudinal (estático) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| contenido_arcilla (estático) | 0.900 | 0.650 | 0.150 | 0.400 | 0.150 |

**Divergencia (poder discriminante) por criterio:**

| criterio | OLD (serie temporal intra-cultivo) | NEW (vector cross-cultivo) |
|---|---|---|
| aptitud_termica | ~0 (plana si el sitio es térmicamente estable) | 0.145 |
| aptitud_altitudinal | 0 | 0.000 (no discrimina a 300 m — correcto) |
| contenido_arcilla | **0** (serie estática plana) | **0.134** |

**Peso híbrido resultante (α=0.7, 3 criterios renormalizados, cultivo = maíz):**

| criterio | AHP norm | híbrido OLD | híbrido NEW | cambio |
|---|---|---|---|---|
| aptitud_termica | 0.406 | 0.584 | 0.440 | **−24.7 %** |
| aptitud_altitudinal | 0.375 | 0.262 | 0.262 | 0.0 % |
| contenido_arcilla | 0.219 | 0.153 | 0.297 | **+94.1 %** |

**Efecto en el score de viabilidad del maíz** (WGM de las 3 membresías con cada
juego de pesos): `0.8930` (OLD) → `0.9008` (NEW), **+0.88 %**. El cambio de
score es moderado en este caso porque las tres membresías del maíz son altas;
el impacto es mayor en cultivos donde un criterio estático discriminante tiene
membresía baja (maracuyá/uva en arcilla), que es justo donde el modelo viejo
subponderaba la restricción real.

**Lectura agronómica (validada con criterio de dominio):** en este sitio la
textura del suelo discrimina entre cultivos **tanto como el clima** (divergencias
0.134 vs 0.145). El modelo viejo le daba a la arcilla peso ≈ 0 y el clima
acaparaba toda la masa objetiva; el nuevo reparte según discriminación real.

---

## 4. Decisiones de diseño

### 4.1 Manejo por-criterio de matriz irregular (no fallback global)

Cuando una columna tiene menos de `min_alternatives` cultivos con dato válido
(criterio faltante en algunos cultivos), **solo ese criterio** se excluye del
vector de entropía y cae a su peso AHP; el resto de la matriz sigue recibiendo
pesos objetivos. Esto es deliberadamente distinto del fallback global anterior:
**el propio bug de entropía temporal enseñó** que colapsar toda la ponderación
porque una serie es degenerada tira información buena. Una columna rala no debe
silenciar la ponderación objetiva de todos los demás criterios.

### 4.2 Umbral de alternativas

La entropía requiere al menos `MCDA_MIN_ALTERNATIVES_FOR_ENTROPY` cultivos
candidatos (default **3**, configurable, validado `>= 2`). Con menos, no hay
dispersión que medir y **cada criterio cae a AHP puro**. Esto cubre limpiamente
el caso borde de **un solo cultivo** (evaluación individual o recomendación):
matriz de una fila → fallback → híbrido = AHP puro, sin caso especial nuevo.

### 4.3 Combinación híbrida sobre subconjunto (mass-preserving)

`HybridWeightsService.combine` recibe el vector de entropía **global** (sobre los
criterios que calificaron) que puede cubrir solo un subconjunto de los criterios
de un cultivo. El blend ocurre en la intersección S, escalado por la masa AHP de
S, de modo que los criterios fuera de S conservan **exactamente** su peso AHP en
vez de ser penalizados. Para matriz completa (S = todos, masa = 1) se reduce al
clásico `α·AHP + (1−α)·entropía`.

---

## 5. Reordenamiento del pipeline

`_build_evaluation` pasó de un solo bucle por-cultivo a **dos pasadas**:

1. **Pasada 1 (por cultivo):** membresías agregadas + pesos AHP, sin entropía ni
   score. La entropía es cross-cultivo, así que necesita todos los cultivos antes
   de poder calcular.
2. **Entropía global (una vez):** se ensambla la matriz `cultivos × criterios` y
   se obtiene un único vector de pesos de entropía.
3. **Pasada 2 (por cultivo):** híbrido = AHP ⊕ entropía global, políticas críticas,
   brechas, suficiencia y `CropResult`.

---

## 6. Qué scores cambiaron en la suite (y por qué)

- **Tests unitarios de dominio/evaluación:** ninguno fija scores absolutos que
  dependan de la entropía, así que **no se rompió ningún assert de score**
  (192/192 en verde tras el cambio). Solo se reescribió
  `test_entropy_and_hybrid_weights.py` por el cambio de firma.
- **E2E multi-cultivo (2 cultivos: maíz + papa):** con umbral 3 y solo 2
  cultivos, la entropía cae a **AHP puro** (antes usaba entropía temporal
  por-cultivo). Los scores cambian levemente; el **ranking se preserva** (maíz
  sigue rank 1). El único fallo observado es el test flaky preexistente de
  timing de recomendación (documentado en Sprint 0: devuelve 202 pending, no un
  flip de ranking), **no** causado por este cambio.
- **Producción (5 cultivos):** aquí la entropía sí se activa y aplica la
  redistribución de la tabla de §3.
