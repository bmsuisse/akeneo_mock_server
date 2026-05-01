import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlglot import Expr
from fastapi import HTTPException
import sqlglot.expressions as exp

from akeneo_mock_server.common import (
    _sanitize_row_entity,
)

SQL_FILTERABLE_FIELDS = frozenset(
    {
        "identifier",
        "uuid",
        "code",
        "enabled",
        "family",
        "parent",
        "created",
        "updated",
    }
)


def parse_search_query(search: str | None) -> dict[str, list[dict[str, Any]]]:
    if search is None or search == "":
        return {}
    try:
        parsed = json.loads(search)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="`search` must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="`search` must be a JSON object")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for field, rules in parsed.items():
        if isinstance(rules, list):
            normalized[field] = [rule for rule in rules if isinstance(rule, dict)]
            continue
        if isinstance(rules, dict):
            normalized[field] = [rules]
            continue
        raise HTTPException(status_code=422, detail=f"Invalid filter for field `{field}`")
    return normalized


def _is_scalar_json_value(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool))


def _contains_locale_scope(rule: dict[str, Any]) -> bool:
    return any(key in rule for key in ("locale", "scope", "channel"))


def _sql_clause_for_rule(table_name: str, field: str, rule: dict[str, Any]) -> Expr | None:
    if field not in SQL_FILTERABLE_FIELDS:
        return None
    if _contains_locale_scope(rule) or field == "values":
        return None
    operator = rule.get("operator")
    expected = rule.get("value")
    if not isinstance(operator, str):
        return None
    op = operator.upper()

    tables_with_data = {
        "asset_families",
        "deprecated_assets",
        "deprecated_asset_categories",
        "deprecated_asset_tags",
        "subscribers",
        "family_variants",
        "reference_entity_records",
        "reference_entity_attributes",
        "assets",
        "asset_attributes",
        "subscriptions",
    }

    column = exp.column(field, table=table_name)
    if table_name in tables_with_data:
        # PostgreSQL JSONB extraction: data->>'field'
        column = exp.JSONExtractScalar(this=exp.column("data", table=table_name), expression=exp.Literal.string(field))
    elif field in {"code", "identifier"}:
        # Non-data tables store code/identifier in the 'id' column (not a separate 'code'/'identifier' column)
        column = exp.column("id", table=table_name)

    if op in {"=", "!="}:
        if not _is_scalar_json_value(expected):
            return None
        literal = exp.Literal.string(str(expected)) if isinstance(expected, str) else exp.Literal.number(str(expected))
        if op == "=":
            return exp.EQ(this=column, expression=literal)
        return exp.NEQ(this=column, expression=literal)

    if op in {"IN", "NOT IN"}:
        if (
            not isinstance(expected, list)
            or len(expected) == 0
            or not all(_is_scalar_json_value(value) for value in expected)
        ):
            return None
        list_exprs = [
            exp.Literal.string(str(v)) if isinstance(v, str) else exp.Literal.number(str(v)) for v in expected
        ]
        if op == "IN":
            return exp.In(this=column, expressions=list_exprs)
        return exp.Not(this=exp.In(this=column, expressions=list_exprs))

    if op in {"CONTAINS", "STARTS WITH", "ENDS WITH"}:
        if not isinstance(expected, str):
            return None
        pattern = expected
        if op == "CONTAINS":
            pattern = f"%{pattern}%"
        elif op == "STARTS WITH":
            pattern = f"{pattern}%"
        else:
            pattern = f"%{pattern}"

        return exp.Like(this=exp.func("LOWER", column), expression=exp.Literal.string(pattern.lower()))

    return None


def apply_sql_search_filters(
    table_name: str,
    search_filters: dict[str, list[dict[str, Any]]],
) -> Expr | None:
    clauses: list[Expr] = []
    for field, rules in search_filters.items():
        field_clauses: list[Expr] = []
        for rule in rules:
            clause = _sql_clause_for_rule(table_name, field, rule)
            if clause is None:
                continue
            field_clauses.append(clause)
        if len(field_clauses) > 1:
            clauses.append(exp.And.from_arg_list(field_clauses))
        elif len(field_clauses) == 1:
            clauses.append(field_clauses[0])

    if len(clauses) > 1:
        return exp.And.from_arg_list(clauses)
    if len(clauses) == 1:
        return clauses[0]
    return None


