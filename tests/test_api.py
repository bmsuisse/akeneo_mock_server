import json

import pytest
import psycopg
from fastapi.testclient import TestClient

from akeneo_mock_server.app import app
from akeneo_mock_server.database import MODELS, SUB_MODELS, get_db

ENTITY_TEST_DATA = {
    "products": {"enabled": False},
    "products-uuid": {"enabled": False},
    "published-products": {"enabled": False},
    "categories": {"position": 99},
    "attributes": {"type": "pim_catalog_text"},
    "attribute-groups": {"sort_order": 99},
    "families": {"attribute_as_label": "my_label"},
    "channels": {"category_tree": "master"},
    "locales": {"enabled": True},
    "currencies": {"enabled": True},
    "measure-families": {"standard": "METER"},
    "measurement-families": {"standard_unit_code": "METER"},
    "association-types": {"is_quantified": True},
    "reference-entities": {"image": "test.jpg"},
    "asset-families": {},
    "product-models": {"family_variant": "shirt_variant"},
}

client = TestClient(app)


def test_psycopg_undefined_table_returns_500_with_details():
    no_raise_client = TestClient(app, raise_server_exceptions=False)

    def broken_db_dependency():
        raise psycopg.errors.UndefinedTable('relation "products" does not exist')

    app.dependency_overrides[get_db] = broken_db_dependency
    try:
        response = no_raise_client.get("/api/rest/v1/products")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 500
    payload = response.json()
    assert payload["code"] == 500
    assert payload["message"] == "Internal Server Error"
    assert payload["details"]["exception_type"] == "UndefinedTable"
    assert "does not exist" in payload["details"]["exception_message"]


def test_root():
    response = client.get("/api/rest/v1")
    assert response.status_code == 200
    assert "authentication" in response.json()


def test_ndjson_patch_products():
    """Verify that multiple products can be patched via NDJSON (non-standard Akeneo but common)."""
    ndjson_data = '{"identifier": "p1", "enabled": true}\n{"identifier": "p2", "enabled": false}\n'
    response = client.patch(
        "/api/rest/v1/products",
        content=ndjson_data,
        headers={"Content-Type": "application/x-ndjson"},
    )
    assert response.status_code == 200


@pytest.mark.parametrize("entity_name, config", MODELS.items())
def test_generic_entity_endpoints(entity_name, config):
    pk_field = config["pk_field"]
    test_code = f"test-{entity_name}-1"

    # Create
    create_data = {pk_field: test_code, **ENTITY_TEST_DATA.get(entity_name, {})}
    if entity_name == "products-uuid":
        create_data["identifier"] = f"identifier-{test_code}"
    response = client.post(f"/api/rest/v1/{entity_name}", json=create_data)
    assert response.status_code == 201
    assert response.headers["Location"] == f"/api/rest/v1/{entity_name}/{test_code}"

    # Read
    response = client.get(f"/api/rest/v1/{entity_name}/{test_code}")
    assert response.status_code == 200
    assert response.json()[pk_field] == test_code

    # Patch (Single)
    patch_data = ENTITY_TEST_DATA.get(entity_name, {})
    response = client.patch(f"/api/rest/v1/{entity_name}/{test_code}", json=patch_data)
    assert response.status_code == 204
    assert response.headers["Location"] == f"/api/rest/v1/{entity_name}/{test_code}"

    # Verify Patch
    response = client.get(f"/api/rest/v1/{entity_name}/{test_code}")
    assert response.status_code == 200

    # List
    response = client.get(f"/api/rest/v1/{entity_name}")
    assert response.status_code == 200
    data = response.json()
    items = data["_embedded"]["items"]
    assert any(item[pk_field] == test_code for item in items)

    # Delete
    response = client.delete(f"/api/rest/v1/{entity_name}/{test_code}")
    assert response.status_code == 204
    response = client.get(f"/api/rest/v1/{entity_name}/{test_code}")
    assert response.status_code == 404


