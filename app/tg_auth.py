"""Checks that a request really comes from Telegram, using the Mini App initData."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class InitDataError(Exception):
    pass


@dataclass(frozen=True)
class TgUser:
    id: int
    first_name: str


def verify_init_data(init_data: str, bot_token: str, max_age: int, now: float | None = None) -> TgUser:
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise InitDataError("malformed") from exc

    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise InitDataError("duplicate fields")

    received = fields.pop("hash", None)
    if not received:
        raise InitDataError("no hash")

    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise InitDataError("bad hash")

    current = time.time() if now is None else now
    try:
        auth_date = int(fields["auth_date"])
        user = json.loads(fields["user"])
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InitDataError("incomplete") from exc

    if current - auth_date > max_age or auth_date - current > 60:
        raise InitDataError("expired")
    return TgUser(id=user_id, first_name=str(user.get("first_name", "")))
