# Flujo de Extracción Agroambiental de la Parcela

> Bounded Context: `agroenv_extraction`  
> Archivos principales: `application/ports.py`, `application/command_service.py`, `infrastructure/extraction_acl.py`, `infrastructure/gee_client.py`, `infrastructure/gee_variable_registry.py`

---

## Visión general

La extracción agroambiental produce un vector de variables geoespaciales (clima, suelo, topografía, índices de vegetación) para una parcela específica en una ventana temporal dada. El resultado alimenta directamente al motor MCDA de `viability_evaluation`. La extracción es completamente **pasiva y no destructiva**: solo lee datos de fuentes externas (GEE) y persiste el vector resultante.

```
IniciarExtraccionAgroambiental (mensaje del saga)
        │
        ▼
┌────────────────────────────────┐
│  AgroenvExtractionConsumer     │  ← interface: valida tipo de mensaje
└────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────┐
│  AgroenvExtractionCommandService     │  ← idempotencia + transacción
└──────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────┐
│  ExtractionAcl.build_vector()  │  ← itera variables × periodos
└────────────────────────────────┘
        │  por cada (variable, periodo)
        ▼
┌────────────────────────────────┐
│  GeeExtractionClient           │  ← llama Google Earth Engine
│  · dispatch por GeeVariableType│
│  · retries con backoff         │
│  · conversiones de unidades    │
└────────────────────────────────┘
        │  ExtractionClientResult
        ▼
┌────────────────────────────────┐
│  AgroenvVector (aggregate)     │  ← lista de VariableEntry
└────────────────────────────────┘
        │
        ├── IExtractionRepository.save()
        └── VectorAgroambientalGenerado → Outbox → Saga
```

---

## Paso 0 — Disparo desde el saga

El flujo se inicia cuando el `EvaluationProcessManager` (saga de orquestación) emite el comando `IniciarExtraccionAgroambiental`. Este mensaje llega al `AgroenvExtractionConsumer` a través del event bus interno.

El payload del mensaje contiene:

| Campo | Descripción |
|---|---|
| `evaluation_id` | UUID de la evaluación en curso |
| `parcel_id` | UUID de la parcela a extraer |
| `parcel_geometry` | GeoJSON Polygon o MultiPolygon en WGS-84 |
| `crop_candidates` | Lista de cultivos candidatos (e.g. `["maiz_amarillo_duro", "palta_hass"]`) |
| `temporal_window` | Ventana temporal `{start, end}` para la extracción |
| `required_extraction_spec` | Especificación detallada de variables y periodos a extraer |

El consumer valida que el tipo de mensaje sea `INICIAR_EXTRACCION_AGROAMBIENTAL` antes de delegar. Cualquier otro tipo se ignora silenciosamente.

---

## Paso 1 — Comando y normalización de geometría

`StartExtractionCommand.from_payload()` deserializa el payload y normaliza la geometría a `MultiPolygon` canónico mediante `normalize_parcel_geometry()`:

- Si llega como `Polygon` → se convierte a `MultiPolygon` con un único polígono
- Si llega como `MultiPolygon` → se valida y se retorna tal cual
- Validaciones obligatorias: anillos cerrados (primer punto == último), mínimo 4 puntos por anillo, coordenadas dentro de WGS-84 (`[-180, 180] × [-90, 90]`)

```python
@dataclass(frozen=True)
class StartExtractionCommand:
    evaluation_id: UUID
    parcel_id: UUID
    parcel_geometry: dict        # siempre MultiPolygon después de normalize
    crop_candidates: list[str]
    temporal_window: dict        # {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
    required_extraction_spec: dict  # especificación completa de variables
```

---

## Paso 2 — Idempotencia y transacción

`AgroenvExtractionCommandService.handle_start_command()` actúa como orquestador transaccional:

1. Abre una sesión de base de datos
2. Consulta `processed_message_store`: si el `message.id` ya fue procesado con el mismo `consumer_name`, retorna inmediatamente (idempotencia)
3. Llama a `ExtractionAcl.build_vector()` — el paso más costoso (múltiples llamadas a GEE)
4. En caso de éxito: persiste el vector + escribe evento `VectorAgroambientalGenerado` en el outbox
5. En caso de excepción: escribe evento `ExtraccionFallida` en el outbox con la causa del fallo
6. Siempre marca el mensaje como procesado y hace commit/rollback

