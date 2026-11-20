# ADR 001 — Adaptar métodos de spec-kit a un ciclo nativo de Roclec

**Fecha:** 2026-10-10
**Estado:** aceptado para la implementación interna 0.4.0

## Contexto

Roclec aporta configuración local, componentes con repositorios independientes, releases autoritativos y vistas generadas. Sus instrucciones iniciales cubrían el ciclo, pero varias eran demasiado breves. spec-kit aporta técnicas útiles para definir requisitos, resolver ambigüedades, investigar, ordenar tareas y analizar consistencia. Mantener dos implementaciones de las etapas produce divergencias: selección de feature, cambios de estado y gates distintos.

El código instalado de `specify-cli 0.13.4` se revisó como referencia verificable. Su licencia MIT permite adaptación con atribución; las fuentes seleccionadas y sus SHA-256 están en `src/roclec_spec_kit/assets/notices/spec-kit-provenance.json`.

## Decisión

- Adaptar métodos seleccionados a las skills nativas, sin dependencia obligatoria de spec-kit ni copia completa de sus prompts/scripts.
- Incorporar revisión de ambigüedades por categorías, historias independientes, investigación y decisiones con alternativas, tareas por historia/dependencias y análisis semántico de trazabilidad.
- Añadir skills de constitución y checklist de calidad de requisitos.
- Mantener plantillas canónicas en `assets/templates/`, instaladas una vez como configuración del consumidor.
- Usar `use`, `inspect`, `artifact` y `transition` para selección, contexto y operaciones estructurales. Las skills conservan la revisión semántica y las decisiones humanas.
- Generar el preset y extensión opcionales desde esas mismas skills/plantillas. Sus versiones provienen de la versión del paquete. No encadenar etapas por hooks.
- Limitar la compatibilidad del adaptador a `>=0.13.4,<0.14.0`, probada con 0.13.4; ampliar el rango solo con evidencia del harness.
- Añadir un harness de wheel instalado con proyectos temporales y fallos inducidos, incluyendo los dos agentes soportados como destinos de instalación.

## Alternativas revisadas

| Alternativa | Ventaja | Motivo de no elegirla |
| --- | --- | --- |
| spec-kit obligatorio | Reutiliza toda su infraestructura | Introduce una segunda capa necesaria para un ciclo que RK ya gestiona; los gates de releases y componentes aún requieren Roclec |
| Copiar todos los prompts y scripts | Adopción inicial rápida | Duplica fuentes, conserva supuestos de feature/branch que no son universales y aumenta mantenimiento |
| Mantener instrucciones breves sin adaptación | Menos código/documentación | No cubre las brechas de clarificación, planificación y trazabilidad encontradas |

## Consecuencias

El kit sigue siendo genérico y se instala dentro del proyecto. La instalación externa de la CLI es posible, pero los artefactos/configuración pertenecen al consumidor. Las plantillas propias no se sobrescriben al refrescar skills; deben revisarse durante actualizaciones. La atribución MIT se entrega en el wheel y consumidor.

Los nuevos gates requieren revisar proyectos de 0.3: plan en ready, aprobación registrada para interfaces, tareas reales con trazabilidad y criterios de publicación antes del cierre. Releases ya publicados no se editan para satisfacer nuevos formatos; su migración exige una política explícita o conservar la versión anterior del kit.

Los controles deterministas no sustituyen las decisiones del usuario, la evaluación semántica de los agentes, las pruebas reales ni la evidencia de publicación. El harness inicial comprueba la infraestructura y los fallos reproducibles; una evaluación de agentes requiere ejecución y revisión adicionales.
