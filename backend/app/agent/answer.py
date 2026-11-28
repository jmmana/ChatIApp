"""Redacción de la respuesta final del turno (docs/FLUJO_CONVERSACIONAL.md, estado «Responder»).

Con privacidad `aggregates` o `samples` y hasta `MAX_ANSWER_ROWS` filas, la IA redacta con
streaming (`answer.delta`). Con `schema`, con resultados grandes o si la IA falla, la respuesta
sale de una plantilla local que formatea los números con el `locale` y la moneda del modelo. En
ambos casos la respuesta menciona el período resuelto. Con `schema` nunca se envía una fila.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agent.events import AnswerDelta, Event
from app.engine.compare import Comparison
from app.engine.periods import PeriodRange
from app.llm.gateway import GatewayError, Usage
from app.llm.routing import LlmClient
from app.semantic.context import Privacy
from app.semantic.schema import Metric, SemanticModel

MAX_ANSWER_ROWS = 50  # filas que, como máximo, se envían a la IA para redactar (privacidad)
PROMPT_PATH = Path(__file__).parent / "prompts" / "answer.md"
DEFAULT_LOCALE = "es-CO"
MIN_FIGURE_DIGITS = 3  # cifras más cortas («3», «12») no sirven para detectar una fila citada
_FIGURE = re.compile(r"\d(?:[\d.,]|[   ](?=\d))*")
# Número tal como lo escribe una respuesta: con miles agrupados («1.234.567,8») o sin agrupar.
_NUMBER_TOKEN = re.compile(r"\d{1,3}(?:[.,   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)*")
MIN_CHECKED_DIGITS = 4  # la comprobación de cifras inventadas solo mira números de 4+ dígitos
_SEPARATOR_STYLES = ((",", "."), (".", ","), ("", "."), ("", ","))
_SCALES = (1, 10**3, 10**6, 10**9)  # «mil», «millones», «mil millones» / «mil M»
_SPACES = "   "

NBSP = " "
NARROW_NBSP = " "

# Idiomas con «1.234,5», con «1 234,5» y regiones de español con «1,234.5».
_DOT_GROUP = {"es", "de", "it", "pt", "nl", "id", "tr", "da", "el", "ro", "hr", "sl"}
_SPACE_GROUP = {"fr", "ru", "pl", "cs", "sv", "nb", "no", "fi", "uk", "sk", "bg", "hu"}
_ES_COMMA_GROUP = {"MX", "US", "PR", "DO", "GT", "HN", "NI", "SV", "PA", "PE"}
_SUFFIX_CURRENCY = _SPACE_GROUP | {"de", "it", "pt"}  # «1.234,50 €»
_SYMBOLS = {"USD": "US$", "EUR": "€", "GBP": "£", "JPY": "¥", "MXN": "MX$"}
_DOLLAR_LIKE = {"COP", "CLP", "ARS", "UYU"}


@dataclass
class Outcome:
    """Lo que el turno sabe para redactar la respuesta."""

    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False
    executed: bool = True
    metric: Metric | None = None
    period: PeriodRange | None = None
    comparison: Comparison | None = None


def escape_data(text: str) -> str:
    """Escapa `&`, `<` y `>` para que un dato no pueda abrir ni cerrar etiquetas del prompt."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def may_send_rows(privacy: Privacy, outcome: Outcome) -> bool:
    """`schema` nunca envía filas; `aggregates` y `samples` hasta MAX_ANSWER_ROWS."""
    return privacy != "schema" and outcome.executed and 0 < len(outcome.rows) <= MAX_ANSWER_ROWS


# --------------------------------------------------------------------------- formato


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parts(locale: str) -> tuple[str, str]:
    lang, _, region = locale.replace("_", "-").partition("-")
    return lang.lower(), region.upper()


def _separators(locale: str) -> tuple[str, str]:
    """(separador de miles, separador decimal) del `locale`."""
    lang, region = _parts(locale)
    if lang == "es" and region in _ES_COMMA_GROUP:
        return ",", "."
    if lang in _DOT_GROUP:
        return ".", ","
    if lang in _SPACE_GROUP:
        return (NARROW_NBSP if lang == "fr" else NBSP), ","
    return ",", "."


def _currency(text: str, code: str | None, locale: str) -> str:
    symbol = "$" if not code or code in _DOLLAR_LIKE else _SYMBOLS.get(code, code)
    lang, region = _parts(locale)
    if lang in _SUFFIX_CURRENCY or (lang, region) == ("es", "ES"):
        return f"{text}{NBSP}{symbol}"
    return f"{symbol}{NBSP}{text}" if symbol.isalpha() else f"{symbol}{text}"


