# Informe de validacion agronomica - Parcela Humalla

Fecha de preparacion: 2026-06-26  
Parcela evaluada: Parcela Humalla - Sector Izquierdo  
Evaluacion VIA: af637625-d38c-43ec-ba5b-a2a4a5d73d87  
Estado: RECOMENDACION_COMPLETADA

## 1. Objetivo del informe

Este informe resume los resultados generados por VIA para la Parcela Humalla - Sector Izquierdo, con el fin de que un ingeniero agronomo pueda validar:

- si las reglas agronomicas usadas son razonables;
- si las caracteristicas encontradas para la parcela tienen sentido;
- si el orden de cultivos propuesto tiene sentido;
- si las recomendaciones generadas son aceptables o requieren ajustes.

El sistema debe entenderse como una herramienta de apoyo para priorizacion inicial. No reemplaza una visita de campo, analisis de suelo, evaluacion de disponibilidad de agua, ni validacion agronomica local.

## 2. Parcela evaluada

La parcela usada para esta revision corresponde al poligono registrado para Humalla - Sector Izquierdo.

| Atributo | Valor |
|---|---:|
| ID parcela | 457236a3-18ee-4a73-ab30-f8defafa9879 |
| Nombre | Parcela Humalla - Sector Izquierdo |
| Descripcion | Parcela lista para cultivar. |
| CRS | EPSG:4326 |
| Tipo de geometria | MultiPolygon |
| Coordenada centroide aproximada | -11.07759, -77.41297 |
| Longitud minima / maxima | -77.41306 / -77.41274 |
| Latitud minima / maxima | -11.07769 / -11.07745 |
| Area aproximada | 466.75 m2 |
| Area aproximada | 0.047 ha |
| Vertices del poligono | 4 vertices utiles + cierre |

La ubicacion corresponde a una condicion de costa central peruana. VIA combina datos de clima, relieve, suelo y cobertura vegetal con reglas agronomicas cargadas para cada cultivo.

## 3. Caracteristicas detectadas de la parcela

Estos valores aparecen repetidamente en las brechas de los cultivos evaluados:

| Variable interpretada | Valor observado | Comentario tecnico |
|---|---:|---|
| Temperatura media critica | 20.47 C | Aparece por debajo del optimo en algunas fases reproductivas o de llenado. |
| Temperatura minima critica | 15.96 C | En maiz aparece casi igual al umbral inferior de floracion; en mandarina aparece como punto a revisar para induccion floral. |
| Temperatura maxima critica | 27.28 C | En algunos cultivos aparece bajo o sobre umbrales de calor segun fase. |
| Indicador hidrico usado por VIA | 1808.12 mm | Requiere revision: el valor aparece como una brecha importante, pero debe confirmarse que el indicador este bien interpretado. |
| Pendiente / aptitud topografica | 4.59 | En maiz aparece apenas sobre un umbral interno de 4.57. Revisar unidad y transformacion. |
| pH de suelo | 7.33 | Ligeramente alcalino frente a algunos rangos optimos. |
| Arcilla | 1.73 % | Muy baja frente a los rangos esperados por varios cultivos. Debe confirmarse con analisis fisico de suelo. |
| Arena | 6.40 % | Muy baja frente a los rangos esperados. Debe confirmarse con analisis fisico de suelo. |
| Carbono organico del suelo | 0.00 | Valor critico o posiblemente faltante/estimado; requiere validacion de laboratorio. |
| Cobertura auxiliar / NDVI | 0.048 | Muy cerca del umbral minimo auxiliar. |

Lectura agronomica preliminar: el resultado esta muy influido por suelo y agua. La textura reportada, especialmente arcilla 1.73 % y arena 6.40 %, no debe aceptarse como definitiva sin laboratorio porque cambia fuertemente la aptitud de palta, vid, maracuya y mandarina.

## 4. Como calcula VIA la aptitud

