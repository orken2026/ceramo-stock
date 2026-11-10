"""Telegram-ға арналған мәтіндік есеп (HTML режимі)."""
from __future__ import annotations

from .classify import DELIVERY, SANITARY, SERVICES, TILE
from .fmt import dstr, h, mln, money, num, pct, qty

TG_LIMIT = 3900  # Telegram шегі 4096, сәл қор қалдырамыз


def split_message(text: str, limit: int = TG_LIMIT) -> list:
    """Ұзын мәтінді жол шекарасынан бөледі (HTML тегтері бір жолдың ішінде)."""
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:  # өте ұзын жол — сирек жағдай
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{cur}\n{line}" if cur else line
        if len(candidate) > limit:
            parts.append(cur)
            cur = line
        else:
            cur = candidate
    if cur.strip():
        parts.append(cur)
    return [p for p in parts if p.strip()]


def _bucket(kind: str) -> str:
    if kind == TILE:
        return "плитка"
    if kind in SANITARY:
        return "сантехника"
    if kind in (DELIVERY, SERVICES):
        return "жеткізу/қызмет"
    return "басқа"


def summary(A: dict) -> str:
    m, k = A["meta"], A["kpi"]
    cur = "₸" if m["currency"] == "KZT" else m["currency"]
    out = ["📊 <b>Сатылым талдауы</b>", f"<i>{h(m['title'])}</i>"]
    if m["period_from"]:
        out.append(f"Кезең: {dstr(m['period_from'])} – {dstr(m['period_to'])}")
    if len(m["managers"]) == 1:
        out.append(f"Менеджер: {h(m['managers'][0])}")
    elif m["managers"]:
        out.append(f"Менеджерлер: {len(m['managers'])}")
    out.append("")
    out.append(f"💰 Сатылым: <b>{money(k['revenue'])} {cur}</b>")
    if k["orders"]:
        line = f"🧾 Заказдар: <b>{k['orders']}</b>"
        if k["lines"]:
            line += f" · тауар жолы: {k['lines']}"
        out.append(line)
    elif k["lines"]:
        out.append(f"🧾 Тауар жолы: <b>{k['lines']}</b> (заказдар есепте жоқ)")
    if k["tile_m2"]:
        out.append(f"📦 Плитка/керамогранит: <b>{money(k['tile_m2'])} м²</b> · орташа {money(k['tile_ppm'])} {cur}/м² · сатылымның {pct(k['tile_share'])}")
    if k["orders"]:
        out.append(f"🧮 Орташа чек: {money(k['avg'])} {cur} · медиана: {money(k['median'])} {cur}")
    if m["has_manual"]:
        out.append(f"🏷 Қолмен жеңілдік: {money(k['manual_disc'])} {cur} (прайстан {pct(k['manual_disc_pct'], 2)})")
    if m["has_auto"] and abs(k["auto_disc"]) >= 100:
        out.append(f"🏷 Автоматты жеңілдік: {money(k['auto_disc'])} {cur} ({pct(k['auto_disc_pct'], 2)})")
    if m["has_profit"]:
        out.append(f"💵 Валовая прибыль: <b>{money(k['profit'])} {cur}</b> · маржа {pct(k['margin'])}")

    out.append("")
    out.append("<b>Негізгісі</b>")
    if k["top_order"]:
        main = f" ({h(k['top_order_main'])})" if k["top_order_main"] else ""
        out.append(f"• Ең ірі заказ <b>{h(k['top_order'])}</b> — {money(k['top_order_rev'])} {cur}, бүкіл сатылымның {pct(k['top_order_share'])}{main}.")
        out.append(f"• Сатылымның жартысы {k['n50']} заказдан, 80%-ы {k['n80']} заказдан келді.")
    if k["before_period_share"]:
        out.append(f"• Кезең басталғанға дейін ашылған заказдар сатылымның {pct(k['before_period_share'])}-ын берді.")
    if A["by_kind"] and A["by_kind"][0]["name"] != TILE:
        top_kind = A["by_kind"][0]
        out.append(f"• Ең көп сатылған топ — {h(top_kind['name'])}: {pct(top_kind['share'])}.")
    if A["by_fmt"]:
        f0 = A["by_fmt"][0]
        out.append(f"• Плиткада {h(f0['name'])} форматы бірінші: {money(f0['revenue'])} {cur} ({pct(f0['share_tiles'])}).")
    if A["by_series"] and len(A["by_series"]) > 1:
        s = " · ".join(f"{h(x['name'])} {pct(x['share'])}" for x in A["by_series"])
        out.append(f"• Сериялар: {s}.")

    out.append("")
    if m["warnings"]:
        for w in m["warnings"]:
            out.append(f"⚠️ {h(w)}")
    elif m["report_total"] is not None:
        out.append(f"✅ Сомалардың қосындысы «Итого»-мен сәйкес: {num(m['report_total'], 2)} {cur}")
    if not m["has_items"]:
        out.append("ℹ️ Бұл есепте тауарлар (номенклатура) жоқ — тек заказдар. Толық талдау үшін 1С-та топтауды "
                   "«Заказ клиента → Сегмент → Номенклатура» етіп шығарыңыз.")
    return "\n".join(out)


