# AGENTS.md - Memoria Operativa del Proyecto

## Reglas

- Todo cambio de codigo debe pasar los tests antes de cerrar la tarea.
- No modificar archivos fuera del directorio de trabajo de la tarea activa.
- Registrar justificacion antes de invocar cualquier herramienta destructiva.
- Proponer actualizacion de AGENTS.md al detectar un patron de error por tercera vez.

## Convenciones

- Nombres de variables en snake_case (Python) o camelCase (TypeScript).
- Commits en formato: `[task_id] tipo: descripcion breve`.
- Documentar toda funcion publica con docstring o JSDoc.

## Arquitectura

- Separacion estricta entre capa de dominio, infraestructura y presentacion.
- Las herramientas del Harness son la unica interfaz permitida para modificar el repositorio.
- Ver `.harness/architecture-rules.yml` para reglas verificables automaticamente.

## Herramientas

- `read_file`: lectura de archivos con rango de lineas opcional.
- `search_repo`: busqueda regex en el repositorio.
- `apply_patch`: aplicacion atomica de diffs.
- `run_command`: ejecucion de comandos en sandbox.
- `run_tests`: ejecucion de la suite de tests.
- `validate_architecture`: validacion de reglas arquitectonicas.

## Flujo_de_Trabajo

INVESTIGAR -> PLANIFICAR -> EJECUTAR -> VERIFICAR -> CERRAR

Cada fase debe completarse antes de avanzar a la siguiente.
VERIFICAR requiere run_tests y validate_architecture sin errores bloqueantes.

## Criterios_de_Verificación

- Todos los tests pasan (exit code 0).
- Sin violaciones arquitectonicas de severidad `error`.
- Cobertura de tests no decrece respecto al estado anterior.

## Restricciones

- No ejecutar comandos con privilegios de root en el sandbox.
- No acceder a URLs externas sin aprobacion explicita del operador.
- No eliminar archivos sin registrar la accion en el Registro_de_Decisiones.

## Historial_de_Cambios

| Fecha | Cambio | Tarea |
|-------|--------|-------|
| 2026-05-05 | Creacion inicial | - |