@pytest.mark.parametrize("sub_entity_path, config", SUB_MODELS.items())
def test_generic_sub_entity_endpoints(sub_entity_path, config):
    if "parent_entity" not in config:
        pytest.skip("Not a sub-entity")

    parent_entity = config["parent_entity"]
    nested_path = config["nested_path"]
    pk_field = config["pk_field"]

    parent_code = f"parent-{parent_entity}-1"
    test_code = f"test-{nested_path}-1"
    base_path = f"/api/rest/v1/{parent_entity}/{parent_code}/{nested_path}"

    if parent_entity in MODELS:
        parent_pk = MODELS[parent_entity]["pk_field"]
        if sub_entity_path == "attributes/attribute-options":
            parent_response = client.post(
                f"/api/rest/v1/{parent_entity}",
                json={parent_pk: parent_code, "type": "pim_catalog_simpleselect"},
            )
            print("attribute parent create response:", parent_response.status_code, parent_response.text)
            assert parent_response.status_code == 201, (
                f"parent create failed with {parent_response.status_code}: {parent_response.text}"
            )
        else:
            client.post(f"/api/rest/v1/{parent_entity}", json={parent_pk: parent_code})

    # Create
    create_data = {pk_field: test_code, "updated": False}
    response = client.post(base_path, json=create_data)
    if sub_entity_path == "attributes/attribute-options":
        print("attribute option create response:", response.status_code, response.text)
    assert response.status_code == 201, f"create failed with {response.status_code}: {response.text}"
    assert response.headers["Location"] == f"{base_path}/{test_code}"

    # Read
    response = client.get(f"{base_path}/{test_code}")
    assert response.status_code == 200
    assert response.json()[pk_field] == test_code

    # Patch (Single)
    patch_data = {"updated": True}
    response = client.patch(f"{base_path}/{test_code}", json=patch_data)
    assert response.status_code == 204

    # Verify Patch
    response = client.get(f"{base_path}/{test_code}")
    assert response.status_code == 200

    # List
    response = client.get(base_path)
    assert response.status_code == 200
    data = response.json()
    if sub_entity_path in {"reference-entities/attributes", "asset-families/attributes"}:
        assert isinstance(data, list)
        items = data
    else:
        items = data["_embedded"]["items"]
    assert any(item[pk_field] == test_code for item in items)


def test_media_endpoints():
    # Category Media
    res = client.post("/api/rest/v1/category-media-files")
    assert res.status_code == 201
    loc = res.headers["Location"]
    code = loc.split("/")[-1]

    res = client.get(f"/api/rest/v1/category-media-files/{code}/download")
    assert res.status_code == 200
    assert b"mock-binary-content" in res.content


def test_patch_attribute_option_requires_select_attribute_type():
    valid_attribute_code = "attr-select-type"
    invalid_attribute_code = "attr-text-type"
    option_code = "black"

    create_valid_attribute = client.post(
        "/api/rest/v1/attributes",
        json={"code": valid_attribute_code, "type": "pim_catalog_simpleselect"},
    )
    assert create_valid_attribute.status_code == 201

    patch_valid_option = client.patch(
        f"/api/rest/v1/attributes/{valid_attribute_code}/options/{option_code}",
        json={"labels": {"en_US": "Black"}},
    )
    print("patch valid option response:", patch_valid_option.status_code, patch_valid_option.text)
    assert patch_valid_option.status_code == 204, (
        f"valid option patch failed with {patch_valid_option.status_code}: {patch_valid_option.text}"
    )

    create_invalid_attribute = client.post(
        "/api/rest/v1/attributes",
        json={"code": invalid_attribute_code, "type": "pim_catalog_text"},
    )
    assert create_invalid_attribute.status_code == 201

    patch_invalid_option = client.patch(
        f"/api/rest/v1/attributes/{invalid_attribute_code}/options/{option_code}",
        json={"labels": {"en_US": "Black"}},
    )
    print("patch invalid option response:", patch_invalid_option.status_code, patch_invalid_option.text)
    assert patch_invalid_option.status_code == 422, (
        f"invalid option patch failed with {patch_invalid_option.status_code}: {patch_invalid_option.text}"
    )
    assert "does not support options" in patch_invalid_option.json()["detail"]


