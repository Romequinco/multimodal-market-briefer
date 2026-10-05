"""Normalización de texto para la locución (TTS) en español.

Carril C. ``normalize_for_speech(text)`` convierte lo que un guion financiero escribe de forma
compacta en lo que un locutor diría en voz alta, para que el TTS no lea «san punto eme ce» ni
«uno punto cinco»:

- Tickers → nombre de la empresa (``SAN.MC`` → «Banco Santander», ``$NVDA`` → «Nvidia»), con
  ``ingest.tickers.TICKER_UNIVERSE`` (solo lectura). «Santander (SAN.MC)» → «Santander».
- Porcentajes con signo: «+1,23 %» → «más uno coma veintitrés por ciento».
- Importes y magnitudes: «1.200 M€» → «mil doscientos millones de euros», «$3bn» → «tres mil
  millones de dólares», «12,5 €» → «doce coma cinco euros».
- Periodos: «3T 2026» / «Q3 2026» / «T3» → «tercer trimestre de dos mil veintiséis»; «1S» / «H1»
  → «primer semestre».
- Fechas: «05/10/2026» y «2026-10-05» → «cinco de octubre de dos mil veintiséis».
- Abreviaturas: IBEX, BCE, Fed, EPS/BPA, EBITDA, EE. UU., S&P, pb, pp, vs., IA, IPO, ETF, YTD… →
  lectura natural; «EUR/USD» → «euro dólar»; «+/-» → «más o menos»; «0,25 €/acción» → «… euros
  por acción».
- Horas, ordinales y múltiplos: «15:30 h» → «quince treinta horas»; «1º», «3ª», «1er» → «primero»,
  «tercera», «primer»; «nº 1» → «número 1»; «3,5x» → «tres coma cinco veces».
- Fechas con mes abreviado: «5 oct. 2026» → «cinco de octubre de dos mil veintiséis»; año fiscal
  «FY26» → «año fiscal dos mil veintiséis».
- Marca: «Market Briefer» → «Márket Brífer» (pronunciación inglesa aproximada con voz es-ES).
- Decimales sueltos (``1,5`` o ``1.5``) → «uno coma cinco»; miles con punto (``10.000``) →
  ``10000`` (el TTS ya lee bien los enteros).

Es una función **pura y determinista** (sin red) y prácticamente idempotente: aplicarla dos veces
da el mismo resultado. Solo afecta a lo que se **sintetiza**: la transcripción y el SRT siguen
mostrando el texto original del guion.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache

# ── Números a palabras ─────────────────────────────────────────────────────────────

_UNITS = [
    "cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
    "diez", "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete",
    "dieciocho", "diecinueve", "veinte", "veintiuno", "veintidós", "veintitrés",
    "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve",
]
_TENS = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta", 8: "ochenta",
         9: "noventa"}
_HUNDREDS = {1: "ciento", 2: "doscientos", 3: "trescientos", 4: "cuatrocientos", 5: "quinientos",
             6: "seiscientos", 7: "setecientos", 8: "ochocientos", 9: "novecientos"}


def _apocope(words: str) -> str:
    """«uno» → «un» al final (``veintiuno`` → ``veintiún``) delante de un sustantivo masculino."""
    if words.endswith("veintiuno"):
        return words[: -len("veintiuno")] + "veintiún"
    if words == "uno" or words.endswith(" uno"):
        return words[:-3] + "un"
    return words


def _below_thousand(n: int) -> str:
    if n < 30:
        return _UNITS[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        return _TENS[tens] + (f" y {_UNITS[unit]}" if unit else "")
    if n == 100:
        return "cien"
    hundreds, rest = divmod(n, 100)
    return _HUNDREDS[hundreds] + (f" {_below_thousand(rest)}" if rest else "")


def number_to_words(n: int, *, apocope: bool = False) -> str:
    """Entero a palabras en español (``21`` → «veintiuno»; con ``apocope`` → «veintiún»).

    Soporta hasta 999 999 999 999 999 (cientos de billones); los negativos llevan «menos».
    """
    n = int(n)
    if n < 0:
        return "menos " + number_to_words(-n, apocope=apocope)
    if n < 1000:
        words = _below_thousand(n)
        return _apocope(words) if apocope else words
    parts: list[str] = []
    billions, n = divmod(n, 10**12)
    millions, n = divmod(n, 10**6)
    thousands, units = divmod(n, 1000)
    if billions:
        parts.append("un billón" if billions == 1 else f"{number_to_words(billions, apocope=True)} billones")
    if millions:
        parts.append("un millón" if millions == 1 else f"{number_to_words(millions, apocope=True)} millones")
    if thousands:
        parts.append("mil" if thousands == 1 else f"{number_to_words(thousands, apocope=True)} mil")
    if units:
        words = _below_thousand(units)
        parts.append(_apocope(words) if apocope else words)
    return " ".join(parts)


def _parse_number(raw: str) -> tuple[int, str]:
    """``"1.234,56"`` → ``(1234, "56")``. Admite coma decimal (es) y punto decimal (en).

    Un punto seguido de exactamente 3 dígitos (y sin coma) es separador de miles; seguido de 1-2
    dígitos es decimal (``"1.5"``). La coma siempre es decimal.
    """
    raw = raw.strip()
    if "," in raw:
        int_part, dec = raw.split(",", 1)
        return int(int_part.replace(".", "") or "0"), dec
    if "." in raw:
        groups = raw.split(".")
        if len(groups) == 2 and len(groups[1]) in (1, 2):
            return int(groups[0] or "0"), groups[1]
        if all(len(g) == 3 for g in groups[1:]):
            return int("".join(groups)), ""
        return int(groups[0] or "0"), "".join(groups[1:])
    return int(raw), ""


def _digits_to_words(digits: str) -> str:
    return " ".join(_UNITS[int(d)] for d in digits)


def decimal_to_words(raw: str, *, apocope: bool = False) -> str:
    """Número escrito (``"1,23"``, ``"0,05"``, ``"1.200"``) a palabras: «uno coma veintitrés».

    La parte decimal se lee como número si tiene 1-2 cifras y no empieza por 0 («coma
    veintitrés»); si no, cifra a cifra («coma cero cinco»). ``apocope`` solo afecta a enteros.
    """
    integer, dec = _parse_number(raw)
    dec = dec.rstrip("0") if dec and set(dec) == {"0"} else dec
    if not dec or set(dec) == {"0"}:
        return number_to_words(integer, apocope=apocope)
    whole = number_to_words(integer)
    if len(dec) <= 2 and not dec.startswith("0"):
        return f"{whole} coma {number_to_words(int(dec))}"
    return f"{whole} coma {_digits_to_words(dec)}"


def _is_one(raw: str) -> bool:
    integer, dec = _parse_number(raw)
    return integer == 1 and (not dec or set(dec) == {"0"})


# ── Piezas de regex comunes ────────────────────────────────────────────────────────

_NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"
# Signo solo si va al principio o tras espacio/paréntesis (no en rangos «1-2 %»).
_SIGN = r"(?:(?<![\w])([+\-−–]))?"
_L = r"(?<![\w.$^&])"           # inicio de «palabra» (para tickers y abreviaturas)
_R = r"(?![\w&]|\.\w)"           # fin de «palabra»

_SIGN_WORDS = {"+": "más", "-": "menos", "−": "menos", "–": "menos"}

_MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre"]
_ORDINAL_PERIOD = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto"}


def _year_words(raw: str) -> str:
    year = int(raw)
    if year < 100:
        year += 2000
    return number_to_words(year)


# ── Tickers ────────────────────────────────────────────────────────────────────────

# Cómo se pronuncia el nombre cuando difiere del nombre oficial del universo.
_SPOKEN_NAMES = {
    "NVDA": "Nvidia",
    "^GSPC": "S&P 500",
    "^IBEX": "Ibex 35",
    "AMS.MC": "Amadeus",
}


@lru_cache(maxsize=1)
def _ticker_table() -> tuple[str, dict[str, str], dict[str, list[str]]]:
    """Alternativas regex de símbolos, ``símbolo → nombre hablado`` y ``símbolo → alias``."""
    from briefer.ingest.tickers import TICKER_UNIVERSE  # solo lectura (carril A)

    spoken: dict[str, str] = {}
    aliases: dict[str, list[str]] = {}
    for ticker, info in TICKER_UNIVERSE.items():
        name = _SPOKEN_NAMES.get(ticker, str(info["name"]))
        names = [str(info["name"]), *[str(a) for a in info.get("aliases", [])], name]
        symbols = {ticker}
        root = ticker.lstrip("^").split(".", 1)[0]
        # La raíz sin sufijo («ITX», «AAPL») también se reconoce, salvo si ya es el nombre (BBVA).
        # Los índices (``^IBEX``) solo por su símbolo completo: «IBEX» suelto lo lee ABBREVIATIONS.
        if len(root) >= 3 and not ticker.startswith("^") and root.upper() != str(info["name"]).upper():
            symbols.add(root)
        for sym in symbols:
            spoken[sym] = name
            aliases[sym] = names
    alternatives = "|".join(re.escape(s) for s in sorted(spoken, key=len, reverse=True))
    return alternatives, spoken, aliases


def _fold(text: str) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _replace_tickers(text: str) -> str:
    alternatives, spoken, aliases = _ticker_table()
    pattern = re.compile(r"(?<![\w.^&])\$?(" + alternatives + r")" + _R)
    # «Santander (SAN.MC)» → «Santander»: el ticker entre paréntesis sobra si ya se nombró.
    paren = re.compile(r"\s*\(\s*\$?(" + alternatives + r")\s*\)")

    def _drop_paren(match: re.Match[str]) -> str:
        sym = match.group(1)
        before = _fold(text[max(0, match.start() - 60): match.start()])
        if any(_fold(a) in before for a in aliases.get(sym, [])):
            return ""
        return f" ({spoken[sym]})"

    text = paren.sub(_drop_paren, text)
    return pattern.sub(lambda m: spoken[m.group(1)], text)


# ── Reglas en orden ────────────────────────────────────────────────────────────────

# Antes de todo: pares de divisas, «+/-», marca y «nº» (si no, «EUR» y «+» se leerían por separado).
_PRE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<![\w/])EUR\s?/\s?USD(?![\w/])"), "euro dólar"),
    (re.compile(r"(?<![\w/])USD\s?/\s?EUR(?![\w/])"), "dólar euro"),
    (re.compile(r"(?<![\w/])EUR\s?/\s?GBP(?![\w/])"), "euro libra"),
    (re.compile(r"\+\s?/\s?-|±"), "más o menos "),
    (re.compile(r"\bMarket Briefer\b"), "Márket Brífer"),
    (re.compile(r"(?<![\w.])(?:N\.?\s?º|n\.?\s?º|núm\.)\s?(?=\d)"), "número "),
]


def _sub_pre(text: str) -> str:
    for pattern, replacement in _PRE_RULES:
        text = pattern.sub(replacement, text)
    return re.sub(r"\s{2,}", " ", text)

# Fechas: dd/mm/aaaa (o dd-mm-aaaa) y aaaa-mm-dd.
_DATE_DMY = re.compile(r"(?<![\d/])(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})(?![\d/])")
_DATE_ISO = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-])")


def _date_words(day: int, month: int, year: str | None) -> str | None:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    text = f"{'uno' if day == 1 else number_to_words(day)} de {_MONTHS[month - 1]}"
    return text + (f" de {_year_words(year)}" if year else "")


def _sub_dates(text: str) -> str:
    def _iso(m: re.Match[str]) -> str:
        return _date_words(int(m.group(3)), int(m.group(2)), m.group(1)) or m.group(0)

    def _dmy(m: re.Match[str]) -> str:
        return _date_words(int(m.group(1)), int(m.group(2)), m.group(3)) or m.group(0)

    text = _DATE_DMY.sub(_dmy, _DATE_ISO.sub(_iso, text))
    return _DATE_ABBR.sub(_abbr_date, text)


_MONTH_ABBR = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9,
               "sept": 9, "oct": 10, "nov": 11, "dic": 12}
# «5 oct. 2026», «5-oct-2026», «5 de oct.» (el día es obligatorio: «mar» o «may» sueltos son palabras).
_DATE_ABBR = re.compile(
    r"(?<![\d/])(\d{1,2})(?:\s|-)(?:de\s)?(" + "|".join(sorted(_MONTH_ABBR, key=len, reverse=True))
    + r")\.?(?:(?:\s|-)(?:de\s)?(\d{4}))?(?![\w])"
)


def _abbr_date(m: re.Match[str]) -> str:
    return _date_words(int(m.group(1)), _MONTH_ABBR[m.group(2)], m.group(3)) or m.group(0)


# Periodos: 3T 2026, 3T26, T3, Q3 2026, 3Q26, 1S, S1, H1 2026, 1H26.
_YEAR_SUFFIX = r"(?:\s*(?:de\s+)?('?\d{4}|'?\d{2})(?!\d))?"
_QUARTER_PATTERNS = [
    re.compile(r"(?<![\w])([1-4])\s?[TQ]" + _YEAR_SUFFIX + r"(?![\w])"),
    re.compile(r"(?<![\w])[TQ]([1-4])" + _YEAR_SUFFIX + r"(?![\w])"),
]
_HALF_PATTERNS = [
    re.compile(r"(?<![\w])([12])\s?[SH]" + _YEAR_SUFFIX + r"(?![\w])"),
    re.compile(r"(?<![\w])[SH]([12])" + _YEAR_SUFFIX + r"(?![\w])"),
]


def _sub_periods(text: str) -> str:
    def _make(kind: str) -> Callable[[re.Match[str]], str]:
        def _fn(m: re.Match[str]) -> str:
            words = f"{_ORDINAL_PERIOD[int(m.group(1))]} {kind}"
            if m.group(2):
                words += f" de {_year_words(m.group(2).lstrip(chr(39)))}"
            return words

        return _fn

    for pat in _QUARTER_PATTERNS:
        text = pat.sub(_make("trimestre"), text)
    for pat in _HALF_PATTERNS:
        text = pat.sub(_make("semestre"), text)
    return _FISCAL_YEAR.sub(lambda m: f"año fiscal {_year_words(m.group(1))}", text)


_FISCAL_YEAR = re.compile(r"(?<![\w])FY\s?'?(\d{4}|\d{2})(?![\w])")


# Importes: [signo] [moneda] número [magnitud] [moneda].
_CUR_WORDS = {"€": "euro", "EUR": "euro", "euros": "euro", "euro": "euro",
              "$": "dólar", "US$": "dólar", "USD": "dólar", "dólares": "dólar", "dólar": "dólar"}
_CUR_PLURAL = {"euro": "euros", "dólar": "dólares"}
# Magnitud → (palabra singular, palabra plural, lleva «de» antes de la moneda).
_MAGNITUDES = {
    "k": ("mil", "mil", False),
    "mil": ("mil", "mil", False),
    "M": ("millón", "millones", True),
    "mill.": ("millón", "millones", True),
    "millón": ("millón", "millones", True),
    "millones": ("millón", "millones", True),
    "MM": ("mil millones", "mil millones", True),
    "bn": ("mil millones", "mil millones", True),
    "B": ("mil millones", "mil millones", True),
    "mil millones": ("mil millones", "mil millones", True),
}
_MAG_RE = r"mil millones|millones|millón|mill\.|MM|bn|M|B|k|mil"
_CUR_RE = r"US\$|€|\$|EUR|USD"
_AMOUNT_PRE = re.compile(
    _SIGN + r"(" + _CUR_RE + r")\s?(" + _NUM + r")(?:\s?(" + _MAG_RE + r"))?(?![\w€$])"
)
_AMOUNT_POST = re.compile(
    _SIGN + r"(?<![\w,.])(" + _NUM + r")\s?(?:(" + _MAG_RE + r")\s?(?:de\s)?)?(" + _CUR_RE + r")(?![\w])"
)
# «3 bn» sin moneda → «tres mil millones».
_BARE_BN = re.compile(_SIGN + r"(?<![\w,.])(" + _NUM + r")\s?(bn|MM)(?![\w])")


def _amount_words(sign: str | None, number: str, magnitude: str | None, currency: str | None) -> str:
    one = _is_one(number)
    words: list[str] = []
    if sign:
        words.append(_SIGN_WORDS[sign])
    if magnitude:
        singular, plural, with_de = _MAGNITUDES[magnitude]
        mag = singular if one else plural
        if one and mag == "mil":
            words.append("mil")
        elif one and mag == "mil millones":
            words.append("mil millones")
        else:
            words.append(f"{decimal_to_words(number, apocope=True)} {mag}")
        if currency:
            cur = _CUR_PLURAL[_CUR_WORDS[currency]]
            words.append(f"de {cur}" if with_de else cur)
    else:
        amount = decimal_to_words(number, apocope=True)
        words.append(amount)
        if currency:
            cur = _CUR_WORDS[currency]
            cur = cur if one else _CUR_PLURAL[cur]
            # «1.000.000 €» → «un millón de euros»
            words.append(f"de {cur}" if amount.endswith(("millón", "millones", "billón", "billones")) else cur)
    return " ".join(words)


def _sub_amounts(text: str) -> str:
    text = _AMOUNT_PRE.sub(lambda m: _amount_words(m.group(1), m.group(3), m.group(4), m.group(2)), text)
    text = _AMOUNT_POST.sub(lambda m: _amount_words(m.group(1), m.group(2), m.group(3), m.group(4)), text)
    return _BARE_BN.sub(lambda m: _amount_words(m.group(1), m.group(2), m.group(3), None), text)


# Porcentajes y puntos.
_PERCENT = re.compile(_SIGN + r"(?<![\w,.])(" + _NUM + r")\s?(?:%|por\s?ciento)")
_POINTS = re.compile(_SIGN + r"(?<![\w,.])(" + _NUM + r")\s?(p\.?\s?b\.?|pbs?|bps?|p\.?\s?p\.?|pp)(?![\w])")


def _signed(sign: str | None, words: str) -> str:
    return f"{_SIGN_WORDS[sign]} {words}" if sign else words


_PERCENT_RANGE = re.compile(r"(?<![\w,.])(" + _NUM + r")\s?(?:%\s?)?[-–]\s?(" + _NUM + r")\s?%")


def _sub_percent_points(text: str) -> str:
    # «1-2 %» → «uno a dos por ciento» (antes de que el «-» se lea como signo).
    text = _PERCENT_RANGE.sub(
        lambda m: f"{decimal_to_words(m.group(1))} a {decimal_to_words(m.group(2))} por ciento", text
    )
    text = _PERCENT.sub(lambda m: _signed(m.group(1), decimal_to_words(m.group(2)) + " por ciento"), text)

    def _pts(m: re.Match[str]) -> str:
        number = m.group(2)
        one = _is_one(number)
        if "b" in m.group(3):
            kind = "básico" if one else "básicos"
        else:
            kind = "porcentual" if one else "porcentuales"
        unit = "punto" if one else "puntos"
        return _signed(m.group(1), f"{decimal_to_words(number, apocope=True)} {unit} {kind}")

    return _POINTS.sub(_pts, text)


# Horas («15:30», «9:05 h»), ordinales («1º», «3ª», «1er») y múltiplos («3,5x»).
_TIME = re.compile(r"(?<![\d:,.])([01]?\d|2[0-3]):([0-5]\d)(?:\s?(h|horas)(?![\w]))?(?![\d:])")
_ORDINALS_M = ["", "primero", "segundo", "tercero", "cuarto", "quinto", "sexto", "séptimo", "octavo",
               "noveno", "décimo"]
_ORDINAL = re.compile(r"(?<![\w,.])(10|[1-9])(?:(º)|(ª)|(er)(?![\w]))")
_MULTIPLE = re.compile(r"(?<![\w,.])(" + _NUM + r")\s?x(?![\w])")


def _sub_times_ordinals(text: str) -> str:
    def _time(m: re.Match[str]) -> str:
        hours, minutes = int(m.group(1)), int(m.group(2))
        words = number_to_words(hours, apocope=True) if hours != 1 else "una"
        if minutes:  # «9:05» -> «nueve y cinco»; «15:30» -> «quince treinta»
            words += f" {'y ' if minutes < 10 else ''}{number_to_words(minutes)}"
        return words + (" horas" if m.group(3) else "")

    def _ordinal(m: re.Match[str]) -> str:
        n = int(m.group(1))
        word = _ORDINALS_M[n]
        if m.group(3):  # femenino
            return word[:-1] + "a"
        if m.group(4) and n in (1, 3):  # «1er», «3er» -> apócope
            return word[:-1]
        return word

    text = _TIME.sub(_time, text)
    text = _ORDINAL.sub(_ordinal, text)
    return _MULTIPLE.sub(lambda m: f"{decimal_to_words(m.group(1))} {'vez' if _is_one(m.group(1)) else 'veces'}", text)


# Números sueltos con decimales o separador de miles.
_DECIMAL = re.compile(_SIGN + r"(?<![\w,.])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+[.,]\d+)(?![\w,]|\.\d)")


def _sub_numbers(text: str) -> str:
    def _fn(m: re.Match[str]) -> str:
        integer, dec = _parse_number(m.group(2))
        if not dec:  # «10.000» → «10000»: el TTS lee bien los enteros
            return _signed(m.group(1), str(integer)) if m.group(1) in ("-", "−", "–") else (
                (m.group(1) or "") + str(integer))
        return _signed(m.group(1), decimal_to_words(m.group(2)))

    return _DECIMAL.sub(_fn, text)


# Abreviaturas y siglas (sensible a mayúsculas, palabra completa).
ABBREVIATIONS: dict[str, str] = {
    "IBEX": "Ibex",
    "Ibex-35": "Ibex 35",
    "BCE": "Banco Central Europeo",
    "Fed": "Reserva Federal",
    "FED": "Reserva Federal",
    "BoE": "Banco de Inglaterra",
    "BoJ": "Banco de Japón",
    "EPS": "beneficio por acción",
    "BPA": "beneficio por acción",
    "EBITDA": "ebitda",
    "EBIT": "ebit",
    "PER": "per",
    "OPA": "opa",
    "CEO": "consejero delegado",
    "CFO": "director financiero",
    "NVIDIA": "Nvidia",
    "YoY": "interanual",
    "QoQ": "intertrimestral",
    "YTD": "en lo que va de año",
    "S&P": "Standard and Poor's",
    "IA": "inteligencia artificial",
    "AI": "inteligencia artificial",
    "IPO": "salida a bolsa",
    "OPV": "oferta pública de venta",
    "ETF": "fondo cotizado",
    "ETFs": "fondos cotizados",
    "PIB": "pib",
    "ROE": "rentabilidad sobre fondos propios",
    "M&A": "fusiones y adquisiciones",
    "CNMV": "Comisión Nacional del Mercado de Valores",
    "UE": "Unión Europea",
    "USD": "dólares",
    "EUR": "euros",
}
# Abreviaturas con puntos o espacios (no encajan en la frontera de palabra estándar).
_SPECIAL_ABBREVIATIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<![\w.])EE\.?\s?UU\.?(?![\w])"), "Estados Unidos"),
    (re.compile(r"(?<![\w.])vs\.?(?![\w])"), "frente a"),
    (re.compile(r"(?<![\w.])a/a(?![\w])"), "interanual"),
    (re.compile(r"(?<![\w.])aprox\.(?![\w])"), "aproximadamente"),
    (re.compile(r"(?<![\w.])etc\.(?![\w])"), "etcétera"),
    (re.compile(r"(?<![\w.])AI Act(?![\w])"), "Reglamento europeo de inteligencia artificial"),
]
_ABBR_RE = re.compile(
    _L + r"(" + "|".join(re.escape(k) for k in sorted(ABBREVIATIONS, key=len, reverse=True)) + r")" + _R
)


def _sub_abbreviations(text: str) -> str:
    for pattern, replacement in _SPECIAL_ABBREVIATIONS:
        text = pattern.sub(replacement, text)
    return _ABBR_RE.sub(lambda m: ABBREVIATIONS[m.group(1)], text)


# Símbolos sueltos que quedan.
_SYMBOLS = [
    (re.compile(r"(euros?|dólares?|€|\$)\s*/\s*(?=[^\W\d])"), r"\1 por "),
    (re.compile(r"\s*&\s*"), " y "),
    (re.compile(r"\s*€"), " euros"),
    (re.compile(r"\s*%"), " por ciento"),
    (re.compile(r"(?<=[^\W\d])\s*/\s*(?=[^\W\d])"), " "),  # «compra/venta» (no fechas ni cifras)
    (re.compile(r"[*_#`]+"), ""),           # restos de markdown
    (re.compile(r"\s+([,.;:!?])"), r"\1"),
    (re.compile(r"\s{2,}"), " "),
]


def _sub_symbols(text: str) -> str:
    for pattern, replacement in _SYMBOLS:
        text = pattern.sub(replacement, text)
    return text.strip()


def normalize_for_speech(text: str) -> str:
    """Devuelve ``text`` preparado para leerse en voz alta en español (ver docstring del módulo).

    El orden importa: pares de divisas/marca → tickers → fechas → periodos → importes →
    porcentajes/puntos → horas/ordinales/múltiplos → números sueltos → abreviaturas → símbolos. Si el resultado quedara vacío, devuelve el original.
    """
    if not text or not text.strip():
        return text
    out = _sub_pre(text)
    out = _replace_tickers(out)
    out = _sub_dates(out)
    out = _sub_periods(out)
    out = _sub_amounts(out)
    out = _sub_percent_points(out)
    out = _sub_times_ordinals(out)
    out = _sub_numbers(out)
    out = _sub_abbreviations(out)
    out = _sub_symbols(out)
    return out or text


__all__ = ["ABBREVIATIONS", "decimal_to_words", "normalize_for_speech", "number_to_words"]
