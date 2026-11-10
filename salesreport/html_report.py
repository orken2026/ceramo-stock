"""Толық есеп — бір файлдық HTML (телефонда да, компьютерде де ашылады)."""
from __future__ import annotations

from datetime import datetime
from html import escape

from datetime import date

from .compare import _arrow, _pp
from .fmt import dstr, money, num, pct, qty

CSS = """
:root{--bg:#f7f6f3;--panel:#fff;--fg:#1f1e1c;--muted:#6b6862;--line:#e4e1da;--accent:#c96442;--track:#efece6;--warn:#b7791f;--bad:#c0392b;--ok:#2f855a}
@media (prefers-color-scheme:dark){:root{--bg:#1c1b19;--panel:#262522;--fg:#ecebe8;--muted:#a5a29b;--line:#3a3833;--accent:#e08a67;--track:#33312d;--warn:#e0a84a;--bad:#e46b5d;--ok:#5fbf8a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:20px 16px 48px}
h1{font:400 28px/1.2 Georgia,"Times New Roman",serif;margin:0}
h2{font-size:19px;margin:36px 0 10px}
h3{font-size:15px;margin:22px 0 8px}
.sub{color:var(--muted);font-size:13px;margin-top:4px}
.lead{font-size:17px;margin:14px 0 0;max-width:62em}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:20px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.k-l{font-size:12px;color:var(--muted)}
.k-v{font:400 24px/1.2 Georgia,serif;margin-top:4px;font-variant-numeric:tabular-nums}
.k-s{font-size:12px;color:var(--muted);margin-top:4px}
.tw{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th{text-align:left;color:var(--muted);font-weight:600;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
.n{text-align:right;white-space:nowrap}
.neg{color:var(--bad)}
.bars{display:flex;flex-direction:column;gap:7px}
.bar{display:grid;grid-template-columns:minmax(110px,30%) 1fr auto;gap:10px;align-items:center;font-size:13px}
.track{height:16px;background:var(--track);border-radius:4px;overflow:hidden}
.fill{height:100%;background:var(--accent);border-radius:4px;min-width:2px}
.val{white-space:nowrap;font-variant-numeric:tabular-nums}
.cols{display:flex;align-items:flex-end;gap:6px;height:170px;border-bottom:1px solid var(--line);padding-top:18px}
.col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%;min-width:0}
.col .c{width:100%;max-width:44px;background:var(--accent);border-radius:4px 4px 0 0;min-height:2px}
.col .t{font-size:11px;white-space:nowrap;margin-bottom:2px;font-variant-numeric:tabular-nums}
.xl{display:flex;gap:6px;margin-top:4px}.xl span{flex:1;text-align:center;font-size:11px;color:var(--muted);min-width:0;overflow:hidden}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.warn{border-left:3px solid var(--warn)}
ul,ol{padding-left:20px;margin:6px 0}li{margin:3px 0}
.muted{color:var(--muted);font-size:13px}
details{margin-top:28px}summary{cursor:pointer;color:var(--muted);font-size:13px}
"""


def e(s) -> str:
    return escape(str(s if s is not None else ""))