VIA evalua cada cultivo con un conjunto de reglas agronomicas. Para cada cultivo se define:

- fases fenologicas del cultivo;
- peso relativo por fase;
- criterios de evaluacion con distinta importancia;
- rangos de pertenencia por criterio y fase;
- factores criticos que pueden bajar el resultado;
- fuentes documentales usadas para justificar los rangos.

En terminos simples:

1. Para cada cultivo se calculan criterios climaticos, hidricos, topograficos, edaficos y de cobertura.
2. Cada criterio se evalua por fase fenologica.
3. El sistema da mas peso a los criterios y fases mas importantes.
4. Si un criterio critico cae fuera de rango, el resultado baja.
5. El puntaje final ordena los cultivos y clasifica la viabilidad.

Categorias observadas en esta evaluacion:

- CONDICIONAL: el cultivo puede considerarse candidato, pero tiene brechas relevantes que requieren manejo o validacion.
- NO_VIABLE: el cultivo queda descartado o muy debilitado por factores limitantes.

## 5. Reglas usadas por cultivo

Todos los cultivos comparten 12 criterios base:

| Criterio | Grupo | Que representa |
|---|---|---|
| `aptitud_termica` | clima | Temperatura media frente al rango optimo por fase. |
| `riesgo_frio` | clima | Riesgo asociado a temperatura minima o necesidad/ausencia de frio segun cultivo y fase. |
| `riesgo_calor` | clima | Riesgo asociado a temperatura maxima o exceso termico. |
| `disponibilidad_hidrica` | clima/agua | Disponibilidad de agua o precipitacion util. |
| `deficit_hidrico` | clima/agua | Deficit o balance hidrico. Debe revisarse la semantica de direccion. |
| `aptitud_altitudinal` | topografia | Compatibilidad con rango altitudinal del cultivo. |
| `aptitud_topografica` | topografia | Pendiente o condicion topografica. |
| `reaccion_suelo_ph` | suelo | pH del suelo frente al rango optimo. |
| `contenido_arcilla` | suelo | Fraccion arcillosa; se trata como condicion fisica, no como algo que se "corrige" aumentando arcilla. |
| `contenido_arena` | suelo | Fraccion arenosa; se trata como condicion fisica, no como algo que se "corrige" aumentando arena. |
| `carbono_organico_suelo` | suelo | Materia organica/carbono organico disponible. |
| `cobertura_actual_auxiliar` | vegetacion | Cobertura o vigor superficial auxiliar. |

### 5.1 Maiz amarillo duro

Fuentes usadas: SENASA Guia BPA Maiz Amarillo Duro; MIDAGRI ficha tecnica de maiz amarillo duro; SENAMHI clima de maiz amarillo duro en costa central; INIA variedades 605, 609 y 619.

Fases fenologicas y pesos:

| Fase | Duracion ref. dias | Peso |
|---|---:|---:|
| germinacion_emergencia | 15 | 0.08 |
| desarrollo_vegetativo | 45 | 0.22 |
| panojamiento | 12 | 0.15 |
| espigamiento_floracion | 12 | 0.28 |
| llenado_grano_lechoso | 20 | 0.15 |
| llenado_grano_pastoso | 15 | 0.08 |
| madurez_cosecha | 21 | 0.04 |

Importancia relativa de criterios:

| Criterio | Peso |
|---|---:|
| aptitud_termica | 0.14 |
| disponibilidad_hidrica | 0.13 |
| aptitud_altitudinal | 0.13 |
| deficit_hidrico | 0.11 |
| riesgo_calor | 0.09 |
| reaccion_suelo_ph | 0.09 |
| contenido_arcilla | 0.07 |
| riesgo_frio | 0.06 |
| aptitud_topografica | 0.06 |
| contenido_arena | 0.05 |
| carbono_organico_suelo | 0.05 |
| cobertura_actual_auxiliar | 0.02 |

