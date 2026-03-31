import json
import re
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4
import psycopg

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from akeneo_mock_server.common import (
    _get_item_data_dict,
    _get_item_pk,
    _sanitize_row_entity,
    apply_patch,
    safe_json_body,
)
from akeneo_mock_server.events import dispatch_event, get_entity_event_name
from akeneo_mock_server.database import MODELS, SUB_MODELS, get_db
from akeneo_mock_server.pagination import (
    build_href,
    is_search_after_only_entity,
    is_search_after_only_sub_entity,
    paginate_page,
    paginate_search_after,
    resolve_pagination_type,
    supports_search_after_entity,
    supports_search_after_sub_entity,
    validate_limit,
)
from akeneo_mock_server.search_filters import collect_filtered_items
from akeneo_mock_server.schemas import EntityListQuery, GenericPayload, SearchProductsUuidQuery, SubEntityListQuery

router = APIRouter(prefix="/api/rest/v1", tags=["rest"])


def _find_product_by_uuid(db: psycopg.Connection, code: str) -> dict[str, Any] | None:
    return db.execute("SELECT * FROM products WHERE uuid = %s", (code,)).fetchone()


def _generate_unique_product_uuid(db: psycopg.Connection) -> str:
    generated = str(uuid4())
    while _find_product_by_uuid(db, generated) is not None:
        generated = str(uuid4())
    return generated


def _ensure_product_uuid(value: Any, db: psycopg.Connection) -> str:
    if isinstance(value, str) and value:
        return value
    return _generate_unique_product_uuid(db)


@router.get("/products-uuid/search")
def search_products_uuid(
    query: SearchProductsUuidQuery = Depends(),
    db: psycopg.Connection = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    return {
        "_links": {"self": {"href": "/api/rest/v1/products-uuid/search"}},
        "current_page": 1,
        "_embedded": {
            "items": collect_filtered_items(
                db=db,
                table_name="products",
                pk_field="uuid",
                limit=query.limit,
                search=query.search,
                search_locale=query.search_locale,
                search_scope=query.search_scope,
                attributes=query.attributes,
                locales=query.locales,
                scope=query.scope,
                model_class=MODELS["products-uuid"]["model"],
            )
        },
    }


def _validate_payload(
    payload: dict[str, Any], model_class: Any | None = None, partial: bool = False
) -> dict[str, Any]:
    if model_class is not None:
        if partial:
            return payload
        try:
            return model_class.model_validate(payload).model_dump(mode="python", exclude_unset=True)
        except ValidationError as e:
            import logging

            logging.error(f"DEBUG: Validation error for model {model_class.__name__}: {e.errors()}")
            raise HTTPException(status_code=422, detail=e.errors())
        except Exception as e:
            raise e
    try:
        return GenericPayload.model_validate(payload).model_dump(mode="python")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())


def _validate_complete_payload(payload: dict[str, Any], model_class: Any) -> dict[str, Any]:
    try:
        return model_class.model_validate(payload).model_dump(mode="python", exclude_unset=True)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())


_ENTITIES_WITH_VALUES: frozenset[str] = frozenset(
    {
        "products",
        "products-uuid",
        "product-models",
        "published-products",
    }
)


def _validate_attribute_value(attr_code: str, attr_type: str, attr: dict[str, Any], data: Any) -> None:
    """Raise HTTPException 422 if data violates the attribute's validation rules."""
    if attr_type in ("pim_catalog_text", "pim_catalog_textarea", "pim_catalog_identifier"):
        max_chars = attr.get("max_characters")
        if max_chars is not None and isinstance(data, str) and len(data) > max_chars:
            raise HTTPException(
                status_code=422,
                detail=f"Attribute '{attr_code}': value exceeds max_characters ({max_chars}).",
            )
        if attr.get("validation_rule") == "regexp":
            pattern = attr.get("validation_regexp")
            if pattern and isinstance(data, str):
                try:
                    if not re.fullmatch(pattern, data):
                        raise HTTPException(
                            status_code=422,
                            detail=f"Attribute '{attr_code}': value does not match validation regexp.",
                        )
                except re.error:
                    pass

    elif attr_type == "pim_catalog_number":
        try:
            num_val = float(str(data))
        except (ValueError, TypeError):
            return
        number_min = attr.get("number_min")
        number_max = attr.get("number_max")
        decimals_allowed = attr.get("decimals_allowed")
        negative_allowed = attr.get("negative_allowed")
        if number_min is not None:
            try:
                if num_val < float(str(number_min)):
                    raise HTTPException(
                        status_code=422,
                        detail=f"Attribute '{attr_code}': value {data} is below minimum {number_min}.",
                    )
            except (ValueError, TypeError):
                pass
        if number_max is not None:
            try:
                if num_val > float(str(number_max)):
                    raise HTTPException(
                        status_code=422,
                        detail=f"Attribute '{attr_code}': value {data} exceeds maximum {number_max}.",
                    )
            except (ValueError, TypeError):
                pass
        if decimals_allowed is not None and not decimals_allowed:
            try:
                if num_val != float(int(num_val)):
                    raise HTTPException(
                        status_code=422,
                        detail=f"Attribute '{attr_code}': decimals are not allowed.",
                    )
            except (OverflowError, ValueError):
                pass
        if negative_allowed is not None and not negative_allowed and num_val < 0:
            raise HTTPException(
                status_code=422,
                detail=f"Attribute '{attr_code}': negative values are not allowed.",
            )

    elif attr_type == "pim_catalog_date":
        date_min = attr.get("date_min")
        date_max = attr.get("date_max")
        if not date_min and not date_max:
            return
        if not isinstance(data, str):
            return
        try:
            date_val = datetime.fromisoformat(data.replace("Z", "+00:00"))
            if date_min:
                min_dt = datetime.fromisoformat(date_min.replace("Z", "+00:00"))
                if date_val.tzinfo is None and min_dt.tzinfo is not None:
                    date_val = date_val.replace(tzinfo=min_dt.tzinfo)
                elif date_val.tzinfo is not None and min_dt.tzinfo is None:
                    min_dt = min_dt.replace(tzinfo=date_val.tzinfo)
                if date_val < min_dt:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Attribute '{attr_code}': date is before minimum {date_min}.",
                    )
            if date_max:
                max_dt = datetime.fromisoformat(date_max.replace("Z", "+00:00"))
                if date_val.tzinfo is None and max_dt.tzinfo is not None:
                    date_val = date_val.replace(tzinfo=max_dt.tzinfo)
                elif date_val.tzinfo is not None and max_dt.tzinfo is None:
                    max_dt = max_dt.replace(tzinfo=date_val.tzinfo)
                if date_val > max_dt:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Attribute '{attr_code}': date is after maximum {date_max}.",
                    )
        except (ValueError, TypeError):
            pass


