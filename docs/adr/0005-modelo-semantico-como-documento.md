# ADR 0005 · El modelo semántico se guarda como documento versionado

- **Estado:** aceptada
- **Fecha:** 2026-11-25

## Contexto

El modelo semántico (tablas, columnas, relaciones, métricas, resumidas, roles) se importa desde archivos, se edita en la interfaz, se exporta a YAML para versionarlo en Git y se valida como un todo, porque sus partes se referencian entre sí (una métrica apunta a columnas, una resumida a métricas, un rol a tablas).

## Decisión

Guardar el modelo como **un documento JSON validado con Pydantic**, con una fila por versión (`semantic_model_version`). Cada publicación crea una versión nueva e inmutable; la vigente es la última.

## Consecuencias

- ✅ Validación cruzada completa en un solo paso antes de guardar.
- ✅ Importar y exportar YAML es una conversión directa, sin mapeo objeto-relacional.
- ✅ Historial, comparación entre versiones y vuelta atrás triviales.
- ✅ Cada consulta auditada puede guardar con qué versión del modelo se respondió.
- ⚠️ No se puede consultar «todas las columnas ocultas» con SQL sobre la BD de la app; no es un caso de uso. Si llega a serlo, se agregan índices derivados.
- ⚠️ Dos personas editando a la vez: se usa control optimista por número de versión (409 si alguien publicó antes).

## Alternativas consideradas

- **Tablas normalizadas** (`tables`, `columns`, `metrics`…). Más consultable, pero la validación cruzada se reparte en muchas restricciones y la importación/exportación necesita un mapeo grande.
- **Solo archivos YAML en disco.** Ideal para GitOps; se soporta vía `chatiapp.yaml` (`semantic_model: ./ruta.yaml`), pero la interfaz necesita poder editar y versionar sin acceso al repositorio.
