"""Pick the prompts of a day's puzzle (F-022).

uv run python -m jobs.generate_daily [--date YYYY-MM-DD] [--days N]

Each day gets PUZZLE_SIZE active prompts, at most MAX_PER_TEMPLATE of them from
one template, none of them used within PROMPT_REPEAT_WINDOW_DAYS days. The pick
depends only on the date, PUZZLE_SEED and the prompts available. A day that
already has a puzzle is left alone, so the job is safe to re-run. Run it after
``jobs.generate_prompts``.
"""

import argparse
import random
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, exists, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DailyPuzzle, Prompt, PromptTemplate

PUZZLE_SIZE = 7
MAX_PER_TEMPLATE = 2


class NotEnoughPromptsError(RuntimeError):
    """Too few usable prompts to fill a day's puzzle."""


def generate_daily(session: Session, day: date, *, seed: str, repeat_window_days: int) -> bool:
    """Create ``day``'s puzzle unless it has one. The caller commits.

    Returns whether a puzzle was created. A prompt used on some day cannot be
    used again until ``repeat_window_days`` full days lie between the two; the
    window is checked in both directions so that backfilling a past day works.
    Raises NotEnoughPromptsError, writing nothing, if the day cannot be filled.
    """
    if session.scalar(select(exists().where(DailyPuzzle.day == day))):
        return False

    window = timedelta(days=repeat_window_days)
    recently_used = select(DailyPuzzle.prompt_id).where(
        DailyPuzzle.day.between(day - window, day + window)
    )
    rows = session.execute(
        select(Prompt.template_id, Prompt.id)
        .join(PromptTemplate, PromptTemplate.id == Prompt.template_id)
        .where(Prompt.active, PromptTemplate.active, Prompt.id.not_in(recently_used))
        .order_by(Prompt.template_id, Prompt.id)
    )
    available: dict[int, list[int]] = {}
    for template_id, prompt_id in rows:
        available.setdefault(template_id, []).append(prompt_id)

    # Pick a template first and then one of its prompts, so that a template
    # with hundreds of prompts (tags) does not crowd out one with a dozen.
    rng = random.Random(f"{seed}:{day.isoformat()}")
    uses: Counter[int] = Counter()
    picked: list[int] = []
    while len(picked) < PUZZLE_SIZE:
        open_templates = [
            template_id
            for template_id, prompt_ids in available.items()
            if prompt_ids and uses[template_id] < MAX_PER_TEMPLATE
        ]
        if not open_templates:
            raise NotEnoughPromptsError(
                f"{day}: only {len(picked)} of {PUZZLE_SIZE} prompts can be picked"
            )
        template_id = rng.choice(open_templates)
        prompt_ids = available[template_id]
        picked.append(prompt_ids.pop(rng.randrange(len(prompt_ids))))
        uses[template_id] += 1

    session.add_all(
        DailyPuzzle(day=day, position=position, prompt_id=prompt_id)
        for position, prompt_id in enumerate(picked, start=1)
    )
    session.flush()
    return True


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def main(
    argv: Sequence[str] | None = None,
    *,
    session: Session | None = None,
    today: date | None = None,
) -> int:
    """Generate the puzzles. ``session`` and ``today`` are injectable for tests."""
    parser = argparse.ArgumentParser(prog="python -m jobs.generate_daily", description=__doc__)
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="first day to generate (default: today, UTC)",
    )
    parser.add_argument(
        "--days",
        type=_positive_int,
        default=1,
        metavar="N",
        help="number of consecutive days to generate (default: 1)",
    )
    args = parser.parse_args(argv)
    first: date = args.date or today or datetime.now(UTC).date()
    settings = get_settings()

    def run(target: Session) -> int:
        """Commit day by day, so the days before a failure are kept."""
        generated = 0
        for offset in range(args.days):
            day = first + timedelta(days=offset)
            try:
                created = generate_daily(
                    target,
                    day,
                    seed=settings.puzzle_seed,
                    repeat_window_days=settings.prompt_repeat_window_days,
                )
            except NotEnoughPromptsError as error:
                print(f"error: {error}", file=sys.stderr)
                return 1
            target.commit()
            generated += created
            print(f"{day}: {'generated' if created else 'already has a puzzle'}")
        print(f"{generated} puzzles generated; {args.days - generated} already existed")
        return 0

    if session is not None:
        return run(session)
    engine = create_engine(settings.sync_database_url)
    try:
        with Session(engine) as own_session:
            return run(own_session)
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
