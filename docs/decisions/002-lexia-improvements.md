# ADR 002 — Adaptar evolución posterior al cierre y evidencia de Lexia

**Estado:** implementado en 0.5.0, 0.6.0 y 0.7.0.
**Fuente:** lexia-specs, ADR 006 y tooling/skills/lexia-reviewer; revisión local de 2026-11-07. No se incorporan reglas de dominio ni código de aplicaciones consumidoras.

## Decisiones

La identidad NNN-A1 separa la evolución de una spec done de su alcance original. Los AC permanecen en spec.md, las tareas en tasks.md y las asignaciones exclusivamente en archivos de versión. La finalización/cobertura de amendments se calcula por componente. No se reabren specs ni se duplica su membresía original.

Las versiones nuevas son vX.Y.Z. Releases normales incrementan X o Y y reinician los números subordinados; Z=0. Hotfix y bugfix son tipos explícitos equivalentes para validación, incrementan Z y solo contienen fixes. Exigen el último tag publicado de su línea y ascendencia del commit publicado. El kit registra evidencia; no crea tags ni despliega. Archivos históricos no se reescriben.

La revisión independiente es opcional por target. Su política y el historial se guardan en reviews/policy.json; el dictamen y su evidencia están en el informe del componente. Huellas verificables detectan cambios declarados, no acreditan independencia ni ejecución. Los gates globales no cambian por participar: las skills comprueban informes y decisiones de salida del piloto. Se rechazó hacer obligatorio un proceso aún sujeto a evaluación.

El coordinador lee configuración y artefactos, nunca convenciones de nombres de repositorios. El producto generado se adopta con rutas explícitas/configurables y sin sobrescribir fuentes. Se admite reutilización de prototipos con aprobación de origen y del alcance actual; el amendment no omite una revisión visual cuando cambia la interacción.

## Compatibilidad y verificación

Plantillas y constitución ya instaladas son propiedad del consumidor. Refresh solo cambia assets administrados, incluidas referencias; los aliases proceden de las skills nativas. Un wheel y un informe de harness por etapa dejan evidencia de instalación real para Codex y Claude. Las pruebas deterministas no equivalen a evaluar agentes ni a acreditar publicación real.
