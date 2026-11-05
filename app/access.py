"""Who may open the Mini App. Only the admin changes this list, through the bot.

The list lives in memory. The bot keeps a durable copy in a pinned message in
the admin's chat, because free hosting wipes local files on every restart.
"""
from __future__ import annotations


class AccessList:
    def __init__(self, admin_id: int, permanent_ids: frozenset[int] = frozenset()):
        self.admin_id = admin_id
        self.permanent_ids = permanent_ids
        self.loaded = False
        self._ids: set[int] = set()

    def replace(self, ids: set[int]) -> None:
        self._ids = set(ids)
        self.loaded = True

    def is_allowed(self, user_id: int) -> bool:
        return user_id == self.admin_id or user_id in self.permanent_ids or user_id in self._ids

    def add(self, user_id: int) -> None:
        self._ids.add(user_id)

    def remove(self, user_id: int) -> bool:
        """Returns False when the id was not in the bot-managed list."""
        if user_id not in self._ids:
            return False
        self._ids.remove(user_id)
        return True

    def managed_ids(self) -> list[int]:
        return sorted(self._ids)
