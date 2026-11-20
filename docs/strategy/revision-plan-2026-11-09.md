# Revisión del plan global de Roclec

Fecha: 9 de noviembre de 2026. Alcance: revisión del plan global, contraste puntual con el núcleo 0.7 y las fuentes del piloto. No se ha modificado el plan revisado, el paquete ni polish-car. No se ha vuelto a ejecutar la suite: este informe no acredita el estado actual de la implementación.

## Dictamen

El plan cubre los grandes bloques necesarios para iniciar el hito de definición y diseño. No es todavía una especificación lista para ejecutar todo el rediseño; no pretende serlo, pues reserva interfaces y reglas detalladas por hito. No se recomienda añadir más subsistemas antes de realizar el primer corte. Se identifican tres puntos prioritarios de diseño/orden y tres preparaciones de ejecución que deben quedar explícitas en el siguiente hito.

Las preguntas de dominio, stack y aprobación comercial de polish-car no impiden avanzar en el diseño de Roclec; sí impiden presentar como aprobada una implementación concreta del consumidor.

## Hallazgos y acciones

### R1 — Prioritario antes de implementar el modelo: fijar identidad, revisiones y estados

Referencia: plan, secciones 3 y fase 1 (líneas 61–76 y 88–94).

El plan distingue conceptos correctamente, pero todavía difiere identificadores, autoridad de revisiones y operaciones. Hace falta una tabla de estados/transiciones por entidad y ejemplos persistidos: requisito vs escenario/AC, ID vs revisión, añadir/sustituir/retirar, cambio rechazado/cancelado/integrado y entrega planificada/publicada/retirada si aplica. Una fase 1 que entregue únicamente ADRs narrativos dejaría decisiones de compatibilidad y trazabilidad al implementador.

Acción: incluir un ejemplo mínimo completo, esquema de referencias, invariantes y operaciones observables. Definir qué aprobación se invalida ante un cambio de intención/candidato y qué cambios administrativos la conservan. La misma consulta debe poder reconstruir el contrato integrado y el de una entrega histórica sin exigir comportamientos incompatibles.

Esto es detalle previsto para el hito de modelo, no una razón para declarar incompleto todo el plan global ni adoptar una base de datos/event sourcing.

### R2 — Prioritario de coherencia: distinguir asignación de release, preparación y publicación

Referencia: diagrama conceptual (líneas 44–53) y fases 3–4 (108–122).

El plan menciona entrega destino antes de implementar, pero dibuja el nodo Release solo después de integrar. Puede interpretarse como asignar versión al final, contradiciendo la regla existente de planificar la pertenencia antes de implementar. Tampoco debe unificarse la integración multirrepo en una supuesta operación atómica.

Acción: mostrar explícitamente release planificado/asignación antes de la implementación, candidato/build posterior a verificación y publicación posterior por componente. Fijar qué significa completo cuando un componente está integrado, otro pendiente y otro ya publicado. Mantener el ensayo sin publicación real. Aclarar el tratamiento de versiones de contenido técnico/refactor sin incumplir la política X.Y.0 y Z reservado a fixes.

### R3 — Prioritario de alcance: definir el mínimo que valida el piloto

Referencia: fases 1–5 (líneas 88–132) y harness (276–349).

El diseño incluye numerosas capacidades deseables y el orden no hace explícito cuáles pueden esperar. Existe riesgo de construir un motor de workflow, evaluación de agentes, gobernanza documental y recuperación multirrepo antes de la primera recepción real.

Acción: mínimo inicial de modelo de contrato/cambio, referencias de fundación, recorrido nativo guiado por hitos y harness determinista con las tres regresiones. Añadir lo mínimo de captura/decisión/trazabilidad de FUT para el primer caso. Evaluaciones semánticas pequeñas desde temprano; una plataforma de evaluación con modelos/proveedores múltiples y automatización amplia se pospone. Probar comportamientos multirrepo y fallos en fixtures al introducir sus operaciones, sin construir una plataforma de coordinación distribuida.

Cada capacidad nueva del framework debe justificar qué escenario del piloto o invariante genérico valida. Las demás se registran para después.

### R4 — Preparación de ejecución: versión y ubicación de los artefactos de planificación