Criterio sensible: altitud. Si queda fuera del rango esperado, el resultado baja.

Lectura: en maiz, el modelo da mucha importancia a floracion, crecimiento vegetativo, temperatura, agua y altitud. Tiene sentido que una brecha termica en panojamiento/floracion pese mas que una brecha en madurez.

### 5.2 Mandarina Murcott

Fuentes usadas: SENASA Guia BPA Mandarina; MIDAGRI/AgroRural guia de cultivo de mandarina; estudio local de W. Murcott en Irrigacion Santa Rosa, Sayan, Lima.

Fases fenologicas y pesos:

| Fase | Duracion ref. dias | Peso |
|---|---:|---:|
| instalacion_establecimiento | 30 | 0.05 |
| brotacion_desarrollo_vegetativo | 45 | 0.12 |
| induccion_floral | 30 | 0.20 |
| floracion | 25 | 0.22 |
| cuajado_fruto | 30 | 0.18 |
| crecimiento_llenado_fruto | 90 | 0.13 |
| maduracion_cosecha | 45 | 0.08 |
| postcosecha | 20 | 0.02 |

Importancia relativa de criterios:

| Criterio | Peso |
|---|---:|
| aptitud_termica | 0.13 |
| disponibilidad_hidrica | 0.12 |
| riesgo_frio | 0.11 |
| aptitud_altitudinal | 0.11 |
| deficit_hidrico | 0.10 |
| riesgo_calor | 0.08 |
| aptitud_topografica | 0.08 |
| reaccion_suelo_ph | 0.07 |
| contenido_arcilla | 0.07 |
| contenido_arena | 0.06 |
| carbono_organico_suelo | 0.05 |
| cobertura_actual_auxiliar | 0.02 |

Criterio sensible: altitud. Si queda fuera del rango esperado, el resultado baja.

Lectura: para mandarina, el modelo prioriza induccion floral, floracion y cuajado. Esto es agronomicamente razonable para un frutal perenne. La recomendacion climatica no deberia hablar de "siembra"; debe hablar de instalacion/renovacion del huerto o manejo fenologico.

### 5.3 Maracuya criolla amarilla

Fuentes usadas: Gerencia Regional Agraria La Libertad - cultivo de maracuya; INIA/MIDAGRI folleto cultivo de maracuya.

Fases fenologicas y pesos:

| Fase | Duracion ref. dias | Peso |
|---|---:|---:|
| vivero_propagacion | 60 | 0.05 |
| trasplante_establecimiento | 30 | 0.06 |
| crecimiento_conduccion | 60 | 0.10 |
| formacion_poda | 30 | 0.08 |
| floracion | 30 | 0.22 |
| polinizacion_fecundacion | 20 | 0.20 |
| crecimiento_fruto | 55 | 0.15 |
| maduracion_cosecha | 20 | 0.08 |
| postcosecha_comercializacion | 15 | 0.03 |
| renovacion_mantenimiento | 30 | 0.03 |

Importancia relativa de criterios:

| Criterio | Peso |
|---|---:|
| aptitud_termica | 0.14 |
| disponibilidad_hidrica | 0.11 |
| aptitud_altitudinal | 0.11 |
| riesgo_calor | 0.10 |
| deficit_hidrico | 0.10 |
| reaccion_suelo_ph | 0.09 |
| contenido_arcilla | 0.09 |
| aptitud_topografica | 0.08 |
| riesgo_frio | 0.07 |
| contenido_arena | 0.06 |
| carbono_organico_suelo | 0.03 |
| cobertura_actual_auxiliar | 0.02 |

Criterios sensibles:

- Altitud.
- Contenido de arcilla, por su relacion con drenaje y riesgo de suelos pesados.

Lectura: maracuya queda muy sensible a floracion, polinizacion/fecundacion y condicion fisica del suelo.

### 5.4 Palta Hass

