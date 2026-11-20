# Ejemplos de relaciones del nuevo modelo

Ejemplos genéricos para revisar el diseño, no archivos consumibles por la CLI 0.7 ni evidencia de tests ejecutados. No contienen datos de polish-car. Ver [modelo](../modelo.md), [interfaces](../interfaces-primer-corte.md) y [example.json](example.json). Los hashes de contenidos son reales para los strings sintéticos incluidos; las referencias Git/build son deliberadamente ausentes para no afirmar una publicación real.

El ejemplo usa D1 confirmada en [ADR 004](../../decisions/004-first-cut-interface-decisions.md): REQ-001 conserva identidad; la revisión cambia de una línea `PASS: Saved` a dos campos `Outcome: PASS` y `Detail: Saved`. AC-001 y AC-002 verifican resultados distintos; evidencia del primero no demuestra el segundo. Confirmar la política del framework no aprueba el cambio sintético CHG-001: su approval sigue null.

`contracts[].content` y `change_content` empaquetan los bytes de archivos en esta fixture; en un consumidor serían archivos Markdown separados, no campos duplicados del descriptor. Los digest de contrato se calculan sobre `descriptor`; el de propuesta sobre `{id, kind, semantic}`. `current` contiene el vector por componente/capacidad. Los estados `derived_*` son resultados esperados de consulta, no banderas editables del registro.

Mientras el cambio no se integra, current y la vista histórica siguen apuntando a la base. Tras integrar con evidencia suficiente, current podrá apuntar al snapshot nuevo; el release anterior conservará su snapshot original. La ejecución preparada tiene candidato null y ningún comando ejecutado. El release solo está planificado. No confundir la vista esperada posterior con estado ya alcanzado.

[base-conflict.json](base-conflict.json) muestra el sobre JSON esperado ante base obsoleta y su exit 3. Los campos de fixture/envuelta no pertenecen a la respuesta real de CLI. Se comprueban referencias/huellas y la forma documental, no comportamiento de un runtime inexistente.
