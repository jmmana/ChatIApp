# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); las versiones siguen [SemVer](https://semver.org/lang/es/).

## [Sin publicar]

## [0.1.0] - 2026-11-27

Primera versión usable: pregunta a tu base de datos en lenguaje natural y recibe una respuesta con su razonamiento a la vista.

### Añadido

- Chat con respuesta en streaming y razonamiento visible; el agente pide el período cuando la pregunta lo necesita, reintenta el plan con el error de verificación y no añade dimensiones que la pregunta no pide.
- Modelo semántico en YAML (métricas, tablas resumidas, relaciones, roles con tablas ocultas y filtros por fila) y pantallas para editarlo, importar la estructura de la base, probar métricas y pedir sugerencias a la IA.
- Guardián de SQL ([sqlguardllm](https://github.com/jmmana/sqlguardllm)): solo `SELECT` permitido por el modelo semántico y el rol del usuario.
- Hub de proveedores de IA con enrutamiento por tarea y respaldo entre proveedores; Ollama local incluido.
- Niveles de privacidad hacia el modelo (`schema`, `aggregates`, `samples`) y defensa contra inyección de prompt directa e indirecta, con pruebas.
- Usuarios y roles, «Ver como», claves de API, auditoría y métricas Prometheus.
- Integración en otras apps: `POST /api/v1/chat` sin streaming, chat embebible (`<chatiapp-chat>` y paquete React) con sesiones de corta duración, contrato `/api/v1` versionado con OpenAPI publicado en `docs/openapi/v1.json` y control de cambios incompatibles en CI.
- Pantalla de evaluación para comparar proveedores y runner de evaluación con planes grabados que corre en CI y exige 100 %.
- Demo «Ventas (demo)» creada al arrancar; imagen única con SQLite y perfiles de Compose para PostgreSQL y Ollama; chart de Helm para Kubernetes probado en `kind`.
- Accesibilidad AA, tema oscuro y diseño responsive, con pruebas E2E en CI.

### Cambiado

- GitHub Models se retira del catálogo de proveedores: GitHub lo cerró el 30 de julio de 2026. La suscripción de Copilot (`github_copilot/`) tampoco se ofrece; el análisis está en `docs/spikes/github-copilot.md`.

### Limitaciones conocidas

- Con modelos pequeños (7B) el planificador puede equivocarse; hay un reintento con el error de verificación, pero conviene un modelo mayor para uso real.
- La verificación manual con un proveedor de pago (10 preguntas de la demo) está pendiente.
- Los SDKs de Python y TypeScript generados desde OpenAPI y la app anfitriona de ejemplo están en desarrollo y no forman parte de esta versión.
