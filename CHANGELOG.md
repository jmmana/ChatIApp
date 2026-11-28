# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); las versiones siguen [SemVer](https://semver.org/lang/es/).

## [Sin publicar]

### Añadido

- Contrato de la API: `docs/openapi/v1.json` versionado, exportador `python -m app.api.openapi` y utilidad `deprecated_route` para anunciar retiros con las cabeceras `Deprecation` y `Sunset`.

## [0.1.0] - 2026-11-27

Primera versión usable: pregunta a tu base de datos en lenguaje natural y recibe una respuesta con su razonamiento a la vista.

### Añadido

- Chat con respuesta en streaming y razonamiento visible; el agente pide el período cuando la pregunta lo necesita.
- Modelo semántico en YAML (métricas, tablas resumidas, relaciones, roles con tablas ocultas y filtros por fila) y pantallas para editarlo, importar la estructura de la base y probar métricas.
- Guardián de SQL ([sqlguardllm](https://github.com/jmmana/sqlguardllm)): solo `SELECT` permitido por el modelo semántico y el rol del usuario.
- Hub de proveedores de IA con enrutamiento por tarea y respaldo entre proveedores; Ollama local incluido.
- Usuarios y roles, «Ver como», claves de API, auditoría y métricas Prometheus.
- Demo «Ventas (demo)» creada al arrancar; imagen única con SQLite y perfiles de Compose para PostgreSQL y Ollama.
- Accesibilidad AA, tema oscuro y diseño responsive.

### Limitaciones conocidas

- Con modelos pequeños (7B) el planificador puede equivocarse; hay un reintento con el error de verificación, pero conviene un modelo mayor para uso real.
- El chat embebible, los SDKs, el chart de Helm y la comparativa de modelos están en desarrollo y no forman parte de esta versión.
- La verificación manual con un proveedor de pago (10 preguntas) está pendiente.
