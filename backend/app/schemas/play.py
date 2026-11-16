"""Response bodies for playing a prompt (F-031)."""

from datetime import datetime

from pydantic import BaseModel


class PromptStart(BaseModel):
    """A served prompt. Never its answers."""

    position: int
    text: str
    # Server time. ``deadline`` is ``started_at`` plus the answer time limit, without the grace.
    started_at: datetime
    deadline: datetime