Fuentes usadas: SENAMHI ficha agroclimatica palto Hass; INIA folleto cultivo de palto; MIDAGRI/AgroRural manual BPA palto.

Fases fenologicas y pesos:

| Fase | Duracion ref. dias | Peso |
|---|---:|---:|
| instalacion_establecimiento | 60 | 0.06 |
| brotacion_foliacion | 45 | 0.08 |
| induccion_floral | 30 | 0.17 |
| floracion | 25 | 0.24 |
| cuajado_fruto | 30 | 0.20 |
| crecimiento_desarrollo_fruto | 90 | 0.14 |
| maduracion_cosecha | 45 | 0.06 |
| postcosecha | 20 | 0.02 |
| renovacion_mantenimiento | 30 | 0.03 |

Importancia relativa de criterios:

| Criterio | Peso |
|---|---:|
| aptitud_termica | 0.15 |
| riesgo_calor | 0.11 |
| deficit_hidrico | 0.11 |
| disponibilidad_hidrica | 0.10 |
| aptitud_topografica | 0.10 |
| contenido_arcilla | 0.09 |
| riesgo_frio | 0.08 |
| aptitud_altitudinal | 0.08 |
| reaccion_suelo_ph | 0.07 |
| contenido_arena | 0.05 |
| carbono_organico_suelo | 0.04 |
| cobertura_actual_auxiliar | 0.02 |

Criterio sensible: contenido de arcilla, por su relacion con drenaje y sanidad radicular.

Lectura: palta queda altamente afectada por suelo fisico. Si el dato de arcilla 1.73 % es correcto, el resultado desfavorable es esperable. Si es un dato estimado o incorrecto, el resultado puede cambiar mucho.

### 5.5 Uva de mesa Sweet Globe

Fuentes usadas: SENAMHI ficha agroclimatica vid; MIDAGRI ficha tecnica de requerimientos agroclimaticos vid; AgroRural/MIDAGRI guia vid; estudio UNALM/ALICIA sobre Sweet Globe; SENASA BPA uva; referencia varietal Bloom Fresh/IFG.

Fases fenologicas y pesos:

| Fase | Duracion ref. dias | Peso |
|---|---:|---:|
| instalacion_establecimiento | 90 | 0.04 |
| reposo_vegetativo | 45 | 0.04 |
| poda_produccion | 20 | 0.06 |
| hinchazon_yemas | 15 | 0.04 |
| brotacion_desarrollo_brotes | 30 | 0.09 |
| aparicion_inflorescencias | 20 | 0.07 |
| floracion | 15 | 0.20 |
| cuajado_fruto | 20 | 0.16 |
| crecimiento_baya | 60 | 0.14 |
| maduracion | 30 | 0.10 |
| cosecha | 15 | 0.03 |
| postcosecha_exportacion | 10 | 0.02 |
| renovacion_mantenimiento | 30 | 0.01 |

Importancia relativa de criterios:

| Criterio | Peso |
|---|---:|
| aptitud_termica | 0.16 |
| riesgo_calor | 0.12 |
| deficit_hidrico | 0.10 |
| disponibilidad_hidrica | 0.09 |
| contenido_arcilla | 0.09 |
| riesgo_frio | 0.08 |
| aptitud_topografica | 0.08 |
| aptitud_altitudinal | 0.07 |
| contenido_arena | 0.07 |
| reaccion_suelo_ph | 0.06 |
| carbono_organico_suelo | 0.06 |
| cobertura_actual_auxiliar | 0.02 |

Criterio sensible: contenido de arcilla, por su relacion con drenaje y riesgo sanitario.

Lectura: la vid queda muy influida por floracion, cuajado, crecimiento de baya, temperatura y textura. La fuente local de Sweet Globe viene de costa norte, por lo que conviene validar si es transferible a esta parcela.

## 6. Resultado comparativo de cultivos

