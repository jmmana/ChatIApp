# ADR 0003 · sqlglot como guardián y traductor de dialectos

- **Estado:** aceptada
- **Fecha:** 2026-11-25

## Contexto

Todo SQL que llega a la base debe ser de solo lectura, tocar solo lo permitido y llevar el filtro del rol. Validar SQL con expresiones regulares es frágil: no distingue un `DELETE` dentro de un comentario de uno dentro de un CTE, ni un `SELECT … INTO` de un `SELECT`. Además, el motor genera SQL para 7 dialectos con diferencias de fechas, truncado y límites.

## Decisión

Usar [sqlglot](https://github.com/tobymao/sqlglot) para:

1. **Analizar** el SQL en el dialecto de la fuente y obtener el árbol sintáctico.
2. **Validar** recorriendo el árbol completo: una sola sentencia, raíz de consulta, ningún nodo de escritura en ningún nivel, tablas y columnas en lista blanca, funciones prohibidas.
3. **Reescribir**: inyectar el filtro del rol ([ADR 0004](0004-filtro-por-rol-como-tabla-derivada.md)) y aplicar el límite de filas.
4. **Regenerar** el SQL desde el árbol en el dialecto destino: lo que se ejecuta es exactamente lo que se validó.

Comprobado con sqlglot 30.35:

- Ida y vuelta en `sqlite`, `postgres`, `mysql`, `tsql`, `oracle`, `snowflake` y `bigquery`.
- El límite se genera como `LIMIT n`, `TOP n` (SQL Server) o `FETCH FIRST n ROWS ONLY` (Oracle) según el dialecto.
- Detecta escrituras escondidas: `SELECT … INTO` en SQL Server (nodo `Into`) y `DELETE` dentro de un CTE en PostgreSQL (nodo `Delete` bajo un `Select`).

## Consecuencias

- ✅ Validación estructural, no textual: robusta ante comentarios, mayúsculas, espacios y anidamiento.
- ✅ Un solo código para siete dialectos.
- ⚠️ sqlglot puede no reconocer extensiones raras de un motor. Política: **si no se puede analizar, no se ejecuta** (falla cerrado), y el caso se agrega a la suite.
- ⚠️ El SQL regenerado puede verse distinto del original (mayúsculas, alias explícitos); es el comportamiento deseado.

## Alternativas consideradas

- **Expresiones regulares o listas de palabras prohibidas.** Fáciles de evadir.
- **Solo permisos de la base.** Indispensables, pero no resuelven lista blanca de columnas, filtros por rol ni límites. Se usan **además**, no en lugar de.
- **Parsers por motor (pglast, etc.).** Más exactos para un motor, pero uno por dialecto.
