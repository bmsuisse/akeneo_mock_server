from fastapi.testclient import TestClient

from akeneo_mock_server.app import app

client = TestClient(app)


def test_page_pagination_on_categories() -> None:
    for code in ["cat-a", "cat-b", "cat-c", "cat-d", "cat-e"]:
        response = client.post("/api/rest/v1/categories", json={"code": code})
        assert response.status_code == 201

    response = client.get("/api/rest/v1/categories", params={"page": 2, "limit": 2})
    assert response.status_code == 200
    body = response.json()

    assert body["current_page"] == 2
    assert len(body["_embedded"]["items"]) == 2
    assert "previous" in body["_links"]
    assert "next" in body["_links"]


def test_search_after_on_products_uuid() -> None:
    payloads = [
        {"uuid": "0001", "identifier": "product-a"},
        {"uuid": "0002", "identifier": "product-b"},
        {"uuid": "0003", "identifier": "product-c"},
    ]
    for payload in payloads:
        response = client.post("/api/rest/v1/products-uuid", json=payload)
        assert response.status_code == 201

    first_page = client.get(
        "/api/rest/v1/products-uuid",
        params={"pagination_type": "search_after", "limit": 2},
    )
    assert first_page.status_code == 200
    first_body = first_page.json()

    first_items = first_body["_embedded"]["items"]
    assert len(first_items) == 2
    assert "next" in first_body["_links"]

    next_href = first_body["_links"]["next"]["href"]
    second_page = client.get(next_href)
    assert second_page.status_code == 200
    second_items = second_page.json()["_embedded"]["items"]
    assert len(second_items) == 1
    assert second_items[0]["identifier"] == "product-c"


def test_search_after_not_available_for_categories() -> None:
    response = client.get(
        "/api/rest/v1/categories",
        params={"pagination_type": "search_after", "limit": 10},
    )
    assert response.status_code == 422


def test_reference_entity_records_default_to_search_after() -> None:
    records_path = "/api/rest/v1/reference-entities/brand/records"
    for code in ["rec-1", "rec-2"]:
        response = client.post(records_path, json={"code": code})
        assert response.status_code == 201

    response = client.get(records_path, params={"limit": 1})
    assert response.status_code == 200
    body = response.json()

    assert "current_page" not in body
    assert body["_links"]["first"]["href"].find("pagination_type=search_after") > 0

    page_response = client.get(records_path, params={"pagination_type": "page"})
    assert page_response.status_code == 422


def test_search_filters_work_with_search_after_pagination() -> None:
    payloads = [
        {"uuid": "a-1", "identifier": "first", "enabled": True},
        {"uuid": "b-1", "identifier": "second", "enabled": False},
        {"uuid": "c-1", "identifier": "third", "enabled": True},
    ]
    for payload in payloads:
        response = client.post("/api/rest/v1/products-uuid", json=payload)
        assert response.status_code == 201

    params = {
        "pagination_type": "search_after",
        "search": '{"enabled":[{"operator":"=","value":true}]}',
        "limit": 1,
    }
    first_page = client.get("/api/rest/v1/products-uuid", params=params)
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert first_body["_embedded"]["items"][0]["identifier"] == "first"

    next_href = first_body["_links"]["next"]["href"]
    second_page = client.get(next_href)
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert second_body["_embedded"]["items"][0]["identifier"] == "third"


def test_reference_entity_attributes_are_not_paginated() -> None:
    parent_code = "brand"
    parent_response = client.post(
        "/api/rest/v1/reference-entities",
        json={"code": parent_code},
    )
    assert parent_response.status_code == 201

    base_path = f"/api/rest/v1/reference-entities/{parent_code}/attributes"
    for code in ["title", "year", "country"]:
        response = client.post(base_path, json={"code": code, "type": "text"})
        assert response.status_code == 201

    response = client.get(base_path, params={"page": 2, "limit": 1, "pagination_type": "page"})
    assert response.status_code == 200
    body = response.json()

    assert isinstance(body, list)
    assert "_embedded" not in body
    assert "_links" not in body
    assert {item["code"] for item in body} == {"title", "year", "country"}


def test_asset_family_attributes_are_not_paginated() -> None:
    family_code = "furniture"
    family_response = client.post(
        "/api/rest/v1/asset-families",
        json={"code": family_code},
    )
    assert family_response.status_code == 201

    base_path = f"/api/rest/v1/asset-families/{family_code}/attributes"
    for code in ["title", "year", "country"]:
        response = client.post(base_path, json={"code": code})
        assert response.status_code == 201

    response = client.get(base_path, params={"page": 2, "limit": 1, "pagination_type": "page"})
    assert response.status_code == 200
    body = response.json()

    assert isinstance(body, list)
    assert "_embedded" not in body
    assert "_links" not in body
    assert {item["code"] for item in body} == {"title", "year", "country"}


def test_three_level_attribute_option_lists_are_not_paginated() -> None:
    response = client.get(
        "/api/rest/v1/reference-entities/brand/attributes/title/options",
        params={"page": 3, "limit": 1, "pagination_type": "page"},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert "_embedded" not in body
    assert "_links" not in body

    asset_response = client.get(
        "/api/rest/v1/asset-families/furniture/attributes/title/options",
        params={"page": 3, "limit": 1, "pagination_type": "page"},
    )
    assert asset_response.status_code == 200
    asset_body = asset_response.json()
    assert isinstance(asset_body, list)
    assert "_embedded" not in asset_body
    assert "_links" not in asset_body


def test_search_after_on_product_models() -> None:
    # Setup family and variant
    client.post("/api/rest/v1/families", json={"code": "pm-fam-pag"})
    client.post(
        "/api/rest/v1/families/pm-fam-pag/variants",
        json={
            "code": "pm-fam-pag-v",
            "variant_attribute_sets": [{"level": 1, "axes": ["color"], "attributes": ["color"]}],
        },
    )

    # Create 3 product models
    for i in range(1, 4):
        code = f"pm-pag-{i}"
        client.post(
            "/api/rest/v1/product-models",
            json={"code": code, "family": "pm-fam-pag", "family_variant": "pm-fam-pag-v"},
        )

    # Get first page with limit 2
    first_page = client.get(
        "/api/rest/v1/product-models",
        params={"pagination_type": "search_after", "limit": 2},
    )
    assert first_page.status_code == 200
    first_body = first_page.json()

    first_items = first_body["_embedded"]["items"]
    assert len(first_items) == 2
    assert "next" in first_body["_links"]
    assert "current_page" not in first_body

    # Get second page
    next_href = first_body["_links"]["next"]["href"]
    second_page = client.get(next_href)
    assert second_page.status_code == 200
    second_body = second_page.json()
    second_items = second_body["_embedded"]["items"]
    assert len(second_items) == 1
    assert second_items[0]["code"] == "pm-pag-3"
    assert "next" not in second_body["_links"]