| Orden | Cultivo | Puntaje | Condicion calculada | Categoria | Brechas | Factores limitantes |
|---:|---|---:|---|---|---:|---:|
| 1 | maiz_amarillo_duro | 0.4223 | DEFINITIVO | CONDICIONAL | 51 | 0 |
| 2 | mandarina_murcott | 0.4142 | DEFINITIVO | CONDICIONAL | 52 | 0 |
| - | palta_hass | 0.2358 | DEFINITIVO | NO_VIABLE | 45 | 1 |
| - | maracuya_criolla_amarilla | 0.2309 | DEFINITIVO | NO_VIABLE | 73 | 1 |
| - | uva_de_mesa_sweet_globe | 0.1274 | DEFINITIVO | NO_VIABLE | 76 | 1 |

Lectura principal:

- Maiz amarillo duro queda primero, pero solo como CONDICIONAL.
- Mandarina Murcott queda muy cerca del maiz, tambien CONDICIONAL.
- Palta, maracuya y uva quedan como NO_VIABLE por restricciones fuertes, especialmente suelo fisico y otras brechas repetidas durante el ciclo.
- Las diferencias entre maiz y mandarina son pequenas; no deberian presentarse como conclusion definitiva sin validacion de campo.

## 7. Brechas principales por cultivo

### 7.1 Maiz amarillo duro

Brechas repetidas:

| Criterio | Repeticiones | Valor observado | Limite optimo usado | Interpretacion |
|---|---:|---:|---:|---|
| Indicador hidrico | 7 | 1808.12 | 600.00 | Marcado como brecha alta, pero requiere revisar si el indicador esta bien interpretado. |
| aptitud_topografica | 7 | 4.59 | 4.57 | Brecha minima; validar unidad. |
| reaccion_suelo_ph | 7 | 7.33 | 7.20 | pH ligeramente por encima del optimo. |
| contenido_arcilla | 7 | 1.73 | 15.00 | Muy bajo; condicion fisica relevante. |
| contenido_arena | 7 | 6.40 | 35.00 | Muy bajo; condicion fisica relevante. |
| carbono_organico_suelo | 7 | 0.00 | 10.00 | Muy bajo o dato faltante; requiere laboratorio. |
| cobertura_actual_auxiliar | 7 | 0.048 | 0.05 | Brecha leve. |
| aptitud_termica | 1 | 20.47 C | 22.00 C | Temperatura media baja en panojamiento. |
| riesgo_frio | 1 | 15.96 C | 16.00 C | Practicamente al umbral en espigamiento/floracion. |

Recomendaciones generadas para maiz:

1. Manejo integrado de suelo: validar textura, pH, salinidad, profundidad y materia organica con analisis de suelo; mejorar estructura, drenaje, cobertura, aporte organico y riego. Evidencia: `suelo.md`. Confianza media.
2. Aptitud termica: monitorear temperatura en panojamiento y ajustar manejo cultural/ventana de siembra. Evidencia: `clima_fenologia.md`. Confianza media.
3. Riesgo de frio: proteger en noches frias o ajustar manejo en fases criticas. Evidencia: `clima_fenologia.md`. Confianza media.
4. El indicador hidrico aparece como punto pendiente de revision antes de convertirlo en una recomendacion de riego.

Validacion agronomica sugerida: el bloque de suelo es razonable como recomendacion general. No se debe recomendar "aumentar arena" ni "aumentar arcilla". Para maiz, hablar de fecha o ventana de siembra si puede ser valido, siempre que se fundamente con calendario local y fase reproductiva.

### 7.2 Mandarina Murcott

Brechas repetidas:

