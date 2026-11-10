"""Ботты Telegram-сыз тексеру: жалған Telegram сервері арқылы шынайы диспетчерге хабарлар жібереміз.

python tests/test_bot_offline.py ЕСЕП1.pdf [ЕСЕП2.pdf ...]

Тексеріледі: иесін құпия кодпен тағайындау, рұқсаттар, PDF талдау, бекітілген жады
(сервер қайта іске қосылғаннан кейін де сақталуы), webhook HTTP қабылдауы.
"""
import asyncio
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(BOT_TOKEN="123456:TEST-TOKEN-abcdefghijklmnopqrstuvwxyz012", ADMIN_IDS="",
                  OWNER_CODE="secret123", DATA_DIR=tempfile.mkdtemp(prefix="salesbot-test-"),
                  PUBLIC_URL="", RENDER_EXTERNAL_URL="")

from aiogram import Bot  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.methods import (DeleteMessage, EditMessageMedia, GetChat, GetFile, GetMe, PinChatMessage,  # noqa: E402
                             SendDocument, SendMessage, SetMyCommands)
from aiogram.types import (AcceptedGiftTypes, Chat, ChatFullInfo, Document, File, Message, Update,  # noqa: E402
                           User)

import bot as botmod  # noqa: E402
import storage  # noqa: E402

BOT_USER = User(id=123456, is_bot=True, first_name="Sales", username="sales_test_bot")


class FakeTelegram(BaseSession):
    """Telegram серверінің қарапайым көшірмесі: хабарлар, файлдар, бекітілген хабарлар."""

    def __init__(self):
        super().__init__()
        self.files = {}        # file_id -> bytes
        self.calls = []
        self.pinned = {}       # chat_id -> Message
        self.docs = {}         # (chat_id, message_id) -> Message
        self._mid = 10_000
        self._fid = 0

    def _store(self, data: bytes) -> str:
        self._fid += 1
        fid = f"botfile{self._fid}"
        self.files[fid] = data
        return fid

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, GetMe):
            return BOT_USER
        if isinstance(method, GetFile):
            data = self.files[method.file_id]
            return File(file_id=method.file_id, file_unique_id="u" + method.file_id, file_size=len(data),
                        file_path=f"documents/{method.file_id}.bin")
        if isinstance(method, GetChat):
            return ChatFullInfo(id=method.chat_id, type="private", accent_color_id=0, max_reaction_count=0,
                                accepted_gift_types=AcceptedGiftTypes(unlimited_gifts=False, limited_gifts=False,
                                                                      unique_gifts=False, premium_subscription=False,
                                                                      gifts_from_channels=False),
                                pinned_message=self.pinned.get(method.chat_id))
        if isinstance(method, SendMessage):
            self._mid += 1
            if method.parse_mode is not None:
                check_html(method.text)
            return Message(message_id=self._mid, date=datetime.now(), chat=Chat(id=method.chat_id, type="private"),
                           from_user=BOT_USER, text=method.text)
        if isinstance(method, SendDocument):
            self._mid += 1
            fid = self._store(method.document.data)
            doc = Document(file_id=fid, file_unique_id="u" + fid, file_name=method.document.filename)
            msg = Message(message_id=self._mid, date=datetime.now(), chat=Chat(id=method.chat_id, type="private"),
                          from_user=BOT_USER, document=doc, caption=method.caption)
            self.docs[(method.chat_id, self._mid)] = msg
            return msg
        if isinstance(method, PinChatMessage):
            self.pinned[method.chat_id] = self.docs[(method.chat_id, method.message_id)]
            return True
        if isinstance(method, EditMessageMedia):
            key = (method.chat_id, method.message_id)
            old = self.docs[key]
            fid = self._store(method.media.media.data)
            new = old.model_copy(update={"document": Document(file_id=fid, file_unique_id="u" + fid,
                                                              file_name=method.media.media.filename)})
            self.docs[key] = new
            if self.pinned.get(method.chat_id) and self.pinned[method.chat_id].message_id == method.message_id:
                self.pinned[method.chat_id] = new
            return True
        if isinstance(method, DeleteMessage):
            return True
        return True

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        fid = url.rsplit("/", 1)[-1].split(".")[0]
        data = self.files[fid]
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]

    async def close(self):
        pass


def check_html(text: str) -> None:
    """Telegram HTML режимі: тегтер теңгерімді, тек рұқсат етілгендері, ұзындығы шектен аспайды."""
    assert len(text) <= 4096, f"хабарлама тым ұзын: {len(text)}"
    allowed = {"b", "i", "u", "s", "code", "pre", "a", "blockquote", "tg-spoiler"}
    stack = []
    for closing, tag in re.findall(r"<(/?)([\w-]+)[^>]*>", text):
        assert tag in allowed, f"рұқсат етілмеген тег: {tag}"
        if closing:
            assert stack and stack[-1] == tag, f"тег теңгерімсіз: {tag}"
            stack.pop()
        else:
            stack.append(tag)
    assert not stack, f"жабылмаған тег: {stack}"
    assert "<" not in re.sub(r"<[^>]+>", "", text), "экрандалмаған <"


