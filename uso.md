# Guia de uso de Agent Harness

Agent Harness es una CLI local para coordinar tareas de desarrollo con un flujo
controlado por fases, estado persistente, reglas de arquitectura, hooks, sandbox
y registro de decisiones.

La idea central es simple: cada trabajo se registra como una tarea, avanza por
fases explicitas y solo se cierra cuando paso las verificaciones requeridas.

## 1. Requisitos

- Python 3.11 o superior.
- pip.
- Git, si quieres usar la politica de commits al cerrar tareas.

Instala el paquete en modo editable desde la raiz del repositorio:

```bash
pip install -e .
```

Si el comando `harness` no queda disponible en Windows, usa:

```bash
python -m harness.cli --help
```

## 2. Inicializar un workspace

Ejecuta:

```bash
harness init
```

Esto crea los archivos base si no existen:

- `.harness/config.yml`: configuracion general del harness.
- `.harness/context.yml`: archivos y limites de contexto por nivel.
- `.harness/hooks.yml`: hooks configurables.
- `.harness/architecture-rules.yml`: reglas verificables de arquitectura.
- `AGENTS.md`: memoria operativa para agentes.

Puedes inicializar otro directorio con:

```bash
harness --repo ruta/al/proyecto init
```

## 3. Crear una tarea

El comando base es:

```bash
harness task create --title "Implementar validacion" --type code_change
```

Tambien puedes agregar descripcion y criterios de aceptacion:

```bash
harness task create \
  --title "Documentar uso del harness" \
  --description "Crear una guia para operadores locales" \
  --type documentation \
  --acceptance "Incluye instalacion" \
  --acceptance "Incluye flujo por fases"
```

El comando imprime un JSON con el `task_id`, por ejemplo:

```json
{
  "task_id": "task-20260505-1a2b3c4d",
  "phase": "INVESTIGAR",
  "status": "ACTIVA"
}
```

El estado queda guardado en:

```text
.harness/tasks/<task_id>/state.json
```

## 4. Consultar estado

```bash
harness task status task-20260505-1a2b3c4d
```

La salida es el estado persistido de la tarea: especificacion, fase actual,
estado, fechas y si quedo algun commit pendiente.

## 5. Avanzar por fases

El flujo permitido es:

```text
INVESTIGAR -> PLANIFICAR -> EJECUTAR -> VERIFICAR -> CERRAR
```

Tambien puedes volver desde:

- `EJECUTAR` a `PLANIFICAR`.
- `VERIFICAR` a `EJECUTAR`.

Ejemplo:

```bash
harness task transition task-20260505-1a2b3c4d PLANIFICAR
harness task transition task-20260505-1a2b3c4d EJECUTAR
harness task transition task-20260505-1a2b3c4d VERIFICAR
harness task transition task-20260505-1a2b3c4d CERRAR
```

Cada transicion queda registrada en:

```text
.harness/tasks/<task_id>/transitions.jsonl
```

## 6. Tipos de tarea y precondiciones de cierre

El tipo de tarea define que evidencias debe tener el registro de decisiones antes
de cerrar.

### `code_change`

Antes de pasar a `VERIFICAR`, debe existir una decision exitosa de `apply_patch`.

Antes de `CERRAR`, debe existir:

- una decision exitosa de `run_tests`;
- una decision exitosa de `validate_architecture`;
- ninguna violacion arquitectonica con severidad `error`.

### `analysis`

Antes de `CERRAR`, debe existir una decision exitosa de `read_file` o
`search_repo`.

### `documentation`

Antes de `CERRAR`, debe existir una decision exitosa de `apply_patch` que haya
modificado un archivo `.md`, `.rst` o `.txt`.

## 7. Ejecutar tests

Suite completa:

```bash
harness test
```

Suite rapida sin tests marcados como `slow`:

```bash
harness test --quick
```

Equivalentes directos con pytest:

```bash
python -m pytest
python -m pytest -m "not slow"
python -m pytest tests/property
```

## 8. Validar arquitectura