El outbox garantiza que el evento de éxito o fallo se entregue al saga exactamente una vez, incluso si el proceso muere entre el paso 4 y la confirmación del commit.

---

## Paso 3 — Anti-Corruption Layer: `ExtractionAcl`

`ExtractionAcl.build_vector()` es el traductor entre el payload del saga y el dominio de extracción. Su responsabilidad es iterar la `required_extraction_spec` y obtener un valor para cada `(variable, periodo)`.

### 3.1 Estructura de `required_extraction_spec`

```json
{
  "variables": [
    {
      "variable_name": "temperatura_media_c",
      "criterion_id": "aptitud_termica",
      "crop_id": "maiz_amarillo_duro",
      "phase_id": "vegetativo",
      "dataset_key": "ECMWF/ERA5_LAND/MONTHLY_AGGR",
      "band": "temperature_2m",
      "unit": "celsius",
      "temporal_resolution": "monthly",
      "spatial_resolution": null,
      "scale": 11132,
      "reducer": "mean",
      "aggregation_method": "mean",
      "quality_mask": null,
      "fallback_allowed": true,
      "temporal_periods": [
        {
          "period_key": "vegetativo_2023",
          "start": "2023-09-01",
          "end": "2023-12-31"
        },
        {
          "period_key": "floracion_2024",
          "start": "2024-01-01",
          "end": "2024-03-31"
        }
      ]
    },
    ...
  ]
}
```

Cada variable puede tener **múltiples periodos temporales** (uno por fase fenológica evaluada). La ACL itera `variables × temporal_periods` y genera un `ExtractionRequest` por cada combinación.

### 3.2 Construcción de `ExtractionRequest`

```python
@dataclass(frozen=True)
class ExtractionRequest:
    parcel_id: UUID
    parcel_geometry: dict         # GeoJSON MultiPolygon
    temporal_window: dict         # ventana global de la evaluación
    variable_name: str            # e.g. "temperatura_media_c"
    criterion_id: str             # e.g. "aptitud_termica"
    crop_id: str                  # e.g. "maiz_amarillo_duro"
    phase_id: str                 # e.g. "vegetativo"
    dataset_key: str              # GEE catalog key
    band: str                     # banda GEE a extraer
    unit: str                     # unidad física esperada
    temporal_resolution: str      # "monthly" | "daily"
    spatial_resolution: str | None
    scale: float | None           # escala en metros para GEE
    reducer: str                  # "mean" | "median" | "min" | "max"
    aggregation_method: str       # "mean" | "sum"
    quality_mask: dict | None     # filtro de calidad de imagen
    fallback_allowed: bool        # si True, un None del cliente es aceptable
    period_key: str               # clave única del periodo
    period_start: str | None      # "YYYY-MM-DD"
    period_end: str | None        # "YYYY-MM-DD"
```

### 3.3 Manejo de resultado ausente

Si `GeeExtractionClient.extract_variable()` retorna `None`:
- Si `fallback_allowed = True` → se registra una entrada con `status = CRITERIO_FALTANTE` y `value = None`
- Si `fallback_allowed = False` → se lanza `AgroenvExtractionError`, lo que causa un evento `ExtraccionFallida`

Este diseño permite que variables opcionales o con datos tardíos (e.g., TerraClimate con lag de 1–2 años) no bloqueen el proceso de evaluación.

---

## Paso 4 — Extracción en GEE: `GeeExtractionClient`

El cliente despacha la extracción a una de **siete estrategias** según el `GeeVariableType` del registro:

```
ExtractionRequest
        │
        ▼ get_variable_definition(variable_name)
        │
        ├── GeeVariableType.SIMPLE_BAND      → _extract_simple()
        ├── GeeVariableType.DERIVED_INDEX    → _extract_index()
        ├── GeeVariableType.TOPO_STATIC      → _extract_topo()
        ├── GeeVariableType.TOPO_DERIVED     → _extract_topo()
        ├── GeeVariableType.CLIMATE_SIMPLE   → _extract_climate_simple()
        ├── GeeVariableType.CLIMATE_DERIVED  → _extract_climate_derived_multivar()
        └── GeeVariableType.SOIL_STATIC      → _extract_soil()
```

Variables desconocidas (sin definición en el registro) caen en `SIMPLE_BAND` por compatibilidad.

