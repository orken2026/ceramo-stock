#!/usr/bin/env python3
"""Checks that the 1C names in .env match your database. Reads data, changes nothing.

    python check_1c.py              checks the connection and field names
    python check_1c.py CS-6060      also searches for this article and shows its stock

The first form prints field names only. No prices, clients or stock figures.
"""
from __future__ import annotations

import asyncio
import re
import sys
import time

from app.config import ConfigError, load_onec_settings
from app.onec import OneCClient, OneCError, OneCQueryError, OneCRejected, OneCUnavailable

HINTS = {
    OneCRejected: "1С логин немесе құпиясөз қате, не пайдаланушыда құқық жоқ.",
    OneCUnavailable: "Сервер жауап бермеді. Мекенжайды және желіні тексеріңіз.",
    OneCQueryError: "1С сұранысты қабылдамады. Атау .env ішіндегіден өзгеше болуы мүмкін.",
}


def ok(text: str) -> None:
    print(f"  [ОК]   {text}")


def fail(text: str) -> None:
    print(f"  [ҚАТЕ] {text}")


async def step(title: str, action):
    print(f"\n{title}")
    started = time.perf_counter()
    try:
        result = await action
    except OneCError as exc:
        fail(HINTS.get(type(exc), str(exc)))
        return None
    ok(f"{time.perf_counter() - started:.1f} сек")
    return result


async def main() -> int:
    try:
        settings = load_onec_settings()
    except ConfigError as exc:
        print(f".env толық емес: {exc}")
        return 1

    client = OneCClient(settings)
    failed = False
    try:
        root = await step("1. Қосылу", client.get_text(""))
        if root is None:
            return 1

        names = sorted(set(re.findall(r'(?:Catalog|AccumulationRegister)_[^"<>\s/]+', root)))
        stock_like = [
            name
            for name in names
            if name.startswith("AccumulationRegister_")
            and not name.endswith("_RecordType")
            and ("Товар" in name or "Остат" in name)
        ]
        print("  Қалдыққа ұқсас регистрлер:")
        for name in stock_like:
            print(f"    {name}")

        for wanted in (
            f"Catalog_{settings.item_catalog}",
            f"Catalog_{settings.warehouse_catalog}",
            f"AccumulationRegister_{settings.stock_register}",
        ):
            if wanted in names:
                ok(f"бар: {wanted}")
            else:
                fail(f"жоқ: {wanted}")
                failed = True

        items = await step(
            "2. Номенклатура өрістері", client.get_json(f"Catalog_{settings.item_catalog}", {"$top": 1})
        )
        if items and items.get("value"):
            fields = sorted(items["value"][0])
            print("  Артикул мен бірлікке ұқсас өрістер:")
            for field in fields:
                if any(part in field for part in ("Артикул", "Единиц", "Упаков", "Штрихкод")):
                    print(f"    {field}")
            if settings.article_field in fields:
                ok(f"бар: {settings.article_field}")
            else:
                fail(f"жоқ: {settings.article_field}")
                failed = True
        else:
            failed = True

        balance = await step(
            "3. Қалдық регистрінің өрістері",
            client.get_json(f"AccumulationRegister_{settings.stock_register}/Balance()", {"$top": 1}),
        )
        if balance and balance.get("value"):
            fields = sorted(balance["value"][0])
            print("  Барлық өрістер:")
            for field in fields:
                print(f"    {field}")
            for wanted in (settings.item_dimension, settings.warehouse_dimension, settings.quantity_field):
                if wanted in fields:
                    ok(f"бар: {wanted}")
                else:
                    fail(f"жоқ: {wanted}")
                    failed = True
            if settings.reserve_field and settings.reserve_field not in fields:
                print(f"  [ЕСКЕРТУ] {settings.reserve_field} жоқ, резерв көрсетілмейді.")
        else:
            failed = True

        if len(sys.argv) > 1:
            text = " ".join(sys.argv[1:])
            found = await step(f"4. Іздеу: {text}", client.search(text))
            if found and found.items:
                for item in found.items[:5]:
                    print(f"    {item.article} | {item.name} | {item.unit}")
                report = await step("5. Қалдық", client.stock(found.items[0].id))
                if report:
                    print(f"    Барлығы: {report.total_quantity}, резервте: {report.total_reserved}")
                    for row in report.warehouses:
                        print(f"    {row.name or 'Қойма көрсетілмеген'}: {row.quantity}")
                else:
                    failed = True
            else:
                print("  Тауар табылмады." if found else "")
                failed = True
    finally:
        await client.aclose()

    print("\nБәрі дұрыс." if not failed else "\nЖоғарыдағы шығысты көшіріп жіберіңіз. Құпиясөз онда жоқ.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
