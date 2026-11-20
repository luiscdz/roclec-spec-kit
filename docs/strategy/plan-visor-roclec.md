# Plan de implementación de `roclec view`

**Propuesta de MVP · 19 de noviembre de 2026 · implementado: ver la [guía del visor](../visor.md).** La planificación de releases se mantiene en el [plan global](plan-global.md).

## Objetivo y alcance

Una persona que trabaja en un proyecto con RK puede abrir su carpeta, buscar documentación y responder qué falta para una release. Desde el gráfico puede llegar al cambio, al requisito y al registro que respalda cada resultado. El visor se instala una vez como complemento opcional de RK y consulta un proyecto por sesión desde el navegador.

El MVP incluye el tablero de releases por componente, el detalle de cambios, requisitos y evidencia, y un explorador de Markdown. La edición, la ejecución de checks, la gestión de Git, la publicación y el alojamiento compartido quedan fuera del alcance. La primera implementación apunta al perfil 3 y `model_schema: 2` de la CLI nativa.

## Experiencia y navegación

| Vista | Contenido | Interacción |
| --- | --- | --- |
| **Release** | Selector de componente y versión, barras apiladas con el conteo de miembros por etapa e indicadores separados para el gate final y la publicación. | Cada segmento filtra la tabla de miembros. El resultado del gate abre el motivo y enlaza las entidades que RK identifique. |
| **Cambio** | Revisión aprobada, línea de etapas por componente y lista de requisitos afectados. | Abrir la base o la propuesta cuando existan ambas revisiones. Los fixes y refactors muestran los contratos de base y su alcance declarado. |
| **Requisito** | Enunciado, componente, capacidad, revisión de contrato y tabla de criterios de aceptación aplicables. | Abrir el criterio, el check que lo cubre o el informe que respalda el resultado. |
| **Evidencia** | Tipo de registro, resultado, alcance, candidato, criterios, limitaciones y procedencia. | Consultar el manifiesto o el informe y volver al criterio. Identificar el origen de cada check e informe. |
| **Documentación** | Árbol de Markdown con búsqueda por título, contenido, ruta e identificador. | Abrir una coincidencia como documento o como entidad con su revisión identificada. |

La URL conserva componente, versión, revisión y filtro donde corresponda. El botón Atrás restaura la lista filtrada. Una ruta de navegación mantiene el contexto de **Release → Cambio → Requisito → Evidencia**. El tablero contempla un proyecto sin releases y una release sin miembros.

## Arquitectura y distribución

- **Comando.** Registrar `view` en `native_cli.py`. `roclec view` usa el descubrimiento de proyecto de RK y `roclec --project RUTA view` permite seleccionar la raíz. `--no-open` imprime la URL sin abrir el navegador. El proceso se mantiene en primer plano y se cierra con `Ctrl+C`. Si falta el extra `viewer`, el comando indica cómo instalar `roclec-spec-kit[viewer]`.
- **Servidor.** Módulo Python opcional dentro de RK, con Flask, enlazado a `127.0.0.1` en un puerto disponible. Servir la interfaz y una API JSON de lectura bajo `/api/v1` desde el mismo origen. Validar el host local y mantener desactivados el modo debug y la recarga automática del servidor distribuido.
- **Consultas.** Usar una capa de lectura que reutilice `Kernel`, `Releases` y `Verification`. Los resultados de `list`, `inspect` y `check` sirven como referencia para validar las proyecciones. Añadir lectores nativos acotados para las revisiones exactas y el detalle de cobertura que hoy no expone el JSON público. React presenta los estados que devuelve RK.
- **Frontend.** React y TypeScript con Vite y CSS con variables de marca. Compilar con un lockfile en desarrollo y CI. Incluir la interfaz compilada, fuentes y assets en el wheel para uso offline. El extra instala las dependencias Python del servidor y el wheel base sigue siendo instalable por sí solo.
- **Actualización.** Mostrar el proyecto y la rama o worktree. Un control **Actualizar** recarga el modelo y reconstruye el índice en memoria. Crear lectores nuevos en cada actualización. Comprobar que un cambio de rama o de archivos durante la captura se detecta antes de publicar una vista mezclada y ofrecer recargar. Probar también cambios locales sin commit.

