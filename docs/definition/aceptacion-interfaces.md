# Aceptación de las interfaces propuestas

**Estado:** C1, C2 y C3 implementados localmente. Resultados y límites en [evidencia C1](../implementation/c1.md), [C2](../implementation/c2.md) y [C3](../implementation/c3.md). No equivalen a la suite 0.7 ni a aceptación de producto. Autoridad de comportamiento: [interfaces](interfaces-primer-corte.md) y [verificación conjunta](../decisions/005-final-release-verification.md). Cada caso parte de un proyecto desechable y compara bytes/permisos autoritativos antes/después.

## Incrementos implementables

| Incremento | Entrega y por qué | Salida necesaria |
| --- | --- | --- |
| C1 — datos y consulta | Perfil 2, referencias, snapshots, vector vigente, borradores/deltas, FUT y pertenencia de release. Fijar autoridad antes de automatizar acciones | I-001–010, consulta de I-011, I-021–024, contratos JSON y wheel nativo; integración de I-011 espera C2 |
| C2 — evidencia e integración | Candidatos, checks reales, observaciones/revisión opcional, gates e integración recuperable. Corregir cobertura y vigencia en la misma entrega | Integración de I-011, I-012–020, I-025–027; interrupciones y concurrencia junto a su operación |
| C3 — cierre e instalación | Preparación/registro de publicación, inclusión real de fixes, skills y aliases desde fuentes nativas | I-028–033; wheel aislado, harness nativo y `--spec-kit` Codex/Claude, sin llamadas a modelos |

Son incrementos del mismo primer corte, no números de versión prometidos. Cada uno incluye validación y documentación. Los gates que dependen de otro incremento informan capacidad aún no disponible; no devuelven un pass vacío. No instalar una etapa parcial como si el piloto tuviera el flujo completo.

## Casos de datos y flujo

| Caso | Preparación / acción | Resultado observable |
| --- | --- | --- |
| I-001 | Inicializar con perfil 2 válido; primera capacidad con base null | Entradas mínimas sin contratos/release ficticios; adición permitida solo si el par sigue ausente; sin nombres/stack del piloto |
| I-002 | Perfil 1, JSON con clave duplicada, versión futura o ruta de contenido que escape mediante `..`/symlink | Exit 2, `UNSUPPORTED_SCHEMA` o entrada inválida; bytes previos intactos |
| I-003 | CAP-001 integrada; crear propuesta que retira AC-001 | `inspect`/cobertura vigente conservan AC-001 hasta integrar; regresión DEF-001 |
| I-004 | ID nuevo ya usado por otra obligación o delta que cita AC ajeno | `ID_COLLISION`/`INVALID_REFERENCE`; sin escritura parcial |
| I-005 | Consultar mismo REQ de dos snapshots | Resolver texto/AC de la revisión solicitada; nunca texto actual bajo enlace histórico |
| I-006 | Alterar Markdown sin cambiar su huella; descriptor reordenado o duplicado | Huella incorrecta rechazada; la serialización canónica válida tiene digest reproducible, duplicados inválidos |
| I-007 | Aprobar digest A; cambiar intención/base/alcance a B | Aprobación A conservada, B vuelve a draft; `APPROVAL_STALE` al intentar iniciar |
| I-008 | Cambiar solo comentario administrativo separado | No altera digest semántico; conservar historial de la edición |
| I-009 | Iniciar sin aprobación, referencias suficientes o asignación de release | Gate identifica el faltante; sin iniciar trabajo ni generar código |
| I-010 | Dos componentes en un repo; mutación sin componente | Rechazo de ambigüedad; `inspect --capability` sí puede mostrar el vector completo |
| I-011 | Dos componentes participantes; integrar el primero con evidencia válida | Solo avanza su par del índice, agregado `partially-integrated`; segundo sigue en base y conserva obligaciones |

## Candidatos, evidencia y recuperación

