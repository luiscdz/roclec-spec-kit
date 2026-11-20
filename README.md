# roclec-spec-kit

Framework local para contratos por capacidad, cambios trazables y releases por componente. El consumidor mantiene sus archivos en Git; Roclec comprueba relaciones, revisiones y decisiones sin imponer su stack ni depender de spec-kit.

**Estado:** desarrollo local **0.8.0 — C1 + C2 + C3**, sin publicación del paquete. Requiere Python >=3.11 y no tiene dependencias de runtime. La CLI pública usa **perfil 2**. Los proyectos 0.7/perfil 1 se rechazan sin migración automática. La [documentación 0.7](docs/workflow-0.7.md), su código y assets históricos se conservan como oráculo explícito de regresión, no como otra modalidad pública del motor nuevo.

## Qué funciona

- Perfil, referencias de fundación e índice de contratos por componente/capacidad.
- Validación de snapshots y contenido Markdown con SHA-256; consulta vigente e histórica.
- Borradores con bases/deltas explícitos, aprobación de intención, asignación e inicio por componente y cancelación.
- Identidades permanentes: mismo REQ con revisión inmutable; AC nuevos ante cambio de conducta. Los IDs reservados no se reciclan.
- FUT con origen, decisiones, promoción y duplicados sin convertir descubrimiento en aprobación.
- Planificación de releases normales/hotfix/bugfix con pertenencia única y reglas numéricas.
- Vistas de contratos, protección de archivos propios, recibos, detección de conflictos y recuperación de escrituras locales interrumpidas.
- Salida JSON y errores estructurados para automatización.
- Candidatos por entradas, clasificación de rutas, ejecuciones reales sin shell, logs inmutables y cobertura explícita por AC.
- Observaciones manuales/externas y revisión independiente opcional con gate por componente; un run pass no sustituye el informe requerido.
- Integración por componente con candidato final limpio, planes reconstruidos, recibos idempotentes y recuperación ante interrupciones.

- RUN de release para el contrato final del conjunto, preparación inmutable y comprobación de inclusión de fixes/backports.
- Registro de publicación Git con commit/tag local y remoto comprobados, incluido tag anotado; sin crear tags, push ni despliegue.
- Instalación/refresh de skills nativas y aliases opcionales para Codex/Claude, preservando plantillas y principios del consumidor.

## Empezar en un proyecto nuevo

```bash
python3 -m venv .venv
.venv/bin/python -m pip install /ruta/al/wheel/roclec_spec_kit-0.8.0-py3-none-any.whl
.venv/bin/roclec --json init . --profile /ruta/a/roclec-spec-kit/docs/examples/c1/profile.toml
.venv/bin/roclec --json check
.venv/bin/roclec --json change new --file /ruta/a/roclec-spec-kit/docs/examples/c1/change/change.json
.venv/bin/roclec --json inspect --change CHG-001
```

El ejemplo es genérico y debe adaptarse al alcance real. `repo` del perfil se interpreta respecto del consumidor, no respecto del archivo de ejemplo. `init` no instala las antiguas skills ni escribe reglas del producto. Conserva archivos existentes y añade `.roclec/runtime/` a `.gitignore` para diarios/locks locales.

La [guía C1](docs/c1.md) explica definición/consulta; la [guía C2](docs/c2.md), verificación e integración; [C3](docs/c3.md), cierre e instalación. Las [interfaces](docs/definition/interfaces-primer-corte.md), [D1–D3](docs/decisions/004-first-cut-interface-decisions.md), [verificación conjunta](docs/decisions/005-final-release-verification.md) y [aceptación](docs/definition/aceptacion-interfaces.md) gobiernan el primer corte completo. El [plan global](docs/strategy/plan-global.md) conserva los hitos posteriores y la separación respecto del piloto.

## Validación del paquete

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
uv build
python3 scripts/harness.py --wheel dist/roclec_spec_kit-0.8.0-py3-none-any.whl --report /tmp/roclec-c3.json
python3 scripts/harness.py --wheel dist/roclec_spec_kit-0.8.0-py3-none-any.whl --report /tmp/roclec-c3-compat.json --spec-kit
```

El harness instala el wheel en un entorno aislado, elimina `PYTHONPATH/PYTHONHOME` de sus subprocesses y recorre operaciones/rechazos reales, con [evidencia C3](docs/implementation/c3.md). `--spec-kit` comprueba el adaptador nativo en Codex/Claude y conserva por separado la regresión anterior. Ejecuta publicaciones Git contra remotos desechables; no publica el paquete ni un producto, ejecuta agentes, despliega o restaura skills externas. Los datos y observaciones de consumidor son sintéticos.

El paquete, preset y extensión obtienen su versión de 0.8.0; no se crean tags ni se publica el wheel al construirlo. Las releases normales aumentan X o Y, reiniciando subordinados y con Z=0. Hotfix/bugfix aumentan exclusivamente Z y contienen fixes. Los métodos adaptados de GitHub spec-kit conservan MIT y procedencia en [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) y los assets distribuidos.
