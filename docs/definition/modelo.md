# Modelo del primer corte — propuesta revisable

**Estado:** C1 implementado en 0.8.0 local; operaciones de C2/C3 todavía especificadas. Decisiones D1–D3 confirmadas en [ADR 004](../decisions/004-first-cut-interface-decisions.md). **Registros nuevos:** model_schema=1, distintos del perfil nuevo schema=2 y del perfil schema=1 de 0.7. [ADR conceptual](../decisions/003-contracts-changes-evidence.md). El detalle se concreta en [interfaces del primer corte](interfaces-primer-corte.md); los casos observables están en [aceptación](aceptacion-interfaces.md).

## Identidad y referencias

IDs permanentes dentro del proyecto: CAP-NNN capacidad, REQ-NNN obligación, AC-NNN escenario, CHG-NNN cambio, RUN-NNN ejecución, EVD-NNN evidencia y FUT-NNN descubrimiento; al menos tres dígitos. Release se identifica por componente + versión; no duplicar esa pertenencia en requisitos. No reutilizar IDs retirados ni renumerar artefactos 0.7 como efecto de este hito. Repetir una identidad en snapshots históricos es válido; redefinirla sin relación con su base no lo es.

Capacidad no significa repositorio: una capacidad puede afectar a varios componentes. REQ expresa una obligación y AC un escenario que la verifica. Un snapshot de capacidad contiene los REQ/AC aplicables y referencias a fuentes/fundación. D1 confirmada: conservar el ID de la misma obligación con revisión inmutable y crear AC nuevos si cambia conducta verificable; otra obligación usa replace/retire explícitos. Las vistas históricas resuelven las revisiones que existían entonces.

Revisión = sha256 del descriptor JSON canónico (claves ordenadas, separadores sin espacios, UTF-8, sin timestamps generados), que incluye hashes de los bytes de contenido Markdown utilizados. Los archivos declarados deben existir y coincidir; JSON no duplica el texto Markdown. Las interfaces fijan orden de listas, campos y rechazo de duplicados. Los candidatos de código siempre se identifican por bytes de archivos, sin normalización de comportamiento. Si un campo es administrativo se almacena fuera del descriptor semántico; no se descartan líneas arbitrarias mediante regex para mantener una aprobación.

Git: registrar repo, base y commit cuando exista, más archivos relevantes nuevos/modificados/eliminados y sus huellas. La comprobación de alcance deriva de diff/estado y rutas de implementación/contratos/referencias, no solamente de la lista elegida por el revisor. Un archivo nuevo fuera del manifiesto obliga a clasificar su relevancia; hasta resolverla el dictamen es incompleto. Un manifiesto no prueba que un test tiene aserciones suficientes ni que quien revisa sea independiente.

## Archivos propuestos

- .roclec/current.json: índice autoritativo por componente/capacidad; el texto vigente se lee del snapshot, no de una copia manual.
- .roclec/contracts/<capacidad>/<revision>/: descriptor y Markdown inmutables.
- .roclec/changes/<id>/change.json y proposal.md: intención, base, delta, alcance y referencias; asignaciones consultadas desde releases.
- .roclec/runs/<id>/manifest.json y .roclec/evidence/: candidato, comandos, salidas resumidas y evidencias.
- .roclec/releases/<componente>/<version>/release.json: única pertenencia; preparaciones y publicación conservan registros separados.

Las rutas propuestas se fijan en las interfaces; no crear este árbol vacío en los consumidores. Foundation se referencia desde sus archivos existentes y el texto vigente es una vista generada. Las [muestras JSON](examples/README.md) muestran base, revisión, ejecución y release genéricos sin datos del piloto.

## Estados y transiciones

| Entidad | Estados propuestos | Reglas |
| --- | --- | --- |
| FUT | captured → evaluating → promoted / discarded / duplicate | Investigación conserva el FUT; promoción apunta a un destino válido y no inventa aprobación; reevaluar requiere nueva decisión histórica |
| Fundación/decisión | proposed → agreed → superseded | Ámbito y responsable explícitos; sustituir conserva razón e historia |
| Cambio | draft → approved → in-progress → verified → integrated | Progreso por componente; agregado partially-integrated cuando corresponde; cancelar solo alcance no integrado; lo integrado se revierte mediante otro cambio |
| Ejecución | prepared → running → completed / failed / interrupted | Reintento es otra ejecución o reanudación explícita del mismo paso con recibo, no sobrescribir resultados |
| Evidencia | pass / fail / incomplete | stale se deriva de entradas/candidato distintos; un resultado histórico no se borra al quedar obsoleto |
| Release/componente | planning → prepared → published | planning puede canceled; prepared pierde elegibilidad si cambia el candidato; published conserva registro inmutable |
| Publicación/entorno | posterior al primer corte del runtime | El corte registra release publicado en Git; no declara despliegue saludable. Retirada/rollback futuro será evento relacionado, sin borrar la publicación original |