Referencia: el plan global reside actualmente en la carpeta de visualizaciones de la conversación; sección 8 establece propiedad separada del núcleo y consumidor.

El archivo es accesible desde el chat, pero no forma parte de una fuente versionada compartida por el equipo o CI. Además, ambos repositorios contienen trabajo previo sin consolidar y polish-car no tiene un commit inicial.

Acción: al iniciar el hito, inventariar y preservar ese trabajo y establecer un estado recuperable sin reset/limpieza ni commits indiscriminados. Incorporar plan/ADRs/escenarios del framework en Roclec y carta/fundación/decisiones de producto en polish-car. El índice del plan debe señalar estado, próximos pasos y bloqueos; evitar mantener dos planes editables con autoridad equivalente. La visualización seguirá siendo una proyección explicativa, no otra fuente de estados.

No es necesario consolidar toda la aplicación o publicar el paquete para comenzar la definición.

### R5 — Preparación de ejecución: contrato de salida del siguiente hito

Referencia: entregables del siguiente hito (sección 8) y criterios generales del harness.

Los entregables están enumerados, pero su aceptación permanece cualitativa. Antes de la primera implementación se debe poder verificar que se entregaron sin interpretar expresiones amplias como fundación mínima o modelo definido.

Acción: fijar un checklist corto: fuentes clasificadas, alcance candidato y exclusiones, decisiones con responsable/estado, autoridad por documento, ejemplo de modelo y transiciones, escenarios de regresión y comandos/rúbricas, y operaciones previstas con fallos observables. Distinguir resultado comprobado, propuesta y pregunta bloqueante. Registrar avance por evidencia/entregables; no por un porcentaje estimado de toda la estrategia.

### R6 — Preparación del consumidor: confirmar alcance y separar ambas fundaciones

Referencia: fase 0 y secciones 9–10; documentos de polish-car.

La fundación del consumidor está detallada, pero también hace falta una fundación técnica del propio Roclec para orientar el rediseño. No se deben transferir las elecciones NestJS/React de una propuesta del piloto al kernel Python. Tampoco se debe bloquear la definición del framework esperando decisiones comerciales del lavadero.

Las fuentes del piloto contienen contradicciones concretas: asignación/liquidación en fase 1 o 2; mensajes automáticos frente a wa.me; cierre como listo frente a estado entregado. Deben resolverse antes de implementar la capacidad afectada. La propuesta básica es una candidata elegida por el usuario, no prueba de aprobación del cliente.

Acción: dos documentos de alcance/fundación separados y responsables de decisión por rol. En el framework: límites del núcleo, almacenamiento, validación, operaciones, skills, adaptadores y pruebas. En el producto: roles, campos, estados, comunicaciones y arquitectura propia. Revisar solo lo necesario para el primer corte y dejar futuras decisiones con propietario.

## Qué ya está suficientemente cubierto en dirección

Independencia de spec-kit; separación contrato/cambio/evidencia/entrega; fuentes y FUT; rutas por tipo de trabajo; fundación y referencias canónicas; diseño aplicable; evaluación determinista y semántica diferenciada; versionado; operación y recuperación; privacidad de evidencias; separación núcleo/consumidor; medición con límites explícitos.

No hace falta añadir otro gran bloque funcional para empezar. Sí hace falta convertir las decisiones del primer corte en ejemplos y criterios verificables antes de programar el rediseño.

## Siguiente paso recomendado

Un hito de definición y diseño con dos recorridos paralelos:

1. Roclec: plan versionado, fundación técnica y ADR del modelo, ejemplos de contrato/cambio/revisiones, estados y tres regresiones reproducibles.
2. polish-car: carta del piloto, mapa de fuentes y contradicciones, alcance candidato de recepción y decisiones que faltan para aprobarlo.

Reunirlos en una revisión del primer corte: qué permite hacer, qué conserva, qué evidencia lo demostrará y qué queda fuera. Después iniciar una implementación pequeña del framework con sus escenarios. No ejecutar el rediseño completo ni desarrollar toda la aplicación a partir de un plan global.

## Incorporación posterior

Los seis hallazgos se incorporaron al plan canónico, sección 12. Este informe conserva el diagnóstico original y sus números de línea históricos; no es una segunda fuente editable del plan.
