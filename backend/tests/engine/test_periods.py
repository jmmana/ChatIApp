from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from app.engine.periods import PeriodConfig, PeriodRange, previous_equivalent, resolve_period

NOW = datetime(2026, 11, 25, 10, 0, tzinfo=ZoneInfo("America/Bogota"))  # miércoles
CFG = PeriodConfig(timezone="America/Bogota")


def d(text: str) -> date:
    return date.fromisoformat(text)


# (expresiones, inicio, fin exclusivo): tabla de docs/FLUJO_CONVERSACIONAL.md con hoy = 2026-11-25
TABLE = [
    (["hoy", "today", "HOY"], "2026-11-25", "2026-11-26"),
    (["ayer", "yesterday"], "2026-11-24", "2026-11-25"),
    (["esta semana", "this week", "semana actual", "WTD"], "2026-11-23", "2026-11-30"),
    (["semana pasada", "la semana pasada", "last week"], "2026-11-16", "2026-11-23"),
    (
        ["este mes", "en lo que va del mes", "mes actual", "MTD", "Este Mes", "month to date",
         "this month", "en lo que va de este mes"],
        "2026-11-01",
        "2026-12-01",
    ),
    (["mes pasado", "mes anterior", "last month", "el mes pasado"], "2026-10-01", "2026-11-01"),
    (["este trimestre", "this quarter", "QTD"], "2026-10-01", "2027-01-01"),
    (["trimestre pasado", "last quarter"], "2026-07-01", "2026-10-01"),
    (
        ["este año", "este ano", "en lo que va del año", "YTD", "this year", "year to date"],
        "2026-01-01",
        "2027-01-01",
    ),
    (["año pasado", "ano pasado", "last year"], "2025-01-01", "2026-01-01"),
    (["últimos 7 días", "ultimos 7 dias", "last 7 days", "past 7 days"], "2026-11-19", "2026-11-26"),
    (
        ["últimos 30 días", "ULTIMOS 30 DIAS", "last 30 days", "ultimos treinta dias"],
        "2026-10-27",
        "2026-11-26",
    ),
    (["últimos 3 meses", "last 3 months", "últimos tres meses"], "2026-08-26", "2026-11-26"),
    (
        ["últimos 3 meses completos", "last 3 full months", "last 3 complete months"],
        "2026-08-01",
        "2026-11-01",
    ),
    (["marzo", "March", "en marzo", "in march"], "2026-03-01", "2026-04-01"),
    (["diciembre", "December"], "2025-12-01", "2026-01-01"),
    (["marzo de 2025", "March 2025", "marzo del 2025"], "2025-03-01", "2025-04-01"),
    (["2024", "en 2024", "year 2024", "año 2024"], "2024-01-01", "2025-01-01"),
    (["Q1", "primer trimestre", "first quarter", "T1", "1er trimestre"], "2026-01-01", "2026-04-01"),
    (["primer semestre de 2025", "first half of 2025", "S1 2025", "H1-2025"], "2025-01-01", "2025-07-01"),
    (
        ["del 1 al 15 de marzo", "1 al 15 de marzo", "March 1 to 15", "from march 1 - 15", "1 to 15 march"],
        "2026-03-01",
        "2026-03-16",
    ),
    (["01/03/2026 al 15/03/2026", "del 01/03/2026 al 15/03/2026"], "2026-03-01", "2026-03-16"),
    (["2026-03-01 - 2026-03-15", "2026-03-01 a 2026-03-15"], "2026-03-01", "2026-03-16"),
]
CASES = [(e, s, f) for exprs, s, f in TABLE for e in exprs]


@pytest.mark.parametrize(("expression", "start", "end"), CASES)
def test_table_ranges(expression: str, start: str, end: str) -> None:
    result = resolve_period(expression, CFG, NOW)
    assert result is not None
    assert (result.start, result.end_exclusive) == (d(start), d(end))


def test_fiscal_year_starting_in_april() -> None:
    cfg = PeriodConfig(timezone="America/Bogota", fiscal_year_start_month=4)
    result = resolve_period("este año fiscal", cfg, NOW)
    assert result == PeriodRange(d("2026-04-01"), d("2027-04-01"), "AF 2026-27 (al 25 nov)", "year", True)
    last = resolve_period("last fiscal year", cfg, NOW)
    assert last is not None
    assert (last.start, last.end_exclusive) == (d("2025-04-01"), d("2026-04-01"))
    assert last.label == "FY 2025-26"


