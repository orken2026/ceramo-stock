from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_1c  # noqa: E402

from app.config import OneCSettings, Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.onec import OneCClient  # noqa: E402

BOT_TOKEN = "123456:TEST-TOKEN"
ADMIN = 1000
STAFF = 2000
STRANGER = 3000


def sign_init_data(user_id: int, token: str = BOT_TOKEN, auth_date: int | None = None, **extra: str) -> str:
    fields = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "query_id": "AAE",
        "user": json.dumps({"id": user_id, "first_name": "Тест"}, ensure_ascii=False),
        **extra,
    }
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def onec_settings(**overrides) -> OneCSettings:
    base = dict(odata_url="http://1c.test/odata/standard.odata", user=fake_1c.USER, password=fake_1c.PASSWORD)
    return OneCSettings(**{**base, **overrides})


class TelegramStub(httpx.AsyncBaseTransport):
    """Remembers messages and the pinned one, like a real chat."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.stored: dict[int, str] = {}
        self.pinned: int | None = None
        self.pinned_by_bot = True
        self.last_id = 100
        self.failing: dict[str, str] = {}

    def pinned_text(self) -> str | None:
        return self.stored.get(self.pinned) if self.pinned else None

    @staticmethod
    def _answer(result=True) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": result})

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content or b"{}")
        self.sent.append((method, payload))
        if method in self.failing:
            return httpx.Response(400, json={"ok": False, "description": self.failing[method]})
        if method == "sendMessage":
            self.last_id += 1
            message_id = self.last_id
            self.stored[message_id] = payload["text"]
            return self._answer({"message_id": message_id})
        if method == "pinChatMessage":
            self.pinned = payload["message_id"]
        if method == "editMessageText":
            if payload["message_id"] not in self.stored:
                return httpx.Response(400, json={"ok": False, "description": "Bad Request: message to edit not found"})
            if self.stored[payload["message_id"]] == payload["text"]:
                return httpx.Response(400, json={"ok": False, "description": "Bad Request: message is not modified"})
            self.stored[payload["message_id"]] = payload["text"]
        if method == "getChat":
            chat: dict = {"id": payload["chat_id"]}
            if self.pinned in self.stored:
                chat["pinned_message"] = {
                    "message_id": self.pinned,
                    "text": self.stored[self.pinned],
                    "from": {"is_bot": self.pinned_by_bot},
                }
            return self._answer(chat)
        return self._answer()

    def messages(self) -> list[dict]:
        return [payload for method, payload in self.sent if method == "sendMessage"]


@pytest.fixture(autouse=True)
def clean_fake():
    fake_1c.state.reset()
    yield
    fake_1c.state.reset()


@pytest.fixture
def onec_transport():
    return httpx.ASGITransport(app=fake_1c.app, raise_app_exceptions=False)


@pytest.fixture
async def onec(onec_transport):
    client = OneCClient(onec_settings(), transport=onec_transport)
    yield client
    await client.aclose()


@pytest.fixture
def telegram():
    return TelegramStub()


@pytest.fixture
def settings():
    return Settings(
        bot_token=BOT_TOKEN,
        admin_id=ADMIN,
        public_url="https://stock.test",
        allowed_ids=frozenset({STAFF}),
        init_data_max_age=86400,
        onec=onec_settings(),
    )


@pytest.fixture
def web(settings, onec_transport, telegram):
    with TestClient(create_app(settings, onec_transport, telegram)) as client:
        yield client


def as_user(user_id: int) -> dict[str, str]:
    return {"Authorization": f"tma {sign_init_data(user_id)}"}