La validacion arquitectonica usa `.harness/architecture-rules.yml`.

Actualmente las reglas soportadas incluyen:

- `forbidden_import`: detecta imports prohibidos en archivos que cumplen un
  patron.
- `min_coverage`: valida umbrales de cobertura cuando existe cobertura provista.

La herramienta interna `validate_architecture` busca cobertura en:

```text
.harness/coverage.json
```

Tambien acepta cobertura como parametro cuando se invoca desde codigo.

## 9. Analisis de entropia

Ejecuta:

```bash
harness entropy
```

El analizador revisa:

- codigo potencialmente muerto;
- documentacion posiblemente desactualizada;
- archivos temporales;
- sugerencias para `AGENTS.md`.

El reporte se guarda en:

```text
.harness/entropy-report.md
```

Por defecto, `entropy.auto_cleanup` esta en `false`, asi que el harness reporta
candidatos pero no los elimina automaticamente.

## 10. Configuracion principal

El archivo `.harness/config.yml` controla valores como:

- `git.commit_policy`: politica de commits. Por defecto, `on_close`.
- `sandbox.mode`: modo de sandbox. El MVP usa `project_write`.
- `sandbox.timeout_seconds`: timeout por defecto.
- `subagents.parallel_execution`: en el MVP local esta en `false`.
- `entropy.auto_cleanup`: si el analizador puede limpiar automaticamente.
- `entropy.analysis_interval_tasks`: cada cuantas tareas cerradas se ejecuta
  analisis automatico.

## 11. Hooks

Los hooks se configuran en:

```text
.harness/hooks.yml
```

Eventos soportados por el modelo:

- `on_code_edited`
- `on_task_close`
- `on_tests_failed`
- `on_docs_modified`
- `on_architecture_violation`
- `on_agents_md_modified`

Cada hook define comando, politica (`warn` o `block`) y timeout.

## 12. Registro de decisiones

Las herramientas del harness escriben evidencias en:

```text
.harness/tasks/<task_id>/decisions.jsonl
```

Cada entrada registra:

- accion;
- justificacion;
- herramienta usada;
- parametros;
- resultado.

Las herramientas `apply_patch`, `run_command` y `run_tests` requieren
justificacion explicita cuando se invocan desde el registro de herramientas.

## 13. Flujo recomendado diario

1. Inicializa el proyecto una vez:

```bash
harness init
```

2. Crea una tarea:

```bash
harness task create --title "Cambio pequeno" --type code_change
```

3. Investiga y planifica antes de editar.

4. Avanza la tarea:

```bash
harness task transition <task_id> PLANIFICAR
harness task transition <task_id> EJECUTAR
```

5. Implementa el cambio usando las herramientas del harness.

6. Pasa a verificacion:

```bash
harness task transition <task_id> VERIFICAR
```

7. Ejecuta tests y validacion arquitectonica.

```bash
harness test --quick
harness test
```

8. Cierra solo cuando no haya errores bloqueantes:

```bash
harness task transition <task_id> CERRAR
```

Con `git.commit_policy: on_close`, el cierre intenta crear un commit con mensaje:

```text
[<task_id>] close task
```

Si el commit falla, la tarea queda con `pending_commit: true`.

## 14. Problemas frecuentes

### `harness` no se reconoce como comando

Usa:

```bash
python -m harness.cli --help
```

O agrega el directorio `Scripts` de tu instalacion de Python al `PATH`.

### Una transicion falla por "invalid transition"

Revisa la fase actual:

```bash
harness task status <task_id>
```

Luego transiciona solo a una fase permitida desde esa fase.

### Una tarea `code_change` no pasa a `VERIFICAR`

El workflow requiere que haya una decision exitosa de `apply_patch` para esa
tarea. Si editaste fuera del mecanismo de herramientas, el harness no tiene la
evidencia necesaria.

### Una tarea no cierra

Revisa el mensaje de error. Para `code_change`, normalmente falta registrar
`run_tests`, falta `validate_architecture` o hay violaciones con severidad
`error`.
