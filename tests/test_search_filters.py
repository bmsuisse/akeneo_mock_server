from typing import Any
from fastapi.testclient import TestClient

from akeneo_mock_server.app import app

client = TestClient(app)


def _create_product_uuid(payload: dict[str, Any]) -> None:
    response = client.post("/api/rest/v1/products-uuid", json=payload)
    assert response.status_code == 201


def _list_products_uuid(params: dict[str, str]) -> list[dict[str, Any]]:
    response = client.get("/api/rest/v1/products-uuid", params=params)
    assert response.status_code == 200
    return response.json()["_embedded"]["items"]


def test_filter_on_enabled_and_categories():
    _create_product_uuid(
        {
            "uuid": "8945388d-cf5b-49af-8799-05d1ed6e296f",
            "identifier": "winter-shirt",
            "enabled": True,
            "categories": ["winter_collection"],
        }
    )
    _create_product_uuid(
        {
            "uuid": "941fe892-99dd-440f-b2a9-8eccb94248f0",
            "identifier": "summer-hat",
            "enabled": False,
            "categories": ["accessories"],
        }
    )

    items = _list_products_uuid(
        {
            "search": '{"enabled":[{"operator":"=","value":true}],"categories":[{"operator":"IN","value":["winter_collection"]}]}'
        }
    )
    assert len(items) == 1
    assert items[0]["identifier"] == "winter-shirt"


def test_filter_on_values_with_search_locale_and_scope():
    _create_product_uuid(
        {
            "uuid": "0a84fa5a-d45d-4294-a0b7-56c7a00e4f77",
            "identifier": "french-only",
            "values": {"name": [{"locale": "fr_FR", "scope": "ecommerce", "data": "Chemise"}]},
        }
    )
    _create_product_uuid(
        {
            "uuid": "9ebeb0d4-1917-420f-ab5e-f5a26722f7fa",
            "identifier": "english-ecommerce",
            "values": {
                "name": [
                    {"locale": "en_US", "scope": "ecommerce", "data": "Shirt"},
                    {"locale": "en_US", "scope": "mobile", "data": "Top"},
                ]
            },
        }
    )

    items = _list_products_uuid(
        {
            "search": '{"name":[{"operator":"CONTAINS","value":"shirt"}]}',
            "search_locale": "en_US",
            "search_scope": "ecommerce",
        }
    )
    assert len(items) == 1
    assert items[0]["identifier"] == "english-ecommerce"


def test_value_projection_with_attributes_locales_and_scope():
    _create_product_uuid(
        {
            "uuid": "91f31a9e-f2d4-4078-9d8f-0b4d9bf05cc1",
            "identifier": "projection-test",
            "values": {
                "name": [
                    {"locale": "en_US", "scope": "ecommerce", "data": "Desk"},
                    {"locale": "fr_FR", "scope": "ecommerce", "data": "Bureau"},
                ],
                "description": [{"locale": "en_US", "scope": "mobile", "data": "Compact desk"}],
            },
        }
    )

    items = _list_products_uuid(
        {
            "attributes": "name",
            "locales": "en_US",
            "scope": "ecommerce",
        }
    )
    assert len(items) == 1
    values = items[0]["values"]
    assert set(values.keys()) == {"name"}
    assert len(values["name"]) == 1
    assert values["name"][0]["locale"] == "en_US"
    assert values["name"][0]["scope"] == "ecommerce"


def test_invalid_search_json_returns_422():
    response = client.get("/api/rest/v1/products-uuid", params={"search": "{"})
    assert response.status_code == 422