| Criterio | Repeticiones | Valor observado | Limite optimo usado | Interpretacion |
|---|---:|---:|---:|---|
| Indicador hidrico | 8 | 1808.12 | 200-600 | Marcado como alto, pero debe revisarse su interpretacion antes de recomendar riego. |
| reaccion_suelo_ph | 8 | 7.33 | 7.00 | pH ligeramente alto para mandarina. |
| contenido_arcilla | 8 | 1.73 | 10.00 | Bajo; condicion fisica importante. |
| contenido_arena | 8 | 6.40 | 25.00 | Bajo; condicion fisica importante. |
| carbono_organico_suelo | 8 | 0.00 | 8.00 | Muy bajo o dato faltante. |
| cobertura_actual_auxiliar | 8 | 0.048 | 0.05 | Brecha leve. |
| Riesgo de calor | 2 | 27.28 C | 28.00 C | La temperatura esta por debajo del limite usado; no deberia interpretarse como exceso de calor sin revisar. |
| aptitud_termica | 1 | 20.47 C | 22.00 C | Temperatura baja en crecimiento/llenado. |
| Riesgo de frio | 1 | 15.96 C | 15.00 C | En induccion floral no debe leerse automaticamente como dano por frio; podria relacionarse con falta de frio inductivo. |

Observacion importante:

Mandarina puede ser un candidato interesante porque su puntaje queda muy cerca del maiz. Sin embargo, requiere revisar con cuidado suelo, disponibilidad de agua y lectura de fases como induccion floral, floracion y cuajado. Al ser un frutal perenne, las recomendaciones no deberian hablar de "calendario de siembra", sino de instalacion del huerto, renovacion o manejo fenologico.

### 7.3 Palta Hass

Resultado: NO_VIABLE, puntaje 0.2358.

Brechas principales:

- `deficit_hidrico` repetido en 9 fases.
- `contenido_arcilla` repetido en 9 fases.
- `contenido_arena` repetido en 9 fases.
- `carbono_organico_suelo` repetido en 9 fases.
- `cobertura_actual_auxiliar` repetido en 9 fases.

Factor limitante:

- Contenido de arcilla: observado 1.73 %, limite usado 10.0 %. El sistema lo toma como una restriccion fuerte.

Lectura: con la textura reportada, el descarte es coherente. Pero si la textura proviene de estimacion secundaria, el resultado debe validarse con laboratorio.

### 7.4 Maracuya criolla amarilla

Resultado: NO_VIABLE, puntaje 0.2309.

Brechas principales:

- `deficit_hidrico` repetido en 10 fases.
- `reaccion_suelo_ph` repetido en 10 fases.
- `contenido_arcilla` repetido en 10 fases.
- `contenido_arena` repetido en 10 fases.
- `carbono_organico_suelo` repetido en 10 fases.
- `cobertura_actual_auxiliar` repetido en 10 fases.
- brechas termicas en varias fases.

Factor limitante:

- Contenido de arcilla: observado 1.73 %, limite usado 8.0 %. El sistema lo toma como una restriccion fuerte.

Lectura: el descarte esta dominado por suelo fisico y clima/fases. Requiere confirmar si el dato de arcilla es real.

### 7.5 Uva de mesa Sweet Globe

Resultado: NO_VIABLE, puntaje 0.1274.

Brechas principales:

- `deficit_hidrico` repetido en 13 fases.
- `contenido_arcilla` repetido en 13 fases.
- `contenido_arena` repetido en 13 fases.
- `carbono_organico_suelo` repetido en 13 fases.
- `cobertura_actual_auxiliar` repetido en 13 fases.
- `riesgo_calor`, `aptitud_termica` y `riesgo_frio` en fases especificas.

Factor limitante:

- Contenido de arcilla: observado 1.73 %, limite usado 8.0 %. El sistema lo toma como una restriccion fuerte.

Lectura: la vid Sweet Globe queda muy castigada por textura y carbono. Ademas, la fuente varietal local no es exactamente de la misma zona, por lo que conviene validar si los rangos usados aplican bien a costa central.

## 8. Puntos que deberia validar

### 8.1 Validacion de datos de suelo

Preguntas:

- El valor de arcilla 1.73 % es plausible para la parcela?
- El valor de arena 6.40 % es plausible?
- El carbono organico 0.00 indica realmente cero, dato faltante o estimacion incorrecta?
- El pH 7.33 coincide con la experiencia local?
- Se cuenta con CE/salinidad, profundidad efectiva, pedregosidad, drenaje e infiltracion?

Recomendacion: antes de tomar decisiones productivas, realizar analisis fisico-quimico de suelo por lote o sublote.

### 8.2 Validacion del indicador hidrico

El indicador hidrico aparece con valor observado 1808.12 y genera dudas de interpretacion:

- Si es deficit, estar por encima deberia representar mayor restriccion.
- Si es disponibilidad o acumulado, podria estar mal nombrada.
- Si es balance hidrico, se debe revisar el signo.

Recomendacion: validar que este indicador represente realmente deficit, disponibilidad o balance hidrico antes de usarlo para decisiones de riego.

### 8.3 Validacion de fases fenologicas

Las fases si afectan la evaluacion porque cada fase tiene peso distinto. Por ejemplo:

- Maiz: espigamiento/floracion pesa 0.28, por lo que una brecha en esa etapa impacta mas.
- Mandarina: floracion pesa 0.22, induccion floral 0.20 y cuajado 0.18.
- Uva: floracion 0.20, cuajado 0.16 y crecimiento de baya 0.14.

Preguntas:

- Los pesos por fase reflejan la realidad productiva local?
- Para cultivos perennes, se esta usando correctamente ciclo anual de produccion y no logica de siembra?
- La induccion floral de mandarina esta correctamente representada?

### 8.4 Validacion de factores criticos

Preguntas:

- Es correcto que palta, maracuya y uva se vean tan afectadas por el contenido de arcilla?
- La altitud deberia ser critica para maiz y mandarina en esta zona?
- Conviene que pH/textura/carbono se repitan por fase, o deberian evaluarse una sola vez como condicion estatica del sitio?

Observacion: actualmente los criterios fijos de suelo se repiten por fase. Eso ayuda a que impacten en todo el ciclo, pero tambien puede exagerar su efecto si no se calibra bien.

### 8.5 Validacion de recomendaciones

Puntos positivos:

- Maiz ya tiene recomendaciones visibles compactas.
- Se agrupan brechas de suelo en una recomendacion integrada.
- Se evita recomendar "aumentar arena" o "aumentar arcilla" como accion directa.
- El indicador hidrico queda como punto pendiente de revision.

Puntos pendientes:

- En mandarina todavia hay recomendaciones que deben revisarse antes de mostrarse como recomendacion final.
- Algunas fuentes usadas como respaldo son generales y no siempre apuntan directamente a la brecha.
- Falta mejorar la referencia a pagina o seccion en algunos documentos.
- Para mandarina, se debe cuidar la interpretacion de frio y calor durante induccion floral y desarrollo.

## 9. Conclusion para discutir

La salida actual es util para una validacion tecnica inicial. El orden obtenido sugiere:

1. Maiz amarillo duro como mejor candidato, pero condicionado.
2. Mandarina Murcott como segundo candidato, muy cercano al maiz y tambien condicionado.
3. Palta, maracuya y uva quedan no viables bajo los datos actuales, principalmente por restricciones de suelo fisico.

La conclusion agronomica no deberia ser "sembrar maiz" o "instalar mandarina" todavia. Una conclusion mas responsable seria:

> Bajo los datos actuales, Parcela Humalla - Sector Izquierdo muestra aptitud condicionada para maiz amarillo duro y mandarina Murcott. La decision final depende de validar textura, materia organica, pH, salinidad, profundidad efectiva, drenaje y disponibilidad real de agua. Los resultados de palta, maracuya y uva parecen fuertemente afectados por la textura reportada, por lo que el descarte debe confirmarse con analisis de suelo.