N = 0


def update(uid, text=None, document=None, name="Test"):
    global N
    N += 1
    msg = Message(message_id=N, date=datetime.now(), chat=Chat(id=uid, type="private"),
                  from_user=User(id=uid, is_bot=False, first_name=name), text=text, document=document)
    return Update(update_id=N, message=msg)


def sent(tg, chat_id, since):
    out = []
    for m in tg.calls[since:]:
        if isinstance(m, SendMessage) and m.chat_id == chat_id:
            out.append(m.text)
        if isinstance(m, SendDocument) and m.chat_id == chat_id:
            out.append(f"[DOCUMENT {m.document.filename}]")
    return out


def new_bot(tg, admin_ids=""):
    os.environ["ADMIN_IDS"] = admin_ids
    cfg = storage.load_config()
    bot = Bot(cfg.token, session=tg, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    return bot, botmod.build_dispatcher(cfg, bot), cfg


async def main(pdfs):
    tg = FakeTelegram()
    OWNER, GUEST, STRANGER = 111, 222, 333

    bot, dp, cfg = new_bot(tg)

    async def feed(u, d=None):
        before = len(tg.calls)
        await (d or dp).feed_update(bot, u)
        return before

    # 1. Кодсыз /start — иесі бола алмайды
    b = await feed(update(STRANGER, "/start"))
    assert any("жабық" in x for x in sent(tg, STRANGER, b)), sent(tg, STRANGER, b)
    assert not dp["store"].admin_ids()
    print("✓ кодсыз /start иесі бола алмайды")

    # 2. Құпия сілтемемен иесі болу
    b = await feed(update(OWNER, "/start secret123", name="Owner"))
    t = sent(tg, OWNER, b)
    assert any("иесісіз" in x for x in t), t
    assert any(isinstance(m, SetMyCommands) and m.scope for m in tg.calls[b:]), "иесінің командалары орнатылмады"
    print("✓ құпия сілтеме арқылы иесі тағайындалды, иесіне арналған командалар қосылды")

    # 3. Бөтен адам → жабық + иесіне хабар
    b = await feed(update(GUEST, "/start", name="Guest"))
    assert any("жабық" in x for x in sent(tg, GUEST, b))
    assert any("Рұқсат сұрап" in x for x in sent(tg, OWNER, b))
    print("✓ бөтен адам бұғатталды, иесіне хабар кетті")

    # 4. /allow → жады иесінің чатында бекітіледі
    b = await feed(update(OWNER, f"/allow {GUEST} Менеджер"))
    assert any("Рұқсат берілді" in x for x in sent(tg, OWNER, b))
    assert OWNER in tg.pinned and tg.pinned[OWNER].document.file_name == "satylym-bot-zhady.json"
    print("✓ /allow: рұқсат иесінің чатындағы бекітілген жадыға жазылды")

    # 5. PDF-тер
    pins_before = sum(isinstance(m, PinChatMessage) for m in tg.calls)
    for i, pdf in enumerate(pdfs):
        fid = f"user{i}"
        tg.files[fid] = Path(pdf).read_bytes()
        doc = Document(file_id=fid, file_unique_id="u" + fid, file_name=Path(pdf).name,
                       mime_type="application/pdf", file_size=len(tg.files[fid]))
        b = await feed(update(GUEST, document=doc))
        t = sent(tg, GUEST, b)
        assert any(x.startswith("📊") for x in t), t[:2]
        assert any(x.startswith("[DOCUMENT satylym_") for x in t), t[-1]
        comp = any("Алдыңғы есеппен салыстыру" in x for x in t)
        print(f"✓ {Path(pdf).name}: {len(t) - 2} хабарлама + HTML" + (" · салыстыру бар" if comp else ""))
    assert sum(isinstance(m, PinChatMessage) for m in tg.calls) == pins_before, "жады жаңа хабармен емес, өңдеумен жаңаруы керек"
    assert any(isinstance(m, EditMessageMedia) for m in tg.calls), "жады өңделмеді"
    print("✓ тарих бекітілген жадыда өңдеу арқылы жаңарды (жаңа хабарсыз)")

    # 6. Бұзылған PDF және PDF емес файл
    tg.files["bad"] = b"%PDF-1.4 not really a pdf"
    b = await feed(update(GUEST, document=Document(file_id="bad", file_unique_id="ubad", file_name="bad.pdf",
                                                   mime_type="application/pdf", file_size=25)))
    assert any("оқи алмадым" in x for x in sent(tg, GUEST, b))
    b = await feed(update(GUEST, document=Document(file_id="x", file_unique_id="ux", file_name="t.xlsx",
                                                   mime_type="application/vnd.ms-excel", file_size=10)))
    assert any("PDF" in x for x in sent(tg, GUEST, b))
    print("✓ бұзылған PDF пен PDF емес файлға түсінікті жауап")

    # 7. СЕРВЕР ҚАЙТА ІСКЕ ҚОСЫЛДЫ (жад тазарды), ADMIN_IDS орнатылған
    bot, dp2, _ = new_bot(tg, admin_ids=str(OWNER))
    b = await feed(update(GUEST, "/history"), dp2)
    t = sent(tg, GUEST, b)
    assert t and "Сақталған есептер" in t[0], t
    print("✓ қайта іске қосылғаннан кейін рұқсат пен тарих Telegram-нан оқылды:", t[0].count("•"), "есеп")
    if len(pdfs) >= 1:
        fid = "again"
        tg.files[fid] = Path(pdfs[-1]).read_bytes()
        doc = Document(file_id=fid, file_unique_id="u" + fid, file_name="again.pdf", mime_type="application/pdf",
                       file_size=len(tg.files[fid]))
        b = await feed(update(GUEST, document=doc), dp2)
        assert any(x.startswith("📊") for x in sent(tg, GUEST, b))
    b = await feed(update(STRANGER, "/start secret123"), dp2)
    assert any("жабық" in x for x in sent(tg, STRANGER, b)), "ADMIN_IDS бар кезде код жұмыс істемеуі керек"
    print("✓ ADMIN_IDS орнатылған соң құпия кодпен ешкім иесі бола алмайды")

    # 8. Қайта іске қосылды, ADMIN_IDS жоқ: иесі сол сілтемемен қайта кіреді, жадысы қайтады
    bot, dp3, _ = new_bot(tg)
    b = await feed(update(OWNER, "/start secret123"), dp3)
    assert await dp3["store"].is_allowed(GUEST), "иесі қайта кіргенде рұқсаттар тізімі қалпына келуі керек"
    print("✓ иесі қайта кіргенде рұқсаттар тізімі қалпына келді")

    # 9. /users, /deny, бөтеннің /allow-ы
    b = await feed(update(OWNER, "/users"), dp3)
    assert any(str(GUEST) in x for x in sent(tg, OWNER, b))
    b = await feed(update(GUEST, f"/allow {STRANGER}"), dp3)
    assert not await dp3["store"].is_allowed(STRANGER)
    b = await feed(update(OWNER, f"/deny {GUEST}"), dp3)
    b = await feed(update(GUEST, "/history"), dp3)
    assert any("жабық" in x for x in sent(tg, GUEST, b))
    print("✓ /users, /deny жұмыс істейді, иесі емес адам рұқсат бере алмайды")

    # 10. Webhook: HTTP арқылы хабар қабылдау
    from aiohttp.test_utils import TestClient, TestServer
    os.environ["PUBLIC_URL"] = "https://example.onrender.com"
    os.environ["ADMIN_IDS"] = str(OWNER)
    cfg = storage.load_config()
    wbot = Bot(cfg.token, session=tg, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    wdp = botmod.build_dispatcher(cfg, wbot)
    info = {"status": "…"}
    app = botmod.build_webhook_app(cfg, wbot, wdp, info)
    await botmod.prepare(wbot, wdp, cfg, info)
    async with TestClient(TestServer(app)) as client:
        r = await client.get("/healthz")
        body = await r.text()
        assert r.status == 200 and "жұмыс істеп тұр" in body, body
        upd = update(OWNER, "/myid").model_dump(mode="json", exclude_none=True)
        r = await client.post(info["path"], json=upd)
        assert r.status == 401, f"құпиясыз сұрау қабылданбауы керек: {r.status}"
        before = len(tg.calls)
        r = await client.post(info["path"], json=upd,
                              headers={"X-Telegram-Bot-Api-Secret-Token": botmod.webhook_secret(cfg)})
        assert r.status == 200
        await client.post(info["path"], json=upd,
                               headers={"X-Telegram-Bot-Api-Secret-Token": botmod.webhook_secret(cfg)})
        await asyncio.sleep(0.5)
        replies = [m for m in sent(tg, OWNER, before) if "Telegram ID" in m]
        assert len(replies) == 1, f"бір хабар бір рет өңделуі керек, келгені: {len(replies)}"
    print(f"✓ webhook: күй беті 200, құпиясыз 401, хабар өңделді, қайталанған хабар өткізілді ({body})")

    print("\nБАРЛЫҚ ТЕСТ ӨТТІ")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
