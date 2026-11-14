"""The prompt query interpreter (F-020).

Turns a template's ``query_def`` plus a prompt's params into one SELECT over
``entity`` and ``fact``. Every question type goes through here; there is no
per-template query code. The condition types are specified in FEATURES.md
under F-020.

``answer_select`` only builds the statement, so the batch jobs (sync sessions)
and the API (async sessions) can both run it.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import ColumnElement, Select, exists, func, select
from sqlalchemy.orm import aliased

from app.models import ENTITY_KINDS, Entity, Fact

# Predicates whose facts point at another entity, and those that hold a literal.
OBJECT_PREDICATES = frozenset({"produced_by", "appears_in"})
VALUE_PREDICATES = frozenset({"format", "genre", "tag", "source_material"})

FIELDS = frozenset({"start_year", "end_year", "score", "episodes", "franchise_id"})
OPERATORS = frozenset({"eq", "between", "gte", "lte", "is_null"})
RANKINGS = frozenset({"popularity", "score"})

# Where a condition list sits: the top-level ``where``, or nested in a condition.
_WHERE = "where"
_WITHIN = "within"
_OBJECT_WHERE = "object_where"


class QueryDefError(ValueError):
    """A ``query_def`` (or the params given to it) is not valid."""


def answer_select(
    answer_kind: str, query_def: Mapping[str, Any], params: Mapping[str, Any]
) -> Select[tuple[Entity]]:
    """The answers to a prompt: a SELECT of ``Entity`` rows, most popular first.

    Raises ``QueryDefError`` if the ``query_def`` is malformed or a ``$param``
    is missing, without touching the database.
    """
    if answer_kind not in ENTITY_KINDS:
        raise QueryDefError(f"unknown answer_kind {answer_kind!r}")
    if not isinstance(query_def, Mapping) or "where" not in query_def:
        raise QueryDefError("a query_def needs a 'where' list")

    compiler = _Compiler(answer_kind, params)
    conditions = compiler.condition_list(query_def["where"], _WHERE)
    if answer_kind == "franchise":
        clauses = compiler.franchise_clauses(conditions)
    else:
        clauses = [compiler.condition(condition, Entity, _WHERE) for condition in conditions]
    return (
        select(Entity)
        .where(Entity.kind == answer_kind, *clauses)
        .order_by(Entity.popularity.desc(), Entity.id)
    )


class _Compiler:
    """Compiles conditions into SQL expressions about a target entity."""

    def __init__(self, answer_kind: str, params: Mapping[str, Any]) -> None:
        self.answer_kind = answer_kind
        self.params = params

    # --- values -------------------------------------------------------------

    def resolve(self, value: Any) -> Any:
        """Replace ``"$name"`` with that prompt param."""
        if isinstance(value, str) and value.startswith("$"):
            name = value[1:]
            if name not in self.params:
                raise QueryDefError(f"missing param {name!r}")
            return self.params[name]
        return value

    def integer(self, value: Any, what: str) -> int:
        resolved = self.resolve(value)
        if isinstance(resolved, bool) or not isinstance(resolved, int):
            raise QueryDefError(f"{what} must be an integer, got {resolved!r}")
        return resolved

    def pair(self, value: Any, what: str) -> tuple[int, int]:
        if not isinstance(value, Sequence) or isinstance(value, str) or len(value) != 2:
            raise QueryDefError(f"{what} must be a [from, to] pair, got {value!r}")
        return self.integer(value[0], what), self.integer(value[1], what)

    def condition_list(self, value: Any, context: str) -> Sequence[Any]:
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise QueryDefError(f"{context} must be a list of conditions, got {value!r}")
        return value

    # --- conditions ---------------------------------------------------------

    def condition(self, condition: Any, target: Any, context: str) -> ColumnElement[bool]:
        """One condition as a SQL expression about ``target`` (``Entity`` or an alias)."""
        if not isinstance(condition, Mapping):
            raise QueryDefError(f"a condition must be an object, got {condition!r}")
        keys = set(condition)
        if "predicate" in keys and len(keys) == 2:
            return self._fact(condition, target, context)
        if "field" in keys:
            return self._field(condition, target)
        if keys == {"airing_between"}:
            return self._airing_between(condition, target)
        if keys == {"ran_for", "as_of"}:
            return self._ran_for(condition, target)
        if keys in ({"top", "by"}, {"top", "by", "within"}):
            return self._top(condition, target, context)
        if keys == {"min_members"}:
            # With franchise answers, franchise_clauses handles it before it gets here.
            if context != _WHERE:
                raise QueryDefError(f"min_members is not allowed inside {context}")
            raise QueryDefError("min_members is only valid when answer_kind is 'franchise'")
        raise QueryDefError(f"unknown condition type: {dict(condition)!r}")

    def franchise_clauses(self, conditions: Sequence[Any]) -> list[ColumnElement[bool]]:
        """Clauses about a franchise ``Entity``: its size, and what one member satisfies."""
        clauses: list[ColumnElement[bool]] = []
        member = aliased(Entity)
        member_clauses: list[ColumnElement[bool]] = []
        for condition in conditions:
            if isinstance(condition, Mapping) and set(condition) == {"min_members"}:
                counted = aliased(Entity)
                size = (
                    select(func.count()).where(counted.franchise_id == Entity.id).scalar_subquery()
                )
                clauses.append(size >= self.integer(condition["min_members"], "min_members"))
            else:
                member_clauses.append(self.condition(condition, member, _WHERE))
        if member_clauses:
            # At least one member anime satisfies every condition.
            clauses.append(exists().where(member.franchise_id == Entity.id, *member_clauses))
        return clauses

    def _fact(self, condition: Mapping[str, Any], target: Any, context: str) -> ColumnElement[bool]:
        predicate = condition["predicate"]
        (matcher,) = set(condition) - {"predicate"}
        if matcher not in ("object", "value", "object_where"):
            raise QueryDefError(f"unknown condition type: {dict(condition)!r}")
        if predicate not in OBJECT_PREDICATES | VALUE_PREDICATES:
            raise QueryDefError(f"unknown predicate {predicate!r}")

        # Facts are existence checks: two sources may assert the same one (F-002).
        fact = aliased(Fact)
        found = exists().where(fact.subject_id == target.id, fact.predicate == predicate)

        if matcher == "value":
            if predicate not in VALUE_PREDICATES:
                raise QueryDefError(f"predicate {predicate!r} takes an object, not a value")
            value = self.resolve(condition["value"])
            if not isinstance(value, str):
                raise QueryDefError(f"{predicate} value must be a string, got {value!r}")
            return found.where(fact.value == value)

        if predicate not in OBJECT_PREDICATES:
            raise QueryDefError(f"predicate {predicate!r} takes a value, not an object")
        if matcher == "object":
            object_id = self.integer(condition["object"], f"{predicate} object")
            return found.where(fact.object_id == object_id)

        if context == _OBJECT_WHERE:
            raise QueryDefError("object_where is not allowed inside object_where")
        nested = self.condition_list(condition["object_where"], _OBJECT_WHERE)
        object = aliased(Entity)
        return found.where(
            object.id == fact.object_id,
            *[self.condition(inner, object, _OBJECT_WHERE) for inner in nested],
        )

    def _field(self, condition: Mapping[str, Any], target: Any) -> ColumnElement[bool]:
        name = condition["field"]
        if name not in FIELDS:
            raise QueryDefError(f"unknown field {name!r}")
        operators = set(condition) - {"field"}
        if len(operators) != 1:
            raise QueryDefError(f"a field condition takes exactly one operator: {condition!r}")
        (operator,) = operators
        if operator not in OPERATORS:
            raise QueryDefError(f"unknown operator {operator!r}")
        if name == "franchise_id" and operator != "eq":
            raise QueryDefError("field 'franchise_id' takes 'eq' only")

        # A NULL column makes every comparison NULL, so it fails them all.
        column = getattr(target, name)
        operand = condition[operator]
        what = f"{name} {operator}"
        if operator == "eq":
            return column == self.integer(operand, what)
        if operator == "gte":
            return column >= self.integer(operand, what)
        if operator == "lte":
            return column <= self.integer(operand, what)
        if operator == "between":
            low, high = self.pair(operand, what)
            return column.between(low, high)
        is_null = self.resolve(operand)
        if not isinstance(is_null, bool):
            raise QueryDefError(f"{what} must be true or false, got {is_null!r}")
        return column.is_(None) if is_null else column.is_not(None)

    def _airing_between(self, condition: Mapping[str, Any], target: Any) -> ColumnElement[bool]:
        first, last = self.pair(condition["airing_between"], "airing_between")
        return (target.start_year <= last) & (
            (target.end_year >= first) | target.end_year.is_(None)
        )

    def _ran_for(self, condition: Mapping[str, Any], target: Any) -> ColumnElement[bool]:
        years = self.integer(condition["ran_for"], "ran_for")
        as_of = self.integer(condition["as_of"], "as_of")
        # as_of stands in for the end of an anime that is still airing.
        return func.coalesce(target.end_year, as_of) - target.start_year >= years

    def _top(self, condition: Mapping[str, Any], target: Any, context: str) -> ColumnElement[bool]:
        if context != _WHERE:
            raise QueryDefError(f"top is not allowed inside {context}")
        if self.answer_kind == "franchise":
            # F-020 does not say whether this would rank franchises or their members.
            raise QueryDefError("top is not supported when answer_kind is 'franchise'")
        by = condition["by"]
        if by not in RANKINGS:
            raise QueryDefError(f"unknown ranking {by!r}")
        limit = self.integer(condition["top"], "top")

        # The ranking covers the whole answer kind (or the part of it that
        # satisfies ``within``), whatever the other conditions say.
        ranked = aliased(Entity)
        within = self.condition_list(condition.get("within", []), _WITHIN)
        rank_by = getattr(ranked, by)
        top_ids = (
            select(ranked.id)
            .where(
                ranked.kind == self.answer_kind,
                rank_by.is_not(None),
                *[self.condition(inner, ranked, _WITHIN) for inner in within],
            )
            .order_by(rank_by.desc(), ranked.popularity.desc(), ranked.id)
            .limit(limit)
        )
        return target.id.in_(top_ids)