def what_sold(A: dict) -> str:
    if not A["by_kind"]:
        return ""
    cur = "₸"
    out = ["🛒 <b>Не сатылды</b>", "", "<b>Тауар топтары:</b>"]
    for d in A["by_kind"]:
        out.append(f"• {h(d['name'])} — {money(d['revenue'])} {cur} ({pct(d['share'])}), {d['orders']} заказ")
    if A["by_fmt"]:
        out += ["", "<b>Плитка форматтары:</b>"]
        for f in A["by_fmt"]:
            out.append(f"• {h(f['name'])} — {money(f['revenue'])} {cur} · {money(f['qty'])} м² · {money(f['ppm'])} {cur}/м² · {f['orders']} заказ")
    out += ["", "<b>Ең көп сатылған 10 позиция:</b>"]
    for i, it in enumerate(A["top_items"][:10], 1):
        out.append(f"{i}. {h(it['name'])} — <b>{money(it['revenue'])} {cur}</b> ({qty(it['qty'])} {it['unit']}, {it['orders']} заказ)")
    if A["frequent_items"]:
        out += ["", "<b>Ең жиі алынатындар:</b>"]
        for it in A["frequent_items"]:
            out.append(f"• {h(it['name'])} — {it['orders']} заказ, {money(it['revenue'])} {cur}")
    return "\n".join(out)


def where_sold(A: dict) -> str:
    cur = "₸"
    out = ["📍 <b>Қай жерде сатылды</b>"]
    if A["by_series"]:
        out += ["", "<b>Заказ сериялары</b> <i>(нөмірдің басы: LI22, XL22 …)</i>:"]
        buckets = {}
        for row in A.get("series_kind", []):
            for s in A.get("series_list", []):
                buckets.setdefault(s, {}).setdefault(_bucket(row["name"]), 0.0)
                buckets[s][_bucket(row["name"])] += row[s]
        for d in A["by_series"]:
            out.append(f"• <b>{h(d['name'])}</b> — {d['orders']} заказ, {money(d['revenue'])} {cur} ({pct(d['share'])}), орташа чек {money(d['avg'])} {cur}")
            b = buckets.get(d["name"])
            if b:
                parts = [f"{name} {money(v)}" for name, v in sorted(b.items(), key=lambda kv: kv[1], reverse=True) if abs(v) >= 1]
                if parts:
                    out.append(f"   ↳ {', '.join(parts)} {cur}")
    if A["by_seg"]:
        out += ["", "<b>Бонус санаттары</b> <i>(1С «Сегмент»)</i>:"]
        for s in A["by_seg"]:
            extra = f" · плитка {money(s['ppm'])} {cur}/м²" if s.get("ppm") else ""
            out.append(f"• {h(s['name'])} — {money(s['revenue'])} {cur} ({pct(s['share'])}), {s['orders']} заказ{extra}")
            if s.get("main"):
                out.append(f"   ↳ {h(s['main'])}")
    if len(A["by_manager"]) > 1:
        out += ["", "<b>Менеджерлер:</b>"]
        for d in A["by_manager"]:
            out.append(f"• {h(d['name'])} — {d['orders']} заказ, {money(d['revenue'])} {cur} ({pct(d['share'])})")
    return "\n".join(out)