En approved se aprueba la intención concreta y su revisión base; verified requiere ejecución suficiente para el alcance. D3 confirmada: cuando participa revisión independiente, CLI exige informes favorables vigentes para verificar/integrar/preparar entrega, por componente afectado. Se pueden ejecutar pruebas y recopilar evidencia antes del informe; completar un run no concede por sí solo verified al cambio. Desactivar requiere decisión del usuario con motivo. Un cambio semántico del proposal después de aprobarlo crea una revisión nueva, vuelve a draft y conserva aprobación histórica. Cambiar código tras verificarlo exige nueva evidencia del candidato. D2 confirmada: integrar/preparar exige commit y manifiesto, sin cambios pendientes en los repos de código afectados; evidencia reutilizable solo por entradas idénticas y contexto válido. Cancelar trabajo no borra su historia ni lo convierte en una entrega.

## Invalidación

| Cambio | Resultado |
| --- | --- |
| Nueva intención, obligación, componente o criterio | Nueva revisión de propuesta; aprobación previa no aplica |
| Cambia el contrato integrado/base | Revalidar delta; bloquear apply sobre base antigua |
| Cambian código, tests, contrato externo o entrada de verificación relevantes | Evidencia previa no habilita candidato nuevo |
| Nuevo archivo relevante no listado | Informe incompleto hasta clasificar y verificar |
| Checkboxes, enlaces de historial o estado administrativo separado | No cambian por sí solos el hash semántico; conservar registro |
| Decisión de terminar piloto de revisión | Registrar responsable/motivo; conservar hallazgos, sin falsificar ready |

## Operaciones observables

Las operaciones de datos/consulta de C1 existen; verificar candidatos, integrar y publicar esperan C2/C3. Las interfaces concretan la sintaxis, sobre JSON y códigos de salida. Un rechazo de preflight no modifica autoridades; una ejecución fallida conserva evidencia del fallo.

| Operación | Entrada / precondición | Resultado |
| --- | --- | --- |
| inspect | capacidad/revisión o componente/versión | Contrato resuelto, aplicabilidad, faltantes y una siguiente acción |
| assess | FUT/fuente + decisión | Origen y destino trazables; sin crear compromiso implícito |
| prepare | cambio + base + alcance | Delta y archivos afectados, hashes esperados y dependencias |
| approve | propuesta exacta + responsable + decisión | Registro ligado a digest, no aprobación por texto en chat ambiguo |
| verify | candidato + escenarios/referencias | Evidencia y límites de ejecución con manifiesto |
| integrate | propuesta aprobada + base vigente + evidencia | Snapshot nuevo, avance de puntero y recibo de integración |
| release-plan | componente + versión + cambios | Pertenencia antes de implementar, sin copiar AC |
| release-prepare | candidato integrado + criterios de versión | Artefacto/commit/manifiesto elegibles; todavía sin publicación |
| release-record | evidencia de publicación autorizada | Registro por componente/entorno y revisión exacta |

## Integración recuperable y concurrencia

1. Leer y validar todo; resolver referencias, aprobaciones, aplicabilidad y revisión base.
2. Preparar archivos temporales y un plan con hashes esperados. Mostrar el delta antes de aplicar.
3. Obtener exclusión mutua local por raíz y volver a comparar precondiciones; conflictos de otro worktree se comprueban también al integrar por Git/CI.
4. Escribir snapshots inmutables antes de cambiar el índice current.json mediante un único reemplazo atómico. Registrar operación/digest y recibo, con journal local para detectar interrupciones.
5. Al reanudar, comprobar hashes y recibos: completar la misma operación si es seguro; si divergen, informar conflicto sin sobrescribir. No afirmar que varias escrituras o repos comparten una transacción atómica.

Orden de integración multicomponente: cambio puede integrado en algunos componentes y pendiente en otros. Cada par componente/capacidad conserva su revisión en el índice y la vista global muestra ese vector. Solo se prepara/publica un componente con dependencias satisfechas y evidencia de su candidato. Un release normal incrementa X o Y y reinicia números subordinados; Z=0. Una corrección incrementa Z, mantiene X.Y y solo incluye fixes. Nunca crear/push tags como efecto lateral de una inspección o validación.

## Invariantes del corte

- Agregar un cambio pendiente no modifica obligaciones ni cobertura del contrato integrado.
- Un replaces/retire debe referenciar una obligación que exista en la base exacta.
- No puede un AC de una revisión demostrar automáticamente conducta distinta de otra.
- El contrato histórico de un release no cambia por integrar otro delta.
- La asignación al release existe antes de implementar y vive en una sola autoridad por componente.
- Un rechazo de precondición no cambia archivos autoritativos; un fallo de IO posterior se declara parcial y recuperable, no se etiqueta rechazo limpio.
- La aprobación semántica no equivale a test ejecutado, integración ni publicación.
- Un SHA sintácticamente válido no acredita inclusión de un fix; resolver commit y ascendencia o backport explícito en el candidato.