def test_fiscal_year_calendar_label() -> None:
    result = resolve_period("this fiscal year", CFG, NOW)
    assert result is not None
    assert result.label == "FY 2026 (to 25 Nov)"


def test_fiscal_quarters_and_semesters() -> None:
    cfg = PeriodConfig(timezone="America/Bogota", fiscal_year_start_month=2)
    quarter = resolve_period("este trimestre", cfg, NOW)
    assert quarter is not None
    assert (quarter.start, quarter.end_exclusive) == (d("2026-11-01"), d("2027-02-01"))
    assert quarter.label == "T4 2026-27 (al 25 nov)"
    q1 = resolve_period("Q1", cfg, NOW)
    assert q1 is not None
    assert q1.start == d("2026-02-01")
    q2 = resolve_period("Q2 2024", cfg, NOW)
    assert q2 is not None
    assert q2.start == d("2024-05-01")
    semester = resolve_period("segundo semestre", cfg, NOW)
    assert semester is not None
    assert (semester.start, semester.end_exclusive) == (d("2026-08-01"), d("2027-02-01"))


@pytest.mark.parametrize(
    ("expression", "start", "end", "label", "grain", "current"),
    [
        ("hoy", "2026-11-25", "2026-11-26", "Hoy, 25 nov 2026", "day", True),
        ("today", "2026-11-25", "2026-11-26", "Today, 25 Nov 2026", "day", True),
        ("ayer", "2026-11-24", "2026-11-25", "Ayer, 24 nov 2026", "day", False),
        ("yesterday", "2026-11-24", "2026-11-25", "Yesterday, 24 Nov 2026", "day", False),
        ("esta semana", "2026-11-23", "2026-11-30", "Semana del 23 nov (al día 25)", "week", True),
        ("this week", "2026-11-23", "2026-11-30", "Week of 23 Nov (through day 25)", "week", True),
        ("semana pasada", "2026-11-16", "2026-11-23", "Semana del 16 al 22 nov", "week", False),
        ("last week", "2026-11-16", "2026-11-23", "Week of 16 – 22 Nov", "week", False),
        ("este mes", "2026-11-01", "2026-12-01", "Noviembre 2026 (al día 25)", "month", True),
        ("this month", "2026-11-01", "2026-12-01", "November 2026 (through day 25)", "month", True),
        ("mes pasado", "2026-10-01", "2026-11-01", "Octubre 2026", "month", False),
        ("este trimestre", "2026-10-01", "2027-01-01", "T4 2026 (al 25 nov)", "quarter", True),
        ("this quarter", "2026-10-01", "2027-01-01", "Q4 2026 (to 25 Nov)", "quarter", True),
        ("trimestre pasado", "2026-07-01", "2026-10-01", "T3 2026", "quarter", False),
        ("este semestre", "2026-07-01", "2027-01-01", "S2 2026 (al 25 nov)", "semester", True),
        ("este año", "2026-01-01", "2027-01-01", "2026 (al 25 nov)", "year", True),
        ("año pasado", "2025-01-01", "2026-01-01", "2025", "year", False),
        ("últimos 7 días", "2026-11-19", "2026-11-26", "19 – 25 nov 2026", "day", True),
        ("últimos 30 días", "2026-10-27", "2026-11-26", "27 oct – 25 nov 2026", "day", True),
        (
            "últimos 3 meses", "2026-08-26", "2026-11-26",
            "26 ago – 25 nov 2026 (ventana móvil)", "month", True,
        ),
        (
            "last 2 years", "2024-11-26", "2026-11-26",
            "26 Nov 2024 – 25 Nov 2026 (rolling window)", "year", True,
        ),
        ("últimos 3 meses completos", "2026-08-01", "2026-11-01", "Ago – oct 2026", "month", False),
        ("last 14 complete months", "2025-09-01", "2026-11-01", "Sep 2025 – Oct 2026", "month", False),
        ("last 1 full month", "2026-10-01", "2026-11-01", "October 2026", "month", False),
        ("últimas 2 semanas completas", "2026-11-09", "2026-11-23", "9 – 22 nov 2026", "week", False),
        ("últimos 2 días completos", "2026-11-23", "2026-11-25", "23 – 24 nov 2026", "day", False),
        ("last 1 day", "2026-11-25", "2026-11-26", "25 Nov 2026", "day", True),
        ("últimos 2 trimestres completos", "2026-04-01", "2026-10-01", "Abr – sep 2026", "quarter", False),
        ("last 1 complete year", "2025-01-01", "2026-01-01", "2025", "year", False),
        ("last 2 semesters", "2025-11-26", "2026-11-26", "26 Nov 2025 – 25 Nov 2026 (rolling window)", "semester", True),
        ("marzo", "2026-03-01", "2026-04-01", "Marzo 2026", "month", False),
        ("noviembre", "2026-11-01", "2026-12-01", "Noviembre 2026 (al día 25)", "month", True),
        ("diciembre", "2025-12-01", "2026-01-01", "Diciembre 2025", "month", False),
        ("Q1", "2026-01-01", "2026-04-01", "T1 2026", "quarter", False),
        ("primer semestre de 2025", "2025-01-01", "2025-07-01", "S1 2025", "semester", False),
        ("first half 2025", "2025-01-01", "2025-07-01", "H1 2025", "semester", False),
        ("del 1 al 15 de marzo", "2026-03-01", "2026-03-16", "1 – 15 mar 2026", "range", False),
        ("01/03/2026 al 15/03/2026", "2026-03-01", "2026-03-16", "1 – 15 mar 2026", "range", False),
        ("15 de marzo", "2026-03-15", "2026-03-16", "15 mar 2026", "day", False),
    ],
)
def test_labels_grain_and_current(
    expression: str, start: str, end: str, label: str, grain: str, current: bool
) -> None:
    result = resolve_period(expression, CFG, NOW)
    assert result is not None
    assert (result.start, result.end_exclusive, result.label) == (d(start), d(end), label)
    assert (result.grain, result.is_current) == (grain, current)