### Contrato de lectura propuesto

| Consulta | Identidad | Respuesta mínima |
| --- | --- | --- |
| Lista de releases | Filtro opcional por componente | Componente, versión, tipo y estado de publicación. |
| Detalle de release | Componente y versión | Miembros, revisiones, conteos derivados de la misma tabla, resultado del gate o registro de publicación y enlace al contrato final disponible. |
| Detalle de cambio | Componente, versión, `CHG` e `intent_revision` | Etapa en ese alcance, deltas y vínculos a revisiones de contrato. |
| Detalle de requisito | Contexto de release o cambio, componente, `CAP`, revisión de contrato y `REQ` | Enunciado, criterios aplicables, estado por criterio y referencias a evidencia. |
| Detalle de evidencia | Contexto, `RUN` y, cuando corresponda, `EVD` o ID de check | Resultado, candidato, criterios, procedencia y limitaciones. |
| Árbol, documento y búsqueda | Ruta relativa validada o consulta de texto | Títulos, rutas, contenido Markdown o coincidencias con contexto y enlaces internos. |

Validar que cada entidad pertenece al contexto solicitado. Conservar el código, mensaje y campos de diagnóstico del gate. Distinguir un recurso ausente, un registro inválido, una consulta fallida y un repositorio que cambió durante la lectura. Cargar detalles y evaluar gates bajo demanda para evitar repetir verificaciones por cada fila de la lista.

## Reglas para representar el workflow

1. **Release en planificación.** Leer la pertenencia de `release.json`. Al abrir o actualizar el detalle, evaluar el gate final con la misma lógica que `check --gate release`. Mostrar el diagnóstico y su alcance. Una preparación existente se puede consultar como registro histórico aunque cambie el candidato. **5 de 5 cambios integrados · verificación final pendiente** es un estado válido.
2. **Release publicada.** Resolver contratos y evidencia desde la publicación y su preparación. Consultar el historial registrado sin evaluar el gate sobre el árbol actual. Si un registro válido tiene procedencia parcial, indicar qué detalles históricos están disponibles. [Guía C3](../c3.md)
3. **Cambio.** Leer la propuesta aprobada por `(CHG, intent_revision)` y resolver integración por `(CHG, componente, intent_revision)`. La línea de etapas usa decisiones, verificaciones e integraciones aplicables a esa revisión. Mostrar **Sin evaluar** cuando falta información para determinar una etapa. Los conteos de la release salen de las mismas filas que se pueden filtrar. [Kernel nativo](../../src/roclec_spec_kit/kernel.py)
4. **Requisito.** Mostrar cobertura por revisión, componente y criterio. Si dos miembros suceden un criterio dentro de la misma release, el gate final usa el criterio del contrato final y el anterior sigue accesible desde su cambio. Mantener visible si se está consultando una propuesta, el contrato vigente o una publicación.
5. **Evidencia.** Exponer el detalle por criterio a partir de la lógica de `Verification`, respetando el candidato, el alcance y la precedencia explícita de runs e informes. Distinguir evidencia aplicable, pendiente, desfavorable y sustituida o desactualizada. Si el gate se detiene antes de evaluar cobertura, mostrar **Sin evaluar** donde falte una conclusión. Presentar la revisión independiente como condición separada cuando la política la exige. [Verificación nativa](../../src/roclec_spec_kit/verification.py) · [Guía C2](../c2.md)

## Diseño de Roclec y lectura de documentos

