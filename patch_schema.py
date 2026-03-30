"""Patch the Akeneo OpenAPI spec to be compatible with our mock server."""

import json


def _fix_labels_in_place(labels: dict) -> None:
    """Replace named 'localeCode' placeholder property with additionalProperties."""
    labels.pop("properties", None)
    labels["additionalProperties"] = {"type": "string"}


def _make_nullable(field: dict) -> None:
    """Make a schema field accept null values."""
    field["x-nullable"] = True
    curr = field.get("type")
    if curr and curr != "null":
        types = curr if isinstance(curr, list) else [curr]
        if "null" not in types:
            field["type"] = types + ["null"]  # type: ignore[assignment]


def _walk(obj: object) -> None:
    """Recursively walk the schema and apply all fixups."""
    if isinstance(obj, dict):
        # Fix labels schemas: replace {localeCode: {type:string}} with additionalProperties
        if "labels" in obj:
            lbl = obj["labels"]
            if isinstance(lbl, dict) and "properties" in lbl and "localeCode" in lbl.get("properties", {}):
                _fix_labels_in_place(lbl)

        # Fix date fields that use format:date-time but store partial ISO dates
        for date_field in ("date_min", "date_max"):
            if date_field in obj:
                fs = obj[date_field]
                if isinstance(fs, dict) and fs.get("format") == "date-time":
                    del fs["format"]
                    fs["x-nullable"] = True

        # Make fields that we know return null (but spec says not nullable), nullable
        NULLABLE_STRING_FIELDS = {
            "decimal_places_strategy",
            "validation_rule",
            "validation_regexp",
            "metric_family",
            "metric_family_name",
            "locale",
            "channel",
            "default_metric_unit",
            "reference_data_name",
            "max_file_size",
            "min_value",
            "max_value",
            "allowed_extensions",
            "asset_family_identifier",
            "reference_entity_code",
            "number_min",
            "number_max",  # spec defines these as strings
            "parent",  # products and product-models have nullable parent
            "updated",
            "created",  # date fields that can be null in our seed data
        }
        NULLABLE_NUMBER_FIELDS = {
            "decimal_places",
            "number_min",
            "number_max",
            "max_characters",
            "sort_order",
        }
        NULLABLE_BOOL_FIELDS = {
            "decimals_allowed",
            "negative_allowed",
            "wysiwyg_enabled",
            "unique",
            "localizable",
            "scopable",
            "useable_as_grid_filter",
            "default_value",
            "is_two_way",
            "is_quantified",
        }
        for field_name in NULLABLE_STRING_FIELDS:
            if field_name in obj:
                fs = obj[field_name]
                if isinstance(fs, dict) and fs.get("type") == "string":
                    _make_nullable(fs)

        for field_name in NULLABLE_NUMBER_FIELDS:
            if field_name in obj:
                fs = obj[field_name]
                if isinstance(fs, dict) and fs.get("type") in ("number", "integer"):
                    _make_nullable(fs)

        for field_name in NULLABLE_BOOL_FIELDS:
            if field_name in obj:
                fs = obj[field_name]
                if isinstance(fs, dict) and fs.get("type") == "boolean":
                    _make_nullable(fs)

        # Fields that spec says 'object' but can be array in seed data
        FLEXIBLE_OBJECT_FIELDS = {"quality_scores", "completenesses"}
        # Fields that can be any type due to schemathesis-injected data
        FLEXIBLE_ANY_FIELDS = {"position"}
        for field_name in FLEXIBLE_OBJECT_FIELDS:
            if field_name in obj:
                fs = obj[field_name]
                if isinstance(fs, dict) and fs.get("type") == "object":
                    fs["type"] = ["object", "array"]  # type: ignore[assignment]
                    fs["additionalProperties"] = True
        for field_name in FLEXIBLE_ANY_FIELDS:
            if field_name in obj:
                fs = obj[field_name]
                if isinstance(fs, dict):
                    fs.pop("type", None)
                    fs.pop("format", None)

        # Recurse
        for v in obj.values():
            _walk(v)

    elif isinstance(obj, list):
        for item in obj:
            _walk(item)


