# roclec-spec-kit

Framework local para contratos por capacidad, cambios trazables y releases por componente. El consumidor mantiene sus archivos en Git; Roclec comprueba relaciones, revisiones y decisiones sin imponer su stack ni depender de spec-kit.

**Estado:** desarrollo de 0.9.0. Requiere Python >=3.11 y Git. La CLI usa **perfil 3 y model_schema 2**. Los perfiles 1 y 2 requieren su wheel anterior. Consulta el [plan global](docs/strategy/plan-global.md) para el gate de cierre y el estado del piloto.

## Qué funciona

- Perfil, referencias de fundación e índice de contratos por componente/capacidad.
- Validación de snapshots y contenido Markdown con SHA-256; consulta vigente e histórica.
- Borradores con bases/deltas explícitos, aprobación de intención, asignación e inicio por componente y cancelación.
- Identidades permanentes: mismo REQ con revisión inmutable; AC nuevos ante cambio de conducta. Los IDs reservados no se reciclan.
- FUT con origen, decisiones, promoción y duplicados sin convertir descubrimiento en aprobación.
- Planificación de releases normales/hotfix/bugfix con pertenencia única y reglas numéricas.
- Vistas de contratos, protección de archivos propios, recibos, detección de conflictos y recuperación de escrituras locales interrumpidas.
- Salida JSON y errores estructurados para automatización.
- Candidatos por entradas, clasificación de rutas, ejecuciones reales sin shell, capturas locales acotadas y cobertura explícita por AC.
- Observaciones manuales/externas y revisión independiente opcional con gate por componente; un run pass no sustituye el informe requerido.
- Integración por componente con candidato final limpio, planes reconstruidos, recibos idempotentes y recuperación ante interrupciones.

- RUN de release para el contrato final del conjunto, preparación inmutable y comprobación de inclusión de fixes/backports.
- Registro de publicación Git con commit/tag local y remoto comprobados, incluido tag anotado; sin crear tags, push ni despliegue.
- Instalación/refresh de skills nativas y aliases opcionales para Codex/Claude, preservando plantillas y principios del consumidor.

## Empezar en un proyecto nuevo

```bash
python3 -m venv .venv
.venv/bin/python -m pip install /ruta/al/wheel/roclec_spec_kit-0.9.0.dev0-py3-none-any.whl
git init -b main
.venv/bin/roclec --json init . --profile /ruta/a/roclec-spec-kit/docs/examples/c1/profile.toml
.venv/bin/roclec --json check
.venv/bin/roclec --json change new --file /ruta/a/roclec-spec-kit/docs/examples/c1/change/change.json
.venv/bin/roclec --json inspect --change CHG-001
```

Usa el wheel de desarrollo que genere el build. El ejemplo declara `trunk_ref` y un `target_ref` por componente. Ajusta ambas referencias al repositorio consumidor. `init` conserva los archivos existentes y añade `.roclec/runtime/` a `.gitignore` para diarios, locks y capturas locales.

Ejecuta `run verify` solo en repositorios de confianza. El perfil define los comandos que invocará Roclec. Los logs locales completos pueden contener secretos. Los extractos versionados son optativos y la redacción se limita a valores y patrones configurados. [Verificación y logs](docs/c2.md)

La [guía C1](docs/c1.md) explica definición/consulta; la [guía C2](docs/c2.md), verificación e integración; [C3](docs/c3.md), cierre e instalación. Las [interfaces](docs/definition/interfaces-primer-corte.md), [D1–D3](docs/decisions/004-first-cut-interface-decisions.md), [verificación conjunta](docs/decisions/005-final-release-verification.md) y [aceptación](docs/definition/aceptacion-interfaces.md) gobiernan el primer corte completo. El [plan global](docs/strategy/plan-global.md) conserva los hitos posteriores y la separación respecto del piloto.

## Validación del paquete

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
uv build
python3 scripts/harness.py --wheel dist/roclec_spec_kit-0.9.0.dev0-py3-none-any.whl --report /tmp/roclec-checks.json
python3 scripts/harness.py --wheel dist/roclec_spec_kit-0.9.0.dev0-py3-none-any.whl --report /tmp/roclec-compat.json --spec-kit
```

El harness instala el wheel en un entorno aislado, elimina `PYTHONPATH/PYTHONHOME` de sus subprocesses y recorre operaciones/rechazos reales, con [evidencia C3](docs/implementation/c3.md). `--spec-kit` comprueba el adaptador nativo en Codex/Claude y conserva por separado la regresión anterior. Ejecuta publicaciones Git contra remotos desechables; no publica el paquete ni un producto, ejecuta agentes, despliega o restaura skills externas. Los datos y observaciones de consumidor son sintéticos.

El paquete y el adaptador toman su versión de `__version__`. Las releases normales aumentan X o Y y llevan Z=0. Hotfix y bugfix aumentan Z y contienen fixes. El proyecto usa [MIT](LICENSE) y conserva la procedencia de los métodos adaptados de GitHub spec-kit. [Avisos de terceros](THIRD_PARTY_NOTICES.md)
