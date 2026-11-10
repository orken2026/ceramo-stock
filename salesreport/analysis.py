"""Оқылған 1С есебінен барлық көрсеткіштерді есептеу."""
from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Optional

from .classify import DELIVERY, SANITARY, SERVICES, TILE, kind_of, segment_label, tile_format, unit_of
from .parser import Report, manager_name

CLEARANCE_PRICE = 1500      # ₸/м² — осыдан арзан плитка «қалдық/уценка» деп белгіленеді
BIG_ORDER = 100_000         # ₸ — «ірі заказ» шегі
WEEKDAYS = ["Дүйсенбі", "Сейсенбі", "Сәрсенбі", "Бейсенбі", "Жұма", "Сенбі", "Жексенбі"]
WEEKDAYS_SHORT = ["Дс", "Сс", "Ср", "Бс", "Жм", "Сн", "Жк"]
SIZE_BUCKETS = [
    ("Қайтару (теріс сома)", None, 0),
    ("10 мың ₸-ге дейін", 0, 10_000),
    ("10–50 мың ₸", 10_000, 50_000),
    ("50–100 мың ₸", 50_000, 100_000),
    ("100–250 мың ₸", 100_000, 250_000),
    ("250 мың – 1 млн ₸", 250_000, 1_000_000),
    ("1 млн ₸-ден көп", 1_000_000, None),
]


def implied_discount(revenue: float, pct: Optional[float]) -> float:
    """Сатылған сома мен жеңілдік пайызынан прайстан берілген жеңілдік сомасы."""
    if pct is None or pct >= 100:
        return 0.0
    return revenue * pct / (100 - pct)


def profit_of(m: dict, measures: list) -> Optional[float]:
    if "profit" in measures:
        if m.get("profit") is not None:
            return m["profit"]
        if "cost" in measures:
            return (m.get("revenue") or 0) - (m.get("cost") or 0)
        return 0.0
    if "cost" in measures:
        return (m.get("revenue") or 0) - (m.get("cost") or 0)
    return None


def _share(part: float, whole: float) -> float:
    return part / whole * 100 if whole else 0.0


def _margin(profit: Optional[float], revenue: float) -> Optional[float]:
    if profit is None or not revenue:
        return None
    return profit / revenue * 100


