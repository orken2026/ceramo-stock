"""Сандарды қазақша пішімдеу (мың бөлгіш — бос орын, ондық — үтір)."""
from __future__ import annotations

from datetime import date
from html import escape
from typing import Optional

NBSP = " "


def _kz(s: str) -> str:
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", NBSP).replace("-", "−")


def money(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return _kz(f"{v:,.0f}")


def num(v: Optional[float], d: int = 1) -> str:
    if v is None:
        return "—"
    return _kz(f"{v:,.{d}f}")


def pct(v: Optional[float], d: int = 1) -> str:
    return "—" if v is None else num(v, d) + "%"


def qty(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if abs(v - round(v)) < 0.005:
        return money(round(v))
    s = _kz(f"{v:,.2f}")
    return s.rstrip("0").rstrip(",") if "," in s else s


def mln(v: float) -> str:
    return _kz(f"{v / 1e6:,.2f}") + " млн"


def dstr(d: Optional[date]) -> str:
    return d.strftime("%d.%m.%Y") if d else "—"


def h(s) -> str:
    return escape(str(s), quote=False)