### 4.1 Reintentos con backoff

El cliente implementa reintentos automáticos con backoff exponencial (`min(2^attempt, 5)` segundos), configurable mediante `gee_max_retries` en `Settings`. La excepción "no bands" (ImageCollection vacía para el periodo) se trata como resultado `None` determinístico — no se reintenta.

### 4.2 Inicialización de Earth Engine

Al construirse (si `gee_enabled = True`), el cliente inicializa la SDK de Earth Engine usando credenciales de cuenta de servicio GCP. Se puede pasar la clave como JSON inline (`gee_private_key_json`) o como ruta de archivo (`gee_private_key_file`). El timeout global se configura con `gee_timeout_seconds`.

---

## Paso 5 — Las siete estrategias de extracción

### 5.1 `SIMPLE_BAND` — Banda cruda de ImageCollection

Usada por: `nir_reflectancia` (Sentinel-2 B8)

```
ImageCollection(dataset_key)
  .filterDate(start, end)
  .select(band)
  [+ quality_mask opcional]
  .mean() / .median() / .min() / .max()    ← reducer temporal
  .reduceRegion(reducer, geometry, scale)  ← reducer espacial
```

Devuelve el valor de la banda sin conversiones.

### 5.2 `DERIVED_INDEX` — Índice espectral calculado

Usada por: `ndvi`, `savi`, `ndmi` (Sentinel-2)

Igual que `SIMPLE_BAND` pero, tras la reducción temporal, aplica la fórmula del índice sobre la imagen reducida antes de `reduceRegion`:

| Variable | Fórmula | Bandas | Escala |
|---|---|---|---|
| `ndvi` | `(B8 - B4) / (B8 + B4)` | B8, B4 | 10 m |
| `savi` | `((B8 - B4) / (B8 + B4 + 0.5)) × 1.5` | B8, B4 | 10 m |
| `ndmi` | `(B8 - B11) / (B8 + B11)` | B8, B11 | 20 m |

Los índices están en el rango `[-1, 1]`. No se aplican conversiones de unidades.

**Máscara de calidad Sentinel-2**: el `quality_mask` en el `ExtractionRequest` permite filtrar imágenes por la banda SCL (`Scene Classification Layer`) para excluir nubes, sombras y agua. Ejemplo: `{"band": "SCL", "allowed_values": [4, 5]}` para vegetación y suelo desnudo.

### 5.3 `TOPO_STATIC` — Imagen estática sin filtro temporal

Usada por: `elevacion_m` (SRTM)

```
ee.Image("USGS/SRTMGL1_003")
  .select("elevation")
  .reduceRegion(reducer, geometry, scale=30m)
```

No necesita `filterDate` — SRTM es un producto estático de una sola toma (2000). El resultado es la elevación media de la parcela en metros sobre el nivel del mar.

### 5.4 `TOPO_DERIVED` — Derivada de imagen estática

Usada por: `pendiente_grados` (SRTM)

```
dem = ee.Image("USGS/SRTMGL1_003")
image = ee.Terrain.slope(dem)          ← calcula pendiente en GEE
image.reduceRegion(reducer, geometry, scale=30m)
```

`ee.Terrain.slope()` aplica un kernel de Sobel al DEM y devuelve pendiente en grados. El resultado es la pendiente media de la parcela.

### 5.5 `CLIMATE_SIMPLE` — Variable climática con conversión de unidades

Usada por: `temperatura_minima_c`, `temperatura_maxima_c`, `temperatura_media_c`, `evapotranspiracion_referencia_mm`, `precipitacion_acumulada_mm`

```
ImageCollection(dataset_key)
  .filterDate(start, end)
  .select(source_band)
  .mean() | .sum()                        ← temporal_aggregation
  .reduceRegion(reducer, sampling_geom, scale)
raw_value → _apply_conversion(scale_factor, offset, normalize_sign)
```

La geometría de muestreo es siempre `centroid_sample` para estas variables (ver §6). La conversión de unidades sigue el orden:

```
raw × scale_factor → abs() si normalize_sign → + offset = valor_final
```

