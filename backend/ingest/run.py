"""Ingest CLI (F-011): fetch source records and upsert them into the knowledge graph.

uv run python -m ingest.run --source anilist --limit 100
"""

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from ingest.anilist import AniListClient
from ingest.normalizer import upsert_anilist

SOURCES = ("anilist",)


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m ingest.run", description=__doc__)
    parser.add_argument("--source", required=True, choices=SOURCES)
    parser.add_argument(
        "--limit",
        required=True,
        type=_positive_int,
        help="how many anime to ingest, most popular first",
    )
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    client: AniListClient | None = None,
    session: Session | None = None,
) -> int:
    """Run one ingest. ``client`` and ``session`` are injectable for tests."""
    args = _parse_args(argv)

    records = (client or AniListClient.from_settings()).fetch_top_anime(args.limit)

    if session is not None:
        upsert_anilist(session, records)
        session.commit()
    else:
        engine = create_engine(get_settings().sync_database_url)
        with Session(engine) as own_session:
            upsert_anilist(own_session, records)
            own_session.commit()
        engine.dispose()

    print(f"Ingested {len(records)} anime from {args.source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
