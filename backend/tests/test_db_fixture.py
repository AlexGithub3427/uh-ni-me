from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings


def _scratch_table_exists(db_session: Session) -> bool:
    return db_session.execute(text("SELECT to_regclass('f001_scratch')")).scalar() is not None


def test_f001_db_session_uses_the_test_database(db_session: Session) -> None:
    name = db_session.execute(text("SELECT current_database()")).scalar()

    assert name == get_settings().test_database_url.rsplit("/", 1)[-1]
    assert name != get_settings().database_url.rsplit("/", 1)[-1]


def test_f001_test_database_is_migrated_and_has_pg_trgm(db_session: Session) -> None:
    assert db_session.execute(text("SELECT to_regclass('alembic_version')")).scalar() is not None
    assert db_session.execute(text("SELECT similarity('naruto', 'narutp')")).scalar() > 0


# The next two tests each write the same table and check it wasn't there first.
# Whichever runs second fails unless the first one was rolled back, even if the
# test commits.
def test_f001_changes_are_rolled_back_after_each_test_a(db_session: Session) -> None:
    assert not _scratch_table_exists(db_session)
    db_session.execute(text("CREATE TABLE f001_scratch (id int)"))
    db_session.commit()
    assert _scratch_table_exists(db_session)


def test_f001_changes_are_rolled_back_after_each_test_b(db_session: Session) -> None:
    assert not _scratch_table_exists(db_session)
    db_session.execute(text("CREATE TABLE f001_scratch (id int)"))
    db_session.commit()
    assert _scratch_table_exists(db_session)
