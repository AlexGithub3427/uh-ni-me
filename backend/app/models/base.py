"""Declarative base shared by the API (async) and the batch scripts (sync)."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, MetaData, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit names, so tests and error handlers can tell which constraint fired.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {str: Text, datetime: DateTime(timezone=True)}


def identity_pk() -> Mapped[int]:
    """A ``bigint GENERATED ALWAYS AS IDENTITY`` primary key."""
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


def check_in(column: str, allowed: tuple[str, ...]) -> CheckConstraint:
    """``text`` + ``CHECK`` in place of a Postgres enum."""
    values = ", ".join(f"'{value}'" for value in allowed)
    return CheckConstraint(f"{column} IN ({values})", name=column)