@pytest.mark.parametrize(
    ("expression", "start", "end"),
    [
        ("del 1 de marzo al 15 de abril", "2026-03-01", "2026-04-16"),
        ("del 20 de diciembre al 5 de enero", "2025-12-20", "2026-01-06"),
        ("1 al 15 de diciembre", "2025-12-01", "2025-12-16"),
        ("1 al 15 de marzo de 2024", "2024-03-01", "2024-03-16"),
        ("15 march 2025", "2025-03-15", "2025-03-16"),
        ("march 1 to march 15 2025", "2025-03-01", "2025-03-16"),
        ("March 15", "2026-03-15", "2026-03-16"),
        ("20/12/2025 al 05/01/2026", "2025-12-20", "2026-01-06"),
        ("25/03/26", "2026-03-25", "2026-03-26"),
    ],
)
def test_date_ranges(expression: str, start: str, end: str) -> None:
    result = resolve_period(expression, CFG, NOW)
    assert result is not None
    assert (result.start, result.end_exclusive) == (d(start), d(end))


def test_cross_year_label() -> None:
    result = resolve_period("20/12/2025 al 05/01/2026", CFG, NOW)
    assert result is not None
    assert result.label == "20 dic 2025 – 5 ene 2026"


def test_locale_changes_numeric_date_order() -> None:
    dmy = resolve_period("03/01/2026", PeriodConfig(locale="es-CO"), NOW)
    mdy = resolve_period("03/01/2026", PeriodConfig(locale="en-US"), NOW)
    gb = resolve_period("03/01/2026", PeriodConfig(locale="en_GB"), NOW)
    assert dmy is not None
    assert mdy is not None
    assert gb is not None
    assert dmy.start == d("2026-01-03")
    assert mdy.start == d("2026-03-01")
    assert gb.start == d("2026-01-03")
    plain = resolve_period("03/15/2026 to 03/20/2026", PeriodConfig(locale="en"), NOW)
    assert plain is not None
    assert (plain.start, plain.end_exclusive) == (d("2026-03-15"), d("2026-03-21"))


def test_locale_decides_language_when_expression_is_neutral() -> None:
    es = resolve_period("Q1", PeriodConfig(locale="es-CO"), NOW)
    en = resolve_period("Q1", PeriodConfig(locale="en-US"), NOW)
    assert es is not None
    assert en is not None
    assert es.label == "T1 2026"
    assert en.label == "Q1 2026"