- **Marca.** Tomar el brief, el lineamiento de documentos y los assets oficiales del repositorio Roclec, en `docs/docs/`. Registrar la procedencia de los archivos incluidos. Usar el símbolo oficial, Plus Jakarta Sans para títulos, Inter para lectura y controles, carbón para la navegación, superficies claras para el contenido y violeta para selección. Usar el verde como acento junto a una etiqueta.
- **Componentes.** Diseñar la barra lateral, el tablero, la línea de etapas y el lector como piezas reutilizables. Cada gráfico tiene conteos y etiquetas visibles, acceso por teclado y una tabla equivalente. Aplicar el tratamiento de tablas, notas y bloques de código del lineamiento de documentos. Probar textos largos, foco visible, contraste y pantallas estrechas.
- **Índice.** Incluir Markdown de `docs/`, `specs/` y referencias declaradas dentro de la raíz. Incorporar los textos normativos de `.roclec` mediante los lectores de snapshots para preservar revisión y procedencia. Permitir buscar por texto y coincidencia exacta de identificadores.
- **Límites de lectura.** Aplicar límites de tamaño, validar rutas relativas y resolver enlaces e imágenes dentro del alcance de lectura. Desactivar HTML crudo en Markdown y permitir únicamente esquemas de URL previstos. Excluir `.git`, runtime y logs crudos del árbol, la búsqueda y la API. El detalle de un run puede mostrar los metadatos de logs que deja el manifiesto.

## Secuencia de implementación

| Etapa | Trabajo | Salida verificable |
| --- | --- | --- |
| **1. Datos y diseño** | Definir las proyecciones JSON y prototipar el tablero y el lector con la marca. Identificar qué datos proveen los lectores nativos y diseñar la consulta de cobertura por criterio. | Una consulta sobre una release en planificación y otra publicada resuelven las revisiones exactas, los criterios y su evidencia. Reutilizar los escenarios C1–C3 que cubran esos estados. |
| **2. Comando y recorrido** | Añadir el extra y el comando, iniciar el servidor local y conectar las cuatro vistas. Implementar barras, tabla filtrable y línea de etapas. | El recorrido funciona en un proyecto aislado. El resultado del gate coincide con la CLI para el mismo estado del repositorio. |
| **3. Exploración y búsqueda** | Añadir árbol, lector, índice en memoria, enlaces cruzados y actualización. | Se puede llegar a un documento por texto o a una entidad por ID. Actualizar tras cambiar de rama omite los resultados de la rama anterior. |
| **4. Empaquetado y aceptación** | Integrar la compilación en CI, verificar contenido del wheel y probar la instalación con y sin el extra. Documentar el lanzamiento y la resolución de errores. | El wheel abre el visor sin Node ni acceso al repo de marca. El recorrido y la lectura se verifican en navegador. |

## Criterios de aceptación del MVP

1. **Instalación.** El wheel base conserva la CLI operativa y da una instrucción útil si se invoca `view` sin el extra. Con el extra, abre la raíz correcta desde un subdirectorio o mediante `--project`. Sirve los recursos de la interfaz localmente.
2. **Avance y bloqueos.** Una release con todos sus miembros integrados y un criterio pendiente muestra ambos hechos. El conteo del gráfico coincide con las filas filtradas y el diagnóstico coincide con `check --gate release`. Abrir y actualizar el visor no ejecuta checks, consulta remotos ni modifica los archivos del consumidor.
3. **Trazabilidad.** El recorrido lleva de una release a la revisión asignada de un cambio, su requisito y el registro que lo respalda. Una release publicada conserva sus contratos y evidencia cuando el proyecto avanza. Una propuesta posterior y un criterio sustituido siguen consultables en sus contextos respectivos.
4. **Evidencia.** Dos componentes que comparten un requisito muestran la cobertura de cada uno. Un run interrumpido, evidencia sustituida y una revisión requerida pendiente se distinguen sin marcar el gate como aprobado.
5. **Lectura.** Buscar por texto, `REQ` o `AC` abre el contexto correcto. El botón Atrás conserva filtros. Las rutas fuera del proyecto se rechazan, los logs crudos quedan inaccesibles y el Markdown con contenido activo se muestra sin ejecutarlo.
6. **Verificación de entrega.** Ejecutar `PYTHONPATH=src python3 -m unittest discover -s tests -v`, construir el wheel y probarlo instalado en un proyecto aislado. Añadir al harness un escenario del visor que compare CLI y API y cubra el recorrido publicado. Revisar las vistas con teclado y en un ancho estrecho.
