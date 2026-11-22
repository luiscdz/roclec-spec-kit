# Flujos de trabajo de Roclec

Esta guía describe el flujo nativo del perfil 3 después de [instalar las skills](c3.md#instalación-nativa-y-aliases). Abre el proyecto en Codex o Claude Code y describe el resultado que buscas. El coordinador consulta los registros del proyecto, elige las skills y ejecuta las operaciones de Roclec.

![Del chat al cambio integrado. El coordinador elige las skills, consulta al usuario cuando falta una decisión y retoma el trabajo desde el estado registrado.](diagrams/flujo-roclec.svg)

[Ver o descargar el SVG](diagrams/flujo-roclec.svg)

## Iniciar un cambio

> Roclec, añade un filtro de registros por fecha y lleva el cambio hasta la integración.

| Etapa | Trabajo del coordinador | Resultado que puedes revisar |
| --- | --- | --- |
| Definir | Busca cambios relacionados, consulta el contrato vigente y prepara la propuesta. Aclara las decisiones que afecten el comportamiento, los permisos o el alcance, y redacta como ADR propuesto la decisión de arquitectura que lo merezca. | ID del cambio, propuesta, criterios de aceptación y ADR que aplica, o ninguno con su motivo. |
| Aprobar y preparar | Registra la aprobación explícita de esa propuesta. Reúne las referencias de fundación, incorpora diseño cuando aplica y prepara el plan y las tareas proporcionales al cambio. Asigna la versión acordada o la que determine la política del proyecto. | Propuesta aprobada, referencias aplicables y release asignada por componente. |
| Implementar y verificar | Comprueba los prerrequisitos, implementa en el repositorio del componente y ejecuta las pruebas del perfil, registrando qué rol y qué contexto produjeron el run. Vincula la evidencia al candidato y obtiene la revisión independiente en un contexto distinto cuando la política está habilitada por defecto o explícitamente. | Código, resultados de comprobación y cobertura de los criterios aplicables. |
| Integrar | Sigue el proceso Git autorizado. Con el repositorio de código limpio y el candidato presente en la rama destino configurada, prepara y aplica la integración desde la troncal de specs. | Registro de integración del componente y revisión vigente del contrato. |

La propuesta conserva una copia Markdown de cada origen y relaciona sus criterios con los criterios de aceptación, exclusiones o diferimientos. El coordinador presenta las exclusiones y diferimientos antes de aprobar. Captura solo el texto necesario y redacta datos personales antes de sellar. Si la fuente cambia, incorporar su texto actualizado crea otra revisión que requiere aprobación. Puedes consultar la cobertura con `inspect --change CHG-001` y buscar cambios con `list changes --origin ID`.

Si tienes una idea que todavía quieres investigar, pide «Roclec, registra esta idea para evaluarla». Se puede capturar como FUT con su fuente y sus preguntas. Si luego se promueve, el coordinador sigue el destino registrado y comprueba si el cambio ya tiene aprobación. [Autoría y descubrimiento](c1.md)

## Roles que intervienen

El coordinador es tu propia sesión. Cuando el host admite subagentes, delega etapas acotadas en los roles que instala Roclec y vuelve a inspeccionar el estado registrado después de cada resultado:

| Rol | Etapas | Lo que no puede hacer |
| --- | --- | --- |
| `roclec-specifier` | Definir, aclarar y analizar la propuesta | Aprobar; tocar código o snapshots aprobados |
| `roclec-implementer` | Planificar, desglosar e implementar un componente | Cambiar la intención aprobada; editar otros componentes |
| `roclec-reviewer` | Revisar el candidato y registrar la evidencia | Editar código o specs; revisar su propio trabajo |

- **Decisiones.** Siguen siendo tuyas. Un rol no puede preguntarte: devuelve sus preguntas abiertas al coordinador, que te las presenta.
- **Proporcionalidad.** Un cambio pequeño lo hace el coordinador solo, porque el traspaso costaría más que el trabajo. La revisión independiente nunca la hace él.
- **Sin subagentes.** Si el host no los admite, o Codex no carga los roles porque el proyecto no es de confianza, el coordinador sigue en secuencia y lo declara. Sin un contexto separado, la revisión queda `incomplete`.
- **Independencia declarada.** El gate rechaza una revisión que declara el mismo contexto que el run revisado. Roclec comprueba lo declarado, no la independencia real.

[Roles, archivos y modelo por rol](c3.md#roles-de-agente)

## Hallazgos de revisión

La revisión registra hallazgos con severidad, ubicación, criterios afectados, condición e impacto. Cada hallazgo conserva su clave `EVD-ID#F-n` al cambiar el candidato. El implementador cita las claves que atendió y una revisión posterior declara cuáles quedaron corregidas o siguen abiertas. El coordinador te presenta los hallazgos materiales que no se pueden corregir dentro del alcance para que decidas si aceptas el riesgo, los consideras inválidos o los difieres a un FUT.

La revisión está habilitada por defecto. Un perfil sin configuración de revisión exige revisión y trata `major` y `blocker` como materiales. Con revisión habilitada, verificar e integrar requieren un informe `ready` vigente y ningún hallazgo material abierto. Los hallazgos menores abiertos se informan. Puedes pedir la lista de un cambio o de una release, y la inspección muestra su estado y el registro que lo produjo. [Detalle y comandos](c2.md#ciclo-de-vida-de-hallazgos)

## Retomar o consultar

> Roclec, retoma el cambio del filtro por fecha y llévalo hasta la integración.

También puedes dar el ID del cambio, como `CHG-001`. El coordinador inspecciona la propuesta y su aprobación vigentes, la asignación de release, el progreso por componente y la evidencia. Si un componente ya está integrado, conserva ese resultado y continúa con el que falta. Si se interrumpió una operación, inspecciona el diario de recuperación antes de volver a escribir.

Para consultar únicamente, pide «Roclec, ¿en qué estado está el cambio del filtro por fecha?». La consulta es de solo lectura.

## Cuándo intervienes

- **Alcance o aprobación.** El coordinador muestra la propuesta concreta y pregunta por la decisión pendiente. Si un cambio de alcance genera una revisión nueva, la aprobación debe corresponder a esa revisión.
- **Decisiones de arquitectura.** El coordinador te presenta cada ADR propuesto con sus alternativas y consecuencias. Solo tu acuerdo lo acepta, y la implementación espera a que todos los ADR citados estén aceptados. [ADR](c1.md#decisiones-de-arquitectura-adr)
- **Diseño, versión o política.** Intervienes si la decisión es material y el proyecto aún no tiene una regla o un acuerdo aplicable.
- **Evidencia o aceptación externa.** Por ejemplo, una validación en un dispositivo al que el agente no tiene acceso, una revisión independiente exigida o una aprobación de Git que depende de otra persona.

El agente puede resolver dentro del alcance tareas como reunir archivos, corregir una prueba o regenerar evidencia después de un cambio. Un bloqueo técnico que persista se informa con su causa y el estado alcanzado. [Verificación, integración y recuperación](c2.md)

## Preparar una release y registrar publicación

> Roclec, verifica y prepara la próxima release del componente con los cambios integrados.

1. El agente inspecciona la versión y sus miembros, y verifica el contrato final del conjunto con una ejecución propia de la release.
2. Si la evidencia está vigente y las comprobaciones se cumplen, aplica la preparación de la release y entrega su identificador.
3. Cuando la publicación Git exista, puedes pedir «Roclec, registra la publicación de esta versión». El agente comprueba el commit y el tag local y remoto antes de registrarlos. La publicación y el despliegue siguen la política del proyecto.

[Guía de release final](c3.md)