| Variable | Dataset | Banda raw | Conversión | Resultado |
|---|---|---|---|---|
| `temperatura_minima_c` | ERA5-Land MONTHLY | `temperature_2m_min` | `raw − 273.15` | °C |
| `temperatura_maxima_c` | ERA5-Land MONTHLY | `temperature_2m_max` | `raw − 273.15` | °C |
| `temperatura_media_c` | ERA5-Land MONTHLY | `temperature_2m` | `raw − 273.15` | °C |
| `evapotranspiracion_referencia_mm` | ERA5-Land MONTHLY | `potential_evaporation_sum` | `abs(raw) × 1000` | mm |
| `precipitacion_acumulada_mm` | CHIRPS DAILY | `precipitation` | sin conversión | mm |

**Agregación temporal**:
- Temperatura → `mean` (promedio de meses en el periodo)
- PET y precipitación → `sum` (acumulado del periodo)

**Convención de signo ERA5 PET**: ERA5-Land reporta la evapotranspiración potencial como flujo hacia arriba (negativo). `normalize_sign = True` aplica `abs()` para obtener la demanda evaporativa positiva en mm.

### 5.6 `CLIMATE_DERIVED` — Variable derivada de múltiples fuentes

Usada por: `deficit_hidrico_mm`

Esta estrategia no llama a GEE directamente. En cambio, extrae cada variable fuente de forma independiente usando `_extract_climate_simple()` con su propia escala y geometría de muestreo, y luego aplica la fórmula de derivación:

```
Para deficit_hidrico_mm:
  PET = extraer evapotranspiracion_referencia_mm  (ERA5, centroid, 11132m)
  P   = extraer precipitacion_acumulada_mm        (CHIRPS, centroid, 5566m)
  resultado = max(0, PET - P)
```

Si cualquiera de las fuentes retorna `None` (periodo sin datos), el resultado del déficit es también `None`.

El déficit hídrico es cero cuando la precipitación cubre o supera la demanda evaporativa. Valores positivos indican déficit real que el cultivo debe compensar con riego u otras fuentes.

### 5.7 `SOIL_STATIC` — Suelo estático con estrategia de profundidad

Usada por: `ph_suelo`, `arcilla_pct`, `arena_pct`, `carbono_organico_suelo`, `textura_suelo_clase`

Las capas de suelo OpenLandMap son imágenes estáticas con múltiples bandas de profundidad (`b0`, `b10`, `b30`, `b60`, `b100`, `b200`) en centímetros. El `depth_strategy` controla cuáles se usan:

**`surface_0cm`**: solo la banda `b0` (capa superficial de 0 cm). Usada para `textura_suelo_clase`.

**`topsoil_0_30cm_mean`**: promedio aritmético de `b0`, `b10` y `b30` (horizonte A típico, 0–30 cm). Usada para `ph_suelo`, `arcilla_pct`, `arena_pct`, `carbono_organico_suelo`.

```
image = ee.Image(dataset_key)
result_image = (image.select("b0")
                 .add(image.select("b10"))
                 .add(image.select("b30"))
                 .divide(3))
               .rename(variable_name)
result_image.reduceRegion(reducer, centroid, scale=250m)
raw → × scale_factor → valor_final
```

Conversiones de OpenLandMap:

| Variable | Dataset | Almacenamiento raw | Conversión | Resultado |
|---|---|---|---|---|
| `ph_suelo` | SOL_PH-H2O | pH × 10 | × 0.1 | pH real (0–14) |
| `arcilla_pct` | SOL_CLAY-WFRACTION | % × 10 | × 0.1 | % (0–100) |
| `arena_pct` | SOL_SAND-WFRACTION | % × 10 | × 0.1 | % (0–100) |
| `carbono_organico_suelo` | SOL_ORGANIC-CARBON | g/kg × 5 | × 0.2 | g/kg |
| `textura_suelo_clase` | SOL_TEXTURE-CLASS | entero 1–12 | sin conversión | clase USDA |

---

## Paso 6 — Geometría de muestreo espacial

El modo de muestreo espacial depende de la resolución nativa del dataset:

### `polygon_mean` (datos de resolución fina)

Aplica el reducer sobre **toda la geometría** de la parcela. Apropiado cuando el pixel es más pequeño o similar al tamaño de la parcela.

| Dataset | Resolución nativa | Uso |
|---|---|---|
| Sentinel-2 | 10–20 m | `polygon_mean` |
| SRTM | 30 m | `polygon_mean` |

