"""Generate prompts and precompute their answers (F-021).

uv run python -m jobs.generate_prompts

For every active template, try each candidate set of params, keep the prompts
whose answer count is within PROMPT_MIN_ANSWERS-PROMPT_MAX_ANSWERS, and store
their answers in ``prompt_answer`` with a ``base_rarity``. Run it after an
ingest; it is safe to re-run.
"""

import argparse
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import product
from string import Formatter
from typing import Any

from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Entity, Fact, Prompt, PromptAnswer, PromptTemplate
from app.services.prompt_templates import TEMPLATES, TemplateDef
from app.services.query_def import answer_select
from app.services.scoring import base_rarities

# Params that hold an entity id. Each is named after the entity's kind.
ENTITY_PARAMS = ("studio", "anime", "franchise")

# "a {genre} anime" must read "an Action anime".
_ARTICLE = re.compile(r"\b(a) \{(\w+)\}", re.IGNORECASE)


class GenerationError(ValueError):
    """A template names a param that generation has no values for."""


@dataclass(frozen=True)
class GenerationResult:
    candidates: int
    kept: int
    deactivated: int


def render_text(text: str, params: Mapping[str, Any], names: Mapping[int, str]) -> str:
    """Fill a template's ``{placeholders}``; entity params show the entity's name."""
    values = {
        name: names[value] if name in ENTITY_PARAMS else value for name, value in params.items()
    }

    def article(match: re.Match[str]) -> str:
        # Goes by the first letter, which is wrong for names such as "ufotable" and
        # "8bit", so no template puts an article before an entity name (tested).
        vowel = str(values.get(match[2], ""))[:1].lower() in tuple("aeiou")
        return f"{match[1]}n {{{match[2]}}}" if vowel else match[0]

    return _ARTICLE.sub(article, text).format_map(values)


def _text_params(text: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(text) if name}


def _query_params(node: Any) -> set[str]:
    """Every ``$name`` anywhere in a ``query_def``."""
    if isinstance(node, str):
        return {node[1:]} if node.startswith("$") else set()
    if isinstance(node, Mapping):
        return set().union(*(_query_params(value) for value in node.values()))
    if isinstance(node, Sequence):
        return set().union(*(_query_params(item) for item in node))
    return set()