def analyze(rep: Report) -> dict:
    measures = rep.measures
    has_profit = "profit" in measures or "cost" in measures
    has_manual = "manual_disc_pct" in measures
    has_auto = "auto_disc_pct" in measures
    orders = rep.real_orders
    lines = rep.lines

    # ---- тауар жолдарын байыту
    rows = []
    for l in lines:
        kind = kind_of(l.item)
        rows.append({
            "order": l.order,
            "item": l.item,
            "segment": l.segment,
            "seg": segment_label(l.segment),
            "kind": kind,
            "fmt": tile_format(l.item) if kind == TILE else "",
            "unit": unit_of(kind),
            "qty": l.qty,
            "revenue": l.revenue,
            "profit": profit_of(l.m, measures),
            "manual": l.m.get("manual_disc_pct"),
            "auto": l.m.get("auto_disc_pct"),
            "manual_disc": implied_discount(l.revenue, l.m.get("manual_disc_pct")),
            "auto_disc": implied_discount(l.revenue, l.m.get("auto_disc_pct")),
        })
    order_by_no = {o.number: o for o in orders}

    revenue = sum(o.revenue for o in orders) if orders else sum(r["revenue"] for r in rows)
    A: dict = {
        "meta": {
            "title": rep.title,
            "currency": rep.currency,
            "period_from": rep.period_from,
            "period_to": rep.period_to,
            "params": rep.params,
            "managers": [manager_name(m[0]) for m in rep.managers],
            "manager_labels": [m[0] for m in rep.managers],
            "pages": rep.pages,
            "measures": measures,
            "warnings": list(rep.warnings),
            "has_items": bool(rows),
            "has_orders": bool(orders),
            "has_profit": has_profit,
            "has_manual": has_manual,
            "has_auto": has_auto,
            "report_total": rep.totals.get("revenue"),
        }
    }

    # ---- негізгі көрсеткіштер
    ords = sorted(orders, key=lambda o: o.revenue, reverse=True)
    tiles = [r for r in rows if r["kind"] == TILE]
    tile_rev = sum(r["revenue"] for r in tiles)
    tile_m2 = sum(r["qty"] for r in tiles)
    if rows:
        manual_disc = sum(r["manual_disc"] for r in rows)
        auto_disc = sum(r["auto_disc"] for r in rows)
    else:
        manual_disc = sum(implied_discount(o.revenue, o.m.get("manual_disc_pct")) for o in orders)
        auto_disc = sum(implied_discount(o.revenue, o.m.get("auto_disc_pct")) for o in orders)
    cum, n50, n80 = 0.0, 0, 0
    for i, o in enumerate(ords):
        cum += o.revenue
        if not n50 and cum >= revenue * 0.5:
            n50 = i + 1
        if not n80 and cum >= revenue * 0.8:
            n80 = i + 1
    k = {
        "revenue": revenue,
        "orders": len(orders),
        "lines": len(rows),
        "empty_orders": [o.number for o in rep.orders if o.empty],
        "avg": revenue / len(orders) if orders else 0,
        "median": median([o.revenue for o in orders]) if orders else 0,
        "tile_m2": tile_m2,
        "tile_ppm": tile_rev / tile_m2 if tile_m2 else 0,
        "tile_share": _share(tile_rev, revenue),
        "manual_disc": manual_disc,
        "manual_disc_pct": _share(manual_disc, revenue + manual_disc),
        "auto_disc": auto_disc,
        "auto_disc_pct": _share(auto_disc, revenue + auto_disc),
        "report_manual_pct": rep.totals.get("manual_disc_pct"),
        "top_order": ords[0].number if ords else None,
        "top_order_rev": ords[0].revenue if ords else 0,
        "top_order_share": _share(ords[0].revenue, revenue) if ords else 0,
        "top_order_main": None,
        "n50": n50,
        "n80": n80,
        "top10_share": _share(sum(o.revenue for o in ords[:10]), revenue),
        "top20_share": _share(sum(o.revenue for o in ords[:20]), revenue),
        "before_period_share": None,
    }
    if ords and ords[0].lines:
        best = max(ords[0].lines, key=lambda l: l.revenue)
        k["top_order_main"] = best.item
    if rep.period_from and orders:
        before = sum(o.revenue for o in orders if o.date and o.date < rep.period_from)
        k["before_period_share"] = _share(before, revenue)
    if has_profit:
        if rows:
            tp = sum(r["profit"] or 0 for r in rows)
        else:
            tp = sum(profit_of(o.m, measures) or 0 for o in orders)
        k["profit"] = tp
        k["margin"] = _margin(tp, revenue)
    A["kpi"] = k

    # ---- топтау көмекшісі
    def group(key, items):
        g = defaultdict(lambda: {"revenue": 0.0, "qty": 0.0, "orders": set(), "profit": 0.0,
                                 "manual_disc": 0.0, "lines": 0})
        for r in items:
            x = g[key(r)]
            x["revenue"] += r["revenue"]
            x["qty"] += r["qty"]
            x["orders"].add(r["order"])
            x["profit"] += r["profit"] or 0
            x["manual_disc"] += r["manual_disc"]
            x["lines"] += 1
        out = []
        for name, x in g.items():
            out.append({
                "name": name,
                "revenue": x["revenue"],
                "qty": x["qty"],
                "orders": len(x["orders"]),
                "lines": x["lines"],
                "share": _share(x["revenue"], revenue),
                "profit": x["profit"] if has_profit else None,
                "margin": _margin(x["profit"], x["revenue"]) if has_profit else None,
                "manual_disc": x["manual_disc"],
                "manual_disc_pct": _share(x["manual_disc"], x["revenue"] + x["manual_disc"]),
            })
        return sorted(out, key=lambda d: d["revenue"], reverse=True)

    if rows:
        A["by_kind"] = group(lambda r: r["kind"], rows)
        fm = group(lambda r: r["fmt"], tiles)
        for f in fm:
            f["share_tiles"] = _share(f["revenue"], tile_rev)
            f["ppm"] = f["revenue"] / f["qty"] if f["qty"] else 0
        A["by_fmt"] = fm

        goods = [r for r in rows if r["kind"] not in (DELIVERY, SERVICES)]
        items = group(lambda r: r["item"], goods)
        meta_by_item = {}
        for r in goods:
            meta_by_item.setdefault(r["item"], (r["seg"], r["kind"], r["unit"]))
        for it in items:
            it["seg"], it["kind"], it["unit"] = meta_by_item[it["name"]]
        A["top_items"] = items[:15]
        A["frequent_items"] = sorted(items, key=lambda d: (d["orders"], d["revenue"]), reverse=True)[:5]
        A["items_count"] = len(items)

        segs = group(lambda r: r["seg"], rows)
        for s in segs:
            srows = [r for r in rows if r["seg"] == s["name"]]
            st = [r for r in srows if r["kind"] == TILE]
            m2 = sum(r["qty"] for r in st)
            s["ppm"] = sum(r["revenue"] for r in st) / m2 if m2 else None
            mains = defaultdict(float)
            for r in srows:
                mains[f"Плитка {r['fmt']}" if r["kind"] == TILE else r["kind"]] += r["revenue"]
            s["main"] = ", ".join(n for n, _ in sorted(mains.items(), key=lambda kv: kv[1], reverse=True)[:2])
        A["by_seg"] = segs

        # серия × тауар тобы
        series = sorted({o.series for o in orders})
        sk = defaultdict(lambda: defaultdict(float))
        for r in rows:
            o = order_by_no.get(r["order"])
            sk[r["kind"]][o.series if o else "—"] += r["revenue"]
        A["series_list"] = series
        A["series_kind"] = sorted(
            [{"name": kd, **{s: v.get(s, 0.0) for s in series}} for kd, v in sk.items()],
            key=lambda d: sum(d[s] for s in series), reverse=True,
        )

        dk = [d for d in A["by_kind"] if abs(d["manual_disc"]) >= 1]
        A["disc_by_kind"] = sorted(dk, key=lambda d: d["manual_disc"], reverse=True)
        deep = [r for r in rows if r["manual"] is not None]
        A["deep_disc"] = sorted(deep, key=lambda r: r["manual_disc"], reverse=True)[:15]
    else:
        A["by_kind"] = A["by_fmt"] = A["top_items"] = A["frequent_items"] = A["by_seg"] = []
        A["series_list"], A["series_kind"], A["disc_by_kind"], A["deep_disc"] = [], [], [], []
        A["items_count"] = 0

    # ---- сериялар (LI22, XL22 ...)
    ser = defaultdict(lambda: {"orders": 0, "revenue": 0.0, "manual_disc": 0.0, "profit": 0.0})
    for o in orders:
        x = ser[o.series]
        x["orders"] += 1
        x["revenue"] += o.revenue
        if o.lines:
            x["manual_disc"] += sum(implied_discount(l.revenue, l.m.get("manual_disc_pct")) for l in o.lines)
            x["profit"] += sum(profit_of(l.m, measures) or 0 for l in o.lines)
        else:
            x["manual_disc"] += implied_discount(o.revenue, o.m.get("manual_disc_pct"))
            x["profit"] += profit_of(o.m, measures) or 0
    A["by_series"] = sorted(
        [{"name": s, "orders": x["orders"], "revenue": x["revenue"], "share": _share(x["revenue"], revenue),
          "avg": x["revenue"] / x["orders"] if x["orders"] else 0, "manual_disc": x["manual_disc"],
          "profit": x["profit"] if has_profit else None,
          "margin": _margin(x["profit"], x["revenue"]) if has_profit else None}
         for s, x in ser.items()],
        key=lambda d: d["revenue"], reverse=True,
    )

    # ---- менеджерлер (бірнешеу болса)
    mg = defaultdict(lambda: {"orders": 0, "revenue": 0.0})
    for o in orders:
        mg[o.manager]["orders"] += 1
        mg[o.manager]["revenue"] += o.revenue
    A["by_manager"] = sorted(
        [{"name": manager_name(n) if n else "—", "label": n, "orders": x["orders"], "revenue": x["revenue"],
          "share": _share(x["revenue"], revenue)} for n, x in mg.items()],
        key=lambda d: d["revenue"], reverse=True,
    )

    # ---- ең ірі заказдар
    top = []
    for i, o in enumerate(ords[:10]):
        main = max(o.lines, key=lambda l: l.revenue).item if o.lines else ""
        p = (sum(profit_of(l.m, measures) or 0 for l in o.lines) if o.lines else profit_of(o.m, measures)) if has_profit else None
        top.append({"pos": i + 1, "number": o.number, "date": o.date, "main": main, "revenue": o.revenue,
                    "share": _share(o.revenue, revenue), "profit": p})
    A["top_orders"] = top

    sizes = []
    for label, lo, hi in SIZE_BUCKETS:
        os_ = [o for o in orders if (o.revenue < 0 if lo is None else (o.revenue >= lo and (hi is None or o.revenue < hi)))]
        if os_:
            s = sum(o.revenue for o in os_)
            sizes.append({"name": label, "n": len(os_), "revenue": s, "share": _share(s, revenue)})
    A["sizes"] = sizes

    # ---- пайда (себестоимость бағаны болса)
    if has_profit:
        P: dict = {}
        if rows:
            P["by_kind"] = sorted(A["by_kind"], key=lambda d: d["profit"] or 0, reverse=True)
            P["by_seg"] = sorted(A["by_seg"], key=lambda d: d["profit"] or 0, reverse=True)
            P["by_fmt"] = sorted(A["by_fmt"], key=lambda d: d["profit"] or 0, reverse=True)
            goods = [r for r in rows if r["kind"] not in (DELIVERY, SERVICES)]
            pit = group(lambda r: r["item"], goods)
            P["top_items"] = sorted(pit, key=lambda d: d["profit"] or 0, reverse=True)[:10]
            P["best_margin_items"] = sorted(
                [d for d in pit if d["revenue"] >= 50_000 and d["margin"] is not None],
                key=lambda d: d["margin"], reverse=True)[:5]
            loss = [r for r in rows if (r["profit"] or 0) < -0.5]
            P["loss_count"] = len(loss)
            P["loss_sum"] = sum(r["profit"] for r in loss)
            P["loss_lines"] = sorted(loss, key=lambda r: r["profit"])[:10]
        op = []
        for o in orders:
            p = sum(profit_of(l.m, measures) or 0 for l in o.lines) if o.lines else (profit_of(o.m, measures) or 0)
            op.append({"number": o.number, "date": o.date, "revenue": o.revenue, "profit": p,
                       "margin": _margin(p, o.revenue)})
        P["top_orders"] = sorted(op, key=lambda d: d["profit"], reverse=True)[:10]
        P["loss_orders"] = sorted([d for d in op if d["profit"] < -0.5], key=lambda d: d["profit"])[:10]
        P["loss_orders_count"] = sum(1 for d in op if d["profit"] < -0.5)
        A["profit"] = P
    else:
        A["profit"] = None

    # ---- уақыт
    wd = defaultdict(lambda: {"n": 0, "revenue": 0.0})
    hr = defaultdict(lambda: {"n": 0, "revenue": 0.0})
    for o in orders:
        if o.date:
            wd[o.date.weekday()]["n"] += 1
            wd[o.date.weekday()]["revenue"] += o.revenue
        if o.time and o.time != "0:00:00":
            h = int(o.time.split(":")[0])
            hr[h]["n"] += 1
            hr[h]["revenue"] += o.revenue
    A["weekdays"] = [{"day": d, "name": WEEKDAYS[d], "short": WEEKDAYS_SHORT[d], **wd[d]} for d in sorted(wd)]
    A["hours"] = [{"hour": h, **hr[h]} for h in sorted(hr)]

    # ---- назар аударатын жайттар
    F: dict = {}
    F["returns"] = [(o.number, o.revenue) for o in orders if o.revenue < 0]
    F["empty_orders"] = k["empty_orders"]
    F["no_time"] = [o.number for o in orders if o.time == "0:00:00"]
    if rows:
        F["services"] = [(r["order"], r["item"], r["revenue"]) for r in rows if r["kind"] == SERVICES]
        cl = [r for r in tiles if r["qty"] > 0 and r["revenue"] / r["qty"] <= CLEARANCE_PRICE]
        F["clearance"] = {"n": len(cl), "m2": sum(r["qty"] for r in cl), "revenue": sum(r["revenue"] for r in cl)}
        kinds_by_order = defaultdict(set)
        for r in rows:
            kinds_by_order[r["order"]].add(r["kind"])
        t_orders = sum(1 for s in kinds_by_order.values() if TILE in s)
        s_orders = sum(1 for s in kinds_by_order.values() if s & SANITARY)
        both = sum(1 for s in kinds_by_order.values() if TILE in s and s & SANITARY)
        F["mix"] = {"tile_orders": t_orders, "san_orders": s_orders, "both": both}
        deliv = [r for r in rows if r["kind"] == DELIVERY]
        d_orders = {r["order"] for r in deliv}
        big = [o for o in orders if o.revenue > BIG_ORDER]
        F["delivery"] = {"n": len(deliv), "revenue": sum(r["revenue"] for r in deliv),
                         "big": len(big), "big_with": sum(1 for o in big if o.number in d_orders)}
        F["unknown_kind"] = sorted({r["item"] for r in rows if r["kind"] == "Басқа тауарлар"})[:10]
    A["flags"] = F
    A["constants"] = {"clearance_price": CLEARANCE_PRICE, "big_order": BIG_ORDER}
    A["_order_dates"] = [o.date for o in orders if o.date]
    return A