def _validate_product_values(db: psycopg.Connection, values: dict[str, Any]) -> None:
    """Validate each attribute value in a product against its attribute definition."""
    for attr_code, attr_value_list in values.items():
        if not isinstance(attr_value_list, list):
            continue
        attr_row = db.execute("SELECT * FROM attributes WHERE id = %s", (attr_code,)).fetchone()
        if attr_row is None:
            continue
        attr = _get_item_data_dict(attr_row)
        attr_type = attr.get("type", "")
        for entry in attr_value_list:
            if not isinstance(entry, dict):
                continue
            data = entry.get("data")
            if data is None:
                continue
            _validate_attribute_value(attr_code, attr_type, attr, data)


def _validate_product_values_if_applicable(db: psycopg.Connection, entity_name: str, data: dict[str, Any]) -> None:
    if entity_name not in _ENTITIES_WITH_VALUES:
        return
    values = data.get("values")
    if values and isinstance(values, dict):
        _validate_product_values(db, values)


_ATTRIBUTE_OPTION_ALLOWED_TYPES: frozenset[str] = frozenset(
    {
        "pim_catalog_simpleselect",
        "pim_catalog_multiselect",
    }
)


def _validate_attribute_option_parent_type(db: psycopg.Connection, attribute_code: str) -> None:
    row = db.execute("SELECT id, type FROM attributes WHERE id = %s", (attribute_code,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"attributes '{attribute_code}' not found.")
    attribute_type = row.get("type")
    if attribute_type not in _ATTRIBUTE_OPTION_ALLOWED_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Attribute '{attribute_code}' has type '{attribute_type}' and does not support options. "
                "Supported types are pim_catalog_simpleselect and pim_catalog_multiselect."
            ),
        )


def _supports_sql_pagination_path(entity_name: str, query: EntityListQuery) -> bool:
    if query.search is not None:
        return False
    if query.search_locale is not None or query.search_scope is not None:
        return False
    if query.attributes is not None or query.locales is not None or query.scope is not None:
        return False
    return True


def _parse_collection_payload(content_type: str, body: bytes, model_class: Any | None = None) -> list[dict[str, Any]]:
    try:
        if "vnd.akeneo.collection+json" in content_type or "ndjson" in content_type:
            text_body = body.decode("utf-8").strip().replace("\\n", "\n")
            payload: list[dict[str, Any]] = []
            for line in text_body.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    payload.append({"_invalid": stripped})
                    continue
                if isinstance(parsed, dict):
                    payload.append(_validate_payload(parsed, model_class, partial=True))
                else:
                    payload.append({"_invalid": parsed})
            return payload
        if "application/json" in content_type:
            try:
                parsed = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise HTTPException(status_code=415, detail="Invalid JSON or encoding")
            if isinstance(parsed, list):
                result: list[dict[str, Any]] = []
                for item in parsed:
                    if isinstance(item, dict):
                        result.append(_validate_payload(item, model_class, partial=True))
                    else:
                        result.append({"_invalid": item})
                return result
            if isinstance(parsed, dict):
                return [_validate_payload(parsed, model_class, partial=True)]
            return [{"_invalid": parsed}]
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="Invalid encoding")

    raise HTTPException(
        status_code=415,
        detail="Unsupported Media Type. Use application/vnd.akeneo.collection+json or application/json",
    )


def _apply_table_select_options_flag(
    entity_name: str,
    item: dict[str, Any],
    with_table_select_options: bool,
) -> dict[str, Any]:
    if entity_name != "attributes" or with_table_select_options:
        return item
    table_configuration = item.get("table_configuration")
    if not isinstance(table_configuration, list):
        return item
    result = deepcopy(item)
    for column in result.get("table_configuration", []):
        if not isinstance(column, dict):
            continue
        validations = column.get("validations")
        if isinstance(validations, dict):
            validations.pop("select_options", None)
    return result


# Cache for table columns to avoid repeated metadata queries
_TABLE_COLUMNS_CACHE: dict[str, set[str]] = {}
_TABLE_COLUMN_TYPES_CACHE: dict[str, dict[str, str]] = {}


def _get_table_columns(db: psycopg.Connection, table: str) -> set[str]:
    if table in _TABLE_COLUMNS_CACHE:
        return _TABLE_COLUMNS_CACHE[table]

    rows = db.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)).fetchall()
    columns = {row["column_name"] for row in rows}
    _TABLE_COLUMNS_CACHE[table] = columns
    return columns


def _get_table_column_types(db: psycopg.Connection, table: str) -> dict[str, str]:
    if table in _TABLE_COLUMN_TYPES_CACHE:
        return _TABLE_COLUMN_TYPES_CACHE[table]

    rows = db.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s", (table,)
    ).fetchall()
    column_types = {row["column_name"]: row["data_type"] for row in rows}
    _TABLE_COLUMN_TYPES_CACHE[table] = column_types
    return column_types


