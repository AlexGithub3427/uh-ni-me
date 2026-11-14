"""The daily puzzle job (F-022)."""

from collections import Counter
from datetime import date, timedelta

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DailyPuzzle, Prompt, PromptTemplate
from jobs.generate_daily import (
    MAX_PER_TEMPLATE,
    PUZZLE_SIZE,
    NotEnoughPromptsError,
    generate_daily,
    main,
)

DAY = date(2026, 6, 1)
SEED = "test-seed"


def make_template(
    session: Session, slug: str, prompt_count: int, *, active: bool = True
) -> PromptTemplate:
    """A template with ``prompt_count`` active prompts."""
    template = PromptTemplate(
        slug=slug, text=f"{slug} {{n}}", answer_kind="anime", query_def={}, active=active
    )
    session.add(template)
    session.flush()
    session.add_all(
        Prompt(template_id=template.id, params={"n": n}, text=f"{slug} {n}")
        for n in range(prompt_count)
    )
    session.flush()
    return template


def make_templates(session: Session, count: int, prompt_count: int) -> list[PromptTemplate]:
    return [make_template(session, f"template-{n}", prompt_count) for n in range(count)]


def generate(session: Session, day: date = DAY, *, seed: str = SEED, window: int = 60) -> bool:
    return generate_daily(session, day, seed=seed, repeat_window_days=window)


def puzzle(session: Session, day: date = DAY) -> list[int]:
    """The day's prompt ids in position order."""
    return list(
        session.scalars(
            select(DailyPuzzle.prompt_id)
            .where(DailyPuzzle.day == day)
            .order_by(DailyPuzzle.position)
        )
    )


def puzzle_days(session: Session) -> list[date]:
    return list(session.scalars(select(DailyPuzzle.day).distinct().order_by(DailyPuzzle.day)))


def clear(session: Session) -> None:
    session.execute(delete(DailyPuzzle))


# --- picking ------------------------------------------------------------------


def test_f022_picks_seven_prompts_at_positions_1_to_7(db_session: Session) -> None:
    make_templates(db_session, 5, 10)

    assert generate(db_session) is True

    positions = db_session.scalars(
        select(DailyPuzzle.position).where(DailyPuzzle.day == DAY).order_by(DailyPuzzle.position)
    ).all()
    assert positions == [1, 2, 3, 4, 5, 6, 7]
    assert len(set(puzzle(db_session))) == PUZZLE_SIZE == 7


def test_f022_no_template_appears_more_than_twice_in_one_day(db_session: Session) -> None:
    # One template holds nearly all the prompts, so a pick that ignored
    # templates would use it for most of the day.
    make_template(db_session, "huge", 500)
    make_templates(db_session, 5, 3)
    template_of = dict(db_session.execute(select(Prompt.id, Prompt.template_id)).all())

    for offset in range(20):
        day = DAY + timedelta(days=offset)
        assert generate(db_session, day, window=0) is True
        per_template = Counter(template_of[prompt_id] for prompt_id in puzzle(db_session, day))
        assert max(per_template.values()) <= MAX_PER_TEMPLATE == 2


def test_f022_four_templates_are_enough_for_a_day(db_session: Session) -> None:
    make_templates(db_session, 4, 2)

    assert generate(db_session) is True

    assert len(puzzle(db_session)) == 7


def test_f022_too_few_templates_raises_and_writes_nothing(db_session: Session) -> None:
    # Three templates give at most six prompts, however many prompts they have.
    make_templates(db_session, 3, 50)

    with pytest.raises(NotEnoughPromptsError):
        generate(db_session)

    assert puzzle(db_session) == []


def test_f022_never_picks_inactive_prompts_or_templates(db_session: Session) -> None:
    make_templates(db_session, 4, 2)
    switched_off = make_template(db_session, "half-off", 40)
    make_template(db_session, "inactive-template", 40, active=False)
    db_session.execute(
        update(Prompt)
        .where(Prompt.template_id == switched_off.id, Prompt.params["n"].as_integer() > 0)
        .values(active=False)
    )
    allowed = set(
        db_session.scalars(
            select(Prompt.id)
            .join(PromptTemplate, PromptTemplate.id == Prompt.template_id)
            .where(Prompt.active, PromptTemplate.active)
        )
    )
    assert len(allowed) == 9

    for offset in range(10):
        day = DAY + timedelta(days=offset)
        generate(db_session, day, window=0)
        assert set(puzzle(db_session, day)) <= allowed


# --- no repeats ---------------------------------------------------------------


def test_f022_no_prompt_repeats_within_60_days(db_session: Session) -> None:
    make_templates(db_session, 8, 100)

    days = [DAY + timedelta(days=offset) for offset in range(61)]
    for day in days:
        assert generate(db_session, day) is True

    used = [prompt_id for day in days for prompt_id in puzzle(db_session, day)]
    assert len(used) == 61 * 7
    assert len(set(used)) == len(used)


