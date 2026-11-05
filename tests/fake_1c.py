"""A small stand-in for the 1C OData interface, used only by tests.

It parses $filter strictly, so a broken quote or an unknown clause fails the
test instead of quietly matching. All data here is invented.
"""
from __future__ import annotations

import base64
import re

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

USER = "tg_bot"
PASSWORD = "test-password"

MAIN = "aaaaaaaa-0000-0000-0000-000000000001"
SHOWROOM = "aaaaaaaa-0000-0000-0000-000000000002"
TRANSIT = "aaaaaaaa-0000-0000-0000-000000000003"

TILE_GREY = "bbbbbbbb-0000-0000-0000-000000000001"
TILE_SAND = "bbbbbbbb-0000-0000-0000-000000000002"
MARBLE = "bbbbbbbb-0000-0000-0000-000000000003"
SOLD_OUT = "bbbbbbbb-0000-0000-0000-000000000004"
ODD_NAME = "bbbbbbbb-0000-0000-0000-000000000005"
DELETED = "bbbbbbbb-0000-0000-0000-000000000006"
GROUP = "bbbbbbbb-0000-0000-0000-000000000007"

ITEMS = [
    dict(Ref_Key=TILE_GREY, Description="Үлгі керамогранит Алатау сұр 60×60", Артикул="CS-6060-GR", unit="м²"),
    dict(Ref_Key=TILE_SAND, Description="Үлгі керамогранит Алатау құм 60×60", Артикул="CS-6060-SD", unit="м²"),
    dict(Ref_Key=MARBLE, Description="Үлгі мәрмәр тақта Жетісу", Артикул="MR-3001", unit="м²"),
    dict(Ref_Key=SOLD_OUT, Description="Үлгі гранит баспалдақ", Артикул="GR-777", unit="дана"),
    dict(Ref_Key=ODD_NAME, Description="Тақта O'Neil", Артикул="ON'1", unit="дана"),
    dict(Ref_Key=DELETED, Description="Өшірілген тауар", Артикул="CS-DEL", unit="дана", DeletionMark=True),
    dict(Ref_Key=GROUP, Description="Керамогранит тобы", Артикул="", unit="", IsFolder=True),
]

BALANCE = [
    dict(item=TILE_GREY, wh=MAIN, q=812.5, r=40.0),
    dict(item=TILE_GREY, wh=MAIN, q=0.1, r=0.0),  # second series in the same warehouse
    dict(item=TILE_GREY, wh=MAIN, q=0.2, r=0.0),
    dict(item=TILE_GREY, wh=SHOWROOM, q=36.0, r=6.0),
    dict(item=TILE_GREY, wh=TRANSIT, q=0.0, r=0.0),  # must not be shown
    dict(item=TILE_SAND, wh=MAIN, q=120.96, r=0.0),
    dict(item=MARBLE, wh=SHOWROOM, q=18.0, r=0.0),
    dict(item=ODD_NAME, wh=MAIN, q=-2.0, r=0.0),
]

WAREHOUSES = {MAIN: "Негізгі қойма", SHOWROOM: "Шоурум", TRANSIT: "Жолда"}