@dataclass(frozen=True)
class _Catalogue:
    """What the data offers as param values, loaded once per run."""

    year: int  # the year of generation
    names: Mapping[int, str]  # canonical names of the entities a param can hold
    ids: Mapping[str, Sequence[int]]  # entity param -> entity ids
    values: Mapping[str, Sequence[str]]  # value predicate -> its distinct values
    first_year: int | None  # the earliest start_year of any anime

    @classmethod
    def load(cls, session: Session, year: int) -> "_Catalogue":
        names: dict[int, str] = {}
        ids: dict[str, list[int]] = {kind: [] for kind in ENTITY_PARAMS}
        entities = session.execute(
            select(Entity.id, Entity.kind, Entity.canonical_name)
            .where(Entity.kind.in_(ENTITY_PARAMS))
            .order_by(Entity.id)
        )
        for entity_id, kind, name in entities:
            names[entity_id] = name
            ids[kind].append(entity_id)
        values = {
            predicate: session.scalars(
                select(Fact.value)
                .where(Fact.predicate == predicate)
                .distinct()
                .order_by(Fact.value)
            ).all()
            for predicate in ("genre", "tag")
        }
        first_year = session.scalar(select(func.min(Entity.start_year)))
        return cls(year=year, names=names, ids=ids, values=values, first_year=first_year)

    def candidates(
        self, text: str, query_def: Mapping[str, Any], choices: Sequence[Mapping[str, Any]]
    ) -> Iterator[dict[str, Any]]:
        """Every set of params to try for a template: its choices x the data's values."""
        in_text = _text_params(text)
        free = (in_text | _query_params(query_def)) - set(choices[0] if choices else ())
        if "decade" in free:
            free -= {"from", "to"}  # they come with the decade
        sources = [self._source(name, name in in_text) for name in sorted(free)]
        for parts in product(choices or ({},), *sources):
            params: dict[str, Any] = {}
            for part in parts:
                params.update(part)
            # "Action and Comedy" and "Comedy and Action" are one prompt.
            if "genre2" in params and params["genre"] >= params["genre2"]:
                continue
            yield params

    def _source(self, name: str, in_text: bool) -> list[dict[str, Any]]:
        if name in ENTITY_PARAMS:
            return [{name: entity_id} for entity_id in self.ids[name]]
        if name in ("genre", "genre2"):
            return [{name: value} for value in self.values["genre"]]
        if name == "tag":
            return [{name: value} for value in self.values["tag"]]
        if name == "year":
            # A year the text does not show is the year of generation ("currently
            # airing", "ran for N+ years"); one it shows is every year so far.
            years = self._years(1) if in_text else [self.year]
            return [{"year": year} for year in years]
        if name == "decade":
            return [
                {"decade": decade, "from": decade, "to": decade + 9} for decade in self._years(10)
            ]
        raise GenerationError(f"no values for param {name!r}")

    def _years(self, step: int) -> range:
        """From the earliest anime to this year, in steps of ``step`` years."""
        if self.first_year is None:
            return range(0)
        return range(self.first_year // step * step, self.year + 1, step)


def _store_prompt(
    session: Session, template: PromptTemplate, params: Mapping[str, Any], text: str, answers: Any
) -> int:
    """Upsert a prompt and replace its answers, keeping ``times_answered``."""
    prompt = insert(Prompt).values(template_id=template.id, params=params, text=text, active=True)
    prompt_id: int = session.execute(
        prompt.on_conflict_do_update(
            index_elements=[Prompt.template_id, Prompt.params],
            set_={"text": prompt.excluded.text, "active": True},
        ).returning(Prompt.id)
    ).scalar_one()

    entity_ids = [entity_id for entity_id, _ in answers]
    rarities = base_rarities([popularity for _, popularity in answers])
    session.execute(
        delete(PromptAnswer).where(
            PromptAnswer.prompt_id == prompt_id, PromptAnswer.entity_id.not_in(entity_ids)
        )
    )
    answer = insert(PromptAnswer).values(
        [
            {"prompt_id": prompt_id, "entity_id": entity_id, "base_rarity": rarity}
            for entity_id, rarity in zip(entity_ids, rarities, strict=True)
        ]
    )
    session.execute(
        answer.on_conflict_do_update(
            index_elements=[PromptAnswer.prompt_id, PromptAnswer.entity_id],
            set_={"base_rarity": answer.excluded.base_rarity},
        )
    )
    return prompt_id


def generate_prompts(
    session: Session,
    *,
    today: date,
    min_answers: int,
    max_answers: int,
    templates: Sequence[TemplateDef] = TEMPLATES,
) -> GenerationResult:
    """Generate the prompts of ``templates`` as of ``today``. The caller commits.

    Only templates that are seeded and active are generated. Afterwards their
    active prompts are exactly the candidates whose answer count is in range:
    any other prompt of theirs is switched off (never deleted, since past
    puzzles may point at it) and keeps its answers as they were.
    """
    choices = {template.slug: template.choices for template in templates}
    rows = session.scalars(
        select(PromptTemplate)
        .where(PromptTemplate.active, PromptTemplate.slug.in_(choices))
        .order_by(PromptTemplate.id)
    ).all()
    catalogue = _Catalogue.load(session, today.year)

    candidates = 0
    kept: list[int] = []
    for row in rows:
        for params in catalogue.candidates(row.text, row.query_def, choices[row.slug]):
            candidates += 1
            answers = session.execute(
                answer_select(row.answer_kind, row.query_def, params).with_only_columns(
                    Entity.id, Entity.popularity
                )
            ).all()
            if min_answers <= len(answers) <= max_answers:
                text = render_text(row.text, params, catalogue.names)
                kept.append(_store_prompt(session, row, params, text, answers))

    deactivated = session.execute(
        update(Prompt)
        .where(
            Prompt.template_id.in_([row.id for row in rows]),
            Prompt.active,
            Prompt.id.not_in(kept),
        )
        .values(active=False)
    ).rowcount
    return GenerationResult(candidates=candidates, kept=len(kept), deactivated=deactivated)


def main(
    argv: Sequence[str] | None = None,
    *,
    session: Session | None = None,
    today: date | None = None,
) -> int:
    """Generate the prompts. ``session`` and ``today`` are injectable for tests."""
    argparse.ArgumentParser(prog="python -m jobs.generate_prompts", description=__doc__).parse_args(
        argv
    )
    settings = get_settings()

    def run(target: Session) -> GenerationResult:
        result = generate_prompts(
            target,
            today=today or datetime.now(UTC).date(),
            min_answers=settings.prompt_min_answers,
            max_answers=settings.prompt_max_answers,
        )
        target.commit()
        return result

    if session is not None:
        result = run(session)
    else:
        engine = create_engine(settings.sync_database_url)
        with Session(engine) as own_session:
            result = run(own_session)
        engine.dispose()

    print(
        f"{result.kept} prompts kept of {result.candidates} candidates; "
        f"{result.deactivated} switched off"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