def _table(headers, rows, num_cols=()) -> str:
    th = "".join(f'<th class="n">{e(x)}</th>' if i in num_cols else f"<th>{e(x)}</th>" for i, x in enumerate(headers))
    body = []
    for r in rows:
        tds = []
        for i, c in enumerate(r):
            cls = []
            if i in num_cols:
                cls.append("n")
            if isinstance(c, str) and c.startswith("−"):
                cls.append("neg")
            attr = f' class="{" ".join(cls)}"' if cls else ""
            tds.append(f"<td{attr}>{e(c)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _hbars(items) -> str:
    """items: [(label, value, text)]"""
    mx = max((abs(v) for _, v, _ in items), default=0) or 1
    out = []
    for label, v, text in items:
        w = max(0.4, abs(v) / mx * 100)
        out.append(f'<div class="bar"><div>{e(label)}</div><div class="track"><div class="fill" style="width:{w:.1f}%"></div></div><div class="val">{e(text)}</div></div>')
    return f'<div class="card"><div class="bars">{"".join(out)}</div></div>'


def _vbars(items) -> str:
    """items: [(xlabel, value, toptext)]"""
    mx = max((v for _, v, _ in items), default=0) or 1
    cols = "".join(
        f'<div class="col"><div class="t">{e(t)}</div><div class="c" style="height:{max(1, v / mx * 85):.1f}%"></div></div>'
        for _, v, t in items
    )
    xl = "".join(f"<span>{e(x)}</span>" for x, _, _ in items)
    return f'<div class="cols">{cols}</div><div class="xl">{xl}</div>'


def _compare_section(snap: dict, prev: dict) -> str:
    d = lambda x: dstr(date.fromisoformat(x)) if x else "—"
    rows = [["Сатылым, ₸", money(snap["revenue"]), money(prev["revenue"]), _arrow(snap["revenue"], prev["revenue"])],
            ["Заказдар", snap["orders"], prev["orders"], _arrow(snap["orders"], prev["orders"])],
            ["Орташа чек, ₸", money(snap["avg"]), money(prev["avg"]), _arrow(snap["avg"], prev["avg"])]]
    if snap.get("tile_m2") and prev.get("tile_m2"):
        rows.append(["Плитка, м²", money(snap["tile_m2"]), money(prev["tile_m2"]), _arrow(snap["tile_m2"], prev["tile_m2"])])
    if snap.get("manual_disc_pct") is not None and prev.get("manual_disc_pct") is not None:
        rows.append(["Қолмен жеңілдік, %", num(snap["manual_disc_pct"], 2), num(prev["manual_disc_pct"], 2), _pp(snap["manual_disc_pct"], prev["manual_disc_pct"])])
    if snap.get("profit") is not None and prev.get("profit") is not None:
        rows.append(["Валовая прибыль, ₸", money(snap["profit"]), money(prev["profit"]), _arrow(snap["profit"], prev["profit"])])
        rows.append(["Маржа, %", num(snap["margin"]), num(prev["margin"]), _pp(snap["margin"], prev["margin"])])
    head = f"<h2>Алдыңғы есеппен салыстыру</h2><p class=\"muted\">Алдыңғы кезең: {d(prev.get('period_from'))} – {d(prev.get('period_to'))}</p>"
    return head + _table(["Көрсеткіш", "Қазір", "Бұрын", "Өзгеріс"], rows, num_cols=(1, 2, 3))


def build_html(A: dict, compare=None) -> str:
    """compare = (қазіргі снимок, алдыңғы снимок) немесе None."""
    m, k, F, C = A["meta"], A["kpi"], A["flags"], A["constants"]
    cur = "₸" if m["currency"] == "KZT" else m["currency"]
    period = f"{dstr(m['period_from'])} – {dstr(m['period_to'])}" if m["period_from"] else ""
    who = ", ".join(m["managers"])
    sub = " · ".join(e(x) for x in [f"Менеджер: {who}" if who else "", f"Кезең: {period}" if period else "", m["title"]] if x)
    P = A["profit"]

    lead = f"Сатылым — <b>{money(k['revenue'])} {cur}</b>, {k['orders']} заказ."
    if k["tile_m2"]:
        lead += f" Оның {pct(k['tile_share'])} — плитка мен керамогранит."
    if k["top_order"]:
        lead += f" Ең ірі заказ <b>{e(k['top_order'])}</b> сатылымның {pct(k['top_order_share'])}-ын берді, ал сатылымның жартысы {k['n50']} заказдан келді."

    cards = [("Сатылым (выручка), " + cur, money(k["revenue"]),
              f"«Итого» {num(m['report_total'], 2)} {'✓' if not m['warnings'] else '⚠'}" if m["report_total"] is not None else ""),
             ("Заказдар", str(k["orders"]), f"{k['lines']} тауар жолы" if k["lines"] else ""),
             ]
    if k["tile_m2"]:
        cards.append(("Плитка мен керамогранит, м²", money(k["tile_m2"]), f"орташа {money(k['tile_ppm'])} {cur}/м²"))
    cards.append(("Орташа чек, " + cur, money(k["avg"]), f"медиана {money(k['median'])} {cur}"))
    if m["has_profit"]:
        cards.append(("Валовая прибыль, " + cur, money(k["profit"]), f"маржа {pct(k['margin'])}"))
    if m["has_manual"]:
        cards.append(("Қолмен жеңілдік, " + cur, money(k["manual_disc"]), f"прайстан {pct(k['manual_disc_pct'], 2)}"))
    cards_html = "".join(f'<div class="card"><div class="k-l">{e(a)}</div><div class="k-v">{e(b)}</div><div class="k-s">{e(c)}</div></div>' for a, b, c in cards)

    S = []
    if compare:
        S.append(_compare_section(*compare))
    warn = "".join(f'<div class="card warn" style="margin-top:12px">⚠️ {e(w)}</div>' for w in m["warnings"])

    # Не сатылды
    if A["by_kind"]:
        S.append("<h2>Не сатылды</h2>")
        S.append("<h3>Тауар топтары бойынша сатылым</h3>")
        S.append(_hbars([(d["name"], d["revenue"], f"{money(d['revenue'])} · {pct(d['share'])}") for d in A["by_kind"]]))
        if A["by_fmt"]:
            S.append("<h3>Плитка форматтары</h3>")
            S.append(_table(["Формат, см", f"Сатылым, {cur}", "Плиткадағы үлесі, %", "Көлемі, м²", f"Орташа баға, {cur}/м²", "Заказ"],
                            [[f["name"], money(f["revenue"]), num(f["share_tiles"]), num(f["qty"]), money(f["ppm"]), f["orders"]] for f in A["by_fmt"]],
                            num_cols=(1, 2, 3, 4, 5)))
        S.append("<h3>Ең көп сатылған 15 позиция</h3>")
        S.append(_table(["#", "Тауар", "Санат", "Заказ", "Саны", "Өлшем", f"Сатылым, {cur}"],
                        [[i, it["name"], it["seg"], it["orders"], qty(it["qty"]), it["unit"], money(it["revenue"])] for i, it in enumerate(A["top_items"], 1)],
                        num_cols=(3, 4, 6)))
        if A["frequent_items"]:
            S.append("<h3>Ең жиі алынатындар</h3>")
            S.append(_table(["Тауар", "Заказ саны", f"Сатылым, {cur}"],
                            [[it["name"], it["orders"], money(it["revenue"])] for it in A["frequent_items"]], num_cols=(1, 2)))

    # Қай жерде
    S.append("<h2>Қай жерде сатылды</h2>")
    S.append('<p class="muted">Заказ сериясы — нөмірдің басы (LI22, XL22 …). Әр серия қай дүкенге не қоймаға тиесілі екенін 1С-тан нақтылаңыз.</p>')
    S.append(_table(["Серия", "Заказ", f"Сатылым, {cur}", "Үлесі, %", f"Орташа чек, {cur}", f"Қолмен жеңілдік, {cur}"] + (["Пайда", "Маржа, %"] if m["has_profit"] else []),
                    [[d["name"], d["orders"], money(d["revenue"]), num(d["share"]), money(d["avg"]), money(d["manual_disc"])] + ([money(d["profit"]), num(d["margin"])] if m["has_profit"] else []) for d in A["by_series"]],
                    num_cols=(1, 2, 3, 4, 5, 6, 7)))
    if A["series_kind"]:
        ser = A["series_list"]
        S.append(f"<h3>Серия және тауар тобы, {cur}</h3>")
        S.append(_table(["Тауар тобы"] + ser, [[r["name"]] + [money(r[s]) for s in ser] for r in A["series_kind"]], num_cols=tuple(range(1, len(ser) + 1))))
    if A["by_seg"]:
        S.append("<h3>Бонус санаттары бойынша</h3>")
        S.append('<p class="muted">1С «Сегмент» бағаны: «N-ая категория для бонусы розница» → N-санат.</p>')
        S.append(_table(["Санат", f"Сатылым, {cur}", "Үлесі, %", "Заказ", f"Плитка бағасы, {cur}/м²", "Негізгі тауар"] + (["Пайда", "Маржа, %"] if m["has_profit"] else []),
                        [[s["name"], money(s["revenue"]), num(s["share"]), s["orders"], money(s["ppm"]) if s.get("ppm") else "", s["main"]] + ([money(s["profit"]), num(s["margin"])] if m["has_profit"] else []) for s in A["by_seg"]],
                        num_cols=(1, 2, 3, 4, 6, 7)))
    if len(A["by_manager"]) > 1:
        S.append("<h3>Менеджерлер</h3>")
        S.append(_table(["Менеджер", "Заказ", f"Сатылым, {cur}", "Үлесі, %"],
                        [[d["name"], d["orders"], money(d["revenue"]), num(d["share"])] for d in A["by_manager"]], num_cols=(1, 2, 3)))

    # Заказдар
    if A["top_orders"]:
        S.append("<h2>Ең көп ақша әкелген заказдар</h2>")
        S.append(f'<p>Ең ірі 10 заказ сатылымның {pct(k["top10_share"])}-ын, 20 заказ {pct(k["top20_share"])}-ын береді. Сатылымның 80%-ы {k["n80"]} заказдан келді.</p>')
        S.append(_table(["№", "Заказ", "Ашылған күні", "Негізгі тауар", f"Сатылым, {cur}", "Үлесі, %"] + (["Пайда"] if m["has_profit"] else []),
                        [[o["pos"], o["number"], dstr(o["date"]), o["main"], money(o["revenue"]), num(o["share"])] + ([money(o["profit"])] if m["has_profit"] else []) for o in A["top_orders"]],
                        num_cols=(4, 5, 6)))
        S.append("<h3>Заказ көлемі бойынша</h3>")
        S.append(_table(["Заказ сомасы", "Заказ саны", f"Сатылым, {cur}", "Үлесі, %"],
                        [[s["name"], s["n"], money(s["revenue"]), num(s["share"])] for s in A["sizes"]], num_cols=(1, 2, 3)))

    # Пайда
    S.append("<h2>Пайда</h2>")
    if P is not None:
        S.append(f'<p>Валовая прибыль — <b>{money(k["profit"])} {cur}</b>, маржа {pct(k["margin"])}.</p>')
        if P.get("by_kind"):
            S.append("<h3>Тауар топтары бойынша пайда</h3>")
            S.append(_hbars([(d["name"], d["profit"] or 0, f"{money(d['profit'])} · {pct(d['margin'])}") for d in P["by_kind"]]))
        if P.get("by_seg"):
            S.append("<h3>Бонус санаттары бойынша пайда</h3>")
            S.append(_table(["Санат", f"Сатылым, {cur}", f"Пайда, {cur}", "Маржа, %"],
                            [[d["name"], money(d["revenue"]), money(d["profit"]), num(d["margin"])] for d in P["by_seg"]], num_cols=(1, 2, 3)))
        if P.get("by_fmt"):
            S.append("<h3>Плитка форматтары бойынша пайда</h3>")
            S.append(_table(["Формат", f"Сатылым, {cur}", f"Пайда, {cur}", "Маржа, %"],
                            [[d["name"], money(d["revenue"]), money(d["profit"]), num(d["margin"])] for d in P["by_fmt"]], num_cols=(1, 2, 3)))
        if P.get("top_items"):
            S.append("<h3>Ең көп пайда әкелген 10 позиция</h3>")
            S.append(_table(["#", "Тауар", f"Сатылым, {cur}", f"Пайда, {cur}", "Маржа, %"],
                            [[i, d["name"], money(d["revenue"]), money(d["profit"]), num(d["margin"])] for i, d in enumerate(P["top_items"], 1)], num_cols=(2, 3, 4)))
        if P["top_orders"]:
            S.append("<h3>Ең пайдалы 10 заказ</h3>")
            S.append(_table(["Заказ", "Күні", f"Сатылым, {cur}", f"Пайда, {cur}", "Маржа, %"],
                        [[d["number"], dstr(d["date"]), money(d["revenue"]), money(d["profit"]), num(d["margin"])] for d in P["top_orders"]], num_cols=(2, 3, 4)))
        if P.get("loss_lines"):
            S.append(f"<h3>Шығынмен сатылған жолдар: {P['loss_count']} (барлығы {money(P['loss_sum'])} {cur})</h3>")
            S.append(_table(["Заказ", "Тауар", f"Сатылым, {cur}", f"Пайда, {cur}"],
                            [[r["order"] or "—", r["item"], money(r["revenue"]), money(r["profit"])] for r in P["loss_lines"]], num_cols=(2, 3)))
        elif P.get("loss_orders"):
            S.append(f"<h3>Шығынды заказдар: {P['loss_orders_count']}</h3>")
            S.append(_table(["Заказ", f"Сатылым, {cur}", f"Пайда, {cur}"],
                            [[d["number"], money(d["revenue"]), money(d["profit"])] for d in P["loss_orders"]], num_cols=(1, 2)))
    else:
        S.append('<div class="card warn"><b>Бұл есепте себестоимость пен валовая прибыль бағандары жоқ</b>, сондықтан нақты пайданы есептеу мүмкін емес. '
                 "«Процент АС» және «Процент РС» — пайда емес, автоматты және қолмен берілген жеңілдік пайызы."
                 + (f" Есептегі пайыздардан шығарылған жалпы қолмен жеңілдік — {pct(k['manual_disc_pct'], 2)}"
                    + (f", есептің «Итого» жолында — {pct(k['report_manual_pct'], 2)}." if k.get("report_manual_pct") is not None else ".")
                    if m["has_manual"] else "") + "</div>")
        if A["disc_by_kind"]:
            S.append("<h3>Жеңілдік қай тауар тобына кетті</h3>")
            S.append(_table(["Тауар тобы", f"Сатылым, {cur}", f"Жеңілдік, {cur}", "Прайстан, %"],
                            [[d["name"], money(d["revenue"]), money(d["manual_disc"]), num(d["manual_disc_pct"])] for d in A["disc_by_kind"]], num_cols=(1, 2, 3)))
        if A["deep_disc"]:
            S.append("<h3>Ең үлкен 15 жеңілдік</h3>")
            S.append(_table(["Заказ", "Тауар", "Саны", f"Сатылған баға, {cur}", "Жеңілдік, %", f"Жеңілдік, {cur}"],
                            [[r["order"] or "—", r["item"], qty(r["qty"]), money(r["revenue"] / r["qty"] if r["qty"] else 0), num(r["manual"], 2), money(r["manual_disc"])] for r in A["deep_disc"]],
                            num_cols=(2, 3, 4, 5)))
        S.append("<h3>Нақты пайданы қалай көруге болады</h3><ol>"
                 "<li>1С-та «Валовая прибыль по клиентам» есебін ашып, «Настройки» ішіндегі «Показатели» (немесе «Поля») бөлімінен <b>Себестоимость</b> және <b>Валовая прибыль</b> бағандарын белгілеңіз.</li>"
                 "<li>Топтауды «Заказ клиента → Сегмент → Номенклатура» күйінде қалдырып, PDF-ке сақтаңыз.</li>"
                 "<li>PDF-ті ботқа жіберіңіз — пайда тауар, санат және заказ бойынша есептеледі.</li></ol>")

    # Уақыт
    if A["weekdays"]:
        S.append("<h2>Заказдар қашан ашылды</h2>")
        if k["before_period_share"]:
            S.append(f'<p>Кезең басталғанға дейін ашылып, кезеңде сатылған заказдар сатылымның {pct(k["before_period_share"])}-ын берді.</p>')
        wd = _vbars([(d["short"], d["revenue"], num(d["revenue"] / 1e6)) for d in A["weekdays"]])
        hr = _vbars([(str(x["hour"]), x["n"], str(x["n"])) for x in A["hours"]]) if A["hours"] else '<p class="muted">Уақыт жоқ</p>'
        S.append(f'<div class="grid2"><div class="card"><h3 style="margin-top:0">Апта күндері бойынша сатылым, млн {cur}</h3>{wd}</div>'
                 f'<div class="card"><h3 style="margin-top:0">Сағат бойынша заказ саны</h3>{hr}<p class="muted">Уақыты 0:00:00 заказдар кірмеді.</p></div></div>')

    # Назар аударатын жайттар
    li = []
    for n, v in F.get("returns", []):
        li.append(f"Қайтару: <b>{e(n)}</b> — {money(v)} {cur}.")
    if F.get("empty_orders"):
        li.append(f"Сомасы жоқ заказдар: {e(', '.join(F['empty_orders']))}.")
    for o, it, v in F.get("services", []):
        li.append(f"Қызмет «{e(it)}»: {e(o)} — {money(v)} {cur}. Дұрыс жазылғанын тексеріңіз.")
    cl = F.get("clearance")
    if cl and cl["n"]:
        li.append(f"{money(C['clearance_price'])} {cur}/м²-ден арзан сатылған плитка: {cl['n']} жол, {num(cl['m2'])} м², {money(cl['revenue'])} {cur} — қалдық/уценка сияқты.")
    mx = F.get("mix")
    if mx and mx["tile_orders"] and mx["san_orders"]:
        li.append(f"Плитка мен сантехника бір заказда: {mx['both']} (плиткалы {mx['tile_orders']}, сантехникалы {mx['san_orders']} заказ).")
    dv = F.get("delivery")
    if dv and dv["big"]:
        li.append(f"{money(C['big_order'])} {cur}-ден асатын {dv['big']} заказдың {dv['big_with']}-інде жеткізу бар (барлығы {dv['n']} жеткізу, {money(dv['revenue'])} {cur}).")
    if F.get("no_time"):
        li.append(f"Уақыты 0:00:00 заказдар: {len(F['no_time'])} ({e(', '.join(F['no_time'][:6]))}).")
    if F.get("unknown_kind"):
        li.append(f"Тобы анықталмаған тауарлар: {e('; '.join(F['unknown_kind']))}.")
    if li:
        S.append("<h2>Назар аударатын жайттар</h2><ul>" + "".join(f"<li>{x}</li>" for x in li) + "</ul>")

    params = "".join(f"<li>{e(p)}</li>" for p in m["params"])
    method = (
        "<details><summary>Әдіс және дереккөз</summary><div class=\"muted\">"
        f"<p>Есеп: {e(m['title'])}, {m['pages']} бет. Бағандар: {e(', '.join(m['measures']))}.</p>"
        + (f"<ul>{params}</ul>" if params else "")
        + "<p>Тауар тобы мен плитка форматы тауар атауынан анықталды. Жеңілдік сомасы = сатылым × РС% ÷ (100 − РС%), яғни прайстан берілген қолмен жеңілдік. "
          "Пайда = «Валовая прибыль» бағаны, ол болмаса «Выручка − Себестоимость».</p>"
        f"<p>Есеп жасалған уақыт: {datetime.now().strftime('%d.%m.%Y %H:%M')}</p></div></details>"
    )

    return (
        "<!DOCTYPE html><html lang=\"kk\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>Сатылым талдауы {e(period)}</title><style>{CSS}</style></head><body><div class=\"wrap\">"
        f"<h1>Сатылым талдауы</h1><div class=\"sub\">{sub}</div><p class=\"lead\">{lead}</p>"
        f"<div class=\"kpis\">{cards_html}</div>{warn}"
        + "".join(S) + method + "</div></body></html>"
    )
