# Política de seguridad

ChatIApp se ubica entre personas, modelos de IA y bases de datos empresariales: los reportes de seguridad tienen la máxima prioridad.

## Cómo reportar una vulnerabilidad

**No abras un issue público.** Usa el reporte privado de GitHub:

1. Ve a la pestaña [**Security**](https://github.com/jmmana/ChatIApp/security) del repositorio.
2. Haz clic en **Report a vulnerability**.
3. Describe el problema, cómo reproducirlo y su impacto.

Recibirás acuse en un máximo de **3 días hábiles** y una evaluación inicial en **10 días hábiles**. Te mantendremos al tanto hasta la corrección y te daremos crédito en el aviso, si lo deseas.

## Qué nos interesa especialmente

- SQL que logre escribir, leer columnas ocultas o saltarse el filtro de rol pese al guardián.
- Inyección de prompt que cambie permisos, filtros o límites.
- Exposición de credenciales de proveedores de IA o de bases de datos.
- Envío al proveedor de IA de datos por encima del nivel de privacidad configurado.

## Versiones soportadas

El proyecto está en diseño; no hay versiones publicadas todavía. A partir de v0.1 se corregirá la última versión menor publicada.

Modelo de amenazas y capas de defensa: [docs/SEGURIDAD.md](docs/SEGURIDAD.md).
