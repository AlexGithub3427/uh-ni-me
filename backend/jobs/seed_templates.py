"""Seed the prompt templates (F-020) into ``prompt_template``.

uv run python -m jobs.seed_templates
"""

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PromptTemplate
from app.services.prompt_templates import TEMPLATES


def seed_templates(session: Session) -> int:
    """Upsert every template by slug and return how many. The caller commits.

    ``active`` is left alone on existing rows, so a template that was switched
    off stays off. Rows for templates no longer in the list are left in place,
    since prompts may still point at them.
    """
    statement = insert(PromptTemplate).values(
        [
            {
                "slug": template.slug,
                "text": template.text,
                "answer_kind": template.answer_kind,
                "query_def": template.query_def,
            }
            for template in TEMPLATES
        ]
    )
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[PromptTemplate.slug],
            set_={
                "text": statement.excluded.text,
                "answer_kind": statement.excluded.answer_kind,
                "query_def": statement.excluded.query_def,
            },
        )
    )
    return len(TEMPLATES)


def main(argv: Sequence[str] | None = None, *, session: Session | None = None) -> int:
    """Seed the templates. ``session`` is injectable for tests."""
    argparse.ArgumentParser(prog="python -m jobs.seed_templates", description=__doc__).parse_args(
        argv
    )

    if session is not None:
        count = seed_templates(session)
        session.commit()
    else:
        engine = create_engine(get_settings().sync_database_url)
        with Session(engine) as own_session:
            count = seed_templates(own_session)
            own_session.commit()
        engine.dispose()

    print(f"Seeded {count} prompt templates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
