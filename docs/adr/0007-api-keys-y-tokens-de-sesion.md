# ADR 0007 · API keys de servidor y tokens de sesión cortos para integrar ChatIApp

- **Estado:** aceptada
- **Fecha:** 2026-11-25

## Contexto

ChatIApp no solo se usa como aplicación: también se descarga como contenedor y se integra en el producto de otra empresa. Esa integración tiene dos formas: el backend del anfitrión llama a la API, o su frontend muestra el chat embebido. Hay que autenticar a la aplicación anfitriona, saber en nombre de qué usuario final se pregunta (los filtros por rol dependen de eso) y no exponer credenciales en el navegador.

## Decisión

1. **API keys de servidor** con formato `chia_<id>_<secreto>`, guardadas solo como hash HMAC-SHA256, con alcances (`chat`, `embed`, `sql:preview`, `semantic:read`, `semantic:write`), fuentes permitidas, roles permitidos o rol fijo, orígenes permitidos, límites propios, expiración y revocación.
2. **Identidad delegada:** cada llamada con API key declara el usuario final (`id`, `role`, `attributes`). ChatIApp confía en el anfitrión **dentro del techo de la key**: rol permitido y atributos obligatorios presentes. El usuario final queda auditado.
3. **Tokens de sesión para el chat embebido:** el backend del anfitrión llama a `POST /api/v1/embed/sessions` con su key y recibe un JWT firmado por ChatIApp, de 15 minutos por defecto, con alcance solo de chat, atado a un usuario, una fuente, un rol, sus atributos y un origen. El navegador solo ve ese token. Revocar la key invalida sus tokens.
4. **API versionada** en `/api/v1` desde el primer endpoint, con OpenAPI publicado y verificación de compatibilidad en CI.

## Consecuencias

- ✅ Ninguna credencial de larga vida llega al navegador.
- ✅ El anfitrión conserva su propio login; ChatIApp no necesita conocer a sus usuarios de antemano.
- ✅ Los filtros por rol funcionan igual en la app completa, la API y el widget: el orquestador siempre recibe un usuario con rol y atributos.
- ✅ Cada key tiene sus límites y su consumo, útil para repartir costos entre integraciones.
- ⚠️ El anfitrión puede afirmar cualquier usuario dentro del techo de su key. Es el modelo esperado para una credencial de servidor y se documenta así; para restringir más, se usa un rol fijo.
- ⚠️ Prefijar todo con `/api/v1` cambia rutas ya escritas en el backlog; se hace ahora, antes de que exista código.

## Alternativas consideradas

- **API key en el frontend con restricción por dominio.** Simple, pero la key queda a la vista de cualquiera y el dominio se falsifica fuera del navegador.
- **Incrustación firmada por el anfitrión** (el anfitrión firma un JWT con un secreto compartido, al estilo de algunos BI). Evita una llamada, pero obliga a cada anfitrión a implementar la firma correctamente y complica revocar y limitar. Puede agregarse después como opción.
- **OAuth 2.0 completo** (client credentials y token exchange). Estándar y potente, pero excesivo para el caso inicial. El diseño de alcances y tokens es compatible con migrar a él.
