# ADR 004 — Identidad, candidato final y revisión opcional

**Fecha:** 2026-11-09. **Estado:** decisiones D1–D3 confirmadas explícitamente por el usuario en la revisión de interfaces. Complementa [ADR 003](003-contracts-changes-evidence.md) y las [interfaces del primer corte](../definition/interfaces-primer-corte.md). No acredita implementación ni aprueba documentos del consumidor o publicaciones.

## D1 — Identidad de una obligación

Conservar el ID del requisito cuando evoluciona la misma obligación y crear una revisión inmutable. Crear AC nuevos cuando cambie la conducta verificable. Si se trata de otra obligación, usar reemplazo/retirada explícitos.

Esto permite seguir una obligación en el tiempo sin cambiar todas sus referencias. Cada cita histórica se resuelve con su revisión; evidencia de un AC anterior no demuestra una conducta distinta. Una edición editorial cambia la huella del contenido, pero no inventa por sí sola otra obligación.

## D2 — Candidato final

Al integrar un cambio o preparar una entrega, exigir candidato identificado por commit y manifiesto, sin cambios pendientes en los repositorios de código afectados. Durante desarrollo se admiten archivos sin commit. La evidencia puede reutilizarse si los bytes verificados son idénticos; además se comprueban ámbito, entradas, política y ascendencia aplicables.

El preflight final comprueba cambios staged/unstaged y archivos untracked no ignorados en los repos afectados; no basta que las rutas elegidas por el autor estén limpias. Los ignorados necesitan clasificación de entradas/salidas ya definida. Los archivos operativos que la propia operación crea después del preflight se registran como efectos, sin afirmar que el repo continúa limpio tras escribirlos. Si viven en el mismo repo de código, se deben confirmar antes del siguiente gate final que exija limpieza. Roclec no realiza commits automáticamente.

Los metadatos de runs/recibos y el índice de integración no forman parte de la huella de código evaluada. Un commit posterior que solo los registre puede reutilizar evidencia de las mismas entradas; el candidato final se identifica de nuevo y se verifica su correspondencia. No se copia un pass por coincidencia de HEAD ni se ocultan cambios de implementación.

## D3 — Revisión independiente opcional con gate

La política sigue siendo opcional y se activa por cambio. Cuando participa, la CLI impide declarar verificado el componente, integrarlo o preparar su entrega si falta un informe favorable vigente para el componente afectado. `changes-needed`, `incomplete`, ausente o stale bloquean. El usuario puede desactivarla con motivo registrado; informes y hallazgos se conservan.

Ejecutar pruebas y registrar resultados sigue permitido para producir la evidencia que necesita el revisor. Un run automatizado completado no equivale a componente `verified`. `check --gate verify` comprueba el conjunto de evidencia y revisión, sin ejecutar pruebas. Esto evita un ciclo en que el revisor necesita resultados que la política impide producir. Integración y preparación de entrega reutilizan el mismo gate y no lo eluden.

La CLI comprueba ámbito, candidato y vigencia del informe; la independencia real, suficiencia de los criterios y calidad visual requieren evaluación semántica. La adopción no añade obligación global ni retroactiva a consumidores que no la hayan activado.

## Consecuencias

Actualizar ejemplos, gates y aceptación sin implementar el runtime en este paso. La primera implementación comienza por C1: perfil, referencias, contratos, consulta, cambios, FUT y pertenencia de release. Las decisiones técnicas/UX y aceptación comercial del piloto conservan su estado propio; estas tres decisiones pertenecen al framework.