def normalize_locale_and_scope(
    rule: dict[str, Any], search_locale: str | None, search_scope: str | None
) -> tuple[str | None, str | None]:
    locale = rule.get("locale")
    if locale is None and isinstance(search_locale, str) and search_locale:
        locale = search_locale
    scope = rule.get("scope", rule.get("channel"))
    if scope is None and isinstance(search_scope, str) and search_scope:
        scope = search_scope
    if not isinstance(locale, str):
        locale = None
    if not isinstance(scope, str):
        scope = None
    return locale, scope


def parse_date_value(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    iso_candidate = value
    if iso_candidate.endswith("Z"):
        iso_candidate = f"{iso_candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(iso_candidate)
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolve_field_values(
    entity: dict[str, Any],
    field: str,
    locale: str | None,
    scope: str | None,
) -> list[Any]:
    if field in entity:
        return [entity[field]]
    values = entity.get("values")
    if not isinstance(values, dict):
        return []
    attr_values = values.get(field)
    if not isinstance(attr_values, list):
        return []
    resolved: list[Any] = []
    for item in attr_values:
        if not isinstance(item, dict):
            continue
        item_locale = item.get("locale")
        item_scope = item.get("scope", item.get("channel"))
        if locale is not None and item_locale not in (None, locale):
            continue
        if scope is not None and item_scope not in (None, scope):
            continue
        resolved.append(item.get("data"))
    return resolved


def is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def matches_operator(value: Any, operator: str, expected: Any) -> bool:
    op = operator.upper()
    if op == "EMPTY":
        return is_empty_value(value)
    if op == "NOT EMPTY":
        return not is_empty_value(value)

    if isinstance(value, list) and op in {
        "IN",
        "NOT IN",
        "IN CHILDREN",
        "NOT IN CHILDREN",
        "IN OR UNCLASSIFIED",
        "UNCLASSIFIED",
    }:
        expected_values = expected if isinstance(expected, list) else []
        if op == "UNCLASSIFIED":
            return len(value) == 0
        if op in {"IN", "IN CHILDREN", "IN OR UNCLASSIFIED"}:
            if op == "IN OR UNCLASSIFIED" and len(value) == 0:
                return True
            return any(item in expected_values for item in value)
        return all(item not in expected_values for item in value)

    if op in {"IN", "NOT IN"}:
        expected_values = expected if isinstance(expected, list) else []
        if op == "IN":
            return value in expected_values
        return value not in expected_values

    if op in {"=", "!="}:
        if op == "=":
            return value == expected
        return value != expected

    if op in {"STARTS WITH", "CONTAINS", "DOES NOT CONTAIN", "ENDS WITH"}:
        if not isinstance(value, str) or not isinstance(expected, str):
            return False
        lhs = value.lower()
        rhs = expected.lower()
        if op == "STARTS WITH":
            return lhs.startswith(rhs)
        if op == "CONTAINS":
            return rhs in lhs
        if op == "DOES NOT CONTAIN":
            return rhs not in lhs
        return lhs.endswith(rhs)

    if op in {"<", "<=", ">", ">="}:
        if isinstance(value, str) and isinstance(expected, str):
            left_date = parse_date_value(value)
            right_date = parse_date_value(expected)
            if left_date is not None and right_date is not None:
                if op == "<":
                    return left_date < right_date
                if op == "<=":
                    return left_date <= right_date
                if op == ">":
                    return left_date > right_date
                return left_date >= right_date
        if not isinstance(value, (int, float)) or not isinstance(expected, (int, float)):
            return False
        if op == "<":
            return value < expected
        if op == "<=":
            return value <= expected
        if op == ">":
            return value > expected
        return value >= expected

    if op in {"BETWEEN", "NOT BETWEEN"}:
        if not isinstance(expected, list) or len(expected) != 2:
            return False
        start_raw, end_raw = expected
        if isinstance(value, str) and isinstance(start_raw, str) and isinstance(end_raw, str):
            value_date = parse_date_value(value)
            start_date = parse_date_value(start_raw)
            end_date = parse_date_value(end_raw)
            if value_date is None or start_date is None or end_date is None:
                return False
            in_range = start_date <= value_date <= end_date
            return in_range if op == "BETWEEN" else not in_range
        if not isinstance(value, (int, float)):
            return False
        if not isinstance(start_raw, (int, float)) or not isinstance(end_raw, (int, float)):
            return False
        in_range = start_raw <= value <= end_raw
        return in_range if op == "BETWEEN" else not in_range

    if op == "SINCE LAST N DAYS":
        if not isinstance(expected, int):
            return False
        value_date = parse_date_value(value)
        if value_date is None:
            return False
        threshold = datetime.now(timezone.utc) - timedelta(days=expected)
        return value_date >= threshold

    return False


def matches_field_rule(
    entity: dict[str, Any],
    field: str,
    rule: dict[str, Any],
    search_locale: str | None,
    search_scope: str | None,
) -> bool:
    operator = rule.get("operator")
    if not isinstance(operator, str):
        return False
    expected = rule.get("value")
    locale, scope = normalize_locale_and_scope(rule, search_locale, search_scope)
    values = resolve_field_values(entity, field, locale, scope)

    op = operator.upper()
    if op == "UNCLASSIFIED":
        return matches_operator(values[0] if values else [], op, expected)
    if not values:
        return op == "EMPTY"
    return any(matches_operator(value, op, expected) for value in values)


def matches_search(
    entity: dict[str, Any],
    search_filters: dict[str, list[dict[str, Any]]],
    search_locale: str | None,
    search_scope: str | None,
) -> bool:
    for field, rules in search_filters.items():
        for rule in rules:
            if not matches_field_rule(entity, field, rule, search_locale, search_scope):
                return False
    return True


def parse_csv_query(value: str | None) -> list[str] | None:
    if value is None:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return parts if parts else None


def project_entity_values(
    entity: dict[str, Any],
    attributes: str | None,
    locales: str | None,
    scope: str | None,
) -> dict[str, Any]:
    values = entity.get("values")
    if not isinstance(values, dict):
        return entity

    selected_attributes = parse_csv_query(attributes)
    selected_locales = parse_csv_query(locales)
    projected_values: dict[str, list[dict[str, Any]]] = {}

    for attr_code, attr_values in values.items():
        if selected_attributes is not None and attr_code not in selected_attributes:
            continue
        if not isinstance(attr_values, list):
            continue
        filtered_attr_values: list[dict[str, Any]] = []
        for attr_value in attr_values:
            if not isinstance(attr_value, dict):
                continue
            attr_locale = attr_value.get("locale")
            attr_scope = attr_value.get("scope")
            if selected_locales is not None and attr_locale not in (None, *selected_locales):
                continue
            if scope is not None and scope != "" and attr_scope not in (None, scope):
                continue
            filtered_attr_values.append(attr_value)
        projected_values[attr_code] = filtered_attr_values

    projected_entity = dict(entity)
    projected_entity["values"] = projected_values
    return projected_entity


def collect_filtered_items(
    db: Any,  # psycopg.Connection
    table_name: str,
    pk_field: str,
    limit: int | None,
    search: str | None,
    search_locale: str | None,
    search_scope: str | None,
    attributes: str | None,
    locales: str | None,
    scope: str | None,
    model_class: Any | None = None,
) -> list[dict[str, Any]]:
    parsed_filters = parse_search_query(search)

    query = exp.select("*").from_(table_name)
    where_clause = apply_sql_search_filters(table_name, parsed_filters)
    if where_clause:
        query = query.where(where_clause)

    sql = query.sql("postgres")
    rows = db.execute(sql).fetchall()

    embedded_items: list[dict[str, Any]] = []

    for row in rows:
        entity = _sanitize_row_entity(row, pk_field, model_class)
        if entity is None:
            continue
        if not matches_search(entity, parsed_filters, search_locale, search_scope):
            continue
        embedded_items.append(project_entity_values(entity, attributes, locales, scope))

    if limit is None:
        return embedded_items
    return embedded_items[:limit]
