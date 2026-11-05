"""Web server: the Mini App page, its API and the Telegram webhook."""

import hmac
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path as FilePath
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .access import AccessList
from .bot import Bot, BotApiError
from .config import Settings, load_settings
from .onec import OneCClient, OneCError, OneCUnavailable
from .tg_auth import InitDataError, TgUser, verify_init_data

log = logging.getLogger(__name__)

WEB_DIR = FilePath(__file__).resolve().parent.parent / "web"
GUID_PATTERN = r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$"
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
CSP = "; ".join(
    [
        "default-src 'none'",
        "script-src 'self' https://telegram.org",
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors https://web.telegram.org https://*.telegram.org",
    ]
)


def create_app(
    settings: Settings,
    onec_transport: httpx.AsyncBaseTransport | None = None,
    telegram_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    access = AccessList(settings.admin_id, settings.allowed_ids)
    onec = OneCClient(settings.onec, transport=onec_transport)
    bot = Bot(
        settings.bot_token,
        settings.public_url,
        settings.webhook_secret,
        access,
        transport=telegram_transport,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await bot.configure()
        await bot.load_access()
        yield
        await onec.aclose()
        await bot.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
        return response

    @app.exception_handler(OneCError)
    async def onec_error(_: Request, exc: OneCError) -> JSONResponse:
        status = 503 if isinstance(exc, OneCUnavailable) else 502
        return JSONResponse({"detail": {"code": exc.code}}, status_code=status)

    async def current_user(authorization: Annotated[str | None, Header()] = None) -> TgUser:
        scheme, _, init_data = (authorization or "").partition(" ")
        if scheme.lower() != "tma" or not init_data:
            raise HTTPException(401, {"code": "not_telegram"})
        try:
            user = verify_init_data(init_data, settings.bot_token, settings.init_data_max_age)
        except InitDataError:
            raise HTTPException(401, {"code": "not_telegram"}) from None
        if not access.is_allowed(user.id) and not access.loaded:
            await bot.load_access()
        if not access.is_allowed(user.id):
            raise HTTPException(403, {"code": "no_access", "user_id": user.id})
        return user

    Allowed = Annotated[TgUser, Depends(current_user)]

    @app.get("/healthz")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/me")
    async def me(user: Allowed) -> dict[str, object]:
        return {"id": user.id, "first_name": user.first_name}

    @app.get("/api/search")
    async def search(_: Allowed, q: Annotated[str, Query(max_length=64)]) -> dict[str, object]:
        text = " ".join(CONTROL_CHARS.sub(" ", q).split())
        if len(text) < 2:
            raise HTTPException(422, {"code": "too_short"})
        result = await onec.search(text)
        return {"items": [asdict(item) for item in result.items], "truncated": result.truncated}

    @app.get("/api/stock/{item_id}")
    async def stock(_: Allowed, item_id: Annotated[str, Path(pattern=GUID_PATTERN)]) -> dict[str, object]:
        report = await onec.stock(item_id)
        return {
            "warehouses": [asdict(row) for row in report.warehouses],
            "total_quantity": report.total_quantity,
            "total_reserved": report.total_reserved,
        }

    @app.post("/telegram/webhook", include_in_schema=False)
    async def webhook(
        request: Request,
        x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, bool]:
        supplied = (x_telegram_bot_api_secret_token or "").encode()
        if not hmac.compare_digest(supplied, settings.webhook_secret.encode()):
            raise HTTPException(401)
        try:
            await bot.handle_update(await request.json())
        except (BotApiError, ValueError) as exc:
            # Answering 200 stops Telegram from re-sending the same update forever.
            log.warning("Telegram update not handled: %s", exc)
        return {"ok": True}

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


def build_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs full URLs at INFO, and Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return create_app(load_settings())
