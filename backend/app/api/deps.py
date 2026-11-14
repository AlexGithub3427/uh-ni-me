"""Dependencies shared by the API routers."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie

# The anonymous player's id (F-034).
PLAYER_COOKIE = "player_id"


def get_now() -> datetime:
    """The current time. Injected, so tests can set the clock."""
    return datetime.now(UTC)


def get_player_id(
    cookie: Annotated[str | None, Cookie(alias=PLAYER_COOKIE)] = None,
) -> uuid.UUID | None:
    """The player id in the cookie, or None when it is missing or malformed.

    TODO(F-034): create the ``player`` row and set the cookie on first visit.
    """
    if cookie is None:
        return None
    try:
        return uuid.UUID(cookie)
    except ValueError:
        return None
