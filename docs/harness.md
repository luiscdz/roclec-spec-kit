> Referencia histórica 0.7/perfil 1. Para 0.8/C1 usar [la guía vigente](c1.md); el adaptador del modelo nuevo continúa pendiente de C3.

# Harness de Roclec

## Para qué sirve

`tests/` valida comportamientos del núcleo. `scripts/harness.py` detecta fallos entre empaquetado, instalación, descubrimiento del proyecto, enlaces de repositorios, artefactos, gates y releases. Usa procesos reales de la CLI instalada desde el wheel; no importa el código de `src/` para probar el consumidor.

## Ejecutarlo

Desde el repositorio del kit, con Python >=3.11, Git y `uv`:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
uv build
python3 scripts/harness.py \
  --wheel dist/roclec_spec_kit-0.7.0-py3-none-any.whl \
  --report /tmp/roclec-harness.json
```

Para comprobar también la integración opcional, instala `specify-cli==0.13.4` en tu entorno y ejecuta:

```bash
python3 scripts/harness.py \
  --wheel dist/roclec_spec_kit-0.7.0-py3-none-any.whl \
  --report /tmp/roclec-harness-compat.json --spec-kit
```

No requiere conexión de red durante el harness. Instala el wheel con `pip --no-index --no-deps` en un `.venv` temporal. Los repositorios sintéticos y sus commits se eliminan al finalizar; el informe se conserva en la ruta elegida. La ejecución termina con código 0 si pasa, 1 si falla. Cada subprocess tiene un límite de 60 segundos.

## Escenarios

- El wheel contiene las 17 skills, plantillas y atribución MIT.
- Instalación local, preservación de instrucciones propias y descubrimiento desde un componente enlazado, incluso con espacios en rutas.
- Selección explícita de spec, estados válidos y rechazo de saltos.
- Los ejemplos comentados no cuentan como AC ni tareas.
- Esfuerzo pendiente y aprobación de prototipo pendiente bloquean planificación.
- Tareas vacías, IDs duplicados, múltiples propietarios y AC desconocidos bloquean implementación.
- Cada componente necesita exactamente un release; asignar solo uno no permite comenzar.
- `done` rechaza tareas abiertas y falta de citas de AC en tests. Las pruebas sintéticas también se ejecutan.
- Releases requieren criterios completos, notas y specs terminadas. Archivos publicados se protegen frente al commit base.
- Vistas generadas alteradas se detectan; actualizar skills conserva las plantillas propias.
- Con `--spec-kit`: instalación y actualización de aliases para Codex y Claude; ambos usan el cuerpo canónico de las skills nativas y sincronizan el contexto de feature.

Las pruebas negativas toman huellas de los archivos y comprueban que los gates no mutan el estado. Las ediciones sintéticas que introducen fallos se restauran antes del siguiente escenario.

## Leer el informe

El JSON contiene `schema`, fecha UTC, nombre y SHA-256 del wheel, tipo de evaluación, resultado global, casos con resultado/evidencia y el primer fallo. Las salidas completas pueden contener rutas temporales que ya no existen. Guarda el informe como artifact de CI asociado al wheel evaluado; no publiques uno de otra compilación como evidencia de la versión actual.

## Cómo extenderlo

Primero reproduce el defecto con una fixture de consumidor. Añade un escenario que invoque la CLI real y falle con el comportamiento anterior. En pruebas negativas comprueba el error y la ausencia de cambios; en positivas inspecciona el resultado persistido. Mantén los componentes genéricos y separa las dependencias opcionales con un flag. Los tests unitarios sirven para variantes rápidas del parser o validador; el harness cubre sus conexiones reales.

## Límites y siguiente evaluación

Este harness no ejecuta agentes ni mide la calidad semántica de sus respuestas. Una cita de AC no demuestra que una prueba cubra realmente el comportamiento; un registro de aprobación no autentica al humano. El fixture de pruebas es sintético y no certifica un producto consumidor.

Para evaluar las skills con agentes después: ejecutar las mismas solicitudes en worktrees aislados con versiones fijadas de Codex/Claude y conservar prompts, archivos, salidas y comandos. Una rúbrica humana debe evaluar ambigüedades detectadas, decisiones inventadas, fuentes únicas, trazabilidad, elección del siguiente paso y respeto de las aprobaciones. Registrar modelo/configuración/repeticiones y comparar contra una línea base. No llamar a esa evaluación automática ni afirmar que se hizo hasta ejecutar y revisar esos casos.

## Cobertura añadida en 0.5–0.7

El recorrido instalado incluye un amendment con selección persistida y release propio, un bugfix basado en un tag sintético publicado, opt-in/opt-out de revisión, referencias instaladas y resolubles desde aliases de ambos agentes, producto opcional y prototipo reutilizado con aprobación de alcance. Los tags del fixture los prepara el harness, no el cierre de la CLI. Las pruebas unitarias complementan el recorrido con releases históricos, colisiones y componentes que terminan en momentos distintos.

Los informes se generan mediante --report y contienen la huella exacta del wheel. Los builds de las tres etapas pueden conservarse en dist/; no implican publicación del paquete ni creación de tags del proyecto.
