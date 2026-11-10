"""Боттың жадысы Telegram-ның өзінде: иесінің чатында бекітілген бір JSON файл.

Тегін хостинг әр қайта іске қосылғанда дискідегі файлдарды өшіреді, сондықтан
рұқсаттар тізімі мен есептер тарихы иесінің чатындағы бекітілген құжатта тұрады.
Бот оны жаңартқанда жаңа хабар жібермейді — сол бекітілген құжатты өңдейді.
"""
from __future__ import annotations

import asyncio
import copy
import io
import json
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InputMediaDocument

from storage import Config

log = logging.getLogger("salesbot.store")

STATE_NAME = "satylym-bot-zhady.json"
CAPTION = ("🗂 <b>Боттың жадысы</b>: рұқсаттар мен есептер тарихы (салыстыру үшін).\n"
           "Бұл бекітілген файлды өшірмеңіз және бекітуден алмаңыз.")
EMPTY = {"version": 1, "users": {}, "history": {}}


class Store:
    def __init__(self, bot: Bot, cfg: Config):
        self.bot = bot
        self.cfg = cfg
        self.claimed: int | None = None     # ADMIN_IDS бос кезде /start арқылы тағайындалған иесі
        self.state: dict | None = None
        self.loaded_for: int | None = None
        self.load_failed = False
        self.msg_id: int | None = None
        self.lock = asyncio.Lock()

    # ------------------------------------------------------------ кім кім

    def holder(self) -> int | None:
        """Жады осы адамның чатында сақталады."""
        return self.cfg.admin_ids[0] if self.cfg.admin_ids else self.claimed

    def admin_ids(self) -> list:
        ids = list(self.cfg.admin_ids)
        if self.claimed and self.claimed not in ids:
            ids.append(self.claimed)
        return ids

    def is_admin(self, uid: int) -> bool:
        return uid in self.admin_ids()

    def can_claim(self) -> bool:
        return not self.cfg.admin_ids and self.claimed is None

    async def claim(self, uid: int, code: str) -> bool:
        """ADMIN_IDS бос болса: OWNER_CODE берілсе — тек сол кодпен, әйтпесе бірінші /start иесі болады."""
        if not self.can_claim():
            return False
        if self.cfg.owner_code and code != self.cfg.owner_code:
            return False
        self.claimed = uid
        log.info("OWNER_CLAIMED id=%s", uid)
        async with self.lock:
            await self._load()
        return True

    async def is_allowed(self, uid: int) -> bool:
        if self.is_admin(uid):
            return True
        return str(uid) in (await self.get_state())["users"]

    # ------------------------------------------------------------ оқу/жазу

    async def get_state(self) -> dict:
        async with self.lock:
            await self._load()
            return self.state

    async def _load(self) -> None:
        holder = self.holder()
        if self.state is not None and self.loaded_for == holder and not self.load_failed:
            return
        loaded, mid, failed = None, None, False
        if holder is not None:
            try:
                chat = await self.bot.get_chat(holder)
                pm = chat.pinned_message
                if (pm and pm.document and pm.document.file_name == STATE_NAME
                        and pm.from_user and pm.from_user.id == self.bot.id):
                    buf = io.BytesIO()
                    await self.bot.download(pm.document, destination=buf)
                    loaded = json.loads(buf.getvalue().decode("utf-8"))
                    mid = pm.message_id
            except TelegramBadRequest as exc:
                if "chat not found" not in str(exc).lower():  # иесі ботты әлі ашпаса — қалыпты жағдай
                    log.warning("Жады оқылмады: %s", exc)
                    failed = True
            except Exception as exc:  # noqa: BLE001
                log.warning("Жады оқылмады: %s", exc)
                failed = True
        if failed:
            # Telegram уақытша қате берсе — бос жадымен үстінен жазып жібермеу үшін сақтауды тоқтатамыз
            self.load_failed = True
            if self.state is None:
                self.state = copy.deepcopy(EMPTY)
            return
        base = copy.deepcopy(EMPTY)
        if isinstance(loaded, dict):
            base.update(loaded)
            base.setdefault("users", {})
            base.setdefault("history", {})
        if self.state is not None and self.loaded_for is None:
            # иесі белгісіз кезде жиналғанды жоғалтпау
            base["users"].update(self.state.get("users", {}))
            for k, v in self.state.get("history", {}).items():
                base["history"].setdefault(k, v)
        self.state, self.msg_id, self.loaded_for, self.load_failed = base, mid, holder, False

    async def _save(self) -> None:
        holder = self.holder()
        if holder is None or self.load_failed:
            return
        data = json.dumps(self.state, ensure_ascii=False, indent=1).encode("utf-8")
        if self.msg_id:
            try:
                await self.bot.edit_message_media(
                    chat_id=holder, message_id=self.msg_id,
                    media=InputMediaDocument(media=BufferedInputFile(data, filename=STATE_NAME),
                                             caption=CAPTION, parse_mode="HTML"),
                )
                return
            except TelegramBadRequest as exc:
                if "not modified" in str(exc).lower():
                    return
                log.warning("Бекітілген жады өңделмеді, жаңасын жазамын: %s", exc)
        try:
            msg = await self.bot.send_document(holder, BufferedInputFile(data, filename=STATE_NAME),
                                               caption=CAPTION, parse_mode="HTML", disable_notification=True)
            self.msg_id = msg.message_id
            await self.bot.pin_chat_message(holder, msg.message_id, disable_notification=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("Жады сақталмады: %s", exc)

    # ------------------------------------------------------------ рұқсаттар

    async def users(self) -> dict:
        return dict((await self.get_state())["users"])

    async def allow(self, uid: int, name: str) -> None:
        async with self.lock:
            await self._load()
            self.state["users"][str(uid)] = name
            await self._save()

    async def deny(self, uid: int) -> bool:
        async with self.lock:
            await self._load()
            existed = self.state["users"].pop(str(uid), None) is not None
            if existed:
                await self._save()
            return existed

    # ------------------------------------------------------------ тарих

    async def history(self, uid: int) -> list:
        return list((await self.get_state())["history"].get(str(uid), []))

    async def put_history(self, uid: int, entries: list) -> None:
        async with self.lock:
            await self._load()
            self.state["history"][str(uid)] = entries
            await self._save()
