"""Event type names consumed and emitted by the evaluation Process Manager."""

from __future__ import annotations


VECTOR_AGROAMBIENTAL_GENERADO = "VectorAgroambientalGenerado"
EVALUACION_VIABILIDAD_COMPLETADA = "EvaluacionViabilidadCompletada"
VECTOR_BRECHAS_GENERADO = "VectorBrechasGenerado"
RECOMENDACION_SUSTENTADA_GENERADA = "RecomendacionSustentadaGenerada"
RECOMENDACION_GENERADA = "RecomendacionGenerada"
EVALUACION_FINALIZADA = "EvaluacionFinalizada"
EXTRACCION_FALLIDA = "ExtraccionFallida"
EVALUACION_VIABILIDAD_FALLIDA = "EvaluacionViabilidadFallida"
RECOMENDACION_SUSTENTADA_FALLIDA = "RecomendacionSustentadaFallida"
RECOMENDACION_FALLIDA = "RecomendacionFallida"

FAILURE_EVENTS = {
    EXTRACCION_FALLIDA,
    EVALUACION_VIABILIDAD_FALLIDA,
    RECOMENDACION_SUSTENTADA_FALLIDA,
    RECOMENDACION_FALLIDA,
}