class State:
    """Lets a test force a failure and inspect what 1C received."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.calls: list[str] = []
        self.fail_with: tuple[int, str] | None = None


state = State()


def odata_error(status: int = 400, message: str = "bad query") -> JSONResponse:
    return JSONResponse({"odata.error": {"code": "-1", "message": {"value": message}}}, status_code=status)


def authorized(request: Request) -> bool:
    expected = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    return request.headers.get("authorization") == f"Basic {expected}"


class Parser:
    """Recursive descent for the exact $filter subset the client may send."""

    def __init__(self, text: str):
        self.text = text
        self.at = 0

    def fail(self) -> None:
        raise ValueError(f"cannot parse at {self.at}: {self.text}")

    def space(self) -> None:
        while self.at < len(self.text) and self.text[self.at] == " ":
            self.at += 1

    def take(self, word: str) -> bool:
        self.space()
        if self.text.startswith(word, self.at):
            self.at += len(word)
            return True
        return False

    def literal(self) -> str:
        self.space()
        if not self.take("'"):
            self.fail()
        out = []
        while True:
            if self.at >= len(self.text):
                self.fail()
            char = self.text[self.at]
            if char == "'":
                if self.text[self.at + 1 : self.at + 2] == "'":
                    out.append("'")
                    self.at += 2
                    continue
                self.at += 1
                return "".join(out)
            out.append(char)
            self.at += 1

    def field(self) -> str:
        self.space()
        match = re.compile(r"[\w]+").match(self.text, self.at)
        if not match or match.group() not in ("Артикул", "Description", "DeletionMark", "IsFolder"):
            self.fail()
        self.at = match.end()
        return match.group()

    def atom(self):
        if self.take("("):
            inner = self.expression()
            if not self.take(")"):
                self.fail()
            return inner
        if self.take("substringof("):
            needle = self.literal()
            if not self.take(","):
                self.fail()
            field = self.field()
            if not self.take(")"):
                self.fail()
            return lambda row: needle.casefold() in str(row.get(field, "")).casefold()
        field = self.field()
        if not self.take("eq "):
            self.fail()
        if self.take("false"):
            return lambda row: row.get(field, False) is False
        value = self.literal()
        return lambda row: str(row.get(field, "")).casefold() == value.casefold()

    def conjunction(self):
        left = self.atom()
        while self.take("and "):
            right, previous = self.atom(), left
            left = lambda row, a=previous, b=right: a(row) and b(row)
        return left

    def expression(self):
        left = self.conjunction()
        while self.take("or "):
            right, previous = self.conjunction(), left
            left = lambda row, a=previous, b=right: a(row) or b(row)
        return left

    def parse(self):
        result = self.expression()
        self.space()
        if self.at != len(self.text):
            self.fail()
        return result


async def service_root(request: Request) -> Response:
    return JSONResponse({"value": [
        {"name": "Catalog_Номенклатура", "url": "Catalog_Номенклатура"},
        {"name": "Catalog_Склады", "url": "Catalog_Склады"},
        {"name": "AccumulationRegister_ТоварыНаСкладах", "url": "AccumulationRegister_ТоварыНаСкладах"},
    ]})


async def catalog_items(request: Request) -> Response:
    condition = request.query_params.get("$filter")
    if condition is None:
        row = {**ITEMS[0]}
        row["ЕдиницаИзмерения____Presentation"] = row.pop("unit")
        return JSONResponse({"value": [row]})
    try:
        matches = Parser(condition).parse()
    except ValueError as exc:
        return odata_error(message=str(exc))
    allowed = set(request.query_params["$select"].split(","))
    if allowed != {"Ref_Key", "Description", "Артикул", "ЕдиницаИзмерения____Presentation"}:
        return odata_error(message="unexpected $select")
    rows = [
        {
            "Ref_Key": row["Ref_Key"],
            "Description": row["Description"],
            "Артикул": row["Артикул"],
            "ЕдиницаИзмерения____Presentation": row["unit"],
        }
        for row in ITEMS
        if matches(row)
    ]
    return JSONResponse({"value": rows[: int(request.query_params["$top"])]})


async def catalog_warehouses(request: Request) -> Response:
    return JSONResponse({"value": [{"Ref_Key": key, "Description": name} for key, name in WAREHOUSES.items()]})


async def balance(request: Request) -> Response:
    tail = request.path_params["tail"]
    match = re.fullmatch(r"\(Condition='Номенклатура_Key eq guid'([0-9a-f-]{36})''\)", tail)
    if tail != "()" and not match:
        return odata_error(message=f"bad Balance call: {tail}")
    rows = [row for row in BALANCE if not match or row["item"] == match.group(1)]
    if not match:
        rows = rows[: int(request.query_params.get("$top", 1))]
    return JSONResponse({"value": [
        {
            "Номенклатура_Key": row["item"],
            "Склад_Key": row["wh"],
            "Характеристика_Key": "00000000-0000-0000-0000-000000000000",
            "Назначение_Key": "00000000-0000-0000-0000-000000000000",
            "Помещение_Key": "00000000-0000-0000-0000-000000000000",
            "Серия_Key": "00000000-0000-0000-0000-000000000000",
            "ВНаличииBalance": row["q"],
            "КОтгрузкеBalance": row["r"],
        }
        for row in rows
    ]})


class Gate:
    """Auth, forced failures and call logging in front of the routes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        state.calls.append(f"{scope['path']}?{scope['query_string'].decode()}")
        if state.fail_with:
            status, body = state.fail_with
            response = Response(body, status_code=status)
        elif not authorized(request):
            response = Response(
                "Unauthorized", status_code=401, headers={"WWW-Authenticate": 'Basic realm="1C:Enterprise 8.3"'}
            )
        elif scope["method"] != "GET":
            response = Response("Read only", status_code=405)
        elif scope["path"].rstrip("/").endswith(".odata") is False and b"allowedOnly=true" not in scope["query_string"]:
            # The real base answers like this for a user under record-level restrictions.
            response = JSONResponse(
                {"odata.error": {"code": "20", "message": {"lang": "ru", "value": "Доступ запрещен"}}},
                status_code=403,
            )
        else:
            return await self.app(scope, receive, send)
        await response(scope, receive, send)


app = Gate(
    Starlette(
        routes=[
            Route("/odata/standard.odata/", service_root),
            Route("/odata/standard.odata/Catalog_Номенклатура", catalog_items),
            Route("/odata/standard.odata/Catalog_Склады", catalog_warehouses),
            Route("/odata/standard.odata/AccumulationRegister_ТоварыНаСкладах/Balance{tail:path}", balance),
        ]
    )
)
