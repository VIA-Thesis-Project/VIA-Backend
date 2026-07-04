# Cambio de contrato API — Autenticación en evaluaciones y recomendaciones

> **Fecha:** 2026-07-03 · **Sprint 0, tarea T0.1** · **Impacta a:** VIA-Frontend
> **Estado:** aplicado en backend (rama `develop`)

## Resumen

Los endpoints de evaluaciones y recomendaciones ahora **requieren autenticación
Bearer JWT** (el mismo token que ya usa el resto del API). Además, el campo
`requested_by` **fue eliminado del body** de `POST /evaluaciones`: el backend
lo toma del usuario autenticado del token.

## Endpoints afectados

Todos requieren ahora header `Authorization: Bearer <access_token>`:

| Método | Endpoint | Cambio adicional |
|---|---|---|
| POST | `/evaluaciones` | **Body: se eliminó `requested_by`** (ver abajo) |
| GET | `/evaluaciones/{id}/estado` | Solo auth |
| GET | `/evaluaciones/{id}/resultado-mcda` | Solo auth |
| GET | `/evaluaciones/{id}/vector-agroambiental` | Solo auth |
| GET | `/recomendaciones/{recommendation_id}` | Solo auth |
| GET | `/evaluaciones/{id}/recomendaciones` | Solo auth |
| GET | `/evaluaciones/{id}/recomendacion-final` | Solo auth |

## Cambio de body en POST /evaluaciones

**Antes:**

```json
{
  "parcel_id": "…",
  "requested_by": "…",        // ← el cliente se auto-identificaba
  "crop_candidates": ["maiz_amarillo_duro"],
  "temporal_window": {"start_date": "2026-01-01", "end_date": "2026-06-30"}
}
```

**Ahora:**

```json
{
  "parcel_id": "…",
  "crop_candidates": ["maiz_amarillo_duro"],
  "temporal_window": {"start_date": "2026-01-01", "end_date": "2026-06-30"}
}
```

`requested_by` se deriva del claim `sub` del access token emitido por
`POST /auth/login`. El frontend **no debe enviar** el campo. (Si lo envía,
Pydantic lo ignora, pero debe removerse para no confundir.)

## Respuestas de error nuevas

| Caso | Status | Body |
|---|---|---|
| Sin header `Authorization` | **401** | `{"detail": "Not authenticated"}` + header `WWW-Authenticate: Bearer` |
| Token inválido/expirado | **401** | `{"detail": "Invalid authentication credentials"}` |
| Rol sin permiso para iniciar evaluación | **403** | `{"detail": "Insufficient permissions"}` |

Nota: antes de este cambio, un request sin header devolvía 403 en los routers
protegidos (comportamiento por defecto de HTTPBearer). Ahora **todos** los
routers devuelven 401 consistentemente cuando falta el token (parcelas,
rulebooks y documentos incluidos).

## Roles

- `POST /evaluaciones`: permitido para `ADMINISTRADOR` y `USUARIO_AGRICOLA`
  (mismo criterio que parcelas: se evalúa sobre parcelas propias).
  `ESPECIALISTA_TECNICO` recibe 403.
- Endpoints GET (estado, resultados, recomendaciones): cualquier usuario
  autenticado, sin restricción de rol.

## Qué debe cambiar el frontend

1. Adjuntar el Bearer token en **todas** las llamadas a `/evaluaciones*` y
   `/recomendaciones*` (interceptor HTTP compartido con parcelas).
2. Eliminar `requested_by` del payload de creación de evaluación.
3. Manejar 401 en estas rutas (redirigir a login / refrescar sesión) y 403
   en el POST (usuario con rol especialista).

## Limitación conocida (documentada, no incluida en este cambio)

El backend aún **no verifica que la parcela pertenezca al usuario** que inicia
la evaluación (chequeo de ownership cross-BC). Queda planificado para un
sprint posterior.
