"""Resolutor determinista de períodos en español e inglés.

Convierte expresiones como «este mes», «trimestre pasado» o «últimos 30 días» en rangos de
fechas semiabiertos ``[start, end_exclusive)``, sin IA: si no reconoce la expresión devuelve
``None`` y nunca adivina. Contrato en docs/FLUJO_CONVERSACIONAL.md#resolutor-de-períodos.
"""

from __future__ import annotations

import re
import unicodedata
from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

Grain = Literal["day", "week", "month", "quarter", "semester", "year", "range"]

_ONE_DAY = timedelta(days=1)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_GRAIN: dict[str, Grain] = {
    "day": "day",
    "week": "week",
    "month": "month",
    "quarter": "quarter",
    "semester": "semester",
    "year": "year",
    "fiscal": "year",
    "range": "range",
}
_MONTHS_IN = {"month": 1, "quarter": 3, "semester": 6, "year": 12, "fiscal": 12}


@dataclass(frozen=True, slots=True)
class PeriodConfig:
    """Ajustes del modelo semántico (`settings`) que afectan a los períodos."""

    timezone: str = "UTC"
    week_starts_on: str = "monday"
    fiscal_year_start_month: int = 1
    locale: str = "es-CO"

    def __post_init__(self) -> None:
        ZoneInfo(self.timezone)
        if self.week_starts_on.lower() not in _WEEKDAYS:
            raise ValueError(f"week_starts_on inválido: {self.week_starts_on!r}")
        if not 1 <= self.fiscal_year_start_month <= 12:
            raise ValueError("fiscal_year_start_month debe estar entre 1 y 12")


@dataclass(frozen=True, slots=True)
class PeriodRange:
    """Rango semiabierto: ``fecha >= start AND fecha < end_exclusive``."""

    start: date
    end_exclusive: date
    label: str
    grain: Grain
    is_current: bool


@dataclass(frozen=True, slots=True)
class _Ctx:
    today: date
    cfg: PeriodConfig
    lang: str


# --------------------------------------------------------------------------- vocabulario

_MONTH_NAMES = {
    "es": [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ],
    "en": [
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    ],
}  # fmt: skip
_MONTH_ABBR = {
    "es": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}


def _build_months() -> dict[str, int]:
    months: dict[str, int] = {"setiembre": 9, "sept": 9}
    for lang in ("es", "en"):
        for number, (full, abbr) in enumerate(
            zip(_MONTH_NAMES[lang], _MONTH_ABBR[lang], strict=True), start=1
        ):
            months[full] = number
            months[abbr.lower()] = number
    return months


_MONTHS = _build_months()

_SINGULAR_UNITS = {
    "semana": "week", "week": "week", "mes": "month", "month": "month",
    "trimestre": "quarter", "quarter": "quarter", "semestre": "semester",
    "semester": "semester", "ano": "year", "year": "year", "fiscalyear": "fiscal",
    "mtd": "month", "ytd": "year", "qtd": "quarter", "wtd": "week",
}  # fmt: skip
_ROLLING_UNITS = {
    "dia": "day", "dias": "day", "day": "day", "days": "day",
    "semana": "week", "semanas": "week", "week": "week", "weeks": "week",
    "mes": "month", "meses": "month", "month": "month", "months": "month",
    "trimestre": "quarter", "trimestres": "quarter", "quarter": "quarter", "quarters": "quarter",
    "semestre": "semester", "semestres": "semester", "semester": "semester",
    "semesters": "semester", "ano": "year", "anos": "year", "year": "year", "years": "year",
}  # fmt: skip
_NUMBER_WORDS = {
    "un": 1, "uno": 1, "una": 1, "one": 1, "dos": 2, "two": 2, "tres": 3, "three": 3,
    "cuatro": 4, "four": 4, "cinco": 5, "five": 5, "seis": 6, "six": 6, "siete": 7,
    "seven": 7, "ocho": 8, "eight": 8, "nueve": 9, "nine": 9, "diez": 10, "ten": 10,
    "once": 11, "eleven": 11, "doce": 12, "twelve": 12, "quince": 15, "fifteen": 15,
    "veinte": 20, "twenty": 20, "treinta": 30, "thirty": 30,
}  # fmt: skip
_ORDINALS = {
    "primer": 1, "primero": 1, "primera": 1, "1er": 1, "1ro": 1, "1st": 1, "first": 1,
    "segundo": 2, "segunda": 2, "2do": 2, "2nd": 2, "second": 2,
    "tercer": 3, "tercero": 3, "tercera": 3, "3er": 3, "3rd": 3, "third": 3,
    "cuarto": 4, "cuarta": 4, "4to": 4, "4th": 4, "fourth": 4,
}  # fmt: skip

