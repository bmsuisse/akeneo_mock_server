import json
from typing import Any, Mapping

from fastapi import HTTPException, Request


class PatchTypeError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def safe_loads(data_str: str | dict | Any) -> dict[str, Any]:
    if not data_str:
        return {}
    if isinstance(data_str, dict):
        return data_str
    try:
        parsed = json.loads(data_str)
    except (json.JSONDecodeError, TypeError):
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


async def safe_json_body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=415, detail="Invalid JSON or encoding") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    return data


def sanitize_entity(data: dict[str, Any]) -> dict[str, Any]:
    labels = data.get("labels")
    if isinstance(labels, dict):
        data["labels"] = {k: v for k, v in labels.items() if isinstance(v, str)}
    return data


def is_valid_code(code: object) -> bool:
    if not isinstance(code, str) or len(code) < 1:
        return False
    try:
        encoded = code.encode("ascii")
    except UnicodeEncodeError:
        return False
    return len(encoded) < 200 and all(32 <= byte < 127 for byte in encoded)


def merge_value_locale_scope(
    existing_arr: list[dict[str, Any]], incoming_arr: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    keyed: dict[tuple[object, object], dict[str, Any]] = {
        (item.get("locale"), item.get("scope", item.get("channel"))): item for item in existing_arr
    }
    for item in incoming_arr:
        key = (item.get("locale"), item.get("scope", item.get("channel")))
        keyed[key] = item
    return list(keyed.values())


def apply_patch(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        existing_value = existing.get(key)
        if isinstance(existing_value, (dict, list)) and value is None:
            raise PatchTypeError(
                f"Property `{key}` expects an array as data, `NULL` given. Check the standard format documentation."
            )
        if isinstance(existing_value, dict) and not isinstance(value, dict):
            raise PatchTypeError(
                f"Property `{key}` expects an object as data, `{type(value).__name__}` given. Check the standard format documentation."
            )
        if isinstance(existing_value, list) and not isinstance(value, list):
            raise PatchTypeError(
                f"Property `{key}` expects an array as data, `{type(value).__name__}` given. Check the standard format documentation."
            )
        if key == "values" and isinstance(value, dict) and isinstance(existing_value, dict):
            merged_values: dict[str, Any] = dict(existing_value)
            for attr, attr_arr in value.items():
                existing_attr = merged_values.get(attr)
                if isinstance(attr_arr, list) and isinstance(existing_attr, list):
                    merged_values[attr] = merge_value_locale_scope(existing_attr, attr_arr)
                else:
                    merged_values[attr] = attr_arr
            existing[key] = merged_values
            continue
        if isinstance(existing_value, dict) and isinstance(value, dict):
            existing[key] = apply_patch(dict(existing_value), value)
            continue
        existing[key] = value
    return existing


def _get_item_pk(item: Any, pk_field: str) -> str:
    if isinstance(item, Mapping) or (hasattr(item, "keys") and callable(getattr(item, "keys"))):
        # item is likely a dict or psycopg Row
        row_dict = dict(item)
        if pk_field in row_dict:
            return str(row_dict[pk_field])
        if "id" in row_dict:
            return str(row_dict["id"])
        if "identifier" in row_dict:
            return str(row_dict["identifier"])
        if "code" in row_dict:
            return str(row_dict["code"])
        if "uuid" in row_dict:
            return str(row_dict["uuid"])
        return str(row_dict.get(pk_field, ""))
    if hasattr(item, "id"):
        return str(item.id)
    return str(getattr(item, pk_field, ""))


def _get_item_data_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping) or (hasattr(item, "keys") and callable(getattr(item, "keys"))):
        if "data" in item and item["data"]:
            return safe_loads(item["data"])
        # If it's a row from an explicit table, we need to convert it to a dict and handle JSON columns
        data = dict(item)
        #
        for key, val in data.items():
            if isinstance(val, str) and val.startswith(("{", "[")):
                try:
                    data[key] = json.loads(val)
                except json.JSONDecodeError:
                    pass
        # Filter out None values to match Akeneo's behavior for optional fields
        return {k: v for k, v in data.items() if v is not None}
    if hasattr(item, "data") and item.data:
        return safe_loads(item.data)
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return {}


def _sanitize_row_entity(
    item: Any, pk_field: str | None = None, model_class: Any | None = None
) -> dict[str, Any] | None:
    pk = _get_item_pk(item, pk_field or "")
    if not is_valid_code(pk):
        return None
    data = _get_item_data_dict(item)

    # Map 'id' to 'identifier' and 'code' to satisfy various Pydantic models
    if "id" in data:
        if "identifier" not in data or data["identifier"] is None:
            data["identifier"] = data["id"]
        if "code" not in data or data["code"] is None:
            data["code"] = data["id"]

    if model_class:
        try:
            # Validate and dump using the model to handle types (booleans) and aliases (metadata)
            entity = model_class.model_validate(data).model_dump(by_alias=True, mode="json", exclude_unset=True)
        except Exception:
            entity = sanitize_entity(data)
    else:
        entity = sanitize_entity(data)
    if pk_field and pk_field not in entity:
        entity[pk_field] = pk
    return entity