```python
# Se usa la geometría completa del polígono
geometry = _gee_geometry(ee, parcel_geometry)
```

### `centroid_sample` (datos de resolución gruesa)

Extrae el valor del **pixel que contiene el centroide** de la parcela. Esto evita que parcelas pequeñas (< 1 pixel) devuelvan `null` por no intersectar suficientemente con un pixel de la grilla.

| Dataset | Resolución nativa | Uso |
|---|---|---|
| ERA5-Land | ~11 132 m | `centroid_sample` |
| CHIRPS | ~5 566 m | `centroid_sample` |
| OpenLandMap SOL | ~250 m | `centroid_sample` |

```python
# Centroide calculado como media de vértices del anillo exterior
# GeoJSON convención: [longitude, latitude]
# MultiPolygon: se usa el anillo del polígono con más vértices (proxy de área)
lon = mean([pt[0] for pt in exterior_ring])
lat = mean([pt[1] for pt in exterior_ring])
geometry = ee.Geometry.Point([lon, lat])
```

---

## Paso 7 — Catálogo de variables registradas

El `GeeVariableRegistry` mantiene 17 variables en 4 categorías:

### Teledetección (Sentinel-2 SR Harmonized)

| Variable | Tipo | Fórmula | Unidad | Escala |
|---|---|---|---|---|
| `nir_reflectancia` | SIMPLE_BAND | B8 raw | reflectance_scaled | 10 m |
| `ndvi` | DERIVED_INDEX | (B8−B4)/(B8+B4) | index [−1,1] | 10 m |
| `savi` | DERIVED_INDEX | ((B8−B4)/(B8+B4+0.5))×1.5 | index [−1,1] | 10 m |
| `ndmi` | DERIVED_INDEX | (B8−B11)/(B8+B11) | index [−1,1] | 20 m |

### Topografía (SRTM GL1)

| Variable | Tipo | Fórmula | Unidad | Escala |
|---|---|---|---|---|
| `elevacion_m` | TOPO_STATIC | banda elevation | m | 30 m |
| `pendiente_grados` | TOPO_DERIVED | ee.Terrain.slope(DEM) | grados | 30 m |

### Clima

| Variable | Fuente | Tipo | Conversión | Agregación | Escala |
|---|---|---|---|---|---|
| `temperatura_minima_c` | ERA5-Land MONTHLY | CLIMATE_SIMPLE | −273.15 | mean | 11132 m |
| `temperatura_maxima_c` | ERA5-Land MONTHLY | CLIMATE_SIMPLE | −273.15 | mean | 11132 m |
| `temperatura_media_c` | ERA5-Land MONTHLY | CLIMATE_SIMPLE | −273.15 | mean | 11132 m |
| `evapotranspiracion_referencia_mm` | ERA5-Land MONTHLY | CLIMATE_SIMPLE | abs()×1000 | sum | 11132 m |
| `precipitacion_acumulada_mm` | CHIRPS DAILY | CLIMATE_SIMPLE | sin conversión | sum | 5566 m |
| `deficit_hidrico_mm` | ERA5+CHIRPS | CLIMATE_DERIVED | max(0, PET−P) | — | — |

### Suelo (OpenLandMap v02, ~250 m)

| Variable | Dataset | Tipo | Profundidad | Conversión | Unidad |
|---|---|---|---|---|---|
| `ph_suelo` | SOL_PH-H2O | SOIL_STATIC | 0–30 cm mean | ×0.1 | pH |
| `arcilla_pct` | SOL_CLAY-WFRACTION | SOIL_STATIC | 0–30 cm mean | ×0.1 | % |
| `arena_pct` | SOL_SAND-WFRACTION | SOIL_STATIC | 0–30 cm mean | ×0.1 | % |
| `carbono_organico_suelo` | SOL_ORGANIC-CARBON | SOIL_STATIC | 0–30 cm mean | ×0.2 | g/kg |
| `textura_suelo_clase` | SOL_TEXTURE-CLASS | SOIL_STATIC | 0 cm (superficial) | sin conv. | clase USDA 1–12 |

---

## Paso 8 — Agregado de dominio: `AgroenvVector`

Una vez que la ACL termina de iterar todas las variables y periodos, construye el agregado:

```python
@dataclass(frozen=True)
class AgroenvVector:
    id: UUID                    # uuid4 generado
    evaluation_id: UUID
    parcel_id: UUID
    temporal_window: TemporalWindow
    variables: list[VariableEntry]   # una entrada por (variable × periodo)
    extracted_at: datetime      # UTC
```

Cada `VariableEntry` lleva trazabilidad completa:

```python
@dataclass(frozen=True)
class VariableEntry:
    variable_name: str          # e.g. "temperatura_media_c"
    criterion_id: str           # e.g. "aptitud_termica"
    crop_id: str                # e.g. "maiz_amarillo_duro"
    phase_id: str               # e.g. "vegetativo"
    dataset_key: str            # GEE catalog key
    band: str                   # banda fuente
    unit: str                   # unidad del valor
    temporal_resolution: str    # "monthly" | "daily"
    spatial_resolution: str | None
    scale: float | None
    reducer: str
    aggregation_method: str
    quality_mask: dict | None
    fallback_allowed: bool
    period_key: str             # e.g. "vegetativo_2023"
    value: float | None         # None si status=CRITERIO_FALTANTE
    source: str                 # "GEE:ERA5_LAND:temperature_2m:centroid_sample:scale=11132"
    extraction_date: date
    status: VariableStatus      # OK | CRITERIO_FALTANTE
```

El `source` es una cadena estructurada que identifica el dataset, banda, estrategia y escala usados, fundamental para la auditoría y reproducibilidad.

### Invariantes del agregado

- El vector requiere al menos una `VariableEntry` — un vector vacío es inválido
- `VariableEntry` con `status=OK` exige `value != None`
- `VariableEntry` con `status=CRITERIO_FALTANTE` tiene `value=None` y `source="unavailable"`
- `scale` debe ser positiva si está presente

---

## Paso 9 — Persistencia y evento de salida

### Persistencia

`IExtractionRepository.save(vector)` persiste el vector en la base de datos dentro de la misma transacción unitaria. El ORM mapea `AgroenvVector` y su lista de `VariableEntry` a sus respectivas tablas.

### Evento de salida

`AgroenvVector.to_event_payload()` serializa el vector para el saga:

```json
{
  "evaluation_id": "...",
  "parcel_id": "...",
  "vector_id": "...",
  "temporal_window": {"start": "...", "end": "..."},
  "extracted_at": "2024-03-15T10:32:00Z",
  "variables": [
    {
      "id": "...",
      "variable_name": "temperatura_media_c",
      "criterion_id": "aptitud_termica",
      "crop_id": "maiz_amarillo_duro",
      "phase_id": "vegetativo",
      "period_key": "vegetativo_2023",
      "value": 22.4,
      "unit": "celsius",
      "status": "OK",
      "dataset_key": "ECMWF/ERA5_LAND/MONTHLY_AGGR",
      "band": "temperature_2m",
      "source": "GEE:ECMWF/ERA5_LAND/MONTHLY_AGGR:temperature_2m:centroid_sample:scale=11132"
    },
    ...
  ]
}
```

El `OutboxWriter` escribe el evento `VectorAgroambientalGenerado` en la tabla de outbox dentro de la misma transacción. El relay worker lo entrega al event bus después del commit.

En caso de error, se escribe `ExtraccionFallida` con `evaluation_id`, `parcel_id` y `failure_cause`.

---

## Paso 10 — Consumo por `viability_evaluation`

El saga recibe `VectorAgroambientalGenerado` y lanza la evaluación MCDA. El vector no se pasa directamente — `viability_evaluation` lo lee desde su propia perspectiva a través del `AgroenvVectorAclAdapter`:

```python
class AgroenvVectorAclAdapter:
    def get_vector_for_evaluation(self, evaluation_id: UUID) -> AgroenvVectorData:
        raw_vector = self._read_source(evaluation_id)   # lee de BD o caché
        return AgroenvVectorData(
            evaluation_id=...,
            parcel_id=...,
            variables=[AgroenvVariableData(
                variable_name=..., criterion_id=..., crop_id=...,
                phase_id=..., period_key=..., value=..., unit=...,
                status=..., dataset_key=..., band=..., source=...
            ) for item in raw_vector["variables"]],
        )
```

El ACL actúa como barrera de corrupción: el bounded context de evaluación nunca conoce los detalles de extracción (GEE, datasets, estrategias) — solo consume `AgroenvVariableData` con los valores ya convertidos a unidades físicas.

