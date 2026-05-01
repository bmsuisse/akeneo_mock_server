from fastapi.testclient import TestClient
from akeneo_mock_server.app import app

client = TestClient(app)


def _setup_family_variant(family_code: str, variant_code: str, axes: list[str]):
    client.post("/api/rest/v1/families", json={"code": family_code})
    client.post(
        f"/api/rest/v1/families/{family_code}/variants",
        json={
            "code": variant_code,
            "variant_attribute_sets": [{"level": 1, "axes": axes, "attributes": axes}],
        },
    )


def test_search_after_on_product_models() -> None:
    _setup_family_variant("pm-fam-pagination", "pm-fam-pagination-v", ["color"])

    # Create 5 product models
    for i in range(1, 6):
        code = f"pm-pag-{i}"
        client.post(
            "/api/rest/v1/product-models",
            json={"code": code, "family": "pm-fam-pagination", "family_variant": "pm-fam-pagination-v"},
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
    assert len(second_items) == 2
    assert "next" in second_body["_links"]

    # Get third page
    next_href_2 = second_body["_links"]["next"]["href"]
    third_page = client.get(next_href_2)
    assert third_page.status_code == 200
    third_body = third_page.json()
    third_items = third_body["_embedded"]["items"]
    assert len(third_items) == 1
    assert "next" not in third_body["_links"]
    assert third_items[0]["code"] == "pm-pag-5"


def test_search_after_with_filter_on_product_models() -> None:
    _setup_family_variant("pm-fam-search", "pm-fam-search-v", ["color"])

    # Create 3 product models in this family
    for i in ["a", "b", "c"]:
        client.post(
            "/api/rest/v1/product-models",
            json={"code": f"pm-search-{i}", "family": "pm-fam-search", "family_variant": "pm-fam-search-v"},
        )
    # Create 1 product model in another family
    _setup_family_variant("pm-fam-other", "pm-fam-other-v", ["color"])
    client.post(
        "/api/rest/v1/product-models",
        json={"code": "pm-other", "family": "pm-fam-other", "family_variant": "pm-fam-other-v"},
    )

    params = {
        "pagination_type": "search_after",
        "search": '{"family":[{"operator":"=","value":"pm-fam-search"}]}',
        "limit": 2,
    }

    first_page = client.get("/api/rest/v1/product-models", params=params)
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["_embedded"]["items"]) == 2
    assert "next" in first_body["_links"]

    next_href = first_body["_links"]["next"]["href"]
    second_page = client.get(next_href)
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["_embedded"]["items"]) == 1
    assert second_body["_embedded"]["items"][0]["code"] == "pm-search-c"