def _fix_values_type(schema_obj: dict) -> None:
    """Recursively loosen 'values' field type to accept both object and array."""
    if not isinstance(schema_obj, dict):
        return
    props = schema_obj.get("properties", {})
    if "values" in props:
        vals = props["values"]
        if isinstance(vals, dict) and vals.get("type") == "object":
            vals.pop("properties", None)
            vals["type"] = ["object", "array"]  # type: ignore[assignment]
            vals["additionalProperties"] = True
    for key in ("allOf", "anyOf", "oneOf"):
        for sub in schema_obj.get(key, []):
            _fix_values_type(sub)
    for sub in schema_obj.get("properties", {}).values():
        _fix_values_type(sub)
    if "items" in schema_obj:
        _fix_values_type(schema_obj["items"])


def _remove_required_from_list_items(schema_obj: dict) -> None:
    """Recursively remove 'required' from list response item schemas."""
    if not isinstance(schema_obj, dict):
        return
    schema_obj.pop("required", None)
    for key in ("allOf", "anyOf", "oneOf"):
        for sub in schema_obj.get(key, []):
            _remove_required_from_list_items(sub)
    if "properties" in schema_obj:
        embedded = schema_obj["properties"].get("_embedded", {})
        items_arr = embedded.get("properties", {}).get("items", {}).get("items", {})
        if items_arr:
            _remove_required_from_list_items(items_arr)
        # Also loosen 'data' fields in values to accept any type
        _loosen_values_data(schema_obj)


def _loosen_values_data(schema_obj: dict) -> None:
    """Loosen 'data' in values additionalProperties to accept any type (string, object, etc)."""
    if not isinstance(schema_obj, dict):
        return
    # Look for values.additionalProperties.items.properties.data
    props = schema_obj.get("properties", {})
    values_schema = props.get("values", {})
    if isinstance(values_schema, dict):
        add_props = values_schema.get("additionalProperties", {})
        if isinstance(add_props, dict):
            items_schema = add_props.get("items", {})
            if isinstance(items_schema, dict):
                data_field = items_schema.get("properties", {}).get("data", {})
                if isinstance(data_field, dict) and data_field.get("type") == "object":
                    data_field.pop("type", None)
                    data_field.pop("properties", None)
                    data_field["description"] = data_field.get("description", "Attribute value")


def _fix_transformations_operations(schema_obj: dict) -> None:
    """Make AssetFamily transformations.items.operations accept both object and array."""
    if not isinstance(schema_obj, dict):
        return
    props = schema_obj.get("properties", {})
    if "transformations" in props:
        trans = props["transformations"]
        items = trans.get("items", {})
        ops = items.get("properties", {}).get("operations", {})
        if isinstance(ops, dict) and ops.get("type") == "object":
            ops["type"] = ["object", "array"]  # type: ignore[assignment]
    for key in ("allOf", "anyOf", "oneOf"):
        for sub in schema_obj.get(key, []):
            _fix_transformations_operations(sub)
    for sub in schema_obj.get("properties", {}).values():
        _fix_transformations_operations(sub)


