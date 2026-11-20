# Visor del proyecto (`roclec view`)

El visor es un complemento opcional de solo lectura. Abre un proyecto con RK (perfil 3, `model_schema: 2`) en el navegador para responder qué falta para una release, de dónde viene cada resultado y qué dice la documentación. El plan de diseño está en [plan-visor-roclec.md](strategy/plan-visor-roclec.md).

## Instalar y abrir

```bash
pip install 'roclec-spec-kit[viewer]'
roclec view
```

`roclec view` busca la raíz del proyecto hacia arriba desde el directorio actual, igual que el resto de comandos. Para elegir otra raíz:

```bash
roclec --project /ruta/al/proyecto view
```

| Opción | Efecto |
| --- | --- |
| `--no-open` | Imprime la URL sin abrir el navegador. |
| `--port N` | Usa el puerto `N`. Sin esta opción elige uno disponible. |

El proceso queda en primer plano y se cierra con `Ctrl+C`. El wheel base no instala Flask: sin el extra, `roclec view` termina con `VIEWER_UNAVAILABLE` y la instrucción de instalación. El resto de la CLI no cambia.

## Qué muestra

| Vista | Para qué sirve |
| --- | --- |
| **Releases** | Selector de componente y versión, barras por etapa con conteos, tabla filtrable de miembros, resultado del gate final y estado de la publicación. |
| **Cambio** | Revisión aprobada (y las anteriores), línea de etapas por componente, requisitos afectados con enlaces a la base y a la propuesta. Los fixes y refactors muestran sus contratos de base y su alcance. |
| **Requisito** | Enunciado, criterios de aceptación y cobertura por componente: cubierto, pendiente, desfavorable, desactualizado, interrumpido o sin evaluar. |
| **Evidencia** | Runs ejecutados por Roclec e informes declarados por una persona, con candidato, criterios, limitaciones y procedencia. |
| **Documentación** | Árbol de `docs/`, `specs/` y las referencias declaradas; búsqueda por texto, ruta o identificador (`REQ-001`, `AC-001`, `CHG-001`). |

La URL conserva componente, versión, revisión y filtro. Atrás restaura la lista filtrada y la ruta de navegación mantiene **Release → Cambio → Requisito → Evidencia**.

## Qué hace y qué no hace

- **Solo lectura.** No ejecuta checks, no consulta remotos Git y no escribe en el proyecto. El servidor define `GIT_OPTIONAL_LOCKS=0` para que las consultas de estado no actualicen el índice de Git.
- **El gate coincide con la CLI.** Para una release en planificación evalúa la misma lógica que `check --gate release` y conserva código, mensaje y campos del diagnóstico. Una release publicada se lee desde su registro de publicación y preparación, sin volver a evaluar el gate sobre el árbol actual.
- **Una conclusión por vez.** El visor presenta lo que RK devuelve. Si el gate se detiene antes de evaluar la cobertura, los criterios sin conclusión aparecen como **Sin evaluar**. La revisión independiente es una condición aparte.
- **Solo en este equipo.** Escucha en `127.0.0.1`, rechaza `Host` y `Origin` ajenos, no habilita el modo debug ni la recarga automática y sirve la interfaz y la API desde el mismo origen.
- **Alcance de lectura.** Solo Markdown de `docs/`, `specs/` y las referencias declaradas dentro de la raíz, más los textos normativos de `.roclec` leídos por los lectores de snapshots. Se rechazan rutas fuera del proyecto, enlaces simbólicos y archivos de más de 512 KiB. `.git`, el runtime y los logs crudos nunca se sirven; un run solo muestra los metadatos de log del manifiesto.
- **Markdown inerte.** El HTML crudo se omite y solo se permiten enlaces `http`, `https`, `mailto`, anclas y rutas relativas dentro del alcance.

## Actualizar y detectar cambios

El botón **Actualizar** recarga el modelo y reconstruye el índice de documentos. Cada respuesta lleva una huella del estado del repositorio (registros de `.roclec`, `HEAD`, rama y cambios locales sin commit). Si cambia mientras se lee, la consulta se rechaza con `repository_changed`; si cambia entre dos consultas, el visor muestra un aviso con **Recargar** en lugar de mezclar dos estados. El índice de búsqueda se reconstruye cuando cambia la huella, así que tras cambiar de rama no aparecen resultados de la anterior.

## Resolución de errores

| Mensaje | Qué significa | Qué hacer |
| --- | --- | --- |
| `VIEWER_UNAVAILABLE` al ejecutar `roclec view` | Falta el extra `viewer` o esta instalación no trae la interfaz compilada. | `pip install 'roclec-spec-kit[viewer]'`, o reinstala el wheel publicado. |
| `No se encontró el recurso` (`not_found`) | La release, el cambio, el requisito o el run no existe, o el recurso está fuera del alcance de lectura. | Revisa el enlace; usa **Actualizar** si lo creó otra rama. |
| `Registro inválido` (`invalid_record`) | Un registro de `.roclec` falló su validación (hash, esquema o referencia). | Ejecuta `roclec check` y corrige el registro que reporta. |
| `La consulta falló` con `IO_PARTIAL` | Hay una operación local interrumpida. | `roclec operation recover <id>` y pulsa **Actualizar**. |
| `La consulta falló` con `OPERATION_CONFLICT` | Otra operación local tiene el bloqueo del proyecto. | Espera a que termine y pulsa **Actualizar**. |
| `El repositorio cambió durante la lectura` (`repository_changed`) | Cambió la rama o un archivo mientras se leía. | Pulsa **Recargar**. |
| `Host not allowed` / `Origin not allowed` | La petición no viene de `127.0.0.1` o `localhost`. | Abre la URL que imprime `roclec view`. |

## Desarrollo

La interfaz es React y TypeScript con Vite, en `viewer-ui/`. El bundle compilado se versiona en `src/roclec_spec_kit/viewer/static/` y viaja en el wheel, de modo que instalar el visor no requiere Node.

```bash
python3 scripts/build_viewer.py          # npm ci + build hacia viewer/static
python3 scripts/build_viewer.py --check  # falla si el bundle versionado está desactualizado (CI)
```

Para iterar sobre la interfaz, ejecuta `roclec view --no-open --port 8765` y, en `viewer-ui/`, `npm run dev` (Vite redirige `/api` a ese puerto).

Verificación de entrega:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
uv build
python3 scripts/harness.py --wheel dist/roclec_spec_kit-0.9.0.dev0-py3-none-any.whl --report /tmp/roclec-viewer.json --viewer
```

`--viewer` instala el wheel sin el extra para comprobar el mensaje de instalación y luego con el extra (necesita un índice de paquetes para Flask), inicia `roclec view` desde un subdirectorio de un consumidor sintético y compara la API con la CLI: gate de la release, membresía, listas, publicación histórica, cobertura por componente, evidencia sustituida, run interrumpido, alcance de lectura y cambio de rama.

Los assets de marca y las tipografías incluidos tienen su procedencia en `viewer-ui/src/assets/brand/PROVENANCE.md`.
