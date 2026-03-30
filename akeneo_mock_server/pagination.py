from typing import Any, Mapping
from urllib.parse import urlencode

from fastapi import HTTPException

SEARCH_AFTER_ENTITIES = frozenset(
    {
        "products",
        "products-uuid",
        "published-products",
        "product-models",
        "assets",
        "asset-families",
        "reference-entities",
    }
)

SEARCH_AFTER_ONLY_ENTITIES = frozenset({"reference-entities"})

SEARCH_AFTER_SUB_ENTITIES = frozenset(
    {
        "reference-entities/records",
        "asset-families/assets",
    }
)

SEARCH_AFTER_ONLY_SUB_ENTITIES = frozenset({"reference-entities/records"})


def supports_search_after_entity(entity_name: str) -> bool:
    return entity_name in SEARCH_AFTER_ENTITIES


def is_search_after_only_entity(entity_name: str) -> bool:
    return entity_name in SEARCH_AFTER_ONLY_ENTITIES


def supports_search_after_sub_entity(sub_entity_key: str) -> bool:
    return sub_entity_key in SEARCH_AFTER_SUB_ENTITIES


def is_search_after_only_sub_entity(sub_entity_key: str) -> bool:
    return sub_entity_key in SEARCH_AFTER_ONLY_SUB_ENTITIES


def validate_limit(limit: int) -> None:
    if limit > 100:
        raise HTTPException(status_code=422, detail="You cannot request more than 100 items.")
    if limit < 1:
        raise HTTPException(status_code=422, detail="`limit` must be greater than 0.")


def resolve_pagination_type(
    pagination_type: str | None,
    *,
    supports_search_after: bool,
    search_after_only: bool,
) -> str:
    if pagination_type is None:
        if search_after_only:
            return "search_after"
        return "page"
    if pagination_type not in {"page", "search_after"}:
        raise HTTPException(status_code=422, detail="`pagination_type` must be `page` or `search_after`.")
    if pagination_type == "search_after" and not supports_search_after:
        raise HTTPException(status_code=422, detail="`search_after` pagination is not available.")
    if pagination_type == "page" and search_after_only:
        raise HTTPException(status_code=422, detail="`page` pagination is not available.")
    return pagination_type


def paginate_page(
    entries: list[tuple[str, dict[str, Any]]],
    page: int,
    limit: int,
) -> tuple[list[dict[str, Any]], bool, bool]:
    if page < 1:
        raise HTTPException(status_code=422, detail="`page` must be greater than 0.")
    offset = (page - 1) * limit
    page_items = [entity for _, entity in entries[offset : offset + limit]]
    has_previous = page > 1 and len(entries) > 0
    has_next = offset + limit < len(entries)
    return page_items, has_previous, has_next


def paginate_search_after(
    entries: list[tuple[str, dict[str, Any]]],
    search_after: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None]:
    offset = 0
    if search_after is not None:
        for index, (cursor, _) in enumerate(entries):
            if cursor > search_after:
                offset = index
                break
        else:
            return [], None

    selected_entries = entries[offset : offset + limit]
    selected_items = [entity for _, entity in selected_entries]
    if len(selected_entries) < limit or offset + limit >= len(entries):
        return selected_items, None
    return selected_items, selected_entries[-1][0]


def build_href(path: str, params: Mapping[str, str | int | None]) -> str:
    query_params = {key: value for key, value in params.items() if value is not None}
    if len(query_params) == 0:
        return path
    query = urlencode(query_params)
    return f"{path}?{query}"
