"""Informe de una evaluación: métricas por proveedor, en JSON y en Markdown."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from app.eval.runner import ResultadoCaso

Informe = dict[str, Any]


def percentil(valores: Sequence[float], q: float) -> float:
    """Percentil `q` (0-100) por rango más cercano; 0 si no hay valores."""
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    posicion = max(math.ceil(q / 100 * len(ordenados)), 1)
    return ordenados[posicion - 1]


def _exactitud(correctos: int, total: int) -> float:
    return correctos / total if total else 0.0


def resumir(proveedor: str, kind: str, modelo: str, resultados: Sequence[ResultadoCaso]) -> Informe:
    """Métricas de un proveedor. La exactitud es una fracción de 0 a 1."""
    total = len(resultados)
    correctos = sum(1 for r in resultados if r.correcto)
    por_etiqueta: dict[str, dict[str, Any]] = {}
    for r in resultados:
        for etiqueta in r.tags:
            grupo = por_etiqueta.setdefault(etiqueta, {"total": 0, "correctos": 0})
            grupo["total"] += 1
            grupo["correctos"] += int(r.correcto)
    for grupo in por_etiqueta.values():
        grupo["exactitud"] = _exactitud(grupo["correctos"], grupo["total"])
    esperadas = [r for r in resultados if r.tipo == "aclaracion"]
    latencias = [r.latencia_ms for r in resultados]
    return {
        "proveedor": proveedor,
        "kind": kind,
        "modelo": modelo,
        "total": total,
        "correctos": correctos,
        "exactitud": _exactitud(correctos, total),
        "por_etiqueta": dict(sorted(por_etiqueta.items())),
        "aclaraciones": {
            "esperadas": len(esperadas),
            "correctas": sum(1 for r in esperadas if r.correcto),
            "innecesarias": sum(1 for r in resultados if r.aclaracion_innecesaria),
        },
        "latencia_ms": {"p50": percentil(latencias, 50), "p95": percentil(latencias, 95)},
        "tokens": {
            "entrada": sum(r.tokens_in for r in resultados),
            "salida": sum(r.tokens_out for r in resultados),
        },
        "costo_usd": round(sum(r.costo_usd for r in resultados), 6),
        "fallidos": [
            {
                "id": r.id,
                "tags": r.tags,
                "motivo": r.motivo,
                "sql": r.sql,
                "sql_esperado": r.sql_esperado,
                "filas": r.filas,
                "aclaracion": r.slot,
            }
            for r in resultados
            if not r.correcto
        ],
    }


def armar_informe(nombre_set: str, proveedores: Sequence[Informe]) -> Informe:
    return {
        "set": nombre_set,
        "generado": datetime.now(UTC).isoformat(timespec="seconds"),
        "proveedores": list(proveedores),
    }


def a_json(informe: Informe) -> str:
    return json.dumps(informe, ensure_ascii=False, indent=2, default=str) + "\n"


def _pct(valor: float) -> str:
    return f"{valor * 100:.1f} %"


def _ms(valor: float) -> str:
    return f"{valor:.0f} ms"


def a_markdown(informe: Informe) -> str:
    proveedores: list[Informe] = informe["proveedores"]
    lineas = [
        f"# Evaluación del set «{informe['set']}»",
        "",
        f"Generado: {informe['generado']}",
        "",
        "| Proveedor | Modelo | Exactitud | Aclaraciones | p50 | p95 | Tokens (ent./sal.) "
        "| Costo |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in proveedores:
        a, lat, tok = p["aclaraciones"], p["latencia_ms"], p["tokens"]
        lineas.append(
            f"| {p['proveedor']} | {p['modelo']} | {_pct(p['exactitud'])} "
            f"({p['correctos']}/{p['total']}) | {a['correctas']}/{a['esperadas']} "
            f"| {_ms(lat['p50'])} | {_ms(lat['p95'])} "
            f"| {tok['entrada']} / {tok['salida']} | $ {p['costo_usd']:.4f} |"
        )
    for p in proveedores:
        lineas += ["", f"## {p['proveedor']} ({p['kind']} · {p['modelo']})", ""]
        lineas += ["| Etiqueta | Exactitud | Casos |", "|---|---|---|"]
        for etiqueta, g in p["por_etiqueta"].items():
            lineas.append(
                f"| {etiqueta} | {_pct(g['exactitud'])} | {g['correctos']}/{g['total']} |"
            )
        a = p["aclaraciones"]
        lineas += [
            "",
            f"Aclaraciones correctas: {a['correctas']} de {a['esperadas']}; "
            f"innecesarias: {a['innecesarias']}.",
            "",
            f"### Casos fallidos ({len(p['fallidos'])})",
        ]
        if not p["fallidos"]:
            lineas += ["", "Ninguno."]
        for f in p["fallidos"]:
            lineas += ["", f"**{f['id']}** — {f['motivo']}"]
            if f["sql"]:
                lineas += ["", "SQL obtenido:", "", "```sql", f["sql"], "```"]
            if f["sql_esperado"]:
                lineas += ["", "SQL esperado:", "", "```sql", f["sql_esperado"], "```"]
    return "\n".join(lineas) + "\n"
