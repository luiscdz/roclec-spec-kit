# ADR 003 — Contrato por capacidad, cambios y evidencia vinculada

**Fecha:** 2026-11-09. **Estado:** separación conceptual y persistencia confirmadas; decisiones de interfaz D1–D3 confirmadas en [ADR 004](004-first-cut-interface-decisions.md). Formatos/protocolo definidos para revisión en hito 01, sin implementación nueva.

## Problema

En 0.7 una carpeta de feature mezcla obligación vigente, historial y ejecución. Un amendment puede retirar de hecho cobertura original; una revisión puede ignorar archivos nuevos; un fix puede citar una referencia no verificada. Resolverlo requiere definir autoridad y revisión, no únicamente añadir prompts.

## Decisiones confirmadas

Una capacidad mantiene un contrato integrado; los cambios preservan intención y base; verificaciones y releases referencian candidatos/revisiones exactos. No equiparar integración con publicación. Persistir contenido en Markdown, relaciones/evidencia en TOML/JSON y usar Git más manifiestos de huellas, sin base de datos del framework. No se necesita migrar consumidores reales anteriores: no existen todavía.

## Propuesta del primer corte

El [modelo](../definition/modelo.md) define identidades, snapshots inmutables de contrato, índice vigente por componente y manifiestos de cambio/ejecución/release. Las [interfaces](../definition/interfaces-primer-corte.md) concretan archivos, comandos, errores y recuperación. Un cambio incluye operaciones add/revise/replace/retire sobre referencias de revisión. D1 confirmada: conservar identidad de la misma obligación con revisión inmutable y nuevos AC al cambiar conducta verificable; otra obligación usa reemplazo/retirada explícitos. En todos los casos se impide reutilizar una cita histórica para aprobar conducta distinta.

Actualizar el contrato vigente mediante aplicar un delta validado; las versiones anteriores permanecen consultables. El historial es evidencia, no otra autoridad editable sobre el estado actual. Datos estructurales y contenido tienen cada uno una fuente; un digest vincula los bytes usados. Git conserva commits y contexto, pero HEAD no identifica por sí solo archivos no confirmados.

Planificar pertenencia a release por componente antes de implementar. Preparar un release no acredita publicación ni ejecución. Una refactorización que se entrega usa release normal con Z=0; no se declara bugfix solo para usar un patch. Backports de fixes necesitan relación explícita al commit incluido cuando el SHA difiere del origen.

## Alternativas

| Alternativa | Ventaja | Razón de no proponerla ahora |
| --- | --- | --- |
| Ampliar indefinidamente la carpeta feature | Menor cambio inicial | Sigue mezclando contrato vigente e historia |
| Base de datos/event sourcing general | Consultas/transacciones centralizadas | Contradice la persistencia acordada y añade infraestructura al primer consumidor |
| Dos modelos permanentes | Compatibilidad inmediata | No hay consumidores previos que lo justifiquen |
| Generar código únicamente desde specs | Autoridad muy fuerte de la especificación | No se ha acreditado generación fiable del producto completo; el código y sus pruebas siguen siendo artefactos revisables |

## Consecuencias y límites

Es necesario un índice de referencias y control de bases obsoletas, no solo una plantilla. Aprobar el modelo no aprueba automáticamente documentos de un consumidor ni una publicación. Las revisiones independientes siguen siendo opcionales por alcance; D3 confirmada impone gate en CLI cuando se activa la política, con desactivación por usuario y motivo. D2 confirmada exige commit/manifiesto y repos afectados sin cambios pendientes al integrar y preparar release. Datos/consulta se implementaron en [C1](../implementation/c1.md); las operaciones de candidato, revisión, integración y publicación continúan pendientes de C2/C3.
