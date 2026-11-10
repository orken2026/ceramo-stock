"""Тест үшін 1С-ке ұқсас PDF жасайды: себестоимость пен валовая прибыль бағандарымен.

python tests/make_synthetic_pdf.py out.pdf 2026-09
"""
import random
import sys
from datetime import date, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

pdfmetrics.registerFont(TTFont("DV", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))

ITEMS = [
    ("2-ая категория для бонусы розница", "Керамогранит D12502 (120*60)3 матовый", 3800, True),
    ("2-ая категория для бонусы розница", "Керамическая плитка 75C09 (150*75)", 3500, True),
    ("4-ая категория для бонусы розница", "Керамическая плитка BK09P (90*15) матовая", 11990, True),
    ("1-ая категория для бонусы розница", "Кафель TP45201DB (45*45)", 2750, True),
    ("5-ая категория для бонусы розница", "Смеситель одноручный для ванны S35-33", 33500, False),
    ("5-ая категория для бонусы розница", "Напольный унитаз без бачка NS-3170-FST", 44990, False),
    ("", "Доставка", 15000, False),
]


def fmt(v, d=2):
    s = f"{v:,.{d}f}".replace(",", " ").replace(".", ",")
    return s


def build(path: str, ym: str, seed: int = 7, manager: str = "Тест Тестов") -> None:
    random.seed(seed)
    y, mth = map(int, ym.split("-"))
    start = date(y, mth, 1)
    end = (date(y + (mth == 12), mth % 12 + 1, 1) - timedelta(days=1))
    orders = []
    for i in range(30):
        d = start + timedelta(days=random.randint(0, (end - start).days))
        lines = []
        for seg, name, price, tile in random.sample(ITEMS, random.randint(1, 3)):
            q = round(random.choice([1.44, 2.16, 4.32, 8.64, 17.28, 30.24]), 3) if tile else 1.0
            rev = round(q * price, 2)
            ratio = 0.0 if name == "Доставка" else random.uniform(0.55, 0.92)
            if i == 3 and tile:
                ratio = 1.25  # шығынмен сатылған жол
            cost = round(rev * ratio, 2)
            rc = 7.0 if i == 0 else None
            lines.append((seg, name, q, rev, cost, rc))
        orders.append((f"LI22-{8000 + i:06d}", d, lines))

    head = f"Валовая прибыль по клиентам (KZT)\nПараметры: Период: {start:%d.%m.%Y} - {end:%d.%m.%Y}\nОтбор: Менеджер Тест"
    data = [[head, "", "", "", "", "", "", ""],
            ["Менеджер", "", "Количество", "Выручка", "Себестоимость", "Валовая прибыль", "Процент", "Процент"],
            ["Заказ клиента / Реализация", "", "", "", "", "", "АС", "РС"],
            ["Сегмент", "Номенклатура", "", "", "", "", "", ""]]
    tot_rev = sum(l[3] for _, _, ls in orders for l in ls)
    tot_cost = sum(l[4] for _, _, ls in orders for l in ls)
    data.append([f"Менеджер розничного отдела ({manager})", "", "", fmt(tot_rev), fmt(tot_cost), fmt(tot_rev - tot_cost), "", ""])
    for num, d, ls in orders:
        rev = sum(l[3] for l in ls)
        cost = sum(l[4] for l in ls)
        data.append([f"Заказ клиента {num} от {d:%d.%m.%Y} {random.randint(10, 18)}:{random.randint(10, 59)}:00", "", "",
                     fmt(rev), fmt(cost), fmt(rev - cost), "", "7,00" if ls[0][5] else ""])
        for seg, name, q, r, c, rc in ls:
            data.append([seg, name, fmt(q, 3), fmt(r), fmt(c) if c else "", fmt(r - c), "", fmt(rc) if rc else ""])
    data.append(["Итого", "", "", fmt(tot_rev), fmt(tot_cost), fmt(tot_rev - tot_cost), "", ""])

    t = Table(data, colWidths=[165, 140, 40, 55, 55, 55, 30, 30], repeatRows=0)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "DV", 5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("SPAN", (0, 0), (-1, 0)),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
    ]))
    SimpleDocTemplate(path, pagesize=A4, leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20).build([t])


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "2026-09",
          manager=sys.argv[3] if len(sys.argv) > 3 else "Тест Тестов")
    print("ok", sys.argv[1])
