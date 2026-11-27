# Contribuir a ChatIApp

¡Gracias por tu interés! ChatIApp está en **diseño abierto**: la documentación y el backlog están publicados y el código empieza por hitos. Hoy la contribución más valiosa es **opinar sobre el diseño** antes de que se construya.

*English speakers: issues and PRs in English are welcome. The docs and backlog are in Spanish, the project's primary language.*

## Formas de contribuir

| Quieres… | Haz esto |
|---|---|
| Opinar sobre una decisión | Comenta en la épica o tarea correspondiente, o abre un issue con la plantilla **Idea** |
| Reportar un error en la documentación | Abre un issue **Error** o envía un PR directo |
| Proponer una funcionalidad | Plantilla **Idea**: el problema primero, la solución después |
| Desarrollar una tarea | Elige un issue con `tipo:tarea` sin asignar, comenta que lo tomas y sigue el flujo de abajo |

## Cómo se escribe una tarea

Cada tarea del backlog sigue el mismo formato, pensado para que **cualquier persona o agente que no conoce el repo** sepa qué hacer, dónde y cómo comprobar que terminó:

| Sección | Qué contiene |
|---|---|
| **Objetivo** | Un solo resultado y su motivo |
| **Criterios de aceptación** | Casillas `- [ ]`, cada una verificable con un comando o una prueba |
| **Archivos relevantes** | Dónde se trabaja y qué pruebas deben seguir pasando |
| **Tamaño** | S (hasta medio día), M (1 a 2 días), L (3 a 5 días). Si no cabe en L, se divide |
| **Notas** | Épica, dependencias (`Depende de #N`) y documentación de referencia |

Las épicas agrupan tareas como *sub-issues* y las dependencias se registran como relaciones *blocked by* de GitHub, así el orden de trabajo es explícito.

## Etiquetas

| Grupo | Etiquetas |
|---|---|
| Tipo | `tipo:épica`, `tipo:tarea`, `tipo:spike`, `tipo:bug`, `tipo:idea` |
| Área | `área:backend`, `área:frontend`, `área:ia`, `área:datos`, `área:seguridad`, `área:infra`, `área:calidad`, `área:docs` |
| Prioridad | `p0` (bloquea el hito), `p1` (necesaria para el hito), `p2` (mejora) |
| Tamaño | `size:s`, `size:m`, `size:l` |

## Flujo de trabajo

1. Rama desde `main`: `tarea/<número>-<descripción-corta>` (por ejemplo `tarea/42-resolutor-periodos`).
2. Commits pequeños en español, en imperativo y explicando el porqué: `Agregar el resolutor de «últimos N días»`.
3. Pruebas y verificaciones locales en verde (`make check` cuando exista el código).
4. PR con la plantilla, enlazando el issue (`Cierra #42`) y marcando los criterios cumplidos.
5. Una revisión aprobada y CI en verde para fusionar.

## Definición de terminado

- Todos los criterios de aceptación del issue están marcados y son verificables.
- Pruebas nuevas para el comportamiento nuevo; las existentes siguen pasando.
- Lint y tipos sin errores.
- Si cambia un contrato (API, modelo semántico, eventos SSE, configuración), la documentación en `docs/` se actualiza en el mismo PR.
- Sin secretos, credenciales ni datos reales en el código, las pruebas o los logs.

## Decisiones de diseño

Si tu propuesta cambia una decisión registrada en [`docs/adr/`](docs/adr/), escribe un ADR nuevo que la reemplace y explica por qué. Las decisiones aceptadas no se editan.

## Cambios en la API

La API publicada bajo `/api/v1` tiene su especificación en `docs/openapi/v1.json`, que debe mantenerse sincronizada con `/api/v1/openapi.json`. Antes de v1.0.0, anuncia cada cambio del contrato en `CHANGELOG.md`. Desde v1.0.0, los cambios incompatibles deben introducirse en `/api/v2`; anuncia las retiradas con las cabeceras `Deprecation` y `Sunset` con al menos seis meses de aviso. Para implementarlas en FastAPI, marca la operación `deprecated=True` y añade `Depends(deprecation_headers(...))`. CI compara la especificación del PR con `main`; para anunciar un cambio incompatible, añade la etiqueta `api:cambio-incompatible` y una entrada en el changelog.

## Conducta

Se espera trato respetuoso y constructivo. Critica ideas, no personas.