def format_value(
    value: Any,
    metric: Metric | None = None,
    *,
    locale: str = DEFAULT_LOCALE,
    currency: str | None = None,
) -> str:
    """Formatea un valor según el formato de la métrica, el `locale` y la moneda del modelo."""
    number = _number(value)
    if number is None:
        return "sin datos" if value is None else str(value)
    kind = metric.format if metric else None
    decimals = 0 if kind == "integer" or (number.is_integer() and kind != "currency") else 2
    group, decimal = _separators(locale)
    text = f"{number:,.{decimals}f}".translate(str.maketrans(",.", "\x00\x01"))
    text = text.replace("\x00", group).replace("\x01", decimal)
    if kind == "currency":
        return _currency(text, currency, locale)
    return f"{text} %" if kind == "percent" else text


def variation_text(comparison: Comparison, locale: str = DEFAULT_LOCALE) -> str:
    if comparison.change_pct is None:
        return comparison.change_note or "sin variación"
    word = "más" if comparison.change_pct >= 0 else "menos"
    _, decimal = _separators(locale)
    pct = f"{abs(comparison.change_pct):.1f}".replace(".", decimal)
    return f"{pct} % {word} que {comparison.previous_period.label}"


def _period_label(outcome: Outcome) -> str | None:
    if outcome.comparison is not None:
        return outcome.comparison.period.label
    return outcome.period.label if outcome.period is not None else None


def template_answer(
    outcome: Outcome, *, locale: str = DEFAULT_LOCALE, currency: str | None = None
) -> str:
    """Respuesta determinista, sin IA: la de privacidad `schema`, resultados grandes o fallos."""
    metric = outcome.metric
    label = _period_label(outcome)
    in_period = f" en {label}" if label else ""
    if not outcome.executed:
        return (
            f"Armé y validé la consulta{in_period}, pero esta fuente no ejecuta consultas. "
            "Revisa el SQL."
        )
    comparison = outcome.comparison
    if comparison is not None:
        name = metric.label if metric else "Valor"
        value = format_value(comparison.value, metric, locale=locale, currency=currency)
        return f"{name}{in_period}: {value}; {variation_text(comparison, locale)}."
    if not outcome.rows:
        return f"La consulta no devolvió filas{in_period}."
    if len(outcome.rows) == 1 and len(outcome.rows[0]) == 1:
        value = format_value(outcome.rows[0][0], metric, locale=locale, currency=currency)
        if metric is None:
            return f"Resultado{in_period}: {value}."
        return f"{metric.label}{in_period}: {value}."
    cut = " (resultado recortado)" if outcome.truncated else ""
    return f"La consulta devolvió {len(outcome.rows)} filas{in_period}{cut}. Revisa la tabla."


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _cell_figures(value: Any, metric: Metric | None, locale: str, currency: str | None) -> set[str]:
    """Cifras (solo dígitos) con que una celda numérica puede citarse en un texto."""
    number = _number(value)
    if number is None:
        return set()
    shown = {
        _digits(format_value(value, metric, locale=locale, currency=currency)),
        _digits(format_value(value, None, locale=locale, currency=currency)),
        str(int(abs(round(number)))),
    }
    return {d for d in shown if len(d) >= MIN_FIGURE_DIGITS}


def quotes_only_first_row(
    text: str, outcome: Outcome, *, locale: str = DEFAULT_LOCALE, currency: str | None = None
) -> bool:
    """¿El texto cita una cifra que solo está en la primera de varias filas?

    Es la señal de que la IA respondió con una fila como si fuera el total.
    """
    if len(outcome.rows) < 2:
        return False

    def figures(rows: list[list[Any]]) -> set[str]:
        found: set[str] = set()
        for row in rows:
            for cell in row:
                found |= _cell_figures(cell, outcome.metric, locale, currency)
        return found

    others = figures(outcome.rows[1:])
    only_first = figures(outcome.rows[:1]) - others
    cited = {_digits(m) for m in _FIGURE.findall(text)}
    # Citar también cifras de las demás filas significa que las enumera todas.
    return bool(only_first & cited) and not (others & cited)


def _figure_tokens(text: str) -> set[str]:
    """Números de 4+ dígitos del texto, sin espacios ni puntuación final."""
    tokens = {re.sub(f"[{_SPACES}]", "", m).rstrip(".,") for m in _NUMBER_TOKEN.findall(text)}
    return {t for t in tokens if len(_digits(t)) >= MIN_CHECKED_DIGITS}


def _value_forms(number: float) -> set[str]:
    """Formas en que un número puede citarse: entero, con decimales, separadores, abreviado."""
    forms: set[str] = set()
    for scale in _SCALES:
        scaled = abs(number) / scale
        for decimals in (0, 1, 2):
            for group, decimal in _SEPARATOR_STYLES:
                text = f"{scaled:,.{decimals}f}".translate(str.maketrans(",.", "\x00\x01"))
                forms.add(text.replace("\x00", group).replace("\x01", decimal))
        forms.add(str(int(scaled)))  # truncado
    return forms


def _is_year(token: str) -> bool:
    return token.isdigit() and len(token) == 4 and 1900 <= int(token) <= 2100


