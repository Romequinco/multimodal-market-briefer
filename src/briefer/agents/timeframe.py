"""Marco temporal del episodio: saludo y si se puede hablar de «cierre» (hora de Madrid).

Carril B. Briefly es la «edición de noche» (marca), pero el briefing puede generarse a cualquier
hora: a mediodía los precios son **intradía** y el guion no debe decir «buenas noches» ni «con el
cierre del día» (evaluación del 06-oct-2026). ``time_frame`` decide, a partir de la hora de
generación en Madrid y de los mercados de los valores del episodio:

- saludo: antes de las 14:00 «Buenos días»; hasta el cierre del IBEX (17:35) «Buenas tardes»;
  después, «Buenas noches» (la edición de noche);
- estado de la sesión: ``pre`` (antes de la apertura: precios del último cierre), ``open``
  (intradía) o ``closed`` (cerrada, o fin de semana: precios del último cierre);
- ``note``: el marco explicado para el prompt del Guionista (y del Analista).

Horarios en hora de Madrid: bolsas europeas 9:00-17:35; Wall Street 15:30-22:00. No contempla
festivos. ``now`` se inyecta en los tests (nunca dependen del reloj real).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Literal

MADRID_TZ = "Europe/Madrid"
#: Cierre del mercado continuo español (y referencia de «edición de noche»).
EU_OPEN, EU_CLOSE = time(9, 0), time(17, 35)
#: Wall Street en hora de Madrid (aprox.; los cambios de hora no coinciden un par de semanas al año).
US_OPEN, US_CLOSE = time(15, 30), time(22, 0)
#: A partir de esta hora el saludo deja de ser «Buenos días».
AFTERNOON = time(14, 0)

#: Índices estadounidenses (el resto de ``^…`` se trata como europeo).
_US_INDICES = frozenset({"^GSPC", "^IXIC", "^DJI", "^NDX", "^RUT"})

Session = Literal["pre", "open", "closed"]


@dataclass(frozen=True)
class TimeFrame:
    """Marco temporal del episodio (ver el docstring del módulo)."""

    when: datetime
    greeting: str
    session: Session
    #: ``True`` si alguno de los mercados del episodio ya ha cerrado hoy (o es fin de semana):
    #: entonces se puede hablar de «cierre». Si es ``False``, el guion no debe afirmarlo.
    can_say_close: bool
    note: str

    @property
    def is_night(self) -> bool:
        return self.greeting == "Buenas noches"


def madrid_now() -> datetime:
    """Hora actual en Madrid (con zona); si no hay base de datos de zonas, la hora local."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(MADRID_TZ))
    except Exception:  # pragma: no cover - sin tzdata
        return datetime.now()


def _to_madrid(now: datetime) -> datetime:
    """``now`` en hora de Madrid (las horas sin zona se interpretan ya como de Madrid)."""
    if now.tzinfo is None:
        return now
    try:
        from zoneinfo import ZoneInfo

        return now.astimezone(ZoneInfo(MADRID_TZ))
    except Exception:  # pragma: no cover - sin tzdata
        return now


def market_of(ticker: str) -> Literal["eu", "us"]:
    """Mercado de un ticker de Yahoo: sin sufijo (``AAPL``) o índice de EE. UU. -> ``"us"``."""
    t = ticker.upper()
    if t.startswith("^"):
        return "us" if t in _US_INDICES else "eu"
    return "eu" if "." in t else "us"


def _state(clock: time, opens: time, closes: time) -> Session:
    if clock < opens:
        return "pre"
    return "open" if clock < closes else "closed"


def greeting_for(clock: time) -> str:
    """Saludo según la hora de Madrid: días (< 14:00), tardes (< 17:35), noches (después)."""
    if clock < AFTERNOON:
        return "Buenos días"
    return "Buenas tardes" if clock < EU_CLOSE else "Buenas noches"


def time_frame(now: datetime | None = None, tickers: list[str] | tuple[str, ...] = ()) -> TimeFrame:
    """Marco temporal para ``now`` (por defecto, la hora actual en Madrid) y los ``tickers`` del
    episodio (sin tickers, mercado europeo)."""
    when = _to_madrid(now) if now is not None else madrid_now()
    clock = when.time().replace(tzinfo=None)
    markets = {market_of(t) for t in tickers if t.strip()} or {"eu"}
    weekend = when.weekday() >= 5
    hours = {"eu": (EU_OPEN, EU_CLOSE), "us": (US_OPEN, US_CLOSE)}
    states = {m: ("closed" if weekend else _state(clock, *hours[m])) for m in markets}
    greeting = greeting_for(clock)
    hhmm = f"{clock:%H:%M}"
    if "open" in states.values():
        session: Session = "open"
    elif all(s == "closed" for s in states.values()):
        session = "closed"
    else:
        session = "pre" if "closed" not in states.values() else "closed"
    can_say_close = "closed" in states.values()

    if weekend:
        note = (
            f"Es fin de semana ({hhmm}, hora de Madrid): los precios son del último cierre (el del "
            "viernes). Habla de «la última sesión» o «el cierre del viernes», no de «hoy»."
        )
    elif all(s == "closed" for s in states.values()):
        note = f"Son las {hhmm} (hora de Madrid) y la sesión ya ha cerrado: puedes hablar del cierre del día."
    elif can_say_close:  # mezcla: Europa cerrada, Wall Street abierta
        note = (
            f"Son las {hhmm} (hora de Madrid): la bolsa europea ya ha cerrado (17:35), pero Wall Street "
            "sigue abierta: los valores de EE. UU. van con precios intradía; de ellos no digas que "
            "«cierran», sino que «suben» o «cotizan» «a esta hora»."
        )
    elif session == "open":
        note = (
            f"Son las {hhmm} (hora de Madrid) y la sesión sigue **abierta**: los precios son intradía, "
            "no de cierre. No digas «el cierre del día», «al cierre», «cierra en/con», «la sesión ha "
            "cerrado» ni «buenas noches»; di «a esta hora de la sesión», «en lo que va de sesión», "
            "«cotiza en», «sube» o «cae». «El cierre anterior» o «el cierre de ayer» sí valen."
        )
    else:
        note = (
            f"Son las {hhmm} (hora de Madrid) y la sesión de hoy aún no ha abierto: los precios son "
            "los del último cierre (la sesión anterior). Di «en la última sesión» o «ayer», no «hoy "
            "cierra»; tampoco «buenas noches»."
        )
    note += f" Saluda con «{greeting}»."
    return TimeFrame(when=when, greeting=greeting, session=session, can_say_close=can_say_close, note=note)


__all__ = [
    "EU_CLOSE",
    "EU_OPEN",
    "MADRID_TZ",
    "US_CLOSE",
    "US_OPEN",
    "TimeFrame",
    "greeting_for",
    "madrid_now",
    "market_of",
    "time_frame",
]
