import json
from fastapi.testclient import TestClient
from akeneo_mock_server.app import app

client = TestClient(app)


def test_patch_attribute_options_collection_json():
    attribute_code = "color_attr"

    # 1. Create a select attribute
    response = client.post(
        "/api/rest/v1/attributes",
        json={"code": attribute_code, "type": "pim_catalog_simpleselect"},
    )
    assert response.status_code == 201

    # 2. PATCH multiple options using application/json
    options_payload = [
        {"code": "red", "labels": {"en_US": "Red", "fr_FR": "Rouge"}},
        {"code": "blue", "labels": {"en_US": "Blue", "fr_FR": "Bleu"}},
    ]
    response = client.patch(f"/api/rest/v1/attributes/{attribute_code}/options", json=options_payload)
    assert response.status_code == 200
    assert response.json() == [
        {"line": 1, "code": "red", "status_code": 201},
        {"line": 2, "code": "blue", "status_code": 201},
    ]

    # 3. Verify with GET collection
    response = client.get(f"/api/rest/v1/attributes/{attribute_code}/options")
    assert response.status_code == 200
    items = response.json()["_embedded"]["items"]
    codes = [item["code"] for item in items]
    assert "red" in codes
    assert "blue" in codes

    # 4. Verify with GET single item
    response = client.get(f"/api/rest/v1/attributes/{attribute_code}/options/red")
    assert response.status_code == 200
    assert response.json()["labels"]["fr_FR"] == "Rouge"

    # 5. PATCH to update existing and add new
    update_payload = [
        {"code": "red", "labels": {"en_US": "Bright Red"}},
        {"code": "green", "labels": {"en_US": "Green"}},
    ]
    response = client.patch(f"/api/rest/v1/attributes/{attribute_code}/options", json=update_payload)
    assert response.status_code == 200
    assert response.json() == [
        {"line": 1, "code": "red", "status_code": 204},  # 204 for update
        {"line": 2, "code": "green", "status_code": 201},  # 201 for create
    ]

    response = client.get(f"/api/rest/v1/attributes/{attribute_code}/options")
    assert response.status_code == 200
    items = response.json()["_embedded"]["items"]
    codes = [item["code"] for item in items]
    assert "red" in codes
    assert "green" in codes
    assert "blue" in codes

    # 6. Verify update
    response = client.get(f"/api/rest/v1/attributes/{attribute_code}/options/red")
    assert response.status_code == 200
    assert response.json()["labels"]["en_US"] == "Bright Red"
    # Note: Depending on implementation, fr_FR might be gone if it's a full replace OR merged.
    # In rest.py: existing.update(data) -> it's a merge of top level keys.
    # labels is a dict, so existing["labels"].update(data["labels"]) would be deeper merge.
    # Let's see what it does.
    assert response.json()["labels"]["fr_FR"] == "Rouge"


def test_patch_attribute_option_single():
    attribute_code = "size_attr"

    # 1. Create a select attribute
    client.post(
        "/api/rest/v1/attributes",
        json={"code": attribute_code, "type": "pim_catalog_simpleselect"},
    )

    # 2. PATCH single option
    response = client.patch(
        f"/api/rest/v1/attributes/{attribute_code}/options/small", json={"labels": {"en_US": "Small"}}
    )
    assert response.status_code == 204

    # 3. Verify
    response = client.get(f"/api/rest/v1/attributes/{attribute_code}/options/small")
    assert response.status_code == 200
    assert response.json()["code"] == "small"
    assert response.json()["labels"] == {"en_US": "Small"}

    # 4. Update
    response = client.patch(f"/api/rest/v1/attributes/{attribute_code}/options/small", json={"sort_order": 10})
    assert response.status_code == 204

    # 5. Verify update
    response = client.get(f"/api/rest/v1/attributes/{attribute_code}/options/small")
    assert response.status_code == 200
    assert response.json()["sort_order"] == 10
    assert response.json()["labels"] == {"en_US": "Small"}  # Labels should be preserved


def test_patch_attribute_options_collection_vnd_json():
    attribute_code = "material_attr"

    # 1. Create a select attribute
    client.post(
        "/api/rest/v1/attributes",
        json={"code": attribute_code, "type": "pim_catalog_simpleselect"},
    )

    # 2. PATCH multiple options using application/vnd.akeneo.collection+json (NDJSON)
    payload = '{"code": "wood", "labels": {"en_US": "Wood"}}\n{"code": "metal", "labels": {"en_US": "Metal"}}'
    response = client.patch(
        f"/api/rest/v1/attributes/{attribute_code}/options",
        content=payload,
        headers={"Content-Type": "application/vnd.akeneo.collection+json"},
    )
    assert response.status_code == 200

    # Response should also be in vnd.akeneo.collection+json format (lines of JSON)
    lines = response.text.strip().split("\n")
    assert len(lines) == 2
    res1 = json.loads(lines[0])
    res2 = json.loads(lines[1])
    assert res1["code"] == "wood"
    assert res1["status_code"] == 201
    assert res2["code"] == "metal"
    assert res2["status_code"] == 201

    # 3. Verify with GET collection
    response = client.get(f"/api/rest/v1/attributes/{attribute_code}/options")
    assert response.status_code == 200
    items = response.json()["_embedded"]["items"]
    codes = {item["code"] for item in items}
    assert "wood" in codes
    assert "metal" in codes

    # 4. Update one and add another
    update_payload = (
        '{"code": "wood", "labels": {"en_US": "Fine Wood"}}\n{"code": "plastic", "labels": {"en_US": "Plastic"}}'
    )
    response = client.patch(
        f"/api/rest/v1/attributes/{attribute_code}/options",
        content=update_payload,
        headers={"Content-Type": "application/vnd.akeneo.collection+json"},
    )
    assert response.status_code == 200
    lines = response.text.strip().split("\n")
    res1 = json.loads(lines[0])
    res2 = json.loads(lines[1])
    assert res1["code"] == "wood"
    assert res1["status_code"] == 204
    assert res2["code"] == "plastic"
    assert res2["status_code"] == 201

    # 5. Verify updates
    response = client.get(f"/api/rest/v1/attributes/{attribute_code}/options/wood")
    assert response.status_code == 200
    assert response.json()["labels"]["en_US"] == "Fine Wood"


def test_patch_attribute_options_invalid_attribute_type():
    attribute_code = "text_attr"

    # 1. Create a text attribute (doesn't support options)
    client.post(
        "/api/rest/v1/attributes",
        json={"code": attribute_code, "type": "pim_catalog_text"},
    )

    # 2. Attempt to PATCH options
    response = client.patch(
        f"/api/rest/v1/attributes/{attribute_code}/options",
        json=[{"code": "opt1"}],
    )
    assert response.status_code == 422
    assert "does not support options" in response.json()["detail"]