| Caso | Preparación / acción | Resultado observable |
| --- | --- | --- |
| I-012 | Candidato verificado; agregar un archivo fuente nuevo relevante | `CANDIDATE_INCOMPLETE`/`EVIDENCE_STALE`; ready anterior no habilita nuevo candidato; DEF-002 |
| I-013 | Archivo nuevo sin categoría o fuente ignorada por Git dentro del alcance | No asumir irrelevancia; clasificación explícita antes de declarar suficiencia; no leer secretos por defecto |
| I-014 | Check devuelve 0 pero faltan AC aplicables | Conservar pass del check; `COVERAGE_MISSING` impide verificar el componente |
| I-015 | Entradas cambian durante el check, falta herramienta o proceso se interrumpe | Run incomplete/fallo de entorno/interrupted, sin pass implícito; conservar resultado y limitación |
| I-016 | Importar informe manual sin ejecutar subprocess | Evidencia de origen manual/externo; nunca `executed_by_roclec=true` ni comandos inventados |
| I-017 | Revisión opcional desactivada, luego activada; informe ausente, changes-needed, incomplete, stale y finalmente ready vigente | Sin adopción no exige informe; activada bloquea verified/integración/preparación hasta ready vigente por componente. Ejecutar pruebas sigue permitido; run completado no implica cambio verified. Desactivar requiere usuario/motivo y conserva historia |
| I-018 | Desarrollo con worktree sucio; candidato final con staged/unstaged o untracked no ignorado en repo afectado | Desarrollo permitido; integrar/preparar rechazan con CANDIDATE_DIRTY hasta commit/manifiesto y repos limpios. Metadatos escritos por una operación se confirman antes del siguiente gate final si viven en el mismo repo; sin commits automáticos |
| I-019 | Mismos bytes/entradas relevantes bajo nuevo commit | Reutilización solo si ámbito, política, bases e inclusión también válidos; no transferir por SHA de HEAD únicamente |
| I-020 | Evolucionar misma obligación; luego proponer otra obligación | Primera conserva REQ con revisión inmutable y AC nuevo al cambiar conducta; segunda exige replace/retire explícito. Evidencia del AC viejo no cubre el nuevo |
| I-021 | FUT promoted sin destino o duplicate que apunta a sí mismo | Rechazo sin borrar descubrimiento; promoted con destino existente conserva origen y no aprueba ese cambio |
| I-022 | FUT descartado/reabierto tras decisión nueva | Historial de decisiones íntegro; ningún cambio/release creado por descarte |
| I-023 | Normal con Z>0; incremento válido X/Y; corrección Z=0, línea incorrecta o tag base ausente | Rechazos/aceptaciones según política acordada, sin exigir saltos consecutivos |
| I-024 | Misma revisión de cambio asignada dos veces al mismo componente; versión histórica v1.2 junto a v1.2.0 | Rechazo de ambigüedad/duplicado; no renombrar historia publicada |
| I-025 | Preparar integración A; otro cambio mueve la base antes de apply | Exit 3 `BASE_CONFLICT`; no sobrescribe índice ni registra A como aplicado |
| I-026 | Interrumpir tras snapshot, tras índice y antes del recibo | Journal detectable; recover completa solo operación compatible; segunda aplicación no duplica ni revierte avances posteriores |
| I-027 | Plan modificado para escribir fuera del destino, o dos procesos con igual base | Plan alterado rechazado; como máximo un avance sobre esa base; lock local no se presenta como coordinación remota |

## Releases, distribución y límites

| Caso | Preparación / acción | Resultado observable |
| --- | --- | --- |
| I-028 | Fix cita SHA inexistente, commit no incluido o backport no acreditado | `FIX_NOT_INCLUDED`; no preparación/publicación; DEF-003 |
| I-029 | Hotfix/bugfix contiene evolución/refactor, aun con versión patch válida | `VERSION_INVALID` o contenido inválido; solo fixes |
| I-030 | Preparación válida; cambia candidato, tag remoto apunta a otro SHA o solo existe local | No registrar publicación; conservar preparación anterior como histórica |
| I-031 | Dos componentes terminan distinto día; uno tiene dependencia explícita no satisfecha | Publicación independiente permitida salvo dependencia; vector nunca presenta ambos publicados por publicar uno |
| I-032 | Integrar revisión nueva después de publicar; intentar modificar registro publicado | Release anterior resuelve contrato/candidato originales; modificación publicada rechazada |
| I-033 | Construir/instalar wheel, refresh con archivos propios y adaptador opcional | Núcleo funciona sin spec-kit; aliases incluyen referencias válidas, no prompts duplicados; archivos propios preservados |

## Oráculos y evidencia del harness

Para preflight fallido, comparar contenido, existencia y permisos de todas las autoridades del consumidor, excluyendo únicamente logs externos explícitos. Para runs ejecutados comprobar que el resultado fallido permanece registrado y está distinguido de un rechazo previo sin escritura. Para recuperación inyectar fallos deterministas en cada límite de escritura, inspeccionar el journal y comparar el resultado final con una operación completa equivalente.

Cada resultado registra escenario, versión/wheel y huella, perfil, repos/candidato, comando, exit, comprobaciones, logs o sus huellas y limitaciones. Separar fallo de entorno/harness del comportamiento bajo prueba. Los ejemplos JSON comprueban integridad de documentación; no sustituyen estas ejecuciones.

La clasificación de un fix, suficiencia de un criterio, independencia de revisión y aprobación visual tienen rúbrica semántica y evidencia humana. Un esquema válido o una suite verde no resuelve esas cuestiones. El piloto implementará sus pruebas de recepción en su propio repo, con las ocho decisiones ya registradas y sin asumir aceptación comercial.