---

## Diagrama de datos completo

```
StartExtractionCommand
├── parcel_id, parcel_geometry (MultiPolygon normalizado)
├── evaluation_id, crop_candidates, temporal_window
└── required_extraction_spec
    └── variables[]
        ├── variable_name → GeeVariableDefinition (registry)
        ├── criterion_id, crop_id, phase_id
        ├── dataset_key, band, unit, scale, reducer
        ├── quality_mask (SCL filter para Sentinel-2)
        ├── fallback_allowed
        └── temporal_periods[]
            ├── period_key
            └── start, end (fechas ISO)
                    │
                    ▼ por cada (variable × periodo)
            ExtractionRequest → GeeExtractionClient
                    │
                    ├── SIMPLE_BAND:
                    │   ImageCollection.filterDate.select.mean/sum
                    │   .reduceRegion(polygon_mean)
                    │
                    ├── DERIVED_INDEX:
                    │   ImageCollection.filterDate.select[multiband].mean
                    │   .normalizedDifference | .expression
                    │   .reduceRegion(polygon_mean)
                    │
                    ├── TOPO_STATIC:
                    │   Image.select(band)
                    │   .reduceRegion(polygon_mean, 30m)
                    │
                    ├── TOPO_DERIVED:
                    │   Terrain.slope(Image)
                    │   .reduceRegion(polygon_mean, 30m)
                    │
                    ├── CLIMATE_SIMPLE:
                    │   ImageCollection.filterDate.select.mean|sum
                    │   .reduceRegion(centroid_sample)
                    │   → _apply_conversion(scale_factor, normalize_sign, offset)
                    │
                    ├── CLIMATE_DERIVED:
                    │   [extrae PET y P por separado como CLIMATE_SIMPLE]
                    │   → max(0, PET − P)
                    │
                    └── SOIL_STATIC:
                        Image.select(b0,b10,b30).mean | select(b0)
                        .rename(variable_name)
                        .reduceRegion(centroid_sample, 250m)
                        → × scale_factor
                                │
                                ▼
                    ExtractionClientResult
                    ├── value: float (ya en unidades físicas)
                    ├── source: "GEE:dataset:band:strategy:scale=N"
                    └── extraction_date: date.today()
                                │
                                ▼
                    VariableEntry
                    ├── status: OK | CRITERIO_FALTANTE
                    ├── value: float | None
                    └── trazabilidad completa (dataset, band, scale, reducer...)
                                │
                                ▼
            AgroenvVector (aggregate)
            ├── id, evaluation_id, parcel_id, temporal_window, extracted_at
            └── variables: list[VariableEntry]
                    │
                    ├── IExtractionRepository.save(vector)
                    └── OutboxWriter → VectorAgroambientalGenerado
                                              │
                                              ▼
                                    AgroenvVectorAclAdapter
                                    └── AgroenvVectorData → viability_evaluation
```

---

## Invariantes y restricciones clave

1. **La geometría siempre se normaliza a MultiPolygon** antes de ser procesada. Polygon de entrada se convierte automáticamente. Anillos sin cerrar o con menos de 4 puntos son rechazados en el port de entrada.

2. **`polygon_mean` vs `centroid_sample` no es configurable por el llamador** — lo determina la `GeeVariableDefinition` en el registry. El llamador no puede elegir la estrategia de muestreo.

3. **Las conversiones de unidades son responsabilidad del cliente GEE**, no de la ACL ni del dominio. Cuando `VariableEntry.value` llega al dominio, ya está en unidades físicas (°C, mm, %, pH, g/kg).

4. **La `required_extraction_spec` es el contrato entre el saga y la extracción.** El saga (proceso manager o quien lo emite) es responsable de emitir la especificación correcta para cada cultivo y ventana temporal. La ACL no infiere qué variables extraer — solo ejecuta lo que se le pide.

5. **Variables con `fallback_allowed = False` y resultado `None` bloquean toda la extracción.** Si una variable crítica no está disponible en GEE para el periodo solicitado, el evento `ExtraccionFallida` se emite y el saga decide si reintentar o descartar la evaluación.

6. **La idempotencia es por `message.id`**, no por `(evaluation_id, parcel_id)`. Si el saga reenvía el mismo mensaje con diferente ID (por retry), se procesará nuevamente.
