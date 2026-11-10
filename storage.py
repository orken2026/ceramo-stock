"""Баптаулар (.env немесе сервердің айнымалылары)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{30,}$")


@dataclass
class Config:
    token: str                      # бос болуы мүмкін (серверде токенсіз тек күй беті ашылады)
    admin_ids: list = field(default_factory=list)  # реті маңызды: біріншісінің чатында жады сақталады
    owner_code: str = ""            # иесі болу үшін құпия сілтеме коды (/start КОД)
    public_url: str = ""            # бос болса — polling, бар болса — webhook
    port: int = 8080
    data_dir: Path = Path("data")
    max_file_mb: int = 20

    @property
    def token_ok(self) -> bool:
        return bool(TOKEN_RE.match(self.token))


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    admins = []
    for x in re.split(r"[,;\s]+", os.getenv("ADMIN_IDS", "")):
        if x.strip().isdigit() and int(x) not in admins:
            admins.append(int(x))
    public = ""
    for name in ("PUBLIC_URL", "RENDER_EXTERNAL_URL"):
        v = os.getenv(name, "").strip().rstrip("/")
        if v.startswith("https://"):
            public = v
            break
    data_dir = Path(os.getenv("DATA_DIR", "data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return Config(
        token=token,
        admin_ids=admins,
        owner_code=os.getenv("OWNER_CODE", "").strip(),
        public_url=public,
        port=int(os.getenv("PORT", "8080") or 8080),
        data_dir=data_dir,
    )