def test_patch_attribute_options_collection_content_type():
    attribute_code = "attr-select-collection"

    create_attribute = client.post(
        "/api/rest/v1/attributes",
        json={"code": attribute_code, "type": "pim_catalog_simpleselect"},
    )
    assert create_attribute.status_code == 201

    response = client.patch(
        f"/api/rest/v1/attributes/{attribute_code}/options",
        headers={"Content-Type": "application/vnd.akeneo.collection+json"},
        data="\n".join(
            [
                json.dumps({"code": "black", "labels": {"en_US": "Black"}}),
                json.dumps({"code": "white", "labels": {"en_US": "White"}}),
            ]
        ),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.akeneo.collection+json")
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert lines == [
        {"line": 1, "code": "black", "status_code": 201},
        {"line": 2, "code": "white", "status_code": 201},
    ]

    black_option_response = client.get(f"/api/rest/v1/attributes/{attribute_code}/options/black")
    assert black_option_response.status_code == 200
    assert black_option_response.json()["labels"] == {"en_US": "Black"}


def test_get_attribute_returns_table_configuration():
    attribute_code = "attr-table-config"
    table_configuration = [
        {"code": "ingredient", "data_type": "select"},
        {"code": "percentage", "data_type": "number"},
    ]

    create_response = client.post(
        "/api/rest/v1/attributes",
        json={
            "code": attribute_code,
            "type": "pim_catalog_table",
            "table_configuration": table_configuration,
        },
    )
    assert create_response.status_code == 201

    get_response = client.get(f"/api/rest/v1/attributes/{attribute_code}")
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["code"] == attribute_code
    assert payload["type"] == "pim_catalog_table"
    assert payload["table_configuration"] == table_configuration


def test_get_attribute_with_table_select_options():
    attribute_code = "attr-table-with-options"
    table_configuration = [
        {
            "code": "ingredient",
            "data_type": "select",
            "validations": {
                "select_options": [
                    {"code": "ing-1", "labels": {"en_US": "Sugar"}},
                    {"code": "ing-2", "labels": {"en_US": "Salt"}},
                ]
            },
        },
        {"code": "percentage", "data_type": "number"},
    ]

    create_response = client.post(
        "/api/rest/v1/attributes",
        json={
            "code": attribute_code,
            "type": "pim_catalog_table",
            "table_configuration": table_configuration,
        },
    )
    assert create_response.status_code == 201

    get_response = client.get(
        f"/api/rest/v1/attributes/{attribute_code}",
        params={"with_table_select_options": "true"},
    )
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["code"] == attribute_code
    assert payload["table_configuration"] == table_configuration


def test_get_attribute_without_table_select_options():
    attribute_code = "attr-table-without-options"
    table_configuration = [
        {
            "code": "ingredient",
            "data_type": "select",
            "validations": {
                "select_options": [
                    {"code": "ing-1", "labels": {"en_US": "Sugar"}},
                    {"code": "ing-2", "labels": {"en_US": "Salt"}},
                ],
                "max": 10,
            },
        },
        {"code": "percentage", "data_type": "number"},
    ]

    create_response = client.post(
        "/api/rest/v1/attributes",
        json={
            "code": attribute_code,
            "type": "pim_catalog_table",
            "table_configuration": table_configuration,
        },
    )
    assert create_response.status_code == 201

    get_response = client.get(
        f"/api/rest/v1/attributes/{attribute_code}",
        params={"with_table_select_options": "false"},
    )
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["code"] == attribute_code
    select_column = payload["table_configuration"][0]
    assert select_column["data_type"] == "select"
    assert select_column["validations"].get("max") == 10
    assert "select_options" not in select_column["validations"]


def test_ee_workflows():
    # Draft & Proposal
    res = client.get("/api/rest/v1/products/p1/draft")
    assert res.status_code == 200
    assert res.json()["status"] == "in_progress"

    res = client.post("/api/rest/v1/products/p1/proposal")
    assert res.status_code == 201
    assert "proposal/1" in res.headers["Location"]


def test_jobs():
    res = client.post("/api/rest/v1/jobs/export/my_export")
    assert res.status_code == 201
    assert "executions/1" in res.headers["Location"]


def test_discovery():
    res = client.get("/api/rest/v1")
    assert res.status_code == 200
    assert res.json()["host"] == "127.0.0.1:8000"


def test_event_platform_webhooks():
    # Subscriber
    subscriber_id = "sub1"
    res = client.post("/api/v1/subscribers", json={"id": subscriber_id, "url": "http://webhook.site/test"})
    assert res.status_code == 201

    res = client.get(f"/api/v1/subscribers/{subscriber_id}")
    assert res.status_code == 200
    assert res.json()["id"] == subscriber_id

    # List
    res = client.get("/api/v1/subscribers")
    assert res.status_code == 200
    assert any(s["id"] == subscriber_id for s in res.json()["items"])

    # Patch
    res = client.patch(f"/api/v1/subscribers/{subscriber_id}", json={"url": "http://webhook.site/updated"})
    assert res.status_code == 204

    # Delete Subscriber
    res = client.delete(f"/api/v1/subscribers/{subscriber_id}")
    assert res.status_code == 204

    res = client.get(f"/api/v1/subscribers/{subscriber_id}")
    assert res.status_code == 404
