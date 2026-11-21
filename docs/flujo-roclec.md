# Flujos de trabajo de Roclec

Esta guía describe el flujo nativo del perfil 3 después de [instalar las skills](c3.md#instalación-nativa-y-aliases). Abre el proyecto en Codex o Claude Code y describe el resultado que buscas. El coordinador consulta los registros del proyecto, elige las skills y ejecuta las operaciones de Roclec.

![Del chat al cambio integrado. El coordinador elige las skills, consulta al usuario cuando falta una decisión y retoma el trabajo desde el estado registrado.](diagrams/flujo-roclec.svg)

[Ver o descargar el SVG](diagrams/flujo-roclec.svg)

## Iniciar un cambio

> Roclec, añade un filtro de registros por fecha y lleva el cambio hasta la integración.

| Etapa | Trabajo del coordinador | Resultado que puedes revisar |
| --- | --- | --- |
| Definir | Busca cambios relacionados, consulta el contrato vigente y prepara la propuesta. Aclara las decisiones que afecten el comportamiento, los permisos o el alcance. | ID del cambio, propuesta y criterios de aceptación. |
| Aprobar y preparar | Registra la aprobación explícita de esa propuesta. Reúne las referencias de fundación, incorpora diseño cuando aplica y prepara el plan y las tareas proporcionales al cambio. Asigna la versión acordada o la que determine la política del proyecto. | Propuesta aprobada, referencias aplicables y release asignada por componente. |
| Implementar y verificar | Comprueba los prerrequisitos, implementa en el repositorio del componente y ejecuta las pruebas del perfil. Vincula la evidencia al candidato y obtiene revisión independiente si la política la exige. | Código, resultados de comprobación y cobertura de los criterios aplicables. |
| Integrar | Sigue el proceso Git autorizado. Con el repositorio de código limpio y el candidato presente en la rama destino configurada, prepara y aplica la integración desde la troncal de specs. | Registro de integración del componente y revisión vigente del contrato. |

Si tienes una idea que todavía quieres investigar, pide «Roclec, registra esta idea para evaluarla». Se puede capturar como FUT con su fuente y sus preguntas. Si luego se promueve, el coordinador sigue el destino registrado y comprueba si el cambio ya tiene aprobación. [Autoría y descubrimiento](c1.md)

## Retomar o consultar

> Roclec, retoma el cambio del filtro por fecha y llévalo hasta la integración.

También puedes dar el ID del cambio, como `CHG-001`. El coordinador inspecciona la propuesta y su aprobación vigentes, la asignación de release, el progreso por componente y la evidencia. Si un componente ya está integrado, conserva ese resultado y continúa con el que falta. Si se interrumpió una operación, inspecciona el diario de recuperación antes de volver a escribir.

Para consultar únicamente, pide «Roclec, ¿en qué estado está el cambio del filtro por fecha?». La consulta es de solo lectura.

## Cuándo intervienes

- **Alcance o aprobación.** El coordinador muestra la propuesta concreta y pregunta por la decisión pendiente. Si un cambio de alcance genera una revisión nueva, la aprobación debe corresponder a esa revisión.
- **Diseño, versión o política.** Intervienes si la decisión es material y el proyecto aún no tiene una regla o un acuerdo aplicable.
- **Evidencia o aceptación externa.** Por ejemplo, una validación en un dispositivo al que el agente no tiene acceso, una revisión independiente exigida o una aprobación de Git que depende de otra persona.

El agente puede resolver dentro del alcance tareas como reunir archivos, corregir una prueba o regenerar evidencia después de un cambio. Un bloqueo técnico que persista se informa con su causa y el estado alcanzado. [Verificación, integración y recuperación](c2.md)

## Preparar una release y registrar publicación

> Roclec, verifica y prepara la próxima release del componente con los cambios integrados.

1. El agente inspecciona la versión y sus miembros, y verifica el contrato final del conjunto con una ejecución propia de la release.
2. Si la evidencia está vigente y las comprobaciones se cumplen, aplica la preparación de la release y entrega su identificador.
3. Cuando la publicación Git exista, puedes pedir «Roclec, registra la publicación de esta versión». El agente comprueba el commit y el tag local y remoto antes de registrarlos. La publicación y el despliegue siguen la política del proyecto.

[Guía de release final](c3.md)