_LABELS = {
    "es": {
        "today": "Hoy", "yesterday": "Ayer", "week": "Semana del ", "week_sep": " al ",
        "to_day": "al día {d}", "to_date": "al {d} {m}", "rolling": "ventana móvil",
        "quarter": "T", "semester": "S", "fiscal": "AF",
    },
    "en": {
        "today": "Today", "yesterday": "Yesterday", "week": "Week of ", "week_sep": " – ",
        "to_day": "through day {d}", "to_date": "to {d} {m}", "rolling": "rolling window",
        "quarter": "Q", "semester": "H", "fiscal": "FY",
    },
}  # fmt: skip


def _alt(words: Iterable[str]) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


_MONTH_ALT = _alt(_MONTHS)
_SINGULAR_ALT = _alt(_SINGULAR_UNITS)
_ROLLING_ALT = _alt(_ROLLING_UNITS)
_NUMBER_ALT = r"\d+|" + _alt(_NUMBER_WORDS)
_ORDINAL_ALT = _alt(_ORDINALS)

_ES_MARKERS = re.compile(
    r"\b(?:hoy|ayer|este|esta|pasad[oa]|anterior|ultim[oa]s|semanas?|mes|meses|anos?|"
    r"trimestres?|semestres?|dias?|de|del|al|hasta|enero|febrero|marzo|abril|mayo|junio|julio|"
    r"agosto|septiembre|setiembre|octubre|noviembre|diciembre|ene|abr|ago|dic|primer\w*|"
    r"segund[oa]|tercer\w*|cuart[oa])\b"
)
_EN_MARKERS = re.compile(
    r"\b(?:today|yesterday|this|last|previous|prior|past|current|weeks?|months?|quarters?|"
    r"years?|semesters?|half|fiscal|to|from|through|until|full|complete|completed|first|"
    r"second|third|fourth|days?|of|january|february|march|april|june|july|august|september|"
    r"october|november|december|jan|apr|aug|dec)\b"
)


# --------------------------------------------------------------------------- utilidades


