# roclec-spec-kit

Framework configurable para gestionar specs, tareas y releases de proyectos de software. El paquete proporciona la CLI y dos skills de agentes; cada proyecto conserva su configuración, producto, decisiones, specs y versiones en Git.

**Estado:** versión inicial `0.1.0` para uso interno. Requiere Python 3.11 o posterior. No necesita servicios ni dependencias de ejecución externas.

## Instalar dentro de un proyecto

En un entorno virtual del proyecto consumidor:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e /ruta/a/roclec-spec-kit
.venv/bin/roclec init . --name "Mi proyecto" --component app=.
.venv/bin/roclec check
```

La instalación editable sirve para desarrollar el kit. Para un equipo, fija una versión del paquete desde un tag Git privado en las dependencias del proyecto y usa esa misma versión en CI. El proyecto consumidor guarda `.roclec/project.toml`, `specs/`, `roadmap/`, `FUTURE.md` y las skills instaladas bajo `.agents/skills/` y `.claude/skills/`. `init` conserva los archivos existentes y se niega a sobrescribir un perfil ya creado.

Si usas [spec-kit](https://github.com/github/spec-kit), inicialízalo en el proyecto y luego instala el preset y la extensión que vienen dentro del paquete. En un proyecto nuevo, ejecuta `specify init` antes de `roclec init`; en uno existente, revisa la combinación de archivos que propone spec-kit:

```bash
specify init --here --integration codex
roclec speckit
```

El preset aporta plantillas genéricas de spec, plan y tareas. La extensión añade sincronización, UX, prototipo, ready gate y releases. Tras actualizar `roclec-spec-kit`, vuelve a ejecutar `roclec speckit` para actualizar esos comandos instalados.

Para varios componentes o repositorios:

```bash
roclec init . --name "Mi producto" \
  --component api=../mi-api \
  --component web=../mi-web --user-facing web
```

Las rutas `repo` son relativas a la raíz que contiene `.roclec/project.toml`. El repositorio de specs puede ser el mismo repositorio de código o uno hermano. Desde otro directorio, pasa `--project` antes del subcomando:

```bash
roclec --project ../mi-producto-specs check --release-gate 001
```

El perfil creado es TOML estándar:

```toml
schema = 1
name = "Mi producto"

[components.api]
repo = "../mi-api"
user_facing = false

[components.web]
repo = "../mi-web"
user_facing = true
```

`user_facing = true` exige `ux.md` y un prototipo HTML antes de que una spec esté `ready`. Cada componente se versiona de forma independiente. Las reglas de dominio, seguridad y contratos se escriben en la constitución del proyecto; no están codificadas en el kit.

## Flujo

```text
idea → draft spec → aclaración/UX → ready gate → plan y tareas
     → asignación de release por componente → release gate
     → implementación y pruebas → done → publicación → cierre del release
```

Comandos principales, ejecutados desde la raíz del proyecto:

```bash
roclec new 001-mi-funcion --title "Mi función" --component api
roclec check --gate 001
roclec release plan api v0.1 001 --title "Primer release"
roclec check --release-gate 001
roclec check --write
roclec check --coverage
roclec release close api v0.1
roclec skills
```

`new` crea un borrador; se editan sus criterios y artefactos antes de cambiarlo a `ready`. `release plan` selecciona explícitamente las specs para una versión. La pertenencia al release solo vive en `roadmap/releases/<component>/vX.Y.md`; el roadmap y cada `INDEX.md` se regeneran con `check --write`. `in-progress` y `done` requieren plan, tareas y una asignación por cada componente. `done` requiere tareas cerradas. `release close` requiere todas las specs en `done` y notas de release escritas; el archivo publicado queda inmutable y debe protegerse en CI.

Las ideas aún no comprometidas viven en `FUTURE.md` con encabezados `## FUT-NNN`. Al promover o descartar una idea, retírala de allí y registra su ID en `roadmap/fut-archive.md`; no reutilices IDs. La spec promovida conserva `origin: FUT-NNN`.

Para verificar la inmutabilidad frente a la rama base:

```bash
roclec check --immutable-base origin/main
```

La cobertura busca referencias `[NNN/AC-NN]` en archivos de pruebas de los repositorios configurados. Usa `roclec check --coverage` cuando estén presentes. No sustituye la ejecución de las pruebas propias de cada componente.

## Agentes y CI

`roclec init` instala `roclec-coordinator` y `roclec-implement` en `.agents/skills/` y `.claude/skills/`. Tras actualizar el paquete, `roclec skills` sincroniza únicamente esos archivos administrados. Las skills leen el perfil y las instrucciones propias del proyecto.

En un repositorio de código separado, puedes instalar las mismas skills allí sin duplicar las specs:

```bash
roclec --project ../mi-producto-specs skills --into ../mi-api
```

Esto crea `.roclec/link.toml` en el repo de código, apuntando al perfil del repositorio de specs. Desde allí, `roclec check` encuentra el proyecto sin pasar `--project`. El link y las skills pueden guardarse en Git; no duplican las specs. La carpeta de specs necesita estar accesible para los cambios de tareas y estados que produzca la implementación.

Ejemplo mínimo de CI desde la raíz del proyecto, después de instalar su versión fijada del paquete:

```bash
roclec check
roclec check --immutable-base "$BASE_REF"
```

Usa `roclec check --write` localmente y confirma los archivos generados antes de la PR. `check` sin `--write` falla si están desactualizados.

## Alcance de esta primera versión

El kit aporta validación, proyecciones, skills y un preset/extensión de spec-kit. Los comandos de agentes guían las etapas de redacción, UX e implementación; la CLI no genera por sí sola esos entregables. Cada proyecto consumidor mantiene sus propias reglas de dominio y puede migrar sus datos por separado.
