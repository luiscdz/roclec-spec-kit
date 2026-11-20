# Harness del hito de definición

## Línea base ejecutada

La suite existente debe ejecutarse sin cambios del núcleo y el wheel debe construirse. [baseline-0.7.0.json](../evaluation/evidence-inventory.md) caracteriza tres defectos con consumidores desechables instalados desde un wheel. No es una suite verde que certifique el nuevo modelo, no ejecuta agentes y no publica realmente.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
uv build
python3 scripts/definition_probe.py --wheel dist/roclec_spec_kit-0.7.0-py3-none-any.whl --report docs/definition/evidence/baseline-0.7.0.json --expect vulnerable
# Modo de rechazo futuro: no debe usarse como evidencia de un fix antes de implementarlo.
python3 scripts/definition_probe.py --wheel dist/roclec_spec_kit-0.7.0-py3-none-any.whl --report /tmp/roclec-expect-fixed.json --expect fixed
```

En el núcleo 0.7 la primera caracterización debe observar tres gaps y salir 0 por reproducir la línea base esperada. El modo fixed debe salir distinto de cero mientras sigan presentes: no son tests aprobados de seguridad/corrección. Cuando cambie la interfaz/formato de la CLI, adaptar las fixtures al modelo nuevo y conservar el origen de estos casos. Un fallo de setup/entorno nunca cuenta como defecto corregido.

| Caso | Preparación | Comportamiento actual observado | Obligación futura |
| --- | --- | --- | --- |
| DEF-001 | Reasignar un AC original a un amendment pendiente y quitar sus citas de tests | check --coverage acepta | El delta pendiente no elimina obligación integrada; rechazar apropiación o preservar cobertura |
| DEF-002 | Informe sintético ready, luego añadir un archivo nuevo de implementación no listado | inspect sigue ready | Clasificar nuevo archivo y candidato; incompleto/stale mientras falte verificación |
| DEF-003 | Fix cita SHA inexistente y el release usa commit base sin corrección | Cierre aceptado | Resolver inclusión o backport explícito; rechazar referencia no verificada |

## Casos del modelo propuesto

M-001: un cambio draft no cambia el puntero vigente ni su cobertura. M-002: replace sobre una base distinta se rechaza sin escrituras. M-003: integrar una revisión conserva la resolución de un release anterior. M-004: aprobar intención no publica ni completa un run. M-005: los hashes del ejemplo resuelven contenido real; no aceptar un digest ilustrativo como prueba de ejecución.

O-001: operación idempotente con recibo; O-002: interrupción entre snapshot y puntero deja estado detectable/recuperable; O-003: concurrencia sobre igual base no permite dos avances silenciosos; O-004: componente no publicado no se presenta publicado porque otro lo está. Estas operaciones todavía no están implementadas: los casos son aceptación del primer corte.

La [matriz de interfaces](aceptacion-interfaces.md) concreta estos compromisos en I-001–I-033 y tres incrementos C1/C2/C3. Es especificación de pruebas futuras, no 33 tests aprobados. Las [interfaces](interfaces-primer-corte.md) fijan salida JSON, exit codes y diferencia entre rechazo previo sin escritura y registro de una ejecución real fallida. D1–D3 están confirmadas en [ADR 004](../decisions/004-first-cut-interface-decisions.md); I-017/018/020 expresan sus efectos. [decisions-validation.json](../evaluation/evidence-inventory.md) registra la comprobación documental posterior; interfaces-validation.json conserva el estado previo a recibir las respuestas.

## Evaluación semántica mínima propuesta

Solicitudes aisladas con fuentes ambiguas, aprobación inexistente, fix que cambia comportamiento y verificación manual ausente. Rúbrica: procedencia correcta, alcance, obligación vigente, evidencia suficiente y siguiente acción. Registrar observado/fallido/incompleto y motivos; no usar un agente que simplemente confirme su propia implementación como única autoridad. No se han ejecutado modelos ni presupuestos de proveedor en este hito.

**Preparación posterior, 2026-11-10:** el [plan semántico C1–C3](../evaluation/semantic-c1-c3.md) concreta diez casos (ocho principales y dos reservados), oráculos y fixtures de wheel. El usuario eligió preparar únicamente casos/rúbrica y acordar las ejecuciones después. Sus precondiciones se validan por CLI; los resultados semánticos permanecen not-run, sin sujetos ni revisores ejecutados.

## Umbrales del primer corte

Cero incumplimientos de las invariantes seleccionadas en escenarios deterministas; cero escrituras autoritativas ante rechazo de validación; toda evidencia tiene candidato/alcance identificados o es incomplete; ninguna publicación real inferida. Cada fixture debe establecer sus precondiciones antes de evaluar resultado. Para interpretar skills se revisarán casos y límites, no una puntuación agregada que oculte una aprobación inventada. Los datos iniciales de coste/tiempo son mediciones, no objetivos arbitrarios de ahorro.

## Producto y operación

El plan del consumidor está en sus documentos, no en este paquete. Los escenarios genéricos no fijan stack ni reglas de negocio del piloto. Los resultados del wheel/harness 0.7 pertenecen a la línea base histórica y no certifican el nuevo contrato. Al cambiar assets/lifecycle/adapter se ejecuta además scripts/harness.py --spec-kit, según AGENTS.md.

## Ejecución C1 posterior a la definición

El runtime público 0.8.0 ahora usa perfil 2. scripts/harness.py ejecuta scripts/c1_scenarios.py contra el wheel instalado, con subprocesses sin PYTHONPATH/PYTHONHOME. `--legacy` conserva regresiones anteriores y `--spec-kit` añade esa regresión y la instalación Codex/Claude. El código previo está disponible solo para pruebas explícitas mediante un shim en su venv desechable; no se expone como motor público alternativo.

Los informes 0.7 anteriores permanecen históricos. Los resultados nuevos y límites están en [C1](../implementation/c1.md), con candidatos/revisión/publicación todavía pendientes de C2/C3. La consulta de I-011 usa estados sintéticos sembrados; no acredita integración ejecutada. Las aserciones del harness no se cuentan como agentes evaluados ni como escenarios completos de las fases pendientes.
