"""1С «Валовая прибыль по клиентам» PDF есебін оқу.

Есептің кестесі pdfplumber арқылы оқылады. Бағандар тақырыбы бойынша
анықталады (Количество, Выручка, Себестоимость, Валовая прибыль,
Процент АС/РС ...), сондықтан 1С-та баған қоссаңыз да, парсер оларды табады.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pdfplumber

from .fmt import num


class ReportParseError(Exception):
    """PDF-тен 1С есебін оқу мүмкін болмағанда."""


# ---------------------------------------------------------------- helpers

_NUM_RE = re.compile(r"^[-−–]?\d[\d\s  ]*(?:[.,]\d+)?$")

DOC_RE = re.compile(
    r"^(?P<doc>.*?)\s*(?P<num>[0-9A-Za-zА-Яа-яЁё]+-\d+)\s+от\s+"
    r"(?P<date>\d{2}\.\d{2}\.\d{4})(?:\s+(?P<time>\d{1,2}:\d{2}:\d{2}))?"
)
PERIOD_RE = re.compile(r"Период:\s*(\d{2}\.\d{2}\.\d{4})\s*[-–]\s*(\d{2}\.\d{2}\.\d{4})")
HEADER_LABELS = {
    "менеджер", "заказ клиента / реализация", "сегмент", "номенклатура",
    "партнер", "клиент", "контрагент", "заказ клиента", "реализация",
}


def clean(cell) -> str:
    if cell is None:
        return ""
    return re.sub(r"\s+", " ", str(cell).replace("\n", " ")).strip()


def parse_num(text: str) -> Optional[float]:
    t = clean(text)
    if not t or not _NUM_RE.match(t):
        return None
    t = t.replace("−", "-").replace("–", "-")
    t = re.sub(r"[\s  ]", "", t).replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def measure_key(name: str) -> Optional[str]:
    """Баған тақырыбын ішкі атқа айналдырады."""
    n = clean(name).lower()
    if not n:
        return None
    words = set(re.findall(r"[a-zа-яё]+", n))
    if "скидк" in n and "сумм" in n:
        if "ручн" in n:
            return "manual_disc_sum"
        if "автомат" in n:
            return "auto_disc_sum"
    if "процент" in n or "%" in n or words & {"ас", "рс"}:
        if "рс" in words or "ручн" in n:
            return "manual_disc_pct"
        if "ас" in words or "автомат" in n:
            return "auto_disc_pct"
    if "себестоимост" in n:
        return "cost"
    if "прибыл" in n:
        return "profit"
    if "рентабельн" in n:
        return "margin_pct"
    if "наценк" in n:
        return "markup_pct"
    if "выручк" in n:
        return "revenue_net" if "без ндс" in n else "revenue"
    if "количеств" in n:
        return "qty"
    if "ндс" in words:
        return "vat"
    return None


MEASURE_TITLES = {
    "qty": "Количество",
    "revenue": "Выручка",
    "revenue_net": "Выручка без НДС",
    "cost": "Себестоимость",
    "profit": "Валовая прибыль",
    "margin_pct": "Рентабельность, %",
    "markup_pct": "Наценка, %",
    "auto_disc_pct": "Процент АС",
    "manual_disc_pct": "Процент РС",
    "auto_disc_sum": "Сумма авт. скидки",
    "manual_disc_sum": "Сумма ручн. скидки",
    "vat": "НДС",
}


# ---------------------------------------------------------------- model

@dataclass
class Line:
    order: Optional[str]
    segment: str
    item: str
    m: dict
    manager: str = ""
    client: str = ""

    @property
    def qty(self) -> float:
        return self.m.get("qty") or 0.0

    @property
    def revenue(self) -> float:
        return self.m.get("revenue") or 0.0


@dataclass
class Order:
    number: str
    series: str
    doc_type: str
    date: Optional[date]
    time: Optional[str]
    m: dict
    manager: str = ""
    client: str = ""
    empty: bool = False
    lines: list = field(default_factory=list)

    @property
    def revenue(self) -> float:
        return self.m.get("revenue") or 0.0

    @property
    def qty(self) -> float:
        return self.m.get("qty") or 0.0


@dataclass
class Report:
    title: str = ""
    currency: str = "KZT"
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    params: list = field(default_factory=list)
    measures: list = field(default_factory=list)
    managers: list = field(default_factory=list)  # [(label, m)]
    orders: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    pages: int = 0
    warnings: list = field(default_factory=list)

    @property
    def has_items(self) -> bool:
        return bool(self.lines)

    @property
    def real_orders(self) -> list:
        return [o for o in self.orders if not o.empty]


def _to_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%d.%m.%Y").date()
    except (TypeError, ValueError):
        return None


def manager_name(label: str) -> str:
    m = re.search(r"\(([^()]+)\)\s*$", label)
    return m.group(1).strip() if m else label.strip()


# ---------------------------------------------------------------- parsing

def _collect_rows(pdf) -> list:
    rows = []
    for page in pdf.pages:
        for table in page.extract_tables():
            for r in table:
                rows.append(list(r))
    return rows


def _header_info(rows: list):
    """Тақырып жолдарын тауып, әр бағанның мағынасын анықтайды."""
    ncols = max((len(r) for r in rows), default=0)
    title_text = ""
    header_rows = []
    first_data = None
    for i, r in enumerate(rows[:12]):
        cells = [clean(c) for c in r]
        if r and all(c is None for c in r[1:]) and cells[0]:
            title_text += ("\n" if title_text else "") + str(r[0])
            continue
        if any(parse_num(c) is not None for c in cells[1:]):
            first_data = i
            break
        if any(cells):
            header_rows.append(r)
    if first_data is None:
        raise ReportParseError("Кестеде сан жолдары табылмады")

    names = []
    for j in range(ncols):
        parts = [clean(r[j]) for r in header_rows if j < len(r) and clean(r[j])]
        names.append(" ".join(parts))
    measure_cols = {}
    label_cols = []
    for j, name in enumerate(names):
        key = measure_key(name)
        if key and key not in measure_cols.values():
            measure_cols[j] = key
        elif not key:
            label_cols.append(j)
    if not label_cols:
        label_cols = [0]
    return title_text, names, measure_cols, label_cols, first_data


def parse_report(path: str) -> Report:
    try:
        pdf = pdfplumber.open(path)
    except Exception as exc:  # noqa: BLE001
        raise ReportParseError(f"PDF ашылмады: {exc}") from exc

    with pdf:
        rows = _collect_rows(pdf)
        rep = Report(pages=len(pdf.pages))
        page_text = ""
        try:
            page_text = pdf.pages[0].extract_text() or ""
        except Exception:  # noqa: BLE001
            pass
    if not rows:
        raise ReportParseError("PDF-те кесте жоқ (сканерленген сурет болуы мүмкін)")

    title_text, names, measure_cols, label_cols, first_data = _header_info(rows)
    # Тақырыбы танылмаған, бірақ ішінде тек сандар тұрған бағанды мәтін бағаны деп санамаймыз
    for j in list(label_cols[1:]):
        filled = [clean(r[j]) for r in rows[first_data:] if j < len(r) and clean(r[j])]
        if filled and sum(parse_num(v) is not None for v in filled) / len(filled) >= 0.8:
            label_cols.remove(j)
    if "revenue" not in measure_cols.values():
        if "revenue_net" in measure_cols.values():
            measure_cols = {j: ("revenue" if k == "revenue_net" else k) for j, k in measure_cols.items()}
        else:
            raise ReportParseError("«Выручка» бағаны табылмады")

    head = title_text or page_text
    first_line = clean(head.split("\n")[0]) if head else ""
    rep.title = first_line or "1С есебі"
    cur = re.search(r"\(([A-Z]{3})\)", first_line)
    if cur:
        rep.currency = cur.group(1)
    pm = PERIOD_RE.search(head) or PERIOD_RE.search(page_text)
    if pm:
        rep.period_from, rep.period_to = _to_date(pm.group(1)), _to_date(pm.group(2))
    for ln in (title_text or "").split("\n")[1:]:
        ln = clean(ln)
        if ln and not ln.startswith("Параметры"):
            rep.params.append(ln)
    rep.measures = list(measure_cols.values())

    header_texts = {clean(n).lower() for n in names if n}
    lbl0 = label_cols[0]
    lbl1 = label_cols[1] if len(label_cols) > 1 else None
    extra_lbls = label_cols[2:]

    cur_order: Optional[Order] = None
    cur_manager = ""
    cur_client = ""
    for r in rows[first_data:]:
        cells = [clean(c) for c in r] + [""] * (len(names) - len(r))
        if not any(cells):
            continue
        a = cells[lbl0]
        b = cells[lbl1] if lbl1 is not None else ""
        if extra_lbls:
            extra = " ".join(cells[j] for j in extra_lbls if cells[j])
            b = f"{b} {extra}".strip()
        vals = {k: parse_num(cells[j]) for j, k in measure_cols.items() if j < len(cells)}
        vals = {k: v for k, v in vals.items() if v is not None}
        if not vals and (a.lower() in HEADER_LABELS or a.lower() in header_texts):
            continue  # қайталанған тақырып
        if a.startswith("Итого"):
            rep.totals = vals
            continue
        dm = DOC_RE.match(a) if a else None
        if dm and (not b or len(b) <= 3):  # құжат жолы (көрші ұяшыққа сыймай кеткен 1–3 таңба болуы мүмкін)
            num = dm.group("num")
            cur_order = Order(
                number=num,
                series=num.split("-")[0],
                doc_type=clean(dm.group("doc")) or "Документ",
                date=_to_date(dm.group("date")),
                time=dm.group("time"),
                m=vals,
                manager=cur_manager,
                client=cur_client,
                empty=not vals,
            )
            rep.orders.append(cur_order)
            continue
        if b:
            if not vals:
                continue
            line = Line(
                order=cur_order.number if cur_order else None,
                segment=a,
                item=b,
                m=vals,
                manager=cur_manager,
                client=cur_client,
            )
            rep.lines.append(line)
            if cur_order:
                cur_order.lines.append(line)
            continue
        if a and vals:
            if a.lower().startswith("менеджер") or not rep.managers or not cur_manager:
                cur_manager = a
                cur_client = ""
                rep.managers.append((a, vals))
            else:
                cur_client = a
            cur_order = None
            continue

    if not rep.orders and not rep.lines:
        raise ReportParseError("Заказ немесе тауар жолдары табылмады")
    _validate(rep)
    return rep


def _validate(rep: Report) -> None:
    tol = 1.0
    real = rep.real_orders
    if rep.totals.get("revenue") is not None:
        s = sum(o.revenue for o in real) if real else sum(l.revenue for l in rep.lines)
        if abs(s - rep.totals["revenue"]) > tol:
            rep.warnings.append(
                f"Заказдар қосындысы ({num(s, 2)}) «Итого»-мен ({num(rep.totals['revenue'], 2)}) сәйкес емес"
            )
    if rep.lines:
        bad = []
        for o in real:
            if o.lines:
                s = sum(l.revenue for l in o.lines)
                if abs(s - o.revenue) > tol:
                    bad.append(o.number)
        if bad:
            rep.warnings.append(f"{len(bad)} заказда тауар жолдарының қосындысы заказ сомасымен сәйкес емес: {', '.join(bad[:5])}")
