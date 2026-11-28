# Set dorado de evaluación

Preguntas con respuesta conocida para medir la exactitud de ChatIApp con cada modelo. El runner (`backend/app/eval/`, tarea aparte) compara **resultados, no texto SQL**.

```
evals/
├── README.md
└── ventas/                  # set sobre la demo «Ventas» (examples/ventas/)
    ├── set.yaml             # datos sobre los que se calcularon los valores: --seed y --hasta
    ├── casos/*.yaml         # un archivo por categoría; cada archivo es una lista de casos
    └── valores.json         # resultados esperados congelados (generado, no se edita a mano)
```

## Los datos: `set.yaml`

```yaml
name: ventas
dataset: { seed: 42, hasta: 2026-11-25 }   # python -m app.demo.seed --seed 42 --hasta 2026-11-25
role: gerencia_general                      # rol con el que se pregunta (ve todas las sucursales)
minimos: { es: 60, en: 20 }                 # casos mínimos por idioma
```

«Hoy» en las preguntas es `dataset.hasta` (miércoles 25 de noviembre de 2026), igual que en la tabla del resolutor de [docs/FLUJO_CONVERSACIONAL.md](../docs/FLUJO_CONVERSACIONAL.md#resolutor-de-períodos). Cambiar `seed` o `hasta` invalida los valores: hay que revisar los SQL y volver a congelar.

## Un caso

```yaml
- id: per-es-mes-pasado          # único; minúsculas, dígitos y guiones
  lang: es                       # es | en
  question: "Ventas del mes pasado"
  previous: []                   # opcional: preguntas anteriores del mismo hilo (seguimientos)
  answers: []                    # opcional: respuestas a las aclaraciones, en orden
  tags: [periodo, periodo:mes-pasado]
  expect:                        # exactamente una de: expect | expect_clarification | expect_out_of_scope
    sql: "SELECT SUM(f.total) AS ventas_netas FROM facturas f WHERE f.estado = 'PAGADA' AND f.fecha >= '2026-10-01' AND f.fecha < '2026-11-01'"
    ordered: false               # true si el orden de las filas importa (rankings, series)
```

| Campo | Obligatorio | Significado |
|---|---|---|
| `id` | sí | Identificador estable; es la llave en `valores.json` |
| `lang` | sí | Idioma de la pregunta |
| `question` | sí | Pregunta final del usuario |
| `previous` | no | Preguntas previas del hilo. El runner las ejecuta antes y `question` es el seguimiento («¿Y por sucursal?») |
| `answers` | no | Lo que el usuario responde a cada aclaración, en orden. Solo con `expect`: el caso termina con respuesta tras aclarar |
| `tags` | sí | Al menos una. Sirven para reportar exactitud por categoría |
| `expect.sql` | uno de tres | SQL **escrito a mano**, de solo lectura (`SELECT`/`WITH`), con fechas literales, que da la respuesta correcta |
| `expect.ordered` | no | Por defecto las filas se comparan sin orden |
| `expect_clarification.slot` | uno de tres | El agente debe preguntar, sin ejecutar nada: `period`, `metric`, `entity` o `dimension` (ver [«Cuándo pregunta»](../docs/FLUJO_CONVERSACIONAL.md#cuándo-pregunta)) |
| `expect_out_of_scope: true` | uno de tres | El agente debe rechazar o explicar que no puede (clima, escritura, columnas ocultas, inyección…), sin ejecutar SQL |

Los valores no se escriben en el caso: se calculan con `expect.sql` y quedan en `valores.json` (`{dataset, casos: {id: {columns, rows}}}`). Los números se comparan con tolerancia de 0,005; las filas, sin orden salvo `ordered: true`.

Etiquetas que el set debe cubrir: `metrica`, `dimension`, `filtro`, `periodo`, `aclaracion`, `seguimiento`, `sql_libre`, `fuera_de_alcance`. Los casos de la tabla del resolutor llevan además `periodo:<expresión>`.

## Flujo de trabajo

Desde `backend/`:

```bash
# 1. Comprobar que cada caso es ejecutable (forma, mínimos, cobertura y SQL contra la demo)
uv run python -m app.eval.golden --validar

# 2. Tras añadir o cambiar casos: recalcular los valores esperados y revisarlos en el diff
uv run python -m app.eval.golden --congelar

# 3. Exigir además que cada caso tenga valores y que coincidan con la base
uv run python -m app.eval.golden --validar --estricto
```

El validador genera la demo en un directorio temporal con el `seed` y `hasta` de `set.yaml` y ejecuta el SQL en una conexión de solo lectura. Falla si hay ids repetidos, menos casos de los mínimos, etiquetas sin cubrir, SQL que no es una única consulta de lectura, SQL que no se ejecuta o no devuelve datos, o valores guardados que ya no coinciden.

Al escribir SQL a mano: cuenta solo facturas `PAGADA` salvo que la pregunta pida otro estado, usa rangos semiabiertos `fecha >= inicio AND fecha < fin`, y desempata los rankings con una segunda columna para que el resultado sea determinista.

## Runner por proveedor

Corre todos los casos contra cada proveedor guardado en la base de la app (los de `chatiapp.yaml` quedan ahí al arrancar), por la misma ruta que el chat. Desde `backend/`:

```bash
uv run python -m app.eval run --set evals/ventas --providers claude,deepseek
```

`--providers` son nombres de proveedor (su `id` en `chatiapp.yaml`).

**Control de gasto.** Con proveedores reales (todo `kind` distinto de `fake`) el comando es un **ensayo por defecto**: imprime cuántas llamadas haría (cota superior: 2 por turno) y para qué proveedores y modelos, y sale con 0 sin llamar a nadie. Para ejecutar de verdad:

```bash
uv run python -m app.eval run --providers claude,deepseek --max-calls 400 --yes
```

- `--yes`: confirma la ejecución real.
- `--max-calls N`: obligatorio con `--yes` si hay proveedores reales. Si el plan supera N, sale con error (código 2) sin hacer ninguna llamada; si aun así se llegara a N durante la corrida, se aborta (código 3), indica cuántas llamadas hizo y no escribe informe.
- Los proveedores `fake` o grabados siguen siendo gratis y no necesitan ninguna de las dos opciones. Las claves nunca se imprimen ni se escriben en el informe.

Otras opciones: `--model` (modelo semántico, por defecto `examples/ventas/semantic-model.yaml`) y `--out` (carpeta del informe, por defecto `eval-reports/`).

- **Exactitud**: se ejecuta `expect.sql` sobre la demo y se comparan las **filas** con las del evento `result` del turno (tolerancia numérica de 0,005; sin orden salvo `ordered: true`). Con `expect_clarification` el caso pasa si el agente pregunta por ese `slot` sin ejecutar nada; con `expect_out_of_scope`, si no ejecuta ninguna consulta ni pregunta (un rechazo del guardián cuenta; un fallo del proveedor, no). Con `answers`, tras cada aclaración se envía la siguiente respuesta y se evalúa el último turno.
- **Informe**: `<set>.md` y `<set>.json` en `--out`. Trae, por proveedor, la exactitud global (fracción de 0 a 1 en el JSON) y por etiqueta, las aclaraciones correctas e innecesarias, la latencia p50 y p95 (por caso, sin contar las preguntas de `previous`), los tokens y el costo (con todos los turnos), y los casos fallidos con su SQL y el esperado.
- **Historial**: guarda un `EVAL_RUN` por proveedor (`accuracy`, `p50_latency_ms`, `cost_usd` y el informe completo en `details`). Las conversaciones de la evaluación van a una base temporal: la base de la app solo recibe los `EVAL_RUN`.

## Evaluación en CI con planes grabados

`evals/recorded/<set>.json` guarda, por caso, el plan que «responde» el proveedor en cada turno (`previous`, pregunta y `answers`). El proveedor grabado (`backend/app/eval/recorded.py`) no usa red ni tokens: con planes fijos el motor es determinista, así que la exactitud esperada es **100 %** y cualquier caída es una regresión del motor o del agente (no del modelo). Desde `backend/`:

```bash
uv run python -m app.eval.recorded --set evals/ventas --out eval-reports --min-accuracy 1.0 --summary "$GITHUB_STEP_SUMMARY"
```

Escribe `<set>-grabado.md` y `.json` en `--out`, añade el Markdown a `--summary` y sale con 1 si la exactitud queda bajo `--min-accuracy` (2 si falta la grabación de algún caso).

Los planes de los casos con `expect` son `intent: sql` con el `expect.sql` del caso: miden guardián, ejecutor, aclaraciones y comparación de resultados, pero **no** el compilador de métricas del catálogo. Al añadir un caso al set hay que añadir su grabación (el comando falla si falta). Pasar a planes `metric` es una mejora aparte.
