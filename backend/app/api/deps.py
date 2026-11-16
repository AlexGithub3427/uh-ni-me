"""Dependencies shared by the API routers."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie

# The anonymous player's id (F-034).
PLAYER_COOKIE = "player_id"
# 400 days, the longest lifetime browsers keep a cookie for.
PLAYER_COOKIE_MAX_AGE = 400 * 24 * 60 * 60


def get_now() -> datetime:
    """The current time. Injected, so tests can set the clock."""
    return datetime.now(UTC)


def get_player_id(
    cookie: Annotated[str | None, Cookie(alias=PLAYER_COOKIE)] = None,
) -> uuid.UUID | None:
    """The player id in the cookie, or None when it is missing or malformed.

    Read-only: the player is created, and the cookie set, when prompt 1 is started (F-034).
    """
    if cookie is None:
        return None
    try:
        return uuid.UUID(cookie)
    except ValueError:
        return None
