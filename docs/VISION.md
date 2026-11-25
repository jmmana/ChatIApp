# Visión

> Que cualquier persona de un negocio obtenga un dato confiable de su base de datos en segundos, preguntando en su idioma, sin que nadie tenga que confiar a ciegas en lo que «dijo la IA».

## El problema

En casi cualquier empresa pasa lo mismo:

- La pregunta es simple, *«¿cuánto vendimos este mes en Medellín?»*, pero la respuesta depende de una persona que sepa SQL, conozca la base y tenga tiempo. Pasan días.
- Los tableros de BI responden lo que alguien previó. La pregunta de hoy casi nunca está en el tablero.
- Las herramientas de *text-to-SQL* con IA son rápidas pero **frágiles**: adivinan el período, confunden `total` con `subtotal`, no saben que las facturas anuladas no cuentan, y algunas ejecutan lo que el modelo escriba. Un número equivocado dicho con seguridad es peor que no tener número.

## Para quién

| Persona | Qué necesita | Qué le da ChatIApp |
|---|---|---|
| **Gerente o dueño de negocio** | El dato, ya, y poder confiar en él | Pregunta en lenguaje natural; si algo falta, ChatIApp pregunta; ve el razonamiento y el SQL |
| **Analista de datos** | Que las respuestas usen las definiciones oficiales del negocio | Estudio del modelo semántico y catálogo de métricas: define «ventas netas» una vez |
| **TI / administrador de datos** | Que nada toque la base sin control, y elegir el proveedor de IA | Guardián SQL, usuario de solo lectura, filtros por rol, auditoría, niveles de privacidad, cualquier proveedor |
| **Equipo de producto que integra** | Ofrecer «pregúntale a tus datos» dentro de su propia app, con su login y su marca | Contenedor listo, API `/api/v1` con API keys, chat embebible con tokens de sesión, SDKs de Python y TypeScript |

## Principios de producto

1. **Preguntar antes de adivinar.** Un dato faltante (período, métrica, entidad) se pregunta con opciones de un clic. Nunca se inventa en silencio.
2. **Mostrar el trabajo.** Cada respuesta trae su razonamiento, el período exacto, la tabla usada y el SQL. La confianza se gana siendo verificable.
3. **Determinista donde se pueda.** Fechas, SQL de métricas del catálogo, permisos y límites los decide código probado, no el modelo de IA. La IA entiende el lenguaje; el motor hace las cuentas.
4. **Seguro por defecto.** Solo lectura, lista blanca, datos personales ocultos y filtros por rol que se aplican aunque la IA no quiera.
5. **Neutral de proveedor.** Ningún proveedor de IA ni motor de base de datos es obligatorio. Cambiar de uno a otro es configuración, no código.
6. **Español primero, bilingüe siempre.** Fechas, números, sinónimos y respuestas pensados para español de Latinoamérica y España, con inglés al mismo nivel.

## Casos de uso

| # | Quién | Situación | Resultado esperado |
|---|---|---|---|
| 1 | Gerente | «¿Cuánto vendí?» | Pregunta el período con opciones; con «este mes» responde el total con el rango exacto |
| 2 | Gerente | «Ventas por sucursal del mes pasado» | Tabla por sucursal + gráfico de barras, desde la tabla resumida si aplica |
| 3 | Gerente | «¿Cómo vamos contra el mes pasado?» | Comparación con el período anterior equivalente (mismo número de días) |
| 4 | Gerente | «¿Y solo en Bogotá?» | Seguimiento: mantiene la métrica y el período, agrega el filtro; si hay varias tiendas «Bogotá», pregunta cuál |
| 5 | Gerente | «¿Qué es el ticket promedio?» | Explica la definición desde el catálogo, sin ejecutar SQL |
| 6 | Analista | Sube el diccionario de datos en Excel | Vista previa de lo que se agrega o cambia; aplica sin perder descripciones ya escritas |
| 7 | Analista | Define la métrica «margen bruto» | Prueba la métrica con un período y ve el SQL generado antes de publicarla |
| 8 | TI | Conecta DeepSeek y Claude | Prueba la conexión de ambos y los compara con el set de evaluación en exactitud, costo y latencia |
| 9 | TI | Un gerente de sucursal pregunta por todas las tiendas | El filtro del rol limita el resultado a sus sucursales; queda en la auditoría |
| 10 | Producto | Su portal de clientes necesita un chat de datos | Levanta el contenedor `api`, crea una API key y embebe `<chatiapp-chat>`; cada cliente ve solo lo suyo |
| 11 | Producto | Su backend genera reportes en lenguaje natural | Llama a `POST /api/v1/chat` con su API key y el usuario final; recibe el SQL validado y el resultado |

## Alcance del MVP (v0.1, hito M1)

- Una fuente de datos y un proveedor de IA configurados por archivo o por interfaz.
- Importar la estructura (DDL, diccionario CSV/XLSX, YAML) y editar descripciones en el Estudio del modelo.
- Catálogo de métricas, resolutor de períodos, tablas resumidas, guardián SQL y ejecución de solo lectura.
- Agente que pide aclaraciones y chat con razonamiento visible, SQL y resultados.
- Base de datos de demostración con su modelo semántico.

## Lo que ChatIApp no es

- **No escribe en tu base.** Nunca `INSERT`, `UPDATE`, `DELETE` ni DDL. Es una decisión de diseño, no una opción.
- **No reemplaza tu BI.** No guarda tableros ni hace ETL. Responde preguntas; si una respuesta se vuelve recurrente, el SQL está a la vista para llevarlo a tu herramienta de BI.
- **No entrena modelos** con tus datos ni los envía a ningún proveedor más allá de lo que permita el nivel de privacidad configurado.
- **No es multiempresa en v1.** Se instala en tu infraestructura (self-hosted). Un modo SaaS multiempresa queda fuera del alcance de v1. Integrarlo en tu propio producto sí está en el alcance: ver [INTEGRACION.md](INTEGRACION.md).

## Cómo sabremos que funciona

| Métrica | Meta v1.0 | Cómo se mide |
|---|---|---|
| Exactitud en el set dorado | ≥ 90 % con el modelo recomendado | Runner de evaluación (épica de calidad): compara resultados, no texto SQL |
| Aclaración cuando falta el período | 100 % de los casos | Casos del set dorado sin período en métricas con `requires_period` |
| SQL de escritura ejecutado | 0 | Suite adversarial del guardián en CI |
| Tiempo hasta la primera señal en el chat | < 500 ms | Primer evento SSE tras enviar la pregunta |
| Tiempo a respuesta (p50, proveedor cloud) | < 8 s | Trazas por turno |
| De `docker compose up` a la primera respuesta | < 5 min | Guía de inicio rápido con la demo |