def _convert_value_to_type(value: Any, column_type: str) -> Any:
    if value is None:
        return None
    if column_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)
    return value


def _upsert_item(
    db: psycopg.Connection, table: str, pk_field: str, code: str, data: dict[str, Any], parent_id: str | None = None
):
    tables_with_data = {
        "asset_families",
        "deprecated_assets",
        "deprecated_asset_categories",
        "deprecated_asset_tags",
        "subscribers",
        "family_variants",
        "attribute_options",
        "reference_entity_records",
        "reference_entity_attributes",
        "assets",
        "asset_attributes",
    }

    if table in tables_with_data:
        if parent_id:
            sql = f'INSERT INTO "{table}" (id, parent_id, data) VALUES (%s, %s, %s) ON CONFLICT (id) DO UPDATE SET parent_id = EXCLUDED.parent_id, data = EXCLUDED.data'
            db.execute(sql, (code, parent_id, json.dumps(data)))
        else:
            sql = (
                f'INSERT INTO "{table}" (id, data) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data'
            )
            db.execute(sql, (code, json.dumps(data)))
    elif table == "subscriptions":
        pk = f"{parent_id}/{code}"
        sql = "INSERT INTO subscriptions (pk, id, parent_id, data) VALUES (%s, %s, %s, %s) ON CONFLICT (pk) DO UPDATE SET id = EXCLUDED.id, parent_id = EXCLUDED.parent_id, data = EXCLUDED.data"
        db.execute(sql, (pk, code, parent_id, json.dumps(data)))
    else:
        columns = []
        placeholders = []
        values = []
        sql_data = dict(data)

        if "metadata_info" in sql_data:
            sql_data["metadata"] = sql_data.pop("metadata_info")

        pk_val = sql_data.pop(pk_field, None)
        sql_data["id"] = pk_val if pk_val is not None else code

        existing_columns = _get_table_columns(db, table)
        column_types = _get_table_column_types(db, table)

        for k, v in sql_data.items():
            if k not in existing_columns:
                continue
            columns.append(f'"{k}"')
            placeholders.append("%s")
            if isinstance(v, (dict, list)):
                values.append(json.dumps(v))
            else:
                col_type = column_types.get(k, "")
                values.append(_convert_value_to_type(v, col_type))

        update_set = ", ".join([f"{col} = EXCLUDED.{col}" for col in columns if col != '"id"'])
        if update_set:
            sql = f'INSERT INTO "{table}" ({", ".join(columns)}) VALUES ({", ".join(placeholders)}) ON CONFLICT (id) DO UPDATE SET {update_set}'
        else:
            sql = f'INSERT INTO "{table}" ({", ".join(columns)}) VALUES ({", ".join(placeholders)}) ON CONFLICT (id) DO NOTHING'

        db.execute(sql, values)


