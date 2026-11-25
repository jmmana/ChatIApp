# ADR 0001 · La IA propone, el motor dispone

- **Estado:** aceptada
- **Fecha:** 2026-11-25

## Contexto

El enfoque más simple de *text-to-SQL* es pedirle al modelo de IA que escriba el SQL completo a partir de la pregunta y el esquema. Funciona en demos y falla en producción de formas difíciles de detectar:

- Calcula mal las fechas («este mes» con el mes equivocado, zonas horarias, semanas que empiezan en domingo).
- Cada vez interpreta distinto la misma métrica (`SUM(total)` hoy, `SUM(subtotal)` mañana).
- No sabe cuándo usar una tabla resumida, o la usa cuando no debe.
- Si no hay período, lo inventa en vez de preguntar.

## Decisión

Separar **entender** de **calcular**:

1. La IA devuelve un **plan estructurado** (JSON validado con Pydantic): intención, métrica, dimensiones, filtros, el período *como lo dijo el usuario*, y si falta algo, la aclaración.
2. Código determinista hace el resto: resuelve el período en fechas, verifica que métrica, dimensiones y filtros existan y estén permitidos, elige la tabla resumida y arma el SQL de las métricas del catálogo.
3. La IA solo escribe SQL cuando la pregunta no corresponde a ninguna métrica del catálogo, y ese SQL pasa por el mismo guardián.

## Consecuencias

- ✅ La misma pregunta produce el mismo SQL para las métricas del catálogo: resultados reproducibles y auditables.
- ✅ El motor se prueba sin red ni IA, con pruebas unitarias rápidas.
- ✅ Un modelo más barato basta para planear, porque no tiene que escribir SQL complejo.
- ⚠️ Hay que mantener un catálogo de métricas. Se mitiga con el Estudio del modelo, sugerencias de IA y la ruta de SQL libre para lo que no está en el catálogo.
- ⚠️ El resolutor de períodos debe cubrir muchas expresiones en dos idiomas; lo que no reconozca se pregunta, no se adivina.

## Alternativas consideradas

- **SQL directo de la IA con validación posterior.** Más simple, pero los errores semánticos (fechas, métrica equivocada) pasan cualquier validación sintáctica.
- **Capa semántica externa (dbt Semantic Layer, Cube).** Potente, pero obliga a adoptar otra herramienta; ChatIApp debe funcionar con solo un esquema y unas descripciones. Integrarse con ellas queda como posible extensión.
