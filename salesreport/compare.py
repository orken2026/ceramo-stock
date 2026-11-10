"""Алдыңғы есеппен салыстыру: тарихқа жазу үшін қысқа жиынтық және өзгерістер."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from .fmt import dstr, h, money, num, pct


def snapshot(A: dict) -> dict:
    """Тарихта сақталатын негізгі сандар."""
    m, k = A["meta"], A["kpi"]
    pf, pt = m["period_from"], m["period_to"]
    approx = False
    if not pf:
        # Кезең көрсетілмесе — заказ күндерінің аралығы
        dates = sorted(d for d in (A.get("_order_dates") or []) if d)
        if dates:
            pf, pt, approx = dates[0], dates[-1], True
    return {
        "period_from": pf.isoformat() if pf else None,
        "period_to": pt.isoformat() if pt else None,
        "period_approx": approx,
        "managers": sorted(m["managers"]),
        "title": m["title"],
        "revenue": k["revenue"],
        "orders": k["orders"],
        "avg": k["avg"],
        "tile_m2": k["tile_m2"],
        "manual_disc_pct": k["manual_disc_pct"] if m["has_manual"] else None,
        "profit": k.get("profit"),
        "margin": k.get("margin"),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }


def find_previous(history: list, snap: dict) -> Optional[dict]:
    """Сол менеджер(лер) бойынша осы кезеңнен бұрынғы ең соңғы есеп."""
    if not snap.get("period_from") or snap.get("period_approx"):
        return None
    cands = [e for e in history
             if e.get("managers") == snap["managers"] and e.get("period_from") and not e.get("period_approx")
             and e["period_from"] < snap["period_from"]]
    return max(cands, key=lambda e: e["period_from"]) if cands else None


def upsert(history: list, snap: dict) -> list:
    """Бір кезең қайта жүктелсе — ескісін ауыстырады."""
    key = (snap.get("period_from"), snap.get("period_to"), tuple(snap.get("managers") or []))
    out = [e for e in history if (e.get("period_from"), e.get("period_to"), tuple(e.get("managers") or [])) != key]
    out.append(snap)
    out.sort(key=lambda e: e.get("period_from") or "")
    return out[-36:]


def _arrow(cur: float, prev: float) -> str:
    if not prev:
        return ""
    ch = (cur - prev) / abs(prev) * 100
    sign = "▲" if ch > 0.05 else ("▼" if ch < -0.05 else "•")
    return f"{sign} {num(abs(ch))}%"


def _pp(cur: Optional[float], prev: Optional[float]) -> str:
    if cur is None or prev is None:
        return ""
    d = cur - prev
    sign = "▲" if d > 0.005 else ("▼" if d < -0.005 else "•")
    return f"{sign} {num(abs(d), 2)} п.п."


def _d(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


def compare_text(snap: dict, prev: dict) -> str:
    cur = "₸"
    out = [f"📈 <b>Алдыңғы есеппен салыстыру</b> ({dstr(_d(prev['period_from']))} – {dstr(_d(prev['period_to']))})"]
    out.append(f"• Сатылым: {money(snap['revenue'])} {cur} ({_arrow(snap['revenue'], prev['revenue'])}, бұрын {money(prev['revenue'])})")
    out.append(f"• Заказдар: {snap['orders']} ({_arrow(snap['orders'], prev['orders'])}, бұрын {prev['orders']})")
    out.append(f"• Орташа чек: {money(snap['avg'])} {cur} ({_arrow(snap['avg'], prev['avg'])})")
    if snap.get("tile_m2") and prev.get("tile_m2"):
        out.append(f"• Плитка: {money(snap['tile_m2'])} м² ({_arrow(snap['tile_m2'], prev['tile_m2'])})")
    if snap.get("manual_disc_pct") is not None and prev.get("manual_disc_pct") is not None:
        out.append(f"• Қолмен жеңілдік: {pct(snap['manual_disc_pct'], 2)} ({_pp(snap['manual_disc_pct'], prev['manual_disc_pct'])})")
    if snap.get("profit") is not None and prev.get("profit") is not None:
        out.append(f"• Валовая прибыль: {money(snap['profit'])} {cur} ({_arrow(snap['profit'], prev['profit'])}), маржа {pct(snap['margin'])} ({_pp(snap['margin'], prev['margin'])})")
    return "\n".join(out)


def history_text(history: list) -> str:
    if not history:
        return "Әзірге сақталған есеп жоқ. 1С-тан PDF жіберіңіз."
    out = ["🗂 <b>Сақталған есептер</b>"]
    for e in reversed(history[-12:]):
        per = f"{dstr(_d(e.get('period_from')))} – {dstr(_d(e.get('period_to')))}" if e.get("period_from") else "кезеңсіз"
        if e.get("period_approx"):
            per = f"≈ {per} (заказ күндері бойынша)"
        who = ", ".join(e.get("managers") or []) or "—"
        line = f"• {per} · {h(who)} — {money(e['revenue'])} ₸, {e['orders']} заказ"
        if e.get("profit") is not None:
            line += f", пайда {money(e['profit'])} ₸"
        out.append(line)
    return "\n".join(out)