def _allowed_figures(outcome: Outcome, locale: str, currency: str | None) -> set[str]:
    allowed = _figure_tokens(template_answer(outcome, locale=locale, currency=currency))
    periods = [outcome.period]
    comparison = outcome.comparison
    if comparison is not None:
        periods += [comparison.period, comparison.previous_period]
        allowed |= _figure_tokens(variation_text(comparison, locale))
        for value in (
            comparison.value,
            comparison.previous_value,
            comparison.difference,
            comparison.change_pct,
        ):
            number = _number(value)
            if number is not None:
                allowed |= _value_forms(number)
    for period in periods:
        if period is not None:
            allowed |= _figure_tokens(period.label) | _figure_tokens(str(period.start))
    for row in outcome.rows:
        for cell in row:
            number = _number(cell)
            if number is not None:
                allowed |= _value_forms(number)
            if not isinstance(cell, bool):
                allowed |= _figure_tokens(str(cell))
    return allowed


def invented_figures(
    text: str, outcome: Outcome, *, locale: str = DEFAULT_LOCALE, currency: str | None = None
) -> list[str]:
    """Cifras de 4+ dígitos del texto que no están en el resultado ni en el período del turno.

    Se comparan como texto, no solo por sus dígitos: «395.407.376.71» tiene los mismos dígitos que
    39540737671 pero no es una forma válida de escribirlo. Los años no se consideran inventados.
    """
    allowed = _allowed_figures(outcome, locale, currency)
    return sorted(t for t in _figure_tokens(text) if t not in allowed and not _is_year(t))


# --------------------------------------------------------------------------- redacción


class AnswerWriter:
    """Redacta la respuesta de un turno; tras `stream`, `text`, `usage` y `warning` están listos."""

    def __init__(
        self, gateway: LlmClient, model: SemanticModel, privacy: Privacy, question: str
    ) -> None:
        self.gateway = gateway
        self.privacy = privacy
        self.question = question
        self.locale = model.settings.locale or DEFAULT_LOCALE
        self.currency = model.settings.currency
        self.text = ""
        self.usage = Usage()
        self.warning: str | None = None

    def stream(self, outcome: Outcome) -> Iterator[Event]:
        """Emite los `answer.delta` (solo si redacta la IA) y deja la respuesta en `text`."""
        self.text = template_answer(outcome, locale=self.locale, currency=self.currency)
        if not may_send_rows(self.privacy, outcome):
            return
        drafted = ""
        try:
            for chunk in self.gateway.stream(self.messages(outcome)):
                if chunk.delta:
                    drafted += chunk.delta
                    yield Event(AnswerDelta(text=chunk.delta))
                if chunk.usage is not None:
                    self.usage += chunk.usage
        except GatewayError as exc:
            self.warning = f"{exc.message} Se usó la respuesta de plantilla."
            return
        if not drafted.strip():
            return
        if quotes_only_first_row(drafted, outcome, locale=self.locale, currency=self.currency):
            self.warning = (
                "La respuesta de la IA citaba solo la primera de varias filas. "
                "Se usó la respuesta de plantilla."
            )
            return
        invented = invented_figures(drafted, outcome, locale=self.locale, currency=self.currency)
        if invented:
            self.warning = (
                f"La respuesta de la IA citaba cifras que no están en el resultado "
                f"({', '.join(invented)}). Se usó la respuesta de plantilla."
            )
            return
        self.text = drafted.strip()
        label = _period_label(outcome)
        if label and label.casefold() not in self.text.casefold():
            suffix = f" (Período: {label}.)"
            self.text += suffix
            yield Event(AnswerDelta(text=suffix))

    def messages(self, outcome: Outcome) -> list[dict[str, str]]:
        """Prompt para la IA; solo se arma con las filas que `may_send_rows` permite."""
        facts: list[str] = []
        if outcome.metric is not None:
            facts.append(f"Métrica: {outcome.metric.label}")
        if outcome.period is not None:
            facts.append(f"Período: {outcome.period.label}")
        comparison = outcome.comparison
        if comparison is not None:
            facts.append(f"Período anterior: {comparison.previous_period.label}")
            facts.append(f"Variación: {variation_text(comparison, self.locale)}")
        moneda = f", moneda {self.currency}" if self.currency else ""
        facts.append(f"Formato: locale {self.locale}{moneda}")
        facts.append(f"Columnas: {', '.join(outcome.columns)}")
        facts += [f"Fila: {row}" for row in outcome.rows]
        # Los valores vienen de la base y no son confiables: sin `<` ni `>` ningún valor puede
        # cerrar <resultado> y colar instrucciones fuera de los datos.
        body = escape_data("\n".join(facts))
        return [
            {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
            {
                "role": "user",
                "content": (
                    f"<pregunta>{escape_data(self.question)}</pregunta>\n"
                    f"<resultado>\n{body}\n</resultado>"
                ),
            },
        ]
