"""Telegram side: opens the Mini App and lets the admin manage access."""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from .access import AccessList

log = logging.getLogger(__name__)

API_ROOT = "https://api.telegram.org"
ACCESS_HEADER = "Рұқсат тізімі. Бұл хабарды өшірмеңіз және бекітуден алмаңыз."
OPEN_BUTTON = "Қалдықты тексеру"
ADMIN_HELP = (
    "Әкімші командалары:\n"
    "/add 123456 — адамға рұқсат беру\n"
    "/remove 123456 — рұқсатты алу\n"
    "/users — рұқсаты бар адамдар"
)


class BotApiError(Exception):
    pass


class Bot:
    def __init__(
        self,
        token: str,
        public_url: str,
        webhook_secret: str,
        access: AccessList,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._token = token
        self._public_url = public_url
        self._webhook_secret = webhook_secret
        self._access = access
        self._http = httpx.AsyncClient(timeout=10, transport=transport)
        self._pinned_id: int | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def call(self, method: str, **payload: Any) -> Any:
        try:
            response = await self._http.post(f"{API_ROOT}/bot{self._token}/{method}", json=payload)
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # The exception text can hold the URL, and the URL holds the bot token.
            raise BotApiError(f"{method}: {type(exc).__name__}") from None
        if not data.get("ok"):
            raise BotApiError(f"{method}: {data.get('description', 'unknown error')}")
        return data.get("result")

    async def configure(self) -> None:
        steps = [
            (
                "setWebhook",
                {
                    "url": f"{self._public_url}/telegram/webhook",
                    "secret_token": self._webhook_secret,
                    "allowed_updates": ["message"],
                },
            ),
            ("setMyCommands", {"commands": [{"command": "start", "description": "Қалдықты тексеру"}]}),
            (
                "setMyCommands",
                {
                    "scope": {"type": "chat", "chat_id": self._access.admin_id},
                    "commands": [
                        {"command": "start", "description": "Қалдықты тексеру"},
                        {"command": "add", "description": "Рұқсат беру: /add 123456"},
                        {"command": "remove", "description": "Рұқсатты алу: /remove 123456"},
                        {"command": "users", "description": "Рұқсаты бар адамдар"},
                    ],
                },
            ),
            (
                "setChatMenuButton",
                {"menu_button": {"type": "web_app", "text": "Қалдық", "web_app": {"url": self._public_url}}},
            ),
        ]
        for method, payload in steps:
            try:
                await self.call(method, **payload)
            except BotApiError as exc:
                log.warning("Telegram setup step failed: %s", exc)

    async def load_access(self) -> None:
        """Reads the pinned list. On a Telegram failure the list stays unloaded, so it is never overwritten."""
        try:
            chat = await self.call("getChat", chat_id=self._access.admin_id)
        except BotApiError as exc:
            if "chat not found" in str(exc).lower():
                self._access.replace(set())  # The admin has not opened the bot yet.
            else:
                log.warning("Access list not loaded: %s", exc)
            return

        pinned = chat.get("pinned_message") or {}
        text = pinned.get("text") or ""
        written_by_bot = (pinned.get("from") or {}).get("is_bot") is True
        if written_by_bot and text.startswith(ACCESS_HEADER):
            self._pinned_id = pinned["message_id"]
            self._access.replace({int(value) for value in re.findall(r"^\d+$", text, re.MULTILINE)})
        else:
            self._access.replace(set())

    async def _save_access(self) -> None:
        text = "\n".join([ACCESS_HEADER, *(str(value) for value in self._access.managed_ids())])
        admin = self._access.admin_id
        if self._pinned_id is not None:
            try:
                await self.call("editMessageText", chat_id=admin, message_id=self._pinned_id, text=text)
                return
            except BotApiError as exc:
                if "not modified" in str(exc):
                    return
                log.warning("Pinned access list not edited, writing a new one: %s", exc)
        sent = await self.call("sendMessage", chat_id=admin, text=text, disable_notification=True)
        self._pinned_id = sent["message_id"]
        await self.call("pinChatMessage", chat_id=admin, message_id=self._pinned_id, disable_notification=True)

    async def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        sender = (message.get("from") or {}).get("id")
        if chat.get("type") != "private" or not isinstance(sender, int):
            return

        words = (message.get("text") or "").split()
        command = words[0].split("@")[0].lower() if words and words[0].startswith("/") else ""
        arguments = words[1:]

        if sender == self._access.admin_id and command in ("/add", "/remove", "/users", "/help"):
            await self._send(chat["id"], await self._admin_reply(command, arguments))
        elif await self._is_allowed(sender):
            await self._send(
                chat["id"],
                "Артикул бойынша қойма қалдығын тексеріңіз.",
                {"inline_keyboard": [[{"text": OPEN_BUTTON, "web_app": {"url": self._public_url}}]]},
            )
        else:
            await self._send(
                chat["id"],
                f"Сізде рұқсат жоқ. Мына ID-ні әкімшіге жіберіңіз: <code>{sender}</code>",
            )

    async def _is_allowed(self, user_id: int) -> bool:
        if not self._access.is_allowed(user_id) and not self._access.loaded:
            await self.load_access()
        return self._access.is_allowed(user_id)

    async def _admin_reply(self, command: str, arguments: list[str]) -> str:
        if command == "/help":
            return ADMIN_HELP

        if not self._access.loaded:
            await self.load_access()
        if not self._access.loaded:
            return "Рұқсат тізімін оқи алмадым. Бір минуттан кейін қайталаңыз."

        if command == "/users":
            lines = [f"Әкімші: <code>{self._access.admin_id}</code>"]
            lines += [f"Тұрақты: <code>{value}</code>" for value in sorted(self._access.permanent_ids)]
            lines += [f"Рұқсат берілген: <code>{value}</code>" for value in self._access.managed_ids()]
            return "\n".join(lines)

        if len(arguments) != 1 or not arguments[0].isascii() or not arguments[0].isdigit():
            return f"ID-ні сан түрінде жазыңыз, мысалы: {command} 123456"
        user_id = int(arguments[0])

        if command == "/add":
            self._access.add(user_id)
            if not await self._saved():
                return f"<code>{user_id}</code> қосылды, бірақ тізім сақталмады. /add командасын қайталаңыз."
            return f"<code>{user_id}</code> қосылды. Енді ол ботқа /start жаза алады."
        if user_id == self._access.admin_id:
            return "Әкімшінің рұқсатын алу мүмкін емес."
        if user_id in self._access.permanent_ids:
            return "Бұл ID тұрақты тізімде тұр. Оны ALLOWED_TELEGRAM_IDS баптауынан өшіріңіз."
        if not self._access.remove(user_id):
            return "Бұл ID тізімде жоқ."
        if not await self._saved():
            return f"<code>{user_id}</code> рұқсаты алынды, бірақ тізім сақталмады. Қайталап көріңіз."
        return f"<code>{user_id}</code> рұқсаты алынды."

    async def _saved(self) -> bool:
        try:
            await self._save_access()
        except BotApiError as exc:
            log.warning("Access list not saved: %s", exc)
            return False
        return True

    async def _send(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        await self.call("sendMessage", **payload)
