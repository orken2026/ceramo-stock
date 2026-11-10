"""Telegram-бот: 1С «Валовая прибыль по клиентам» PDF есебін жіберсеңіз, талдап береді.

Компьютерде:  python bot.py            (polling, .env ішінде BOT_TOKEN)
Серверде:     PUBLIC_URL немесе RENDER_EXTERNAL_URL берілсе — webhook режимі.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import sys
import tempfile
from collections import deque
from datetime import datetime
from html import escape
from pathlib import Path

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter, TelegramUnauthorizedError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BotCommand, BotCommandScopeChat, BufferedInputFile, Message
from aiohttp import web

from salesreport.compare import compare_text, find_previous, history_text, snapshot, upsert
from storage import Config, load_config
from tgstore import Store

log = logging.getLogger("salesbot")
PARSE_SLOTS = asyncio.Semaphore(2)

WELCOME = (
    "👋 Сәлем! Мен 1С-тің <b>«Валовая прибыль по клиентам»</b> есебін талдаймын.\n\n"
    "📎 PDF файлды осы чатқа жіберіңіз — мен есептеп, мыналарды айтамын:\n"
    "• сатылым, заказ саны, орташа чек, плитка м²\n"
    "• не сатылды: тауар топтары, форматтар, ең көп сатылған позициялар\n"
    "• қай жерде: LI/XL сериялары, бонус санаттары\n"
    "• ең ірі заказдар, жеңілдіктер, пайда (1С-та себестоимость бағаны болса)\n"
    "• алдыңғы есеппен салыстыру\n\n"
    "Соңында толық есепті HTML файл етіп жіберемін — телефонда ашылады.\n"
    "Нұсқаулық: /help"
)
HELP = (
    "📘 <b>Есепті 1С-тан қалай шығару керек</b>\n\n"
    "1. 1С-та «Валовая прибыль по клиентам» есебін ашыңыз.\n"
    "2. Кезең мен менеджерді таңдаңыз.\n"
    "3. Тауар бойынша талдау керек болса, топтау: <i>Менеджер → Заказ клиента → Сегмент → Номенклатура</i>.\n"
    "4. Пайданы да көру үшін «Настройки» ішіндегі «Показатели» (немесе «Поля») бөлімінен "
    "<b>Себестоимость</b> және <b>Валовая прибыль</b> белгілеңіз.\n"
    "5. «Сформировать» → «Сохранить как» (немесе Печать) → <b>PDF</b>.\n"
    "6. PDF-ті осы чатқа жіберіңіз.\n\n"
    "<b>Командалар</b>\n"
    "/history — сақталған есептер\n"
    "/myid — Telegram ID-іңіз\n"
)
ADMIN_HELP = (
    "\n<b>Иесіне арналған</b>\n"
    "/allow ID [аты] — рұқсат беру\n"
    "/deny ID — рұқсатты алу\n"
    "/users — рұқсаты бар адамдар\n"
)
LOCKED = (
    "🔒 Бұл бот жабық. Рұқсат алу үшін бот иесіне ID-іңізді жіберіңіз: <code>{uid}</code>\n"
    "Сұрауыңыз иесіне жіберілді."
)
PARSE_ERROR = (
    "❌ Есепті оқи алмадым: {err}\n\n"
    "Тексеріңіз:\n"
    "• бұл 1С-тің «Валовая прибыль по клиентам» есебі ме?\n"
    "• PDF сурет (скан) емес, 1С-тан тікелей сақталған ба?\n"
    "• кестеде «Выручка» бағаны бар ма?\n"
    "Толығырақ: /help"
)
USER_COMMANDS = [
    BotCommand(command="start", description="Бастау"),
    BotCommand(command="help", description="Есепті 1С-тан қалай шығару"),
    BotCommand(command="history", description="Сақталған есептер"),
    BotCommand(command="myid", description="Telegram ID"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="allow", description="Рұқсат беру: /allow 123456"),
    BotCommand(command="deny", description="Рұқсатты алу: /deny 123456"),
    BotCommand(command="users", description="Рұқсаты бар адамдар"),
]


def who(message: Message) -> str:
    u = message.from_user
    name = u.full_name or ""
    if u.username:
        name += f" (@{u.username})"
    return name.strip() or str(u.id)


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


async def send_text(message: Message, text: str) -> None:
    for _ in range(3):
        try:
            await message.answer(text)
            break
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
        except TelegramBadRequest as exc:
            log.warning("HTML жіберілмеді (%s), жай мәтінмен жіберемін", exc)
            await message.answer(strip_tags(text), parse_mode=None)
            break
    await asyncio.sleep(0.3)


async def safe_delete(msg) -> None:
    try:
        await msg.delete()
    except Exception:  # noqa: BLE001
        pass


async def notify_admins(bot: Bot, store: Store, text: str) -> None:
    for aid in store.admin_ids():
        try:
            await bot.send_message(aid, text)
        except (TelegramForbiddenError, TelegramBadRequest):
            log.warning("Иесіне хабар жетпеді: %s", aid)


async def set_admin_commands(bot: Bot, store: Store) -> None:
    for aid in store.admin_ids():
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=aid))
        except Exception as exc:  # noqa: BLE001
            log.warning("Иесінің командалары орнатылмады: %s", exc)


class DropRepeats(BaseMiddleware):
    """Сервер оянып жатқанда Telegram бір хабарды қайта жіберсе — екі рет өңдемейміз."""

    def __init__(self, size: int = 500):
        self.seen = deque(maxlen=size)

    async def __call__(self, handler, event, data):
        uid = getattr(event, "update_id", None)
        if uid is not None:
            if uid in self.seen:
                return None
            self.seen.append(uid)
        return await handler(event, data)


# ---------------------------------------------------------------- commands

async def cmd_start(message: Message, command: CommandObject, bot: Bot, store: Store) -> None:
    uid = message.from_user.id
    if store.can_claim() and await store.claim(uid, (command.args or "").strip()):
        log.info("Бот иесі: %s %s", uid, who(message))
        await message.answer("👑 Сіз осы боттың иесісіз. Басқаларға рұқсатты өзіңіз бересіз: /allow ID")
        await set_admin_commands(bot, store)
    if await store.is_allowed(uid):
        await message.answer(WELCOME + (ADMIN_HELP if store.is_admin(uid) else ""))
        return
    await message.answer(LOCKED.format(uid=uid))
    await notify_admins(bot, store, f"🔔 Рұқсат сұрап тұр: {escape(who(message))}\nID: <code>{uid}</code>\n"
                                    f"Рұқсат беру: <code>/allow {uid}</code>")


async def cmd_help(message: Message, store: Store) -> None:
    await message.answer(HELP + (ADMIN_HELP if store.is_admin(message.from_user.id) else ""))


async def cmd_myid(message: Message) -> None:
    await message.answer(f"Сіздің Telegram ID: <code>{message.from_user.id}</code>")


async def cmd_allow(message: Message, command: CommandObject, bot: Bot, store: Store) -> None:
    if not store.is_admin(message.from_user.id):
        return
    parts = (command.args or "").split(maxsplit=1)
    if not parts or not parts[0].isdigit():
        await message.answer("Қолданылуы: <code>/allow 123456789 Аты</code>")
        return
    uid, name = int(parts[0]), (parts[1] if len(parts) > 1 else "")
    await store.allow(uid, name)
    await message.answer(f"✅ Рұқсат берілді: <code>{uid}</code> {escape(name)}")
    try:
        await bot.send_message(uid, "✅ Сізге ботқа рұқсат берілді. 1С есебінің PDF файлын жіберіңіз. /help")
    except (TelegramForbiddenError, TelegramBadRequest):
        pass


async def cmd_deny(message: Message, command: CommandObject, store: Store) -> None:
    if not store.is_admin(message.from_user.id):
        return
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Қолданылуы: <code>/deny 123456789</code>")
        return
    ok = await store.deny(int(arg))
    await message.answer("🚫 Рұқсат алынды." if ok else "Бұл ID тізімде жоқ.")


async def cmd_users(message: Message, store: Store) -> None:
    if not store.is_admin(message.from_user.id):
        return
    lines = [f"👑 <code>{a}</code> (иесі)" for a in store.admin_ids()]
    lines += [f"• <code>{uid}</code> {escape(name)}" for uid, name in (await store.users()).items()]
    await message.answer("👥 <b>Рұқсаты барлар</b>\n" + "\n".join(lines))


async def cmd_history(message: Message, store: Store) -> None:
    uid = message.from_user.id
    if not await store.is_allowed(uid):
        await message.answer(LOCKED.format(uid=uid))
        return
    await message.answer(history_text(await store.history(uid)))


# ---------------------------------------------------------------- PDF

def _analyze_file(path: str) -> dict:
    from salesreport.analysis import analyze
    from salesreport.parser import parse_report
    return analyze(parse_report(path))


def _html_name(A: dict, original: str) -> str:
    pf = A["meta"]["period_from"]
    if pf:
        return f"satylym_{pf:%Y-%m-%d}.html"
    stem = re.sub(r"[^\w\-]+", "_", Path(original).stem)[:40] or "report"
    return f"satylym_{stem}.html"


async def on_document(message: Message, bot: Bot, store: Store, cfg: Config) -> None:
    from salesreport.html_report import build_html
    from salesreport.parser import ReportParseError
    from salesreport.text_report import build_messages

    uid = message.from_user.id
    if not await store.is_allowed(uid):
        await message.answer(LOCKED.format(uid=uid))
        return
    doc = message.document
    fname = doc.file_name or "report.pdf"
    if not (fname.lower().endswith(".pdf") or doc.mime_type == "application/pdf"):
        await message.answer("Маған 1С есебінің <b>PDF</b> файлын жіберіңіз. Нұсқаулық: /help")
        return
    if doc.file_size and doc.file_size > cfg.max_file_mb * 1024 * 1024:
        await message.answer(f"Файл тым үлкен: Telegram ботқа {cfg.max_file_mb} МБ-қа дейінгі файлды ғана береді.")
        return

    status = await message.answer("⏳ Есепті оқып, есептеп жатырмын…")
    started = datetime.now()
    try:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "report.pdf"
            await bot.download(doc, destination=path)
            async with PARSE_SLOTS:
                A = await asyncio.to_thread(_analyze_file, str(path))
    except ReportParseError as exc:
        await safe_delete(status)
        await message.answer(PARSE_ERROR.format(err=escape(str(exc))))
        return
    except Exception:  # noqa: BLE001
        log.exception("Есепті өңдеу кезінде қате (%s)", fname)
        await safe_delete(status)
        await message.answer("❌ Күтпеген қате шықты. Файлды қайта жіберіп көріңіз немесе бот иесіне хабарлаңыз.")
        return

    snap = snapshot(A)
    past = await store.history(uid)
    prev = find_previous(past, snap)

    messages = build_messages(A)
    if prev:
        messages.insert(1, compare_text(snap, prev))
    html = build_html(A, compare=(snap, prev) if prev else None)

    await safe_delete(status)
    for text in messages:
        await send_text(message, text)
    await message.answer_document(
        BufferedInputFile(html.encode("utf-8"), filename=_html_name(A, fname)),
        caption="📎 Толық есеп — дашборд түрінде (браузерде ашылады).",
    )
    await store.put_history(uid, upsert(past, snap))
    log.info("Талданды: %s, %s, %d заказ, %.1f с", uid, fname, A["kpi"]["orders"],
             (datetime.now() - started).total_seconds())


async def on_photo(message: Message) -> None:
    await message.answer("Сурет емес, 1С-тан сақталған <b>PDF</b> файлды жіберіңіз. Нұсқаулық: /help")


async def on_other(message: Message, store: Store) -> None:
    uid = message.from_user.id if message.from_user else 0
    if not await store.is_allowed(uid):
        await message.answer(LOCKED.format(uid=uid))
        return
    await message.answer("📎 1С есебінің PDF файлын жіберіңіз — мен оны талдаймын. Нұсқаулық: /help")


# ---------------------------------------------------------------- run

def make_router() -> Router:
    r = Router()
    r.message.register(cmd_start, CommandStart())
    r.message.register(cmd_help, Command("help"))
    r.message.register(cmd_myid, Command("myid"))
    r.message.register(cmd_allow, Command("allow"))
    r.message.register(cmd_deny, Command("deny"))
    r.message.register(cmd_users, Command("users"))
    r.message.register(cmd_history, Command("history"))
    r.message.register(on_document, F.document)
    r.message.register(on_photo, F.photo)
    r.message.register(on_other)
    return r


def build_dispatcher(cfg: Config, bot: Bot) -> Dispatcher:
    dp = Dispatcher()
    dp["cfg"] = cfg
    dp["store"] = Store(bot, cfg)
    dp.update.outer_middleware(DropRepeats())
    dp.include_router(make_router())
    return dp


def setup_logging(cfg: Config) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(cfg.data_dir / "bot.log", encoding="utf-8")],
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)  # әр сұрауды журналға жазбаймыз


def webhook_secret(cfg: Config) -> str:
    return hashlib.sha256(f"salesbot-webhook:{cfg.token}".encode()).hexdigest()[:48]


def status_app(text_getter) -> web.Application:
    app = web.Application()

    async def status(_request):
        return web.Response(text=text_getter(), content_type="text/plain", charset="utf-8")

    app.router.add_get("/", status)
    app.router.add_get("/healthz", status)
    return app


async def serve_forever(app: web.Application, port: int) -> None:
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("HTTP сервер: порт %s", port)
    await asyncio.Event().wait()


def build_webhook_app(cfg: Config, bot: Bot, dp: Dispatcher, info: dict) -> web.Application:
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler

    app = status_app(lambda: info["status"])
    path = f"/tg/{webhook_secret(cfg)[:16]}"
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=webhook_secret(cfg)).register(app, path=path)
    info["path"] = path
    return app


async def prepare(bot: Bot, dp: Dispatcher, cfg: Config, info: dict) -> None:
    """Порт ашылғаннан кейін: токенді тексеру, командалар, webhook."""
    store: Store = dp["store"]
    delay = 5
    while True:
        try:
            me = await bot.get_me()
            break
        except TelegramUnauthorizedError:
            info["status"] = "BOT_TOKEN дұрыс емес — @BotFather берген токенді тексеріңіз."
            log.error(info["status"])
            return
        except Exception as exc:  # noqa: BLE001 — желі уақытша жоқ болса, қайталаймыз
            info["status"] = f"Telegram-ға қосылу мүмкін болмады, {delay} с кейін қайталаймын: {exc}"
            log.warning(info["status"])
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)
    try:
        await bot.set_my_commands(USER_COMMANDS)
        await set_admin_commands(bot, store)
        if cfg.public_url:
            await bot.set_webhook(cfg.public_url + info["path"], secret_token=webhook_secret(cfg),
                                  allowed_updates=dp.resolve_used_update_types(), drop_pending_updates=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("Telegram баптауы толық орындалмады: %s", exc)
    owner = "иесі: " + ", ".join(map(str, store.admin_ids())) if store.admin_ids() else "иесі әлі тағайындалмаған"
    info["status"] = f"Сатылым боты жұмыс істеп тұр: @{me.username} ({owner})"
    log.info("Бот іске қосылды: @%s, %s, режим: %s", me.username, owner, "webhook" if cfg.public_url else "polling")
    if not store.admin_ids():
        log.info("ADMIN_IDS бос: иесі болу үшін /start %s", "<OWNER_CODE>" if cfg.owner_code else "(бірінші жазған адам)")


async def main() -> None:
    cfg = load_config()
    setup_logging(cfg)

    if not cfg.token_ok:
        msg = "BOT_TOKEN орнатылмаған немесе дұрыс емес. @BotFather берген токенді BOT_TOKEN айнымалысына жазыңыз."
        if cfg.public_url:
            log.warning(msg)
            await serve_forever(status_app(lambda: msg), cfg.port)  # сервер «тірі» тұрады, токенді күтеді
            return
        raise SystemExit(msg)

    bot = Bot(cfg.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    dp = build_dispatcher(cfg, bot)
    info = {"status": "Бот іске қосылып жатыр…"}

    if cfg.public_url:
        app = build_webhook_app(cfg, bot, dp, info)
        info["task"] = asyncio.create_task(prepare(bot, dp, cfg, info))
        await serve_forever(app, cfg.port)
    else:
        await prepare(bot, dp, cfg, info)
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(exc.code)