@pytest.mark.parametrize(
    ("week_starts_on", "start", "end"),
    [
        ("monday", "2026-11-23", "2026-11-30"),
        ("sunday", "2026-11-22", "2026-11-29"),
        ("Saturday", "2026-11-21", "2026-11-28"),
        ("wednesday", "2026-11-25", "2026-12-02"),
    ],
)
def test_week_starts_on(week_starts_on: str, start: str, end: str) -> None:
    cfg = PeriodConfig(timezone="America/Bogota", week_starts_on=week_starts_on)
    result = resolve_period("esta semana", cfg, NOW)
    assert result is not None
    assert (result.start, result.end_exclusive) == (d(start), d(end))


def test_timezone_decides_today() -> None:
    instant = datetime(2026, 11, 26, 2, 0, tzinfo=UTC)  # 21:00 del 25 en Bogotá
    bogota = resolve_period("hoy", PeriodConfig(timezone="America/Bogota"), instant)
    utc = resolve_period("hoy", PeriodConfig(timezone="UTC"), instant)
    assert bogota is not None
    assert utc is not None
    assert bogota.start == d("2026-11-25")
    assert utc.start == d("2026-11-26")


def test_naive_now_is_taken_in_business_timezone() -> None:
    result = resolve_period("hoy", CFG, datetime(2026, 11, 25, 23, 30))
    assert result is not None
    assert result.start == d("2026-11-25")


def test_without_now_uses_the_system_clock() -> None:
    result = resolve_period("hoy")
    assert result is not None
    assert result.is_current


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "asdf",
        "el próximo mes",
        "último mes",
        "last 0 days",
        "últimos 0 meses",
        "tercer semestre",
        "q5",
        "31/02/2026",
        "1/3/202",
        "15/03/2026 al 01/03/2026",
        "del 15 al 1 de marzo",
        "31 de febrero",
        "1 al 15",
        "ultimos 999999999 dias",
        "last 99999 years",
        "año 0000",
        "marzo de 0000",
    ],
)
def test_unrecognized_returns_none(expression: str) -> None:
    assert resolve_period(expression, CFG, NOW) is None


def test_invalid_config() -> None:
    with pytest.raises(ValueError, match="week_starts_on"):
        PeriodConfig(week_starts_on="funday")
    with pytest.raises(ValueError, match="fiscal_year_start_month"):
        PeriodConfig(fiscal_year_start_month=13)
    with pytest.raises(ValueError, match="fiscal_year_start_month"):
        PeriodConfig(fiscal_year_start_month=0)
    with pytest.raises(ZoneInfoNotFoundError):
        PeriodConfig(timezone="No/Existe")


def previous(expression: str, now: datetime = NOW, cfg: PeriodConfig = CFG) -> PeriodRange:
    period = resolve_period(expression, cfg, now)
    assert period is not None
    return previous_equivalent(period, cfg, now)


@pytest.mark.parametrize(
    ("expression", "start", "end"),
    [
        ("este mes", "2026-10-01", "2026-10-26"),  # octubre al día 25
        ("mes pasado", "2026-09-01", "2026-10-01"),
        ("hoy", "2026-11-24", "2026-11-25"),
        ("esta semana", "2026-11-16", "2026-11-19"),
        ("este trimestre", "2026-07-01", "2026-08-26"),
        ("este año", "2025-01-01", "2025-11-26"),
        ("año pasado", "2024-01-01", "2025-01-01"),
        ("últimos 30 días", "2026-09-27", "2026-10-27"),
        ("últimos 3 meses", "2026-05-26", "2026-08-26"),
        ("del 1 al 15 de marzo", "2026-02-14", "2026-03-01"),
    ],
)
def test_previous_equivalent(expression: str, start: str, end: str) -> None:
    result = previous(expression)
    assert (result.start, result.end_exclusive) == (d(start), d(end))
    assert result.is_current is False


def test_previous_equivalent_label_and_grain() -> None:
    result = previous("este mes")
    assert result.label == "1 – 25 oct 2026"
    assert result.grain == "month"
    english = previous("this month", cfg=PeriodConfig(timezone="America/Bogota", locale="en-US"))
    assert english.label == "1 – 25 Oct 2026"


def test_previous_equivalent_is_capped_at_period_start() -> None:
    march_30 = datetime(2026, 3, 30, 12, 0, tzinfo=ZoneInfo("America/Bogota"))
    result = previous("este mes", march_30)
    assert (result.start, result.end_exclusive) == (d("2026-02-01"), d("2026-03-01"))


def test_previous_equivalent_without_now() -> None:
    period = resolve_period("2024", CFG, NOW)
    assert period is not None
    assert previous_equivalent(period).start == d("2023-01-01")