def _normalize(text: str) -> str:
    """Minúsculas, sin tildes ni puntuación, sin artículos y con guiones largos unificados."""
    s = unicodedata.normalize("NFKD", text.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[–—]", " - ", s)
    s = re.sub(r"[¿?¡!,;:\"'()]", " ", s).strip(" .")
    s = re.sub(r"\b(?:ano fiscal|fiscal year|fy|af)\b", "fiscalyear", s)
    skip = {"el", "la", "los", "las", "the", "en", "in", "durante", "during", "mi", "my"}
    return " ".join(t for t in s.split() if t not in skip)


def _today(cfg: PeriodConfig, now: datetime | None) -> date:
    tz = ZoneInfo(cfg.timezone)
    moment = datetime.now(tz) if now is None else now
    if moment.tzinfo is not None:
        moment = moment.astimezone(tz)
    return moment.date()


def _language(s: str, cfg: PeriodConfig) -> str:
    if _ES_MARKERS.search(s):
        return "es"
    if _EN_MARKERS.search(s):
        return "en"
    return "en" if cfg.locale.lower().startswith("en") else "es"


def _add_months(d: date, months: int) -> date:
    year, month0 = divmod(d.year * 12 + d.month - 1 + months, 12)
    return date(year, month0 + 1, min(d.day, monthrange(year, month0 + 1)[1]))


def _fiscal_year_start(d: date, start_month: int) -> date:
    return date(d.year if d.month >= start_month else d.year - 1, start_month, 1)


def _current_start(ctx: _Ctx, unit: str) -> date:
    """Inicio del período en curso de la unidad (semana, mes, trimestre, semestre, año)."""
    today, fm = ctx.today, ctx.cfg.fiscal_year_start_month
    if unit == "week":
        first = _WEEKDAYS.index(ctx.cfg.week_starts_on.lower())
        return today - timedelta(days=(today.weekday() - first) % 7)
    if unit == "month":
        return today.replace(day=1)
    if unit == "year":
        return date(today.year, 1, 1)
    fiscal = _fiscal_year_start(today, fm)
    if unit == "fiscal":
        return fiscal
    size = _MONTHS_IN[unit]
    elapsed = (today.year * 12 + today.month) - (fiscal.year * 12 + fiscal.month)
    return _add_months(fiscal, elapsed // size * size)


def _mon(ctx: _Ctx, d: date) -> str:
    return _MONTH_ABBR[ctx.lang][d.month - 1]


def _span(ctx: _Ctx, a: date, b: date, *, year: bool = True, sep: str = " – ") -> str:
    """«1 – 15 mar 2026», «27 oct – 25 nov 2026» o, entre años, con ambos años."""
    tail = f" {b.year}" if year else ""
    if a == b:
        return f"{b.day} {_mon(ctx, b)}{tail}"
    if year and a.year != b.year:
        return f"{a.day} {_mon(ctx, a)} {a.year}{sep}{b.day} {_mon(ctx, b)} {b.year}"
    head = f"{a.day}" if a.month == b.month else f"{a.day} {_mon(ctx, a)}"
    return f"{head}{sep}{b.day} {_mon(ctx, b)}{tail}"


def _month_span(ctx: _Ctx, a: date, b: date) -> str:
    """«Ago – oct 2026» para ventanas de meses completos."""
    first = _mon(ctx, a).capitalize()
    if a.year == b.year:
        return f"{first} – {_mon(ctx, b)} {b.year}"
    return f"{first} {a.year} – {_mon(ctx, b)} {b.year}"


def _fiscal_label(ctx: _Ctx, start: date) -> str:
    fm = ctx.cfg.fiscal_year_start_month
    fy = _fiscal_year_start(start, fm).year
    return str(fy) if fm == 1 else f"{fy}-{(fy + 1) % 100:02d}"


def _make(ctx: _Ctx, start: date, end: date, label: str, grain: str) -> PeriodRange:
    return PeriodRange(start, end, label, _GRAIN[grain], start <= ctx.today < end)


def _block(ctx: _Ctx, unit: str, start: date) -> PeriodRange:
    """Período calendario o fiscal completo de `unit` que empieza en `start`."""
    text = _LABELS[ctx.lang]
    today = ctx.today
    end = start + timedelta(days=7) if unit == "week" else _add_months(start, _MONTHS_IN[unit])
    current = start <= today < end
    suffix = ""
    if current:
        key = "to_day" if unit in ("week", "month") else "to_date"
        suffix = f" ({text[key].format(d=today.day, m=_mon(ctx, today))})"
    if unit == "week":
        if current:
            label = f"{text['week']}{start.day} {_mon(ctx, start)}"
        else:
            span = _span(ctx, start, end - _ONE_DAY, year=False, sep=text["week_sep"])
            label = f"{text['week']}{span}"
    elif unit == "month":
        label = f"{_MONTH_NAMES[ctx.lang][start.month - 1].capitalize()} {start.year}"
    elif unit in ("quarter", "semester"):
        size = _MONTHS_IN[unit]
        number = ((start.month - ctx.cfg.fiscal_year_start_month) % 12) // size + 1
        label = f"{text[unit]}{number} {_fiscal_label(ctx, start)}"
    elif unit == "year":
        label = str(start.year)
    else:
        label = f"{text['fiscal']} {_fiscal_label(ctx, start)}"
    return _make(ctx, start, end, label + suffix, unit)


# --------------------------------------------------------------------------- analizadores


def _parse_day(s: str, ctx: _Ctx) -> PeriodRange | None:
    if s in ("hoy", "today"):
        day, key = ctx.today, "today"
    elif s in ("ayer", "yesterday"):
        day, key = ctx.today - _ONE_DAY, "yesterday"
    else:
        return None
    label = f"{_LABELS[ctx.lang][key]}, {day.day} {_mon(ctx, day)} {day.year}"
    return _make(ctx, day, day + _ONE_DAY, label, "day")


_CURRENT = re.compile(
    rf"(?:(?:este|esta|actual|presente|this|current)\s+({_SINGULAR_ALT})"
    rf"|({_SINGULAR_ALT})\s+(?:actual|curso|to date)"
    rf"|lo que va (?:del?|de este|de esta)\s+({_SINGULAR_ALT})"
    rf"|(mtd|ytd|qtd|wtd))"
)
_PREVIOUS = re.compile(
    rf"(?:({_SINGULAR_ALT})\s+(?:pasad[oa]|anterior|previo|previa)"
    rf"|(?:last|previous|prior|past)\s+({_SINGULAR_ALT}))"
)


def _parse_relative(s: str, ctx: _Ctx) -> PeriodRange | None:
    if m := _CURRENT.fullmatch(s):
        offset = 0
    elif m := _PREVIOUS.fullmatch(s):
        offset = -1
    else:
        return None
    unit = _SINGULAR_UNITS[next(g for g in m.groups() if g)]
    start = _current_start(ctx, unit)
    if offset and unit == "week":
        start -= timedelta(days=7)
    elif offset:
        start = _add_months(start, offset * _MONTHS_IN[unit])
    return _block(ctx, unit, start)


_ROLLING = re.compile(
    rf"(?:de\s+)?(?:ultim[oa]s|last|past|previous|prior)\s+({_NUMBER_ALT})\s+"
    rf"(?:(full|complete|completed)\s+)?({_ROLLING_ALT})(?:\s+(completos?|completas?))?"
)


def _parse_rolling(s: str, ctx: _Ctx) -> PeriodRange | None:
    m = _ROLLING.fullmatch(s)
    if not m:
        return None
    n = int(m[1]) if m[1].isdigit() else _NUMBER_WORDS[m[1]]
    if n < 1:
        return None
    unit, complete = _ROLLING_UNITS[m[3]], bool(m[2] or m[4])
    today = ctx.today
    if unit in ("day", "week"):
        if complete:
            end = today if unit == "day" else _current_start(ctx, "week")
        else:
            end = today + _ONE_DAY
        start = end - timedelta(days=n if unit == "day" else 7 * n)
        return _make(ctx, start, end, _span(ctx, start, end - _ONE_DAY), unit)
    end = _current_start(ctx, unit) if complete else today + _ONE_DAY
    start = _add_months(end, -n * _MONTHS_IN[unit])
    last = end - _ONE_DAY
    if complete and n == 1:
        label = _block(ctx, unit, start).label
    elif complete:
        label = _month_span(ctx, start, last)
    else:
        label = f"{_span(ctx, start, last)} ({_LABELS[ctx.lang]['rolling']})"
    return _make(ctx, start, end, label, unit)


_NAMED_MONTH = re.compile(rf"({_MONTH_ALT})(?:\s+(?:de\s+|del\s+|of\s+)?(\d{{4}}))?")
_YEAR = re.compile(r"(?:(?:ano|year)\s+(?:de\s+)?)?(\d{4})")


def _parse_month_or_year(s: str, ctx: _Ctx) -> PeriodRange | None:
    if m := _NAMED_MONTH.fullmatch(s):
        number = _MONTHS[m[1]]
        year = int(m[2]) if m[2] else ctx.today.year
        start = date(year, number, 1)
        if not m[2] and start > ctx.today:
            start = date(year - 1, number, 1)
        return _block(ctx, "month", start)
    if m := _YEAR.fullmatch(s):
        return _block(ctx, "year", date(int(m[1]), 1, 1))
    return None


_YEAR_TAIL = r"(?:\s*-?\s*(?:de\s+|of\s+)?(\d{4}))?"
_QUARTER = re.compile(rf"(?:[qt]([1-4])|({_ORDINAL_ALT})\s+(?:trimestre|quarter)){_YEAR_TAIL}")
_SEMESTER = re.compile(rf"(?:[sh]([12])|({_ORDINAL_ALT})\s+(?:semestre|semester|half)){_YEAR_TAIL}")


def _parse_fiscal_block(s: str, ctx: _Ctx) -> PeriodRange | None:
    """Trimestres y semestres del año fiscal (Q1, «primer semestre de 2025»)."""
    for pattern, unit, limit in ((_QUARTER, "quarter", 4), (_SEMESTER, "semester", 2)):
        if m := pattern.fullmatch(s):
            index = int(m[1]) if m[1] else _ORDINALS[m[2]]
            if index > limit:
                return None
            fm = ctx.cfg.fiscal_year_start_month
            base = date(int(m[3]), fm, 1) if m[3] else _fiscal_year_start(ctx.today, fm)
            return _block(ctx, unit, _add_months(base, _MONTHS_IN[unit] * (index - 1)))
    return None


_SEP = r"\s+(?:al?|to|hasta|through|until|-)\s+"
_PRE = r"(?:del?\s+|from\s+|desde\s+)?"
_DE = r"(?:de\s+|del\s+|of\s+)?"
_DAY_FIRST = re.compile(
    rf"{_PRE}(\d{{1,2}})(?:\s+{_DE}({_MONTH_ALT}))?(?:{_SEP}(\d{{1,2}}))?"
    rf"\s+{_DE}({_MONTH_ALT})(?:\s+{_DE}(\d{{4}}))?"
)
_MONTH_FIRST = re.compile(
    rf"{_PRE}({_MONTH_ALT})\s+(\d{{1,2}})(?:{_SEP}(?:({_MONTH_ALT})\s+)?(\d{{1,2}}))?"
    rf"(?:\s+(\d{{4}}))?"
)
_NUM_DATE = r"(\d{1,4})[/.-](\d{1,2})[/.-](\d{1,4})"
_NUMERIC = re.compile(rf"{_PRE}{_NUM_DATE}(?:{_SEP}{_NUM_DATE})?")


def _day_range(ctx: _Ctx, start: date, last: date) -> PeriodRange | None:
    if last < start:
        return None
    grain = "day" if start == last else "range"
    return _make(ctx, start, last + _ONE_DAY, _span(ctx, start, last), grain)


def _named_days(
    ctx: _Ctx, d1: str, m1: str, d2: str, m2: str, year: str | None
) -> PeriodRange | None:
    """«1 al 15 de marzo», «March 1 to 15»: sin año, el más reciente que no está en el futuro."""
    month1, month2 = _MONTHS[m1], _MONTHS[m2]
    y = int(year) if year else ctx.today.year
    start = date(y, month1, int(d1))
    if not year and start > ctx.today:
        y -= 1
        start = date(y, month1, int(d1))
    last = date(y + 1 if month2 < month1 else y, month2, int(d2))
    return _day_range(ctx, start, last)


def _numeric_date(ctx: _Ctx, a: str, b: str, c: str) -> date:
    """ISO (año primero) o según `locale`: día/mes/año, o mes/día/año en en-US."""
    if len(a) == 4:
        return date(int(a), int(b), int(c))
    if len(c) not in (2, 4):
        raise ValueError("año inválido")
    year = int(c) + 2000 if len(c) == 2 else int(c)
    month_first = ctx.cfg.locale.replace("_", "-").lower() in ("en", "en-us")
    return date(year, int(a) if month_first else int(b), int(b) if month_first else int(a))


def _parse_dates(s: str, ctx: _Ctx) -> PeriodRange | None:
    if m := _DAY_FIRST.fullmatch(s):
        d1, m1, d2, m2, year = m.groups()
        return _named_days(ctx, d1, m1 or m2, d2 or d1, m2, year)
    if m := _MONTH_FIRST.fullmatch(s):
        m1, d1, m2, d2, year = m.groups()
        return _named_days(ctx, d1, m1, d2 or d1, m2 or m1, year)
    if m := _NUMERIC.fullmatch(s):
        start = _numeric_date(ctx, m[1], m[2], m[3])
        last = _numeric_date(ctx, m[4], m[5], m[6]) if m[4] else start
        return _day_range(ctx, start, last)
    return None


_PARSERS = (
    _parse_day,
    _parse_relative,
    _parse_rolling,
    _parse_month_or_year,
    _parse_fiscal_block,
    _parse_dates,
)


# --------------------------------------------------------------------------- API pública


def resolve_period(
    expression: str, config: PeriodConfig | None = None, now: datetime | None = None
) -> PeriodRange | None:
    """Resuelve `expression` a un rango de fechas, o `None` si no la reconoce.

    `now` fija el instante de referencia (si es ingenuo se toma en la zona del negocio); sin él
    se usa el reloj del sistema. La etiqueta sigue el idioma de la expresión.
    """
    cfg = config or PeriodConfig()
    s = _normalize(expression)
    ctx = _Ctx(_today(cfg, now), cfg, _language(s, cfg))
    try:
        for parser in _PARSERS:
            if result := parser(s, ctx):
                return result
    except (ValueError, OverflowError):
        return None  # fecha inexistente (31/02) o fuera de rango: no se adivina
    return None


def previous_equivalent(
    period: PeriodRange, config: PeriodConfig | None = None, now: datetime | None = None
) -> PeriodRange:
    """Período anterior equivalente, con el mismo número de días transcurridos.

    Si `period` está en curso («este mes al día 25») devuelve el anterior hasta el mismo día
    («octubre al día 25», acotado al inicio de `period`); si está completo, el inmediato anterior
    de igual duración (calendario para meses, trimestres, semestres y años).
    """
    cfg = config or PeriodConfig()
    today = _today(cfg, now)
    ctx = _Ctx(today, cfg, "en" if cfg.locale.lower().startswith("en") else "es")
    start, end = period.start, period.end_exclusive
    months = (end.year - start.year) * 12 + end.month - start.month
    calendar_unit = period.grain in ("month", "quarter", "semester", "year")
    if calendar_unit and months > 0 and _add_months(start, months) == end:
        prev_start = _add_months(start, -months)
    else:
        prev_start = start - (end - start)
    prev_end = start
    if start <= today and end > today + _ONE_DAY:
        prev_end = min(prev_start + (today - start + _ONE_DAY), start)
    label = _span(ctx, prev_start, prev_end - _ONE_DAY)
    return PeriodRange(prev_start, prev_end, label, period.grain, False)