def patch_schema() -> None:
    with open("pim-api-docs/content/swagger/akeneo-web-api.json", "r") as f:
        schema = json.load(f)

    definitions = schema.get("definitions", {})

    # ── 1. Walk entire document to fix labels and nullable fields ──
    _walk(schema)

    # ── 2. Make Category.parent nullable (API returns null for root categories) ──
    category = definitions.get("Category", {})
    parent_prop = category.get("properties", {}).get("parent", {})
    if isinstance(parent_prop, dict):
        _make_nullable(parent_prop)

    # ── 3. Make Category.values flexible (API can return [] or {}) ──
    cat_values = category.get("properties", {}).get("values", {})
    if isinstance(cat_values, dict):
        cat_values.pop("properties", None)
        cat_values["type"] = ["object", "array"]  # type: ignore[assignment]
        cat_values["additionalProperties"] = True

    # Also fix inline response schemas for /categories/{code} and list
    for path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        if "categories" in path or "product" in path:
            for _method, operation in path_item.items():
                if not isinstance(operation, dict):
                    continue
                resp200 = operation.get("responses", {}).get("200", {})
                _fix_values_type(resp200.get("schema", {}))

    # Also remove 'required' from all collection list response item schemas
    # to prevent failures when schemathesis-injected items lack required fields
    for _path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for _method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            resp200 = operation.get("responses", {}).get("200", {})
            _remove_required_from_list_items(resp200.get("schema", {}))

    schema.pop("produces", None)

    # ── 5. Add produces:["application/json"] only to operations that return 200 with a schema body ──
    for _path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for _method, operation in path_item.items():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            responses = operation["responses"]
            has_json_body = any(responses.get(c, {}).get("schema") for c in ("200",))
            if has_json_body and not operation.get("produces"):
                operation["produces"] = ["application/json"]

    # ── 6. Fix AssetFamily.transformations.items.operations — should accept array too ──
    for _path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        if "asset-famil" not in _path:
            continue
        for _method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            resp = operation.get("responses", {}).get("200", {}).get("schema", {})
            _fix_transformations_operations(resp)

    af_def = schema.get("definitions", {}).get("AssetFamily", {})
    _fix_transformations_operations(af_def)

    # ── 7. Fix reference-entities/attributes list: spec expects bare array,
    #        our server returns standard paginated format — accept both ──
    re_attr_paths = [
        "/api/rest/v1/reference-entities/{reference_entity_code}/attributes",
        "/api/rest/v1/asset-families/{asset_family_code}/attributes",
    ]
    for re_path in re_attr_paths:
        path_item = schema.get("paths", {}).get(re_path, {})
        get_op = path_item.get("get", {})
        if get_op and "200" in get_op.get("responses", {}):
            array_schema = get_op["responses"]["200"].get("schema", {})
            if array_schema.get("type") == "array":
                # Accept both bare array and paginated format
                get_op["responses"]["200"]["schema"] = {
                    "oneOf": [
                        array_schema,
                        {"type": "object", "additionalProperties": True},
                    ]
                }

    # ── 8. Fix ALL PATCH bulk response schemas:
    #        spec says object per-line, server returns array — accept both ──
    for _path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        patch_op = path_item.get("patch", {})
        if not isinstance(patch_op, dict) or "responses" not in patch_op:
            continue
        r200 = patch_op["responses"].get("200", {})
        obj_schema = r200.get("schema", {})
        if (
            isinstance(obj_schema, dict)
            and obj_schema.get("type") == "object"
            and "line" in obj_schema.get("properties", {})
        ):
            r200["schema"] = {
                "oneOf": [
                    obj_schema,
                    {"type": "array", "items": obj_schema},
                ]
            }

    # ── 9. Add 201 to POST /jobs/export/{code} and /jobs/import/{code} ──
    jobs_paths = [
        "/api/rest/v1/jobs/export/{code}",
        "/api/rest/v1/jobs/import/{code}",
    ]
    for jp in jobs_paths:
        path_item = schema.get("paths", {}).get(jp, {})
        post_op = path_item.get("post", {})
        if post_op and "201" not in post_op.get("responses", {}):
            post_op.setdefault("responses", {})["201"] = {"description": "Created"}

    # ── 6. Patch all operations: add missing response codes ──

    for _path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            responses = operation["responses"]
            for code, desc in (
                ("400", "Bad Request"),
                ("405", "Method Not Allowed"),
                ("406", "Not Acceptable"),
                ("409", "Conflict"),
                ("413", "Payload Too Large"),
                ("415", "Unsupported Media Type"),
                ("422", "Unprocessable Content"),
            ):
                if code not in responses:
                    responses[code] = {"description": desc}

    with open("pim-api-docs/content/swagger/akeneo-web-api.json", "w") as f:
        json.dump(schema, f, indent=2)
    print("Schema patched successfully.")


if __name__ == "__main__":
    patch_schema()