def top_orders(A: dict) -> str:
    if not A["top_orders"]:
        return ""
    cur, k = "₸", A["kpi"]
    out = ["🏆 <b>Ең көп ақша әкелген заказдар</b>", ""]
    for o in A["top_orders"]:
        main = f" · {h(o['main'])}" if o["main"] else ""
        prof = f" · пайда {money(o['profit'])}" if o.get("profit") is not None else ""
        out.append(f"{o['pos']}. <b>{h(o['number'])}</b> ({dstr(o['date'])}) — {money(o['revenue'])} {cur} · {pct(o['share'])}{prof}{main}")
    out += ["", f"Ең ірі 10 заказ — {pct(k['top10_share'])}, 20 заказ — {pct(k['top20_share'])} сатылым.", "",
            "<b>Заказ көлемі бойынша:</b>"]
    for s in A["sizes"]:
        out.append(f"• {h(s['name'])} — {s['n']} заказ, {money(s['revenue'])} {cur} ({pct(s['share'])})")
    return "\n".join(out)


def profit_part(A: dict) -> str:
    cur, m, k, P = "₸", A["meta"], A["kpi"], A["profit"]
    if P is not None:
        out = ["💵 <b>Пайда (валовая прибыль)</b>", "",
               f"Барлығы: <b>{money(k['profit'])} {cur}</b> · маржа {pct(k['margin'])}"]
        if P.get("by_kind"):
            out += ["", "<b>Тауар топтары бойынша:</b>"]
            for d in P["by_kind"]:
                out.append(f"• {h(d['name'])} — {money(d['profit'])} {cur} (маржа {pct(d['margin'])})")
        if P.get("by_seg"):
            out += ["", "<b>Бонус санаттары бойынша:</b>"]
            for d in P["by_seg"]:
                out.append(f"• {h(d['name'])} — {money(d['profit'])} {cur} (маржа {pct(d['margin'])})")
        if P.get("by_fmt"):
            out += ["", "<b>Плитка форматтары бойынша:</b>"]
            for d in P["by_fmt"][:6]:
                out.append(f"• {h(d['name'])} — {money(d['profit'])} {cur} (маржа {pct(d['margin'])})")
        if P.get("top_items"):
            out += ["", "<b>Ең көп пайда әкелген 10 позиция:</b>"]
            for i, d in enumerate(P["top_items"], 1):
                out.append(f"{i}. {h(d['name'])} — <b>{money(d['profit'])} {cur}</b> (маржа {pct(d['margin'])}, сатылым {money(d['revenue'])})")
        if P.get("best_margin_items"):
            out += ["", "<b>Маржасы ең жоғары (сатылымы 50 мыңнан асқан):</b>"]
            for d in P["best_margin_items"]:
                out.append(f"• {h(d['name'])} — маржа {pct(d['margin'])}, пайда {money(d['profit'])} {cur}")
        if P["top_orders"]:
            out += ["", "<b>Ең пайдалы заказдар:</b>"]
        for d in P["top_orders"][:5]:
            out.append(f"• {h(d['number'])} ({dstr(d['date'])}) — {money(d['profit'])} {cur} (маржа {pct(d['margin'])})")
        if P.get("loss_count"):
            out += ["", f"⚠️ <b>Шығынмен сатылған жолдар: {P['loss_count']}</b>, барлығы {money(P['loss_sum'])} {cur}"]
            for r in P["loss_lines"][:7]:
                out.append(f"• {h(r['item'])} ({h(r['order'] or '—')}) — {money(r['profit'])} {cur}, сатылым {money(r['revenue'])}")
        elif P.get("loss_orders_count"):
            out += ["", f"⚠️ <b>Шығынды заказдар: {P['loss_orders_count']}</b>"]
            for d in P["loss_orders"][:7]:
                out.append(f"• {h(d['number'])} — {money(d['profit'])} {cur}")
        return "\n".join(out)

    out = ["💵 <b>Пайда туралы</b>", "",
           "Бұл есепте <b>себестоимость</b> пен <b>валовая прибыль</b> бағандары жоқ, сондықтан нақты пайданы есептеу мүмкін емес."]
    if m["has_manual"]:
        check = ""
        if k.get("report_manual_pct") is not None:
            ok = abs(k["report_manual_pct"] - round(k["manual_disc_pct"], 2)) < 0.02
            check = f" («Итого»-да {pct(k['report_manual_pct'], 2)} {'✓' if ok else '≠'})"
        out.append(f"«Процент АС» мен «Процент РС» — пайда емес, автоматты және қолмен берілген жеңілдік пайызы. "
                   f"Есептегі пайыздардан шығарғанда жалпы қолмен жеңілдік {pct(k['manual_disc_pct'], 2)}{check}.")
        if A["disc_by_kind"]:
            out += ["", "<b>Жеңілдік қайда кетті:</b>"]
            for d in A["disc_by_kind"]:
                out.append(f"• {h(d['name'])} — {money(d['manual_disc'])} {cur} (прайстан {pct(d['manual_disc_pct'])})")
        if A["deep_disc"]:
            out += ["", "<b>Ең үлкен жеңілдіктер:</b>"]
            for i, r in enumerate(A["deep_disc"][:10], 1):
                price = r["revenue"] / r["qty"] if r["qty"] else 0
                out.append(f"{i}. {h(r['item'])} ({h(r['order'] or '—')}) — {pct(r['manual'], 2)}, {money(r['manual_disc'])} {cur}; сатылған баға {money(price)} {cur}/{r['unit']}")
    out += ["", "👉 <b>Пайданы көру үшін:</b> 1С-та осы есептің «Настройки» ішіндегі «Показатели» (немесе «Поля») бөлімінен «Себестоимость» және "
            "«Валовая прибыль» бағандарын белгілеп, PDF-ті қайта жіберіңіз — бот пайданы өзі есептейді."]
    return "\n".join(out)


