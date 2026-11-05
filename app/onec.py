"""Read-only client for the 1C standard OData interface (OData 3.0).

Only GET requests are ever sent. Values typed by people reach 1C solely as
escaped OData string literals, and item ids are checked to be GUIDs first.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx

from .config import OneCSettings

log = logging.getLogger(__name__)

GUID_RE = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
WAREHOUSE_CACHE_SECONDS = 3600
MAX_PARALLEL_REQUESTS = 4
MAX_SEARCH_WORDS = 4
UNKNOWN_WAREHOUSE_RETRY_SECONDS = 60
PATH_SAFE_CHARS = "/(),='"


class OneCError(Exception):
    code = "onec_error"


class OneCUnavailable(OneCError):
    """Server is down, slow, or answered with something that is not OData."""

    code = "onec_unavailable"


class OneCRejected(OneCError):
    """1C refused the login, or the user lacks rights."""

    code = "onec_auth"


class OneCQueryError(OneCError):
    """1C rejected the query, usually a wrong field or register name."""

    code = "onec_query"


@dataclass(frozen=True)
class Item:
    id: str
    article: str
    name: str
    unit: str


@dataclass(frozen=True)
class SearchResult:
    items: list[Item]
    truncated: bool


@dataclass(frozen=True)
class WarehouseStock:
    id: str
    name: str | None
    quantity: float
    reserved: float


@dataclass(frozen=True)
class StockReport:
    warehouses: list[WarehouseStock]
    total_quantity: float
    total_reserved: float


def odata_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class OneCClient:
    def __init__(self, settings: OneCSettings, transport: httpx.AsyncBaseTransport | None = None):
        self._s = settings
        self._http = httpx.AsyncClient(
            auth=httpx.BasicAuth(settings.user, settings.password),
            timeout=settings.timeout,
            headers={"Accept": "application/json", "User-Agent": "ceramo-stock/1.0"},
            transport=transport,
        )
        self._gate = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)
        self._warehouses: dict[str, str] = {}
        self._warehouses_at = 0.0
        self._warehouses_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        # 1C expects "$filter" with a literal dollar sign, so the query string is built by hand.
        pairs = {"$format": "json", **(params or {})}
        query = "&".join(f"{key}={quote(str(value), safe='')}" for key, value in pairs.items())
        return f"{self._s.odata_url}/{quote(path, safe=PATH_SAFE_CHARS)}?{query}"

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        async with self._gate:
            try:
                response = await self._http.get(self._url(path, params))
            except httpx.HTTPError as exc:
                log.warning("1C request failed: %s", type(exc).__name__)
                raise OneCUnavailable from exc

        if response.status_code in (401, 403):
            log.error("1C refused access: HTTP %s", response.status_code)
            raise OneCRejected
        if response.status_code >= 400:
            log.error("1C error on %s: HTTP %s %s", path.split("(")[0], response.status_code, response.text[:400])
            raise OneCQueryError if self._is_odata_error(response) else OneCUnavailable
        return response

    async def get_text(self, path: str, params: dict[str, Any] | None = None) -> str:
        return (await self._get(path, params)).text

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        # Without allowedOnly, 1C answers "Доступ запрещен" for users under record-level restrictions.
        response = await self._get(path, {"allowedOnly": "true", **(params or {})})
        try:
            return response.json()
        except ValueError as exc:
            log.error("1C answered with non-JSON content")
            raise OneCUnavailable from exc

    @staticmethod
    def _is_odata_error(response: httpx.Response) -> bool:
        return "odata.error" in response.text or "m:error" in response.text

    async def search(self, text: str, limit: int = 20) -> SearchResult:
        """Exact article match first, then every word anywhere in article or name."""
        article = self._s.article_field
        exact = await self._find_items(f"{article} eq {odata_literal(text)}", limit)
        if exact.items:
            return exact

        clauses = []
        for word in text.split()[:MAX_SEARCH_WORDS]:
            literal = odata_literal(word)
            clauses.append(f"(substringof({literal}, {article}) or substringof({literal}, Description))")
        return await self._find_items(" and ".join(clauses), limit)

    async def _find_items(self, condition: str, limit: int) -> SearchResult:
        fields = ["Ref_Key", "Description", self._s.article_field]
        if self._s.unit_field:
            fields.append(self._s.unit_field)
        data = await self.get_json(
            f"Catalog_{self._s.item_catalog}",
            {
                "$select": ",".join(fields),
                "$filter": f"({condition}) and DeletionMark eq false and IsFolder eq false",
                "$top": limit + 1,
            },
        )
        rows = data.get("value", [])
        items = [
            Item(
                id=row["Ref_Key"],
                article=(row.get(self._s.article_field) or "").strip(),
                name=(row.get("Description") or "").strip(),
                unit=(row.get(self._s.unit_field) or "").strip() if self._s.unit_field else "",
            )
            for row in rows[:limit]
        ]
        items.sort(key=lambda item: (item.article.casefold(), item.name.casefold()))
        return SearchResult(items=items, truncated=len(rows) > limit)

    async def stock(self, item_id: str) -> StockReport:
        if not GUID_RE.match(item_id):
            raise ValueError("item id must be a GUID")

        condition = f"{self._s.item_dimension} eq guid'{item_id}'"
        data = await self.get_json(
            f"AccumulationRegister_{self._s.stock_register}/Balance(Condition='{condition}')"
        )
        rows = data.get("value", [])
        if rows and self._s.quantity_field not in rows[0]:
            log.error("Field %s is not in the register. Available: %s", self._s.quantity_field, sorted(rows[0]))
            raise OneCQueryError

        # One warehouse can hold several rows (series, characteristics), so they are summed.
        totals: dict[str, list[Decimal]] = {}
        for row in rows:
            key = row.get(self._s.warehouse_dimension) or ""
            quantity = Decimal(str(row.get(self._s.quantity_field) or 0))
            reserved = Decimal(str(row.get(self._s.reserve_field) or 0)) if self._s.reserve_field else Decimal(0)
            entry = totals.setdefault(key, [Decimal(0), Decimal(0)])
            entry[0] += quantity
            entry[1] += reserved

        totals = {key: value for key, value in totals.items() if value[0] or value[1]}
        names = await self._warehouse_names(set(totals))
        warehouses = [
            WarehouseStock(id=key, name=names.get(key), quantity=float(value[0]), reserved=float(value[1]))
            for key, value in totals.items()
        ]
        warehouses.sort(key=lambda row: (-row.quantity, row.name or ""))
        return StockReport(
            warehouses=warehouses,
            total_quantity=float(sum((value[0] for value in totals.values()), Decimal(0))),
            total_reserved=float(sum((value[1] for value in totals.values()), Decimal(0))),
        )

    async def _warehouse_names(self, needed: set[str]) -> dict[str, str]:
        async with self._warehouses_lock:
            age = time.monotonic() - self._warehouses_at
            unknown = (needed - {""}) - set(self._warehouses)
            if not self._warehouses or age > WAREHOUSE_CACHE_SECONDS or (
                unknown and age > UNKNOWN_WAREHOUSE_RETRY_SECONDS
            ):
                data = await self.get_json(
                    f"Catalog_{self._s.warehouse_catalog}", {"$select": "Ref_Key,Description"}
                )
                self._warehouses = {row["Ref_Key"]: row.get("Description", "") for row in data.get("value", [])}
                self._warehouses_at = time.monotonic()
            return self._warehouses
