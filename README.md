# roclec-spec-kit

[English](#english) · [Español](#español)

## English

Roclec Spec Kit is a local framework for capability contracts, traceable changes, and per-component releases. Consumer projects own their files in Git. Roclec checks relationships, revisions, and decisions and works with any project stack. GitHub spec-kit is optional.

**Status:** `0.9.0.dev0`. The first native cut (Milestone 01, `0.8.0`) was implemented and verified locally. Milestone 02 has recorded technical verification for F0–F3. Closing `0.9.0` still requires a real change to go through approval, verification, and integration in the pilot (F4). [Global plan (Spanish)](docs/strategy/plan-global.md#13-hito-02)

### Requirements and compatibility

Python 3.11 or later and Git. The native CLI uses **profile 3 and model schema 2**. Projects using profile 1 or 2 require the corresponding earlier wheel. Profile 3 uses a project-wide `trunk_ref` and a `target_ref` for each component. Administrative writes are restricted to the trunk and return `OFF_TRUNK` on other branches. `change start` requires an explicit `--actor`.

### Install Roclec in your project

1. **Get the wheel.** If you already have it, set `ROCLEC_WHEEL="/absolute/path/to/the.whl"`. To build it with `uv`, run the following from the Roclec Spec Kit checkout.

   ```bash
   uv build
   ROCLEC_WHEEL="$PWD/dist/roclec_spec_kit-0.9.0.dev0-py3-none-any.whl"
   ```

2. **Install the CLI in the consumer project.** Open a terminal at its root and keep using the same shell. If the directory is new, run `git init -b main` first. Use your existing `.venv` if you have one.

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install "$ROCLEC_WHEEL"
   ```

3. **Configure and initialize Roclec.** Save a copy of the example as `profile.toml` and adapt it to your project. Set `trunk_ref` to the local branch that manages specs. For each component, configure its repo, input and generated paths, and verification commands. Set `user_facing` according to whether the component has a UI, and `target_ref` to the remote-tracking branch where its code is integrated. Run `init` from the configured trunk. [Example profile](docs/examples/c1/profile.toml)

   ```bash
   .venv/bin/roclec --json init . --profile profile.toml
   ```

4. **Install and check the native skills.** Run these commands from the consumer root. For a separate code repo already configured as a component, you can also run `.venv/bin/roclec --json skills --into COMPONENT` from the consumer root. [Installation details (Spanish)](docs/c3.md#instalación-nativa-y-aliases)

   ```bash
   .venv/bin/roclec --json skills
   ./.roclec/run --json check
   ```

5. **Open the project in Codex or Claude Code.** The installed `AGENTS.md` and `CLAUDE.md` instructions point the agent to the coordinator. To update an existing profile-3 project, install the new wheel in its environment and rerun `skills` to refresh the managed files.

#### Native skills installed by Roclec

`roclec skills` installs these 17 skills in both `.agents/skills/` and `.claude/skills/`.

| Use | Skills |
| --- | --- |
| Start or resume work | `roclec-coordinator` |
| Set project context and principles | `roclec-foundation`, `roclec-constitution` |
| Capture, define, clarify, or amend a change | `roclec-idea`, `roclec-specify`, `roclec-clarify`, `roclec-amend` |
| Design and prototype | `roclec-ux`, `roclec-prototype` |
| Plan and review requirements and tasks | `roclec-plan`, `roclec-tasks`, `roclec-checklist`, `roclec-analyze` |
| Implement, review, and integrate | `roclec-implement`, `roclec-reviewer`, `roclec-converge` |
| Plan and prepare releases | `roclec-release` |

#### Agent roles installed by Roclec

`roclec skills` also installs three subagent roles for Claude Code (`.claude/agents/`) and Codex (`.codex/agents/`). They are generated from host- and model-neutral contracts. The coordinator runs in your own session and delegates bounded stages to them.

| Role | Skills it loads | Returns |
| --- | --- | --- |
| `roclec-specifier` | `roclec-specify`, `roclec-clarify`, `roclec-analyze`, `roclec-checklist` | A sealed change bundle and open questions; never approves |
| `roclec-implementer` | `roclec-plan`, `roclec-tasks`, `roclec-implement` | A candidate and a verification run for one component |
| `roclec-reviewer` | `roclec-reviewer` | Review evidence from a context separate from the implementation |

Each role inherits the session's model unless the profile pins one per host with `[agents.<role>]`. Codex loads project roles only in a trusted project. Your own roles in those folders are left untouched. [Roles, files and model pinning (Spanish)](docs/c3.md#roles-de-agente)

#### Optional external design skills

Roclec ships a suggested lockfile for projects with a UI. Profile 3 restores the entries from the consumer's own `skills-lock.json`. If your project has no lockfile and you want the suggested set, review the file and save a copy as `skills-lock.json` in the consumer root. Keep your existing lockfile if you already manage these dependencies. [Suggested design lockfile](src/roclec_spec_kit/assets/profiles/design-skills-lock.json)

| Skill | Source repository |
| --- | --- |
| `design-lab` | `0xdesign/design-plugin` |
| `design-taste-frontend` | `Leonxlnx/taste-skill` |
| `frontend-design` | `anthropics/skills` |
| `impeccable` | `pbakaus/impeccable` |
| `ui-ux-pro-max` | `nextlevelbuilder/ui-ux-pro-max-skill` |
| `web-design-guidelines` | `vercel-labs/agent-skills` |

The full suggested lockfile currently fails to restore because the sources for `design-taste-frontend`, `impeccable`, and `ui-ux-pro-max` have changed. `design-lab`, `frontend-design`, and `web-design-guidelines` restored successfully in a project lockfile containing only those three entries. If you want that subset, keep their original entries and hashes in your project copy.

With Node.js and `npx` available, run the following from the consumer root. Roclec verifies the downloaded files against the lockfile hashes before installing them for both agents. A linked code repo uses its own lockfile when you pass `--into COMPONENT`.

```bash
./.roclec/run --json skills --restore
```

For optional GitHub spec-kit aliases, initialize the desired spec-kit integration first, then run `./.roclec/run --json speckit`. The aliases use the same native skills. [Adapter setup (Spanish)](docs/c3.md#instalación-nativa-y-aliases)

### Start or resume a change in chat

Open the initialized project in Codex or Claude Code and describe the work in plain language.

> Roclec, add the ability to filter records by date and take the change through integration.

In a later chat, use the change ID or a clear description to resume.

> Roclec, resume the date filter change and take it through integration.

The installed project instructions route the request to `roclec-coordinator`. It finds or drafts the change, selects the relevant skills and runs the CLI steps itself, delegating larger specification, implementation and review stages to the installed roles when the host supports subagents. It handles planning, implementation, verification and integration within the requested scope and the project's Git policy. It asks when a decision or evidence is missing, such as approval of a specific proposal or an unresolved release assignment. Once you respond, it continues from the recorded state. To see progress only, ask “What is the status of this change?”.

Use this flow in trusted repositories. Verification runs commands defined in the profile. Full local logs can contain secrets, and optional committed excerpts redact configured values and patterns. [Verification and logs (Spanish)](docs/c2.md)

For the full workflow and SVG diagram, see the [Roclec workflow guide (Spanish)](docs/flujo-roclec.md).

For direct CLI use, see [definition and queries](docs/c1.md), [verification and integration](docs/c2.md), and [release preparation and installation](docs/c3.md). These references are in Spanish.

### What works

- Foundation references and a contract index by component and capability. Query current and historical revisions, with SHA-256 validation of snapshots and Markdown.
- Draft changes with explicit bases and deltas, approval of intent, per-component release assignment and start, and cancellation. Requirement IDs keep immutable revisions, and changes in behavior get new acceptance criteria IDs. Reserved IDs are permanent.
- Change origins with captured source text and structural coverage of source criteria by acceptance criteria. Capture only necessary text and redact personal data before sealing. `inspect --change ID` shows the records and `list changes --origin ID` finds related changes.
- Discovery items (FUTs) with provenance, decisions, promotion, and duplicate tracking. Release planning enforces unique membership and versioning rules.
- Generated contract views, protection of project-owned files, operation receipts, conflict detection, and recovery from interrupted local writes. JSON output and structured errors support automation.
- Input-based candidates, path classification, direct command execution, bounded local logs, and explicit coverage by acceptance criterion. Manual or external observations and optional independent review support per-component verification gates. When review is required, a passing run must be accompanied by a current favorable report.
- Per-component integration with a clean final candidate, reconstructed plans, idempotent receipts, and recovery.
- Release verification against the final combined contract, immutable release preparation, and inclusion checks for fixes and backports. Git publication records verify local and remote commits and tags, including annotated tags. Tag creation, pushing, and deployment are separate operations.
- Install or refresh native skills, agent roles and optional spec-kit aliases for Codex and Claude while preserving project-owned templates, principles and roles. A refresh removes files Roclec no longer ships and refuses to overwrite managed files you edited.
- Architecture decision records (ADR) as project-owned Markdown registered with role `decision`, with derived state (proposed, accepted, stale, superseded) and supersession. Each change declares the ADRs it applies, pinned at approval, or none with a reason; implementation is blocked while a cited ADR is not accepted. [ADRs (Spanish)](docs/c1.md#decisiones-de-arquitectura-adr)
- Runs record the role and context that produced them, and the review gate rejects a review that declares the same context as the run it reviews.
- Optional local viewer: `pip install 'roclec-spec-kit[viewer]'` then `roclec view` opens a read-only browser view of releases, changes, requirements, evidence and project Markdown. The gate shown matches `check --gate release`. [Viewer guide (Spanish)](docs/visor.md)

### Validate the package

From the Roclec Spec Kit checkout:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
uv build
python3 scripts/harness.py --wheel dist/roclec_spec_kit-0.9.0.dev0-py3-none-any.whl --report /tmp/roclec-checks.json
python3 scripts/harness.py --wheel dist/roclec_spec_kit-0.9.0.dev0-py3-none-any.whl --report /tmp/roclec-compat.json --spec-kit
```

The harness installs the wheel in an isolated environment, clears `PYTHONPATH` and `PYTHONHOME` from subprocesses, and checks successful operations and expected rejections with synthetic consumers and disposable Git remotes. `--spec-kit` also checks the optional adapter for Codex and Claude and runs separate legacy regression checks. [Harness](docs/harness.md) · [C3 evidence (Spanish)](docs/implementation/c3.md)

The package and adapter share `__version__`. Regular releases increment the major or minor version and reset lower version numbers. Hotfix and bugfix releases increment only the patch version and contain fixes. The project uses MIT and preserves attribution for methods adapted from GitHub spec-kit. [License](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)

## Español

Roclec Spec Kit es un framework local para contratos por capacidad, cambios trazables y releases por componente. Cada proyecto consumidor mantiene sus archivos en Git. Roclec comprueba relaciones, revisiones y decisiones y funciona con cualquier stack. GitHub spec-kit es opcional.

**Estado:** `0.9.0.dev0`. El primer corte nativo (Hito 01, `0.8.0`) se implementó y verificó localmente. El Hito 02 tiene evidencia técnica registrada para F0–F3. Para cerrar `0.9.0` falta que un cambio real del piloto recorra aprobación, verificación e integración (F4). [Plan global](docs/strategy/plan-global.md#13-hito-02)

### Requisitos y compatibilidad

Python 3.11 o posterior y Git. La CLI nativa usa **perfil 3 y esquema de modelo 2**. Los proyectos con perfil 1 o 2 requieren el wheel anterior correspondiente. El perfil 3 usa un `trunk_ref` global y un `target_ref` por componente. Las escrituras administrativas se restringen a la troncal y devuelven `OFF_TRUNK` en otras ramas. `change start` exige un `--actor` explícito.

### Instalar Roclec en tu proyecto

1. **Consigue el wheel.** Si ya lo tienes, define `ROCLEC_WHEEL="/ruta/absoluta/al.whl"`. Para construirlo con `uv`, ejecuta lo siguiente desde el repositorio de Roclec Spec Kit.

   ```bash
   uv build
   ROCLEC_WHEEL="$PWD/dist/roclec_spec_kit-0.9.0.dev0-py3-none-any.whl"
   ```

2. **Instala la CLI en el proyecto consumidor.** Abre una terminal en su raíz y sigue en la misma sesión. Si el directorio es nuevo, ejecuta primero `git init -b main`. Si ya tienes un entorno `.venv`, úsalo.

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install "$ROCLEC_WHEEL"
   ```

3. **Configura e inicializa Roclec.** Guarda una copia del ejemplo como `profile.toml` y adáptala al proyecto. Define `trunk_ref` como la rama local que administra las specs. Para cada componente, configura su repositorio, las rutas de entrada y de archivos generados, y los comandos de verificación. Configura `user_facing` según tenga interfaz y usa como `target_ref` la referencia de seguimiento remoto de la rama donde se integra su código. Ejecuta `init` desde la troncal configurada. [Perfil de ejemplo](docs/examples/c1/profile.toml)

   ```bash
   .venv/bin/roclec --json init . --profile profile.toml
   ```

4. **Instala y comprueba las skills nativas.** Ejecuta estos comandos desde la raíz del consumidor. Si un componente tiene un repositorio de código separado y ya está configurado en el perfil, también puedes ejecutar `.venv/bin/roclec --json skills --into COMPONENTE` desde esa raíz. [Detalles de instalación](docs/c3.md#instalación-nativa-y-aliases)

   ```bash
   .venv/bin/roclec --json skills
   ./.roclec/run --json check
   ```

5. **Abre el proyecto en Codex o Claude Code.** Las instrucciones instaladas en `AGENTS.md` y `CLAUDE.md` dirigen al agente al coordinador. Para actualizar un proyecto que ya usa perfil 3, instala el nuevo wheel en su entorno y vuelve a ejecutar `skills` para actualizar los archivos administrados.

#### Skills nativas que instala Roclec

`roclec skills` instala estas 17 skills en `.agents/skills/` y `.claude/skills/`.

| Uso | Skills |
| --- | --- |
| Iniciar o retomar el trabajo | `roclec-coordinator` |
| Establecer el contexto y los principios del proyecto | `roclec-foundation`, `roclec-constitution` |
| Capturar, definir, aclarar o enmendar cambios | `roclec-idea`, `roclec-specify`, `roclec-clarify`, `roclec-amend` |
| Diseñar y prototipar | `roclec-ux`, `roclec-prototype` |
| Planificar y revisar requisitos y tareas | `roclec-plan`, `roclec-tasks`, `roclec-checklist`, `roclec-analyze` |
| Implementar, revisar e integrar | `roclec-implement`, `roclec-reviewer`, `roclec-converge` |
| Planificar y preparar releases | `roclec-release` |

#### Roles de agente que instala Roclec

`roclec skills` también instala tres roles de subagente para Claude Code (`.claude/agents/`) y Codex (`.codex/agents/`). Se generan desde contratos que no nombran proveedores ni modelos. El coordinador corre en tu propia sesión y les delega etapas acotadas.

| Rol | Skills que carga | Entrega |
| --- | --- | --- |
| `roclec-specifier` | `roclec-specify`, `roclec-clarify`, `roclec-analyze`, `roclec-checklist` | Un bundle de cambio sellado y preguntas abiertas; nunca aprueba |
| `roclec-implementer` | `roclec-plan`, `roclec-tasks`, `roclec-implement` | Un candidato y un run de verificación para un componente |
| `roclec-reviewer` | `roclec-reviewer` | Evidencia de revisión desde un contexto distinto del de la implementación |

Cada rol hereda el modelo de la sesión, salvo que el perfil fije uno por host con `[agents.<rol>]`. Codex solo carga los roles del proyecto si el proyecto es de confianza. Tus propios roles en esas carpetas no se tocan. [Roles, archivos y modelo por rol](docs/c3.md#roles-de-agente)

#### Skills externas de diseño opcionales

Roclec incluye un lockfile sugerido para proyectos con interfaz. El perfil 3 restaura las entradas del `skills-lock.json` del consumidor. Si tu proyecto todavía no tiene uno y quieres usar el conjunto sugerido, revisa el archivo y guarda una copia como `skills-lock.json` en su raíz. Conserva tu lockfile si ya administras esas dependencias. [Lockfile de diseño sugerido](src/roclec_spec_kit/assets/profiles/design-skills-lock.json)

| Skill | Repositorio de origen |
| --- | --- |
| `design-lab` | `0xdesign/design-plugin` |
| `design-taste-frontend` | `Leonxlnx/taste-skill` |
| `frontend-design` | `anthropics/skills` |
| `impeccable` | `pbakaus/impeccable` |
| `ui-ux-pro-max` | `nextlevelbuilder/ui-ux-pro-max-skill` |
| `web-design-guidelines` | `vercel-labs/agent-skills` |

La restauración del lockfile sugerido completo falla actualmente porque cambiaron las fuentes de `design-taste-frontend`, `impeccable` y `ui-ux-pro-max`. `design-lab`, `frontend-design` y `web-design-guidelines` se restauraron correctamente con un lockfile de proyecto que incluía solo esas tres entradas. Si quieres usar ese conjunto, conserva sus entradas y huellas originales en la copia de tu proyecto.

Con Node.js y `npx` disponibles, ejecuta lo siguiente desde la raíz del consumidor. Roclec compara los archivos descargados con las huellas del lockfile antes de instalarlos para ambos agentes. Un repositorio de código vinculado usa su propio lockfile al indicar `--into COMPONENTE`.

```bash
./.roclec/run --json skills --restore
```

Para usar los aliases opcionales de GitHub spec-kit, inicializa primero la integración de spec-kit que quieras usar y después ejecuta `./.roclec/run --json speckit`. Los aliases usan las mismas skills nativas. [Configuración del adaptador](docs/c3.md#instalación-nativa-y-aliases)

### Iniciar o retomar un cambio en el chat

Abre el proyecto inicializado en Codex o Claude Code y describe el trabajo en lenguaje natural.

> Roclec, añade un filtro de registros por fecha y lleva el cambio hasta la integración.

En otro chat, retoma con el ID del cambio o una descripción clara.

> Roclec, retoma el cambio del filtro por fecha y llévalo hasta la integración.

Las instrucciones instaladas dirigen la solicitud a `roclec-coordinator`. El coordinador encuentra o prepara el cambio, elige las skills pertinentes y ejecuta los comandos; cuando el host admite subagentes, delega en los roles instalados las etapas mayores de especificación, implementación y revisión. Se ocupa de la planificación, la implementación, la verificación y la integración dentro del alcance solicitado y la política Git del proyecto. Pregunta cuando falta una decisión o evidencia, como la aprobación de una propuesta concreta o la elección de una release que aún no está definida. Con tu respuesta, continúa desde el estado registrado. Para consultar el avance, pide «¿En qué estado está este cambio?».

Usa este flujo en repositorios de confianza. La verificación ejecuta comandos del perfil. Los logs locales completos pueden contener secretos y los extractos versionados optativos ocultan los valores y patrones configurados. [Verificación y logs](docs/c2.md)

Consulta el recorrido detallado y su diagrama SVG en la [guía de flujos de Roclec](docs/flujo-roclec.md).

Para usar la CLI directamente, consulta las guías de [definición y consulta](docs/c1.md), [verificación e integración](docs/c2.md) y [preparación de releases e instalación](docs/c3.md).

### Qué funciona

- Referencias de fundación e índice de contratos por componente y capacidad. Consulta de revisiones vigentes e históricas con validación SHA-256 de snapshots y contenido Markdown.
- Borradores con bases y deltas explícitos, aprobación de intención, asignación a release e inicio por componente, y cancelación. Los IDs de requisitos conservan revisiones inmutables y los cambios de conducta reciben IDs de criterios de aceptación nuevos. Los IDs reservados son permanentes.
- Orígenes de cambio con texto capturado y cobertura estructural de criterios del origen por criterios de aceptación. Captura solo el texto necesario y redacta datos personales antes de sellar. `inspect --change ID` muestra los registros y `list changes --origin ID` encuentra cambios relacionados.
- FUTs con procedencia, decisiones, promoción y seguimiento de duplicados. La planificación de releases aplica pertenencia única y reglas de versionado.
- Vistas de contratos generadas, protección de archivos propios, recibos de operaciones, detección de conflictos y recuperación de escrituras locales interrumpidas. Salida JSON y errores estructurados para automatización.
- Candidatos por entradas, clasificación de rutas, ejecución directa de comandos, logs locales acotados y cobertura explícita por criterio de aceptación. Observaciones manuales o externas y revisión independiente opcional para los controles de verificación por componente. Cuando se exige revisión, un run favorable debe ir acompañado de un informe favorable vigente.
- Integración por componente con candidato final limpio, planes reconstruidos, recibos idempotentes y recuperación.
- Verificación de release contra el contrato final del conjunto, preparación inmutable y comprobación de inclusión de fixes y backports. El registro de publicación Git verifica commits y tags locales y remotos, incluidos los tags anotados. La creación de tags, el push y el despliegue son operaciones separadas.
- Instalación y actualización de skills nativas, roles de agente y aliases opcionales de spec-kit para Codex y Claude, preservando plantillas, principios y roles del consumidor. Una actualización borra los archivos que Roclec ya no distribuye y se niega a sobrescribir archivos administrados que editaste.
- Decisiones de arquitectura (ADR) como Markdown propio del proyecto registrado con el rol `decision`, con estado derivado (propuesta, aceptada, desactualizada, sustituida) y sustitución. Cada cambio declara los ADR que aplica, fijados al aprobar, o ninguno con su motivo; la implementación se bloquea mientras un ADR citado no esté aceptado. [ADR](docs/c1.md#decisiones-de-arquitectura-adr)
- Los runs registran el rol y el contexto que los produjeron, y el gate de revisión rechaza una revisión que declara el mismo contexto que el run revisado.
- Visor local opcional: `pip install 'roclec-spec-kit[viewer]'` y luego `roclec view` abre una vista de solo lectura de releases, cambios, requisitos, evidencia y Markdown del proyecto. El gate que muestra coincide con `check --gate release`. [Guía del visor](docs/visor.md)

### Validar el paquete

Desde el repositorio de Roclec Spec Kit:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
uv build
python3 scripts/harness.py --wheel dist/roclec_spec_kit-0.9.0.dev0-py3-none-any.whl --report /tmp/roclec-checks.json
python3 scripts/harness.py --wheel dist/roclec_spec_kit-0.9.0.dev0-py3-none-any.whl --report /tmp/roclec-compat.json --spec-kit
```

El harness instala el wheel en un entorno aislado, elimina `PYTHONPATH` y `PYTHONHOME` de los subprocesos y comprueba operaciones exitosas y rechazos previstos con consumidores sintéticos y remotos Git desechables. `--spec-kit` también comprueba el adaptador opcional para Codex y Claude y ejecuta por separado las regresiones del modelo anterior. [Harness](docs/harness.md) · [Evidencia C3](docs/implementation/c3.md)

El paquete y el adaptador comparten `__version__`. Las releases normales incrementan la versión mayor o menor y reinician los números subordinados. Las releases hotfix y bugfix incrementan solo la versión de parche y contienen fixes. El proyecto usa MIT y conserva la atribución de los métodos adaptados de GitHub spec-kit. [Licencia](LICENSE) · [Avisos de terceros](THIRD_PARTY_NOTICES.md)