def time_and_flags(A: dict) -> str:
    cur, F, C = "₸", A["flags"], A["constants"]
    out = []
    if A["weekdays"]:
        out.append("🕒 <b>Заказдар қашан ашылды</b>")
        out.append(" · ".join(f"{d['short']} {mln(d['revenue'])} ({d['n']})" for d in A["weekdays"]))
        if A["hours"]:
            busiest = sorted(A["hours"], key=lambda x: x["n"], reverse=True)[:3]
            out.append("Ең көп заказ: " + ", ".join(f"{x['hour']}:00–{x['hour'] + 1}:00 ({x['n']})" for x in busiest))
        out.append("")
    items = []
    for n, v in F.get("returns", []):
        items.append(f"• Қайтару: {h(n)} — {money(v)} {cur}")
    if F.get("empty_orders"):
        items.append(f"• Сомасы жоқ заказдар: {h(', '.join(F['empty_orders']))}")
    for o, it, v in F.get("services", []):
        items.append(f"• Қызмет «{h(it)}»: {h(o)} — {money(v)} {cur}, дұрыс жазылғанын тексеріңіз")
    cl = F.get("clearance")
    if cl and cl["n"]:
        items.append(f"• {money(C['clearance_price'])} {cur}/м²-ден арзан сатылған плитка: {cl['n']} жол, {num(cl['m2'])} м², {money(cl['revenue'])} {cur}")
    mx = F.get("mix")
    if mx and mx["tile_orders"] and mx["san_orders"]:
        items.append(f"• Плитка мен сантехника бір заказда: {mx['both']} (плиткалы {mx['tile_orders']}, сантехникалы {mx['san_orders']} заказ)")
    dv = F.get("delivery")
    if dv and dv["big"]:
        items.append(f"• {money(C['big_order'])} {cur}-ден асатын {dv['big']} заказдың {dv['big_with']}-інде жеткізу бар (барлығы {dv['n']} жеткізу, {money(dv['revenue'])} {cur})")
    if F.get("no_time"):
        items.append(f"• Уақыты 0:00:00 заказдар: {len(F['no_time'])} ({h(', '.join(F['no_time'][:5]))})")
    if F.get("unknown_kind"):
        items.append(f"• Тобы анықталмаған тауарлар: {h('; '.join(F['unknown_kind'][:5]))}")
    if items:
        out.append("⚠️ <b>Назар аударатын жайттар</b>")
        out += items
    return "\n".join(out)


def build_messages(A: dict) -> list:
    sections = [summary(A), what_sold(A), where_sold(A), top_orders(A), profit_part(A), time_and_flags(A)]
    msgs = []
    for s in sections:
        if s and s.strip():
            msgs += split_message(s)
    return msgs