def register_entity_routes(entity_name: str, config: dict[str, Any]) -> None:
    model = config["model"]
    pk_field = config["pk_field"]
    table = config["table"]
    base_path = f"/{entity_name}"

    @router.get(base_path)
    def get_items(
        query: EntityListQuery = Depends(),
        with_table_select_options: bool = False,
        db: psycopg.Connection = Depends(get_db, scope="function"),
    ) -> dict[str, Any]:
        validate_limit(query.limit)
        resolved_pagination_type = resolve_pagination_type(
            query.pagination_type,
            supports_search_after=supports_search_after_entity(entity_name),
            search_after_only=is_search_after_only_entity(entity_name),
        )
        entries: list[tuple[str, dict[str, Any]]] = []

        if _supports_sql_pagination_path(entity_name, query):
            order_column = "id" if entity_name != "products-uuid" else "uuid"
            if resolved_pagination_type == "page":
                if query.page < 1:
                    raise HTTPException(status_code=422, detail="`page` must be greater than 0.")
                if query.page > 1000000000:
                    raise HTTPException(status_code=422, detail="`page` is too large.")
                offset = (query.page - 1) * query.limit
                sql = f"SELECT * FROM {table} ORDER BY {order_column} LIMIT %s OFFSET %s"
                rows = db.execute(sql, (query.limit + 1, offset)).fetchall()
                sanitized_items: list[tuple[str, dict[str, Any]]] = []
                for row in rows:
                    entity = _sanitize_row_entity(row, pk_field, model)
                    if entity is None:
                        continue
                    sanitized_items.append((str(entity.get(pk_field, "")), entity))
                entries = sanitized_items
            else:
                if query.search_after is not None:
                    sql = f"SELECT * FROM {table} WHERE {order_column} > %s ORDER BY {order_column} LIMIT %s"
                    params = (query.search_after, query.limit + 1)
                else:
                    sql = f"SELECT * FROM {table} ORDER BY {order_column} LIMIT %s"
                    params = (query.limit + 1,)
                rows = db.execute(sql, params).fetchall()
                sanitized_items = []
                for row in rows:
                    entity = _sanitize_row_entity(row, pk_field, model)
                    if entity is None:
                        continue
                    sanitized_items.append((str(entity.get(pk_field, "")), entity))
                entries = sanitized_items
        else:
            embedded_items = collect_filtered_items(
                db=db,
                table_name=table,
                pk_field=pk_field,
                limit=None,
                search=query.search,
                search_locale=query.search_locale,
                search_scope=query.search_scope,
                attributes=query.attributes,
                locales=query.locales,
                scope=query.scope,
                model_class=model,
            )
            entries = sorted(
                [(str(item.get(pk_field, "")), item) for item in embedded_items],
                key=lambda entry: entry[0],
            )

        base_path = f"/api/rest/v1/{entity_name}"
        common_params: dict[str, str | int | None] = {
            "search": query.search,
            "search_locale": query.search_locale,
            "search_scope": query.search_scope,
            "attributes": query.attributes,
            "locales": query.locales,
            "scope": query.scope,
            "limit": query.limit,
        }
        if resolved_pagination_type == "page":
            if _supports_sql_pagination_path(entity_name, query):
                page_items = [entity for _, entity in entries[: query.limit]]
                has_previous = query.page > 1
                has_next = len(entries) > query.limit
            else:
                page_items, has_previous, has_next = paginate_page(entries, page=query.page, limit=query.limit)
            links: dict[str, dict[str, str]] = {
                "self": {
                    "href": build_href(base_path, {**common_params, "pagination_type": "page", "page": query.page})
                },
                "first": {"href": build_href(base_path, {**common_params, "pagination_type": "page", "page": 1})},
            }
            if has_previous:
                links["previous"] = {
                    "href": build_href(base_path, {**common_params, "pagination_type": "page", "page": query.page - 1})
                }
            if has_next:
                links["next"] = {
                    "href": build_href(base_path, {**common_params, "pagination_type": "page", "page": query.page + 1})
                }
            page_items = [
                _apply_table_select_options_flag(entity_name, item, with_table_select_options) for item in page_items
            ]
            return {
                "_links": links,
                "current_page": query.page,
                "_embedded": {"items": page_items},
            }

        if _supports_sql_pagination_path(entity_name, query):
            selected_entries = entries[: query.limit]
            search_after_items = [entity for _, entity in selected_entries]
            next_cursor = selected_entries[-1][0] if len(entries) > query.limit and len(selected_entries) > 0 else None
        else:
            search_after_items, next_cursor = paginate_search_after(entries, query.search_after, query.limit)
        search_after_items = [
            _apply_table_select_options_flag(entity_name, item, with_table_select_options)
            for item in search_after_items
        ]

        links = {
            "self": {
                "href": build_href(
                    base_path, {**common_params, "pagination_type": "search_after", "search_after": query.search_after}
                )
            },
            "first": {
                "href": build_href(
                    base_path, {**common_params, "pagination_type": "search_after", "search_after": None}
                )
            },
        }
        if next_cursor is not None:
            links["next"] = {
                "href": build_href(
                    base_path, {**common_params, "pagination_type": "search_after", "search_after": next_cursor}
                )
            }
        return {"_links": links, "_embedded": {"items": search_after_items}}

    @router.get(f"{base_path}/{{code}}")
    def get_item(
        code: str,
        with_table_select_options: bool = False,
        db: psycopg.Connection = Depends(get_db, scope="function"),
    ) -> dict[str, Any] | None:
        if entity_name == "products-uuid":
            item = _find_product_by_uuid(db, code)
        else:
            item = db.execute(f"SELECT * FROM {table} WHERE id = %s", (code,)).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail=f"{entity_name} '{code}' not found.")
        sanitized = _sanitize_row_entity(item, pk_field, model)
        if sanitized is None:
            raise HTTPException(status_code=404, detail=f"{entity_name} '{code}' not found.")
        return _apply_table_select_options_flag(entity_name, sanitized, with_table_select_options)

    @router.post(base_path, status_code=status.HTTP_201_CREATED)
    async def create_item(
        request: Request,
        background_tasks: BackgroundTasks,
        db: psycopg.Connection = Depends(get_db, scope="function"),
    ) -> JSONResponse:
        data = _validate_payload(await safe_json_body(request), model)
        code = data.get(pk_field)
        if not isinstance(code, str) or not code:
            raise HTTPException(status_code=422, detail=f"Missing or invalid '{pk_field}' in payload.")

        if entity_name == "products":
            existing = db.execute(f"SELECT 1 FROM {table} WHERE id = %s", (code,)).fetchone()
            if existing is not None:
                raise HTTPException(status_code=409, detail=f"{entity_name} '{code}' already exists.")
            product_uuid = _ensure_product_uuid(data.get("uuid"), db)
            existing_with_uuid = _find_product_by_uuid(db, product_uuid)
            if existing_with_uuid is not None:
                raise HTTPException(status_code=409, detail=f"Product uuid '{product_uuid}' already exists.")
            data["uuid"] = product_uuid
            _validate_product_values_if_applicable(db, entity_name, data)
            _upsert_item(db, table, pk_field, code, data)
            db.commit()
        elif entity_name == "products-uuid":
            identifier = data.get("identifier")
            if not isinstance(identifier, str) or not identifier:
                raise HTTPException(status_code=422, detail="Missing or invalid 'identifier' in payload.")
            existing_identifier = db.execute("SELECT 1 FROM products WHERE id = %s", (identifier,)).fetchone()
            if existing_identifier is not None:
                raise HTTPException(status_code=409, detail=f"products '{identifier}' already exists.")
            existing_uuid = _find_product_by_uuid(db, code)
            if existing_uuid is not None:
                raise HTTPException(status_code=409, detail=f"products-uuid '{code}' already exists.")
            data["uuid"] = code
            _validate_product_values_if_applicable(db, entity_name, data)
            _upsert_item(db, "products", "identifier", identifier, data)
            db.commit()
        else:
            existing = db.execute(f"SELECT 1 FROM {table} WHERE id = %s", (code,)).fetchone()
            if existing is not None:
                raise HTTPException(status_code=409, detail=f"{entity_name} '{code}' already exists.")
            _validate_product_values_if_applicable(db, entity_name, data)
            _upsert_item(db, table, pk_field, code, data)
            db.commit()

        event_name = get_entity_event_name(entity_name, "created")
        background_tasks.add_task(dispatch_event, event_name, data)

        from urllib.parse import quote

        headers = {"Location": f"/api/rest/v1/{entity_name}/{quote(code)}", "Content-Type": "application/json"}
        return JSONResponse(content={}, status_code=status.HTTP_201_CREATED, headers=headers)

    @router.patch(f"{base_path}/{{code}}", status_code=status.HTTP_204_NO_CONTENT)
    async def patch_item(
        code: str,
        request: Request,
        background_tasks: BackgroundTasks,
        db: psycopg.Connection = Depends(get_db, scope="function"),
    ) -> Response:
        data = _validate_payload(await safe_json_body(request), model, partial=True)

        if entity_name == "products":
            row = db.execute(f"SELECT * FROM {table} WHERE id = %s", (code,)).fetchone()
            if row is None:
                data["identifier"] = code
                product_uuid = _ensure_product_uuid(data.get("uuid"), db)
                existing_with_uuid = _find_product_by_uuid(db, product_uuid)
                if existing_with_uuid is not None:
                    raise HTTPException(status_code=409, detail=f"Product uuid '{product_uuid}' already exists.")
                data["uuid"] = product_uuid
                validated_data = _validate_complete_payload(data, model)
                _validate_product_values_if_applicable(db, entity_name, validated_data)
                _upsert_item(db, table, pk_field, code, validated_data)
            else:
                existing_data = _get_item_data_dict(row)
                patched_data = apply_patch(existing_data, data)
                patched_data["identifier"] = code
                product_uuid = _ensure_product_uuid(patched_data.get("uuid"), db)
                existing_with_uuid = _find_product_by_uuid(db, product_uuid)
                if existing_with_uuid is not None and _get_item_pk(existing_with_uuid, pk_field) != code:
                    raise HTTPException(status_code=409, detail=f"Product uuid '{product_uuid}' already exists.")
                patched_data["uuid"] = product_uuid
                validated_data = _validate_complete_payload(patched_data, model)
                _validate_product_values_if_applicable(db, entity_name, validated_data)
                _upsert_item(db, table, pk_field, code, validated_data)
        elif entity_name == "products-uuid":
            row = _find_product_by_uuid(db, code)
            if row is None:
                identifier = data.get("identifier")
                if not isinstance(identifier, str) or not identifier:
                    raise HTTPException(status_code=422, detail="Missing or invalid 'identifier' in payload.")
                existing_identifier = db.execute("SELECT 1 FROM products WHERE id = %s", (identifier,)).fetchone()
                if existing_identifier is not None:
                    raise HTTPException(status_code=409, detail=f"products '{identifier}' already exists.")
                data["uuid"] = code
                validated_data = _validate_complete_payload(data, model)
                _validate_product_values_if_applicable(db, entity_name, validated_data)
                _upsert_item(db, "products", "identifier", identifier, validated_data)
            else:
                existing_data = _get_item_data_dict(row)
                patched_data = apply_patch(existing_data, data)
                patched_data["uuid"] = code
                new_identifier = patched_data.get("identifier")
                current_identifier = _get_item_pk(row, "identifier")
                if not isinstance(new_identifier, str) or not new_identifier:
                    new_identifier = current_identifier
                    patched_data["identifier"] = current_identifier
                if new_identifier != current_identifier:
                    existing_identifier = db.execute(
                        "SELECT 1 FROM products WHERE id = %s", (new_identifier,)
                    ).fetchone()
                    if existing_identifier is not None:
                        raise HTTPException(status_code=409, detail=f"products '{new_identifier}' already exists.")
                    # If we change identifier, we might need to delete old row and insert new one
                    db.execute("DELETE FROM products WHERE id = %s", (current_identifier,))
                validated_data = _validate_complete_payload(patched_data, model)
                _validate_product_values_if_applicable(db, entity_name, validated_data)
                _upsert_item(db, "products", "identifier", new_identifier, validated_data)
        else:
            row = db.execute(f"SELECT * FROM {table} WHERE id = %s", (code,)).fetchone()
            if row is None:
                data[pk_field] = code
                validated_data = _validate_complete_payload(data, model)
                _validate_product_values_if_applicable(db, entity_name, validated_data)
                _upsert_item(db, table, pk_field, code, validated_data)
            else:
                existing_data = _get_item_data_dict(row)
                patched_data = apply_patch(existing_data, data)
                patched_data[pk_field] = code
                validated_data = _validate_complete_payload(patched_data, model)
                _validate_product_values_if_applicable(db, entity_name, validated_data)
                _upsert_item(db, table, pk_field, code, validated_data)

        db.commit()
        event_name = get_entity_event_name(entity_name, "updated")
        background_tasks.add_task(dispatch_event, event_name, data)
        from urllib.parse import quote

        headers = {"Location": f"/api/rest/v1/{entity_name}/{quote(code)}", "Content-Type": "application/json"}
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)

    @router.delete(f"{base_path}/{{code}}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_item(
        code: str,
        background_tasks: BackgroundTasks,
        db: psycopg.Connection = Depends(get_db, scope="function"),
    ) -> Response:
        if entity_name == "products-uuid":
            row = _find_product_by_uuid(db, code)
        else:
            row = db.execute(f"SELECT * FROM {table} WHERE id = %s", (code,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"{entity_name} '{code}' not found.")

        deleted_data = _get_item_data_dict(row)
        if entity_name == "products-uuid":
            db.execute("DELETE FROM products WHERE uuid = %s", (code,))
        else:
            db.execute(f"DELETE FROM {table} WHERE id = %s", (code,))
        db.commit()

        event_name = get_entity_event_name(entity_name, "deleted")
        background_tasks.add_task(dispatch_event, event_name, deleted_data)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.patch(base_path, status_code=status.HTTP_200_OK)
    async def patch_multiple_items(
        request: Request,
        background_tasks: BackgroundTasks,
        db: psycopg.Connection = Depends(get_db, scope="function"),
    ) -> Response:
        content_type = request.headers.get("content-type", "")
        body = await request.body()
        items_payload = _parse_collection_payload(content_type, body, model)
        responses: list[dict[str, Any]] = []

        for index, data in enumerate(items_payload):
            if "_invalid" in data:
                responses.append({"line": index + 1, "status_code": 400, "message": "Invalid item"})
                continue
            code = data.get(pk_field)
            if not isinstance(code, str) or not code:
                responses.append({"line": index + 1, "status_code": 400, "message": f"Missing {pk_field}"})
                continue

            if entity_name == "products":
                row = db.execute("SELECT * FROM products WHERE id = %s", (code,)).fetchone()
                if row is None:
                    product_uuid = _ensure_product_uuid(data.get("uuid"), db)
                    existing_with_uuid = _find_product_by_uuid(db, product_uuid)
                    if existing_with_uuid is not None:
                        responses.append({"line": index + 1, "status_code": 409, "message": "UUID exists"})
                        continue
                    data["identifier"] = code
                    data["uuid"] = product_uuid
                    _upsert_item(db, "products", "identifier", code, data)
                    responses.append({"line": index + 1, pk_field: code, "status_code": 201})
                    background_tasks.add_task(dispatch_event, get_entity_event_name(entity_name, "created"), data)
                    continue
                existing_data = _get_item_data_dict(row)
                existing_data.update(data)
                existing_data["identifier"] = code
                product_uuid = _ensure_product_uuid(existing_data.get("uuid"), db)
                existing_data["uuid"] = product_uuid
                _upsert_item(db, "products", "identifier", code, existing_data)
                responses.append({"line": index + 1, pk_field: code, "status_code": 204})
                background_tasks.add_task(dispatch_event, get_entity_event_name(entity_name, "updated"), existing_data)
            elif entity_name == "products-uuid":
                row = _find_product_by_uuid(db, code)
                if row is None:
                    identifier = data.get("identifier")
                    if not identifier:
                        responses.append({"line": index + 1, "status_code": 400, "message": "Missing identifier"})
                        continue
                    data["uuid"] = code
                    _upsert_item(db, "products", "identifier", identifier, data)
                    responses.append({"line": index + 1, pk_field: code, "status_code": 201})
                    background_tasks.add_task(dispatch_event, get_entity_event_name(entity_name, "created"), data)
                    continue
                existing_data = _get_item_data_dict(row)
                existing_data.update(data)
                existing_data["uuid"] = code
                _upsert_item(db, "products", "identifier", existing_data.get("identifier", ""), existing_data)
                responses.append({"line": index + 1, pk_field: code, "status_code": 204})
                background_tasks.add_task(dispatch_event, get_entity_event_name(entity_name, "updated"), existing_data)
            else:
                row = db.execute(f"SELECT * FROM {table} WHERE id = %s", (code,)).fetchone()
                if row is None:
                    _upsert_item(db, table, pk_field, code, data)
                    responses.append({"line": index + 1, pk_field: code, "status_code": 201})
                    background_tasks.add_task(dispatch_event, get_entity_event_name(entity_name, "created"), data)
                else:
                    existing_data = _get_item_data_dict(row)
                    existing_data.update(data)
                    _upsert_item(db, table, pk_field, code, existing_data)
                    responses.append({"line": index + 1, pk_field: code, "status_code": 204})
                    background_tasks.add_task(
                        dispatch_event, get_entity_event_name(entity_name, "updated"), existing_data
                    )
        db.commit()
        media_type = (
            "application/json" if "application/json" in content_type else "application/vnd.akeneo.collection+json"
        )
        content = (
            json.dumps(responses)
            if media_type == "application/json"
            else "\n".join(json.dumps(r) for r in responses) + "\n"
        )
        return Response(content=content, media_type=media_type)


def register_sub_entity_routes(sub_entity_key: str, config: dict[str, Any]) -> None:
    model = config["model"]
    pk_field = config["pk_field"]
    parent_entity = config["parent_entity"]
    nested_path = config["nested_path"]
    table = config["table"]
    is_attribute_options_sub_entity = sub_entity_key == "attributes/attribute-options"
    is_non_paginated_sub_entity = sub_entity_key in {
        "reference-entities/attributes",
        "asset-families/attributes",
    }
    base_path = f"/{parent_entity}/{{parent_code}}/{nested_path}"

    @router.get(base_path)
    def get_sub_items(
        parent_code: str,
        query: SubEntityListQuery = Depends(),
        db: psycopg.Connection = Depends(get_db, scope="function"),
    ) -> dict[str, Any] | list[dict[str, Any]]:
        if is_non_paginated_sub_entity:
            rows = db.execute(
                f"SELECT * FROM {table} WHERE parent_id = %s ORDER BY id",
                (parent_code,),
            ).fetchall()
            items: list[dict[str, Any]] = []
            for row in rows:
                entity = _sanitize_row_entity(row, pk_field, model)
                if entity:
                    items.append(entity)
            return items

        validate_limit(query.limit)
        resolved_pagination_type = resolve_pagination_type(
            query.pagination_type,
            supports_search_after=supports_search_after_sub_entity(sub_entity_key),
            search_after_only=is_search_after_only_sub_entity(sub_entity_key),
        )

        order_column = "id"
        if resolved_pagination_type == "page":
            if query.page < 1:
                raise HTTPException(status_code=422, detail="`page` must be greater than 0.")
            if query.page > 1000000000:
                raise HTTPException(status_code=422, detail="`page` is too large.")
            offset = (query.page - 1) * query.limit
            sql = f"SELECT * FROM {table} WHERE parent_id = %s ORDER BY {order_column} LIMIT %s OFFSET %s"
            rows = db.execute(sql, (parent_code, query.limit + 1, offset)).fetchall()
        else:
            if query.search_after:
                sql = f"SELECT * FROM {table} WHERE parent_id = %s AND {order_column} > %s ORDER BY {order_column} LIMIT %s"
                rows = db.execute(sql, (parent_code, query.search_after, query.limit + 1)).fetchall()
            else:
                sql = f"SELECT * FROM {table} WHERE parent_id = %s ORDER BY {order_column} LIMIT %s"
                rows = db.execute(sql, (parent_code, query.limit + 1)).fetchall()

        entries = []
        for row in rows:
            entity = _sanitize_row_entity(row, pk_field, model)
            if entity:
                entries.append((str(entity.get(pk_field, "")), entity))

        resolved_path = f"/api/rest/v1/{parent_entity}/{parent_code}/{nested_path}"
        common_params = {"limit": query.limit}
        if resolved_pagination_type == "page":
            page_items = [e[1] for e in entries[: query.limit]]
            links = {
                "self": {
                    "href": build_href(resolved_path, {**common_params, "pagination_type": "page", "page": query.page})
                }
            }
            if query.page > 1:
                links["previous"] = {
                    "href": build_href(
                        resolved_path, {**common_params, "pagination_type": "page", "page": query.page - 1}
                    )
                }
            if len(entries) > query.limit:
                links["next"] = {
                    "href": build_href(
                        resolved_path, {**common_params, "pagination_type": "page", "page": query.page + 1}
                    )
                }
            return {"_links": links, "current_page": query.page, "_embedded": {"items": page_items}}

        selected = entries[: query.limit]
        next_cursor = selected[-1][0] if len(entries) > query.limit and len(selected) > 0 else None
        links = {
            "self": {
                "href": build_href(
                    resolved_path,
                    {**common_params, "pagination_type": "search_after", "search_after": query.search_after},
                )
            },
            "first": {
                "href": build_href(
                    resolved_path, {**common_params, "pagination_type": "search_after", "search_after": None}
                )
            },
        }
        if next_cursor:
            links["next"] = {
                "href": build_href(
                    resolved_path, {**common_params, "pagination_type": "search_after", "search_after": next_cursor}
                )
            }
        return {"_links": links, "_embedded": {"items": [e[1] for e in selected]}}

    @router.get(f"{base_path}/{{code}}")
    def get_sub_item(
        parent_code: str, code: str, db: psycopg.Connection = Depends(get_db, scope="function")
    ) -> dict[str, Any] | None:
        row = db.execute(f"SELECT * FROM {table} WHERE parent_id = %s AND id = %s", (parent_code, code)).fetchone()
        if not row:
            raise HTTPException(status_code=404)
        return _sanitize_row_entity(row, pk_field, model)

    @router.post(base_path, status_code=201)
    async def create_sub_item(
        parent_code: str, request: Request, db: psycopg.Connection = Depends(get_db, scope="function")
    ) -> JSONResponse:
        if is_attribute_options_sub_entity:
            _validate_attribute_option_parent_type(db, parent_code)
        data = await safe_json_body(request)
        data["parent_id"] = parent_code
        code = data.get(pk_field)
        if not isinstance(code, str) or not code:
            raise HTTPException(status_code=422)
        validated_data = _validate_complete_payload(data, model)
        _upsert_item(db, table, pk_field, code, validated_data, parent_code)
        db.commit()
        from urllib.parse import quote

        return JSONResponse(
            content={},
            status_code=201,
            headers={"Location": f"/api/rest/v1/{parent_entity}/{quote(parent_code)}/{nested_path}/{quote(code)}"},
        )

    @router.patch(base_path, status_code=status.HTTP_200_OK)
    async def patch_multiple_sub_items(
        parent_code: str,
        request: Request,
        db: psycopg.Connection = Depends(get_db, scope="function"),
    ) -> Response:
        if is_attribute_options_sub_entity:
            _validate_attribute_option_parent_type(db, parent_code)
        content_type = request.headers.get("content-type", "")
        body = await request.body()
        items_payload = _parse_collection_payload(content_type, body, model)
        responses: list[dict[str, Any]] = []

        for index, data in enumerate(items_payload):
            if "_invalid" in data:
                responses.append({"line": index + 1, "status_code": 400, "message": "Invalid item"})
                continue
            code = data.get(pk_field)
            if not isinstance(code, str) or not code:
                responses.append({"line": index + 1, "status_code": 400, "message": f"Missing {pk_field}"})
                continue

            row = db.execute(
                f"SELECT * FROM {table} WHERE parent_id = %s AND id = %s",
                (parent_code, code),
            ).fetchone()
            if row is None:
                payload = dict(data)
                payload[pk_field] = code
                payload["parent_id"] = parent_code
                validated_payload = _validate_complete_payload(payload, model)
                _upsert_item(db, table, pk_field, code, validated_payload, parent_code)
                responses.append({"line": index + 1, pk_field: code, "status_code": 201})
                continue

            existing_data = _get_item_data_dict(row)
            existing_data.update(data)
            existing_data[pk_field] = code
            existing_data["parent_id"] = parent_code
            validated_payload = _validate_complete_payload(existing_data, model)
            _upsert_item(db, table, pk_field, code, validated_payload, parent_code)
            responses.append({"line": index + 1, pk_field: code, "status_code": 204})

        db.commit()
        media_type = (
            "application/json" if "application/json" in content_type else "application/vnd.akeneo.collection+json"
        )
        content = (
            json.dumps(responses)
            if media_type == "application/json"
            else "\n".join(json.dumps(response) for response in responses) + "\n"
        )
        return Response(content=content, media_type=media_type)

    @router.patch(f"{base_path}/{{code}}", status_code=204)
    async def patch_sub_item(
        parent_code: str, code: str, request: Request, db: psycopg.Connection = Depends(get_db, scope="function")
    ) -> Response:
        if is_attribute_options_sub_entity:
            _validate_attribute_option_parent_type(db, parent_code)
        data = await safe_json_body(request)
        row = db.execute(f"SELECT * FROM {table} WHERE parent_id = %s AND id = %s", (parent_code, code)).fetchone()
        if row:
            existing = _get_item_data_dict(row)
            existing.update(data)
            data = existing
        data[pk_field] = code
        data["parent_id"] = parent_code
        validated_data = _validate_complete_payload(data, model)
        _upsert_item(db, table, pk_field, code, validated_data, parent_code)
        db.commit()
        return Response(status_code=204)


def register_ee_workflow_routes(entity_name: str) -> None:
    @router.get(f"/{entity_name}/{{code}}/draft")
    def get_draft(code: str) -> dict[str, str]:
        return {"status": "in_progress", "code": code}

    @router.post(f"/{entity_name}/{{code}}/proposal", status_code=201)
    def create_proposal(code: str) -> Response:
        from urllib.parse import quote

        return Response(status_code=201, headers={"Location": f"/api/rest/v1/{entity_name}/{quote(code)}/proposal/1"})


def register_three_level_routes(parent_entity: str) -> None:
    base_path = f"/{parent_entity}/{{parent_code}}/attributes/{{attribute_code}}/options"

    @router.get(base_path)
    def get_three_level_items(parent_code: str, attribute_code: str) -> JSONResponse:
        return JSONResponse(content=[], status_code=200)

    @router.get(f"{base_path}/{{code}}")
    def get_three_level_item(parent_code: str, attribute_code: str, code: str) -> JSONResponse:
        return JSONResponse(content={"code": code}, status_code=200)

    @router.patch(f"{base_path}/{{code}}", status_code=204)
    async def patch_three_level_item(parent_code: str, attribute_code: str, code: str, request: Request) -> Response:
        return Response(status_code=204)


@router.post("/media-files", status_code=201)
@router.post("/category-media-files", status_code=201)
@router.post("/reference-entities-media-files", status_code=201)
@router.post("/asset-media-files", status_code=201)
async def upload_media_file() -> Response:
    return Response(status_code=201, headers={"Location": "/api/rest/v1/media-files/mock-media-code"})


@router.get("/media-files/{code}")
async def get_media_file(code: str) -> JSONResponse:
    return JSONResponse(
        content={
            "code": code,
            "original_filename": f"{code}.jpg",
            "mime_type": "image/jpeg",
            "size": 1024,
            "extension": "jpg",
            "_links": {
                "self": {"href": f"/api/rest/v1/media-files/{code}"},
                "download": {"href": f"/api/rest/v1/media-files/{code}/download"},
            },
        },
        status_code=200,
    )


@router.get("/media-files/{code}/download")
@router.get("/category-media-files/{file_path}/download")
async def download_media_file(code: str | None = None, file_path: str | None = None) -> Response:
    return Response(
        content=f"mock-binary-content-for-{code or file_path}".encode(),
        media_type="application/octet-stream",
        status_code=200,
    )


@router.get("/assets/{asset_code}/reference-files/{locale_code}")
async def get_deprecated_asset_reference_file(asset_code: str, locale_code: str) -> dict[str, Any]:
    return {
        "code": asset_code,
        "locale": locale_code,
        "_link": {"download": {"href": f"/api/rest/v1/assets/{asset_code}/reference-files/{locale_code}/download"}},
    }


@router.get("/assets/{asset_code}/reference-files/{locale_code}/download")
async def download_deprecated_asset_reference_file(asset_code: str, locale_code: str) -> JSONResponse:
    return JSONResponse(content={}, status_code=200)


@router.get("/assets/{asset_code}/variation-files/{channel_code}/{locale_code}")
async def get_deprecated_asset_variation_file(asset_code: str, channel_code: str, locale_code: str) -> dict[str, Any]:
    return {
        "code": asset_code,
        "channel": channel_code,
        "locale": locale_code,
        "_link": {
            "download": {
                "href": f"/api/rest/v1/assets/{asset_code}/variation-files/{channel_code}/{locale_code}/download"
            }
        },
    }


@router.get("/assets/{asset_code}/variation-files/{channel_code}/{locale_code}/download")
async def download_deprecated_asset_variation_file(
    asset_code: str, channel_code: str, locale_code: str
) -> JSONResponse:
    return JSONResponse(content={}, status_code=200)


@router.post("/jobs/export/{code}", status_code=201)
@router.post("/jobs/import/{code}", status_code=201)
async def launch_job(code: str) -> JSONResponse:
    from urllib.parse import quote

    return JSONResponse(
        content={},
        status_code=201,
        headers={
            "Location": f"/api/rest/v1/jobs/import/{quote(code)}/executions/1",
            "Content-Type": "application/json",
        },
    )


@router.get("")
def get_endpoints() -> dict[str, Any]:
    return {"host": "127.0.0.1:8000", "authentication": {"oauth2": "/api/oauth/v1/token"}, "routes": {}}


@router.get("/system-information")
def get_system_information() -> dict[str, str]:
    return {"version": "7.0.0", "edition": "EE"}


def register_routes() -> None:
    for entity_name, config in MODELS.items():
        register_entity_routes(entity_name, config)
    for sub_entity_key, config in SUB_MODELS.items():
        if "parent_entity" in config:
            register_sub_entity_routes(sub_entity_key, config)
    for ee_entity_name in ["products", "products-uuid", "product-models"]:
        register_ee_workflow_routes(ee_entity_name)
    for parent_entity in ["reference-entities", "asset-families"]:
        register_three_level_routes(parent_entity)


register_routes()
