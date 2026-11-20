# ADR 005 — Verificación del candidato conjunto de release

**Fecha:** 2026-11-10. **Estado:** confirmado explícitamente por el usuario durante la implementación de C3. Complementa D1–D3 de [ADR 004](004-first-cut-interface-decisions.md).

Una release puede reunir varios CHG y esos cambios pueden sustituir criterios anteriores. La interfaz inicial `release prepare ... --run RUN` no fijaba si ese RUN cubría un cambio o el contrato conjunto. Se consultó al usuario entre añadir una verificación propia de release o reutilizar runs por cambio sobre el candidato final. Eligió **añadir verificación de release: un RUN cubre el contrato final de todos sus miembros**.

Se incorpora `run verify --release VERSION --component NAME --base REF`, excluyente con el selector CHG. La base publicada y las revisiones aprobadas de sus miembros determinan el contrato final por linaje explícito; no se acreditan automáticamente criterios sustituidos ni trabajo futuro de otras releases por estar integrado. Una corrección histórica usa su baseline publicado declarado. El RUN registra ámbito release, pertenencia/contratos y candidato, sin inventar una identidad CHG.

El gate release y prepare requieren este RUN, no transfieren pass de un cambio. Los runs por cambio siguen habilitando verificación e integración C2. Observaciones y revisión final citan el ámbito de release y sus entradas exactas. La revisión sigue siendo opcional por cambio: si algún miembro participa, la revisión final cubre el conjunto y queda ligada a la combinación de decisiones vigentes. No se crea adopción global ni se autentica la independencia del revisor.

Preparar fija el commit/manifiesto y la evidencia del conjunto. Metadatos posteriores pueden confirmarse en un descendiente con entradas idénticas; el registro de publicación conserva el commit preparado y comprueba su tag remoto. Esta decisión no autoriza crear/push tags, publicar el paquete ni desplegar el consumidor.
