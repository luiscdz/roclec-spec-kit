# Hito 01 — Definición de Roclec y primer piloto

**Actualización:** 2026-11-10. **Estado:** primer corte determinista C1/C2/C3 implementado localmente en 0.8.0, con D1–D3 y [verificación conjunta](../decisions/005-final-release-verification.md). **Autoridad:** [plan global](../strategy/plan-global.md). Evidencias [C1](../implementation/c1.md), [C2](../implementation/c2.md), [C3](../implementation/c3.md). Avance por entregables/evidencias, no por porcentajes. Las decisiones técnicas/UX y aceptación del consumidor conservan su revisión propia.

## Alcance autorizado

La definición incorporó R1–R6 y preparó fundación/modelo/operaciones/ejemplos del kit y carta/fuentes/fundación/criterios del consumidor sin modificar entonces el núcleo. El usuario autorizó sucesivamente C1, C2 y C3, preservando cambios y validando con harness. Ese alcance no incluye implementar el producto, publicar el paquete ni aprobar decisiones comerciales/técnicas del consumidor.

## Mapa de documentos

| Documento | Qué gobierna / estado |
| --- | --- |
| [Plan global](../strategy/plan-global.md) | Dirección confirmada y seis hallazgos incorporados |
| [Revisión histórica](../strategy/revision-plan-2026-11-09.md) | Hallazgos originales; no otra autoridad de planificación |
| [Fundación del kit](fundacion-roclec.md) | Persistencia confirmada y arquitectura técnica candidata |
| [ADR 003](../decisions/003-contracts-changes-evidence.md) | Decisiones confirmadas frente a detalles propuestos |
| [ADR 004](../decisions/004-first-cut-interface-decisions.md) | D1 identidad, D2 candidato final y D3 revisión opcional, confirmadas explícitamente |
| [Modelo](modelo.md) | Identidades, revisiones, estados, invalidación y protocolo propuestos |
| [Interfaces del primer corte](interfaces-primer-corte.md) | Rutas, autoridad por componente, comandos, gates, errores y recuperación; D1–D3 incorporadas |
| [Aceptación de interfaces](aceptacion-interfaces.md) | 33 escenarios y tres incrementos implementables; especificados, no ejecutados |
| [Ejemplos](examples/README.md) | Datos sintéticos persistidos para revisar relaciones y hashes |
| [Harness](harness.md) | Regresiones ejecutadas y escenarios futuros diferenciados |
| Repositorio privado del piloto | Autoridad de alcance/reglas del consumidor; repos hermano local |

## Checklist de salida

| ID | Criterio verificable | Evidencia / estado |
| --- | --- | --- |
| H01-01 | Plan canónico en el repo, revisión mapeada, copia del chat solo enlaza | docs/strategy; preparado para Git, sin commit automático |
| H01-02 | Estado previo recuperable e inventario de ambos repos | [Preservación](../evaluation/evidence-inventory.md); respaldo externo verificado |
| H01-03 | Fundación de Roclec separada de la del producto | fundacion-roclec.md y docs/pilot/fundacion.md del consumidor |
| H01-04 | Tablas de identidad/revisión/estado e invalidación con ejemplos consistentes | Modelo e interfaces revisados; fixture con escenarios distintos y digest reales; D1–D3 confirmadas en ADR 004 |
| H01-05 | Asignación de release antes de implementar y preparación/publicación posteriores | Diagrama y estados corregidos en plan/modelo |
| H01-06 | Primer corte acotado y exclusiones explícitas | Plan sección 12; sin motor de workflow general ni migrador |
| H01-07 | Tres defectos caracterizados de forma reproducible desde wheel | [Diagnóstico](../evaluation/evidence-inventory.md); siguen presentes, no corregidos |
| H01-08 | Suite previa y build ejecutados con resultado atribuido a esta línea base | [Validación](../evaluation/evidence-inventory.md); no acredita el modelo futuro |
| H01-09 | Fuentes del consumidor clasificadas y huellas registradas | docs/pilot/fuentes.md/json; materiales no analizados identificados |
| H01-10 | Decisiones y bloqueos del primer ingreso explícitos | docs/pilot/decisiones.md: ocho decisiones confirmadas; las cuatro preguntas de ingreso resueltas, aceptación comercial separada |
| H01-11 | Referencias locales y hashes de ejemplos comprobados | [Validación tras decisiones](../evaluation/evidence-inventory.md); [revisión previa de interfaces](../evaluation/evidence-inventory.md) conservada como histórica |
| H01-12 | Revisión del primer corte antes de cambiar runtime/skills | Cinco huecos tratados y D1–D3 confirmadas; interfaces documentadas para implementar C1. UX/stack del consumidor se resuelven antes de su implementación |

Los estados preparado/verificado/propuesto no significan aprobación humana. El hecho de guardar documentación no completa una implementación ni una capacidad del consumidor.

## Orden de trabajo posterior

1. C1 de aceptación: perfil/referencias/contrato/cambio/consulta, FUT y pertenencia de release, con sus invariantes y rechazo de deltas inválidos (DEF-001). Incorporar las decisiones confirmadas desde el esquema; no introducir un modelo provisional que las contradiga.
2. C2/C3: candidato/evidencia, gates, integración/recuperación y cierre real de referencias (DEF-002/003), después skills/adaptador. Validar wheel y harness antes de instalar el flujo completo en el piloto; evaluaciones semánticas pequeñas separadas.
3. Resolver decisiones técnicas y de UX del primer corte consumidor, asignar su release e implementar solo la recepción acordada. Probar evolución/publicación parcial en fixtures, no provocar fallos reales del negocio.

Los pasos mecánicos C1/C2/C3 de esta secuencia ya se ejecutaron. I-011 incluye integración real C2 en fixtures y C3 comprueba publicación Git contra remotos desechables e instalación nativa.

La evaluación semántica C1–C3 documenta una primera campaña cuyos agentes heredaron los oráculos, una campaña ciega con tres recorridos sin completar y una regresión de 10/10 sobre casos conocidos. El recorrido real y la aceptación del piloto siguen pendientes. [Informe semántico](../evaluation/semantic-c1-c3.md)

Se ejecutan pasos mecánicos dentro del alcance aprobado; decisiones materiales y publicaciones vuelven a la persona responsable. No se solicita de nuevo la aprobación de principios ya confirmados en la sesión.

## Fuera del primer corte

Workflow genérico configurable, servicio alojado/DB del framework, motor distribuido, compatibilidad permanente dual 0.7, migrador de consumidores inexistentes, benchmark masivo/modelos de pago, automatizaciones periódicas y publicación real. La evaluación semántica pequeña sí pertenece al proceso, con evidencia y límites explícitos.
