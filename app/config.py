"""Settings. Every secret comes from the environment, never from the code."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set")
    return value


def _optional(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _ids(raw: str) -> frozenset[int]:
    try:
        return frozenset(int(part) for part in raw.replace(" ", "").split(",") if part)
    except ValueError as exc:
        raise ConfigError("ALLOWED_TELEGRAM_IDS must be numbers separated by commas") from exc


@dataclass(frozen=True)
class OneCSettings:
    odata_url: str
    user: str
    password: str
    timeout: float = 20.0
    item_catalog: str = "Номенклатура"
    article_field: str = "Артикул"
    unit_field: str = "ЕдиницаИзмерения____Presentation"
    warehouse_catalog: str = "Склады"
    stock_register: str = "ТоварыНаСкладах"
    item_dimension: str = "Номенклатура_Key"
    warehouse_dimension: str = "Склад_Key"
    quantity_field: str = "ВНаличииBalance"
    reserve_field: str = ""


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_id: int
    public_url: str
    allowed_ids: frozenset[int]
    init_data_max_age: int
    onec: OneCSettings

    @property
    def webhook_secret(self) -> str:
        return hashlib.sha256(f"webhook:{self.bot_token}".encode()).hexdigest()


def load_onec_settings() -> OneCSettings:
    load_dotenv()
    defaults = OneCSettings(odata_url="", user="", password="")
    password = os.environ.get("ONEC_PASSWORD", "")
    if not password:
        raise ConfigError("ONEC_PASSWORD is not set")
    return OneCSettings(
        odata_url=_required("ONEC_ODATA_URL").rstrip("/"),
        user=_required("ONEC_USER"),
        password=password,
        timeout=float(_optional("ONEC_TIMEOUT", str(defaults.timeout))),
        item_catalog=_optional("ONEC_ITEM_CATALOG", defaults.item_catalog),
        article_field=_optional("ONEC_ARTICLE_FIELD", defaults.article_field),
        unit_field=_optional("ONEC_UNIT_FIELD", defaults.unit_field),
        warehouse_catalog=_optional("ONEC_WAREHOUSE_CATALOG", defaults.warehouse_catalog),
        stock_register=_optional("ONEC_STOCK_REGISTER", defaults.stock_register),
        item_dimension=_optional("ONEC_ITEM_DIMENSION", defaults.item_dimension),
        warehouse_dimension=_optional("ONEC_WAREHOUSE_DIMENSION", defaults.warehouse_dimension),
        quantity_field=_optional("ONEC_QUANTITY_FIELD", defaults.quantity_field),
        reserve_field=_optional("ONEC_RESERVE_FIELD", defaults.reserve_field),
    )


BOT_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{30,}$")
REQUIRED = ("BOT_TOKEN", "ADMIN_TELEGRAM_ID", "ONEC_ODATA_URL", "ONEC_USER", "ONEC_PASSWORD")


def _public_url() -> str:
    """PUBLIC_URL wins when valid; on Render the service's own address is the fallback."""
    for name in ("PUBLIC_URL", "RENDER_EXTERNAL_URL"):
        value = os.environ.get(name, "").strip().rstrip("/")
        if value.startswith("https://"):
            return value
    return ""


def environment_problems() -> list[str]:
    """Every configuration problem at once, naming variables but never printing their values."""
    problems = [f"{name} is not set" for name in REQUIRED if not os.environ.get(name, "").strip()]
    token = os.environ.get("BOT_TOKEN", "").strip()
    if token and not BOT_TOKEN_RE.match(token):
        problems.append("BOT_TOKEN does not look like a token from @BotFather")
    admin = os.environ.get("ADMIN_TELEGRAM_ID", "").strip()
    if admin and not admin.isdigit():
        problems.append("ADMIN_TELEGRAM_ID must be a number")
    odata = os.environ.get("ONEC_ODATA_URL", "").strip()
    if odata and not odata.startswith("https://"):
        problems.append("ONEC_ODATA_URL must start with https://")
    if not _public_url():
        problems.append("PUBLIC_URL must start with https://")
    return problems


def load_settings() -> Settings:
    load_dotenv()
    problems = environment_problems()
    if problems:
        raise ConfigError("; ".join(problems))
    public_url = _public_url()
    try:
        admin_id = int(_required("ADMIN_TELEGRAM_ID"))
    except ValueError as exc:
        raise ConfigError("ADMIN_TELEGRAM_ID must be a number") from exc
    return Settings(
        bot_token=_required("BOT_TOKEN"),
        admin_id=admin_id,
        public_url=public_url,
        allowed_ids=_ids(_optional("ALLOWED_TELEGRAM_IDS", "")),
        init_data_max_age=int(_optional("INIT_DATA_MAX_AGE", "86400")),
        onec=load_onec_settings(),
    )