def test_f022_prompt_may_return_on_day_61_but_not_day_60(db_session: Session) -> None:
    # Eight prompts in all: once a day has used seven, no day inside the window
    # can be filled.
    make_templates(db_session, 4, 2)
    generate(db_session, DAY)

    with pytest.raises(NotEnoughPromptsError):
        generate(db_session, DAY + timedelta(days=60))
    assert generate(db_session, DAY + timedelta(days=61)) is True


def test_f022_repeat_window_also_looks_ahead_when_backfilling(db_session: Session) -> None:
    make_templates(db_session, 4, 2)
    generate(db_session, DAY)

    with pytest.raises(NotEnoughPromptsError):
        generate(db_session, DAY - timedelta(days=60))
    assert generate(db_session, DAY - timedelta(days=61)) is True


# --- determinism --------------------------------------------------------------


def test_f022_same_date_and_seed_give_the_same_puzzle(db_session: Session) -> None:
    make_templates(db_session, 8, 100)
    generate(db_session)
    first = puzzle(db_session)
    clear(db_session)

    generate(db_session)

    assert puzzle(db_session) == first


def test_f022_another_seed_gives_another_puzzle(db_session: Session) -> None:
    make_templates(db_session, 8, 100)
    generate(db_session, seed="one")
    first = puzzle(db_session)
    clear(db_session)

    generate(db_session, seed="two")

    assert puzzle(db_session) != first


def test_f022_another_date_gives_another_puzzle(db_session: Session) -> None:
    make_templates(db_session, 8, 100)
    generate(db_session, DAY)
    first = puzzle(db_session, DAY)
    clear(db_session)

    other = DAY + timedelta(days=1)
    generate(db_session, other)

    assert puzzle(db_session, other) != first


# --- re-running ---------------------------------------------------------------


def test_f022_rerunning_for_a_date_with_a_puzzle_is_a_noop(db_session: Session) -> None:
    make_templates(db_session, 8, 100)
    generate(db_session)
    first = puzzle(db_session)

    # Even a new seed must not touch a day that players may have started.
    assert generate(db_session, seed="another seed") is False

    assert puzzle(db_session) == first
    assert db_session.scalar(select(func.count()).select_from(DailyPuzzle)) == 7


# --- the command line ---------------------------------------------------------


def test_f022_cli_generates_the_given_date(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    make_templates(db_session, 8, 100)

    assert main(["--date", "2026-07-04"], session=db_session, today=DAY) == 0

    assert puzzle_days(db_session) == [date(2026, 7, 4)]
    assert len(puzzle(db_session, date(2026, 7, 4))) == 7
    assert "2026-07-04" in capsys.readouterr().out


def test_f022_cli_date_defaults_to_today(db_session: Session) -> None:
    make_templates(db_session, 8, 100)

    assert main([], session=db_session, today=DAY) == 0

    assert puzzle_days(db_session) == [DAY]


def test_f022_cli_uses_puzzle_seed_and_repeat_window_from_settings(db_session: Session) -> None:
    make_templates(db_session, 8, 100)
    settings = get_settings()
    generate(db_session, seed=settings.puzzle_seed, window=settings.prompt_repeat_window_days)
    expected = puzzle(db_session)
    clear(db_session)

    main([], session=db_session, today=DAY)

    assert puzzle(db_session) == expected


def test_f022_cli_days_generates_consecutive_days(db_session: Session) -> None:
    make_templates(db_session, 8, 100)

    assert main(["--date", "2026-06-29", "--days", "3"], session=db_session, today=DAY) == 0

    days = [date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 1)]
    assert puzzle_days(db_session) == days
    used = [prompt_id for day in days for prompt_id in puzzle(db_session, day)]
    assert len(set(used)) == 3 * 7


def test_f022_cli_days_skips_days_that_already_have_a_puzzle(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    make_templates(db_session, 8, 100)
    main(["--days", "2"], session=db_session, today=DAY)
    existing = {day: puzzle(db_session, day) for day in puzzle_days(db_session)}
    capsys.readouterr()

    # The nightly run: one day later, a week ahead.
    tomorrow = DAY + timedelta(days=1)
    assert main(["--days", "7"], session=db_session, today=tomorrow) == 0

    assert puzzle_days(db_session) == [DAY + timedelta(days=offset) for offset in range(8)]
    for day, prompt_ids in existing.items():
        assert puzzle(db_session, day) == prompt_ids
    out = capsys.readouterr().out
    assert "6 puzzles generated" in out
    assert "1 already existed" in out


def test_f022_cli_fails_when_prompts_run_out_and_keeps_earlier_days(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    make_templates(db_session, 4, 2)  # enough for one day only

    assert main(["--days", "3"], session=db_session, today=DAY) == 1

    assert puzzle_days(db_session) == [DAY]
    assert "2026-06-02" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["--days", "0"], ["--days", "-1"], ["--date", "June 1st"]])
def test_f022_cli_rejects_bad_arguments(db_session: Session, argv: list[str]) -> None:
    make_templates(db_session, 8, 100)

    with pytest.raises(SystemExit):
        main(argv, session=db_session, today=DAY)

    assert puzzle_days(db_session) == []
