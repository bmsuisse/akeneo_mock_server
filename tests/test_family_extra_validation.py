from fastapi.testclient import TestClient
from akeneo_mock_server.app import app

client = TestClient(app)

def test_create_family_with_non_existing_attribute_as_label():
    response = client.post(
        "/api/rest/v1/families",
        json={
            "code": "family_label_fail",
            "attribute_as_label": "non_existing_label_attr"
        }
    )
    assert response.status_code == 422
    assert "non_existing_label_attr" in response.text

def test_create_family_with_non_existing_attribute_as_image():
    response = client.post(
        "/api/rest/v1/families",
        json={
            "code": "family_image_fail",
            "attribute_as_image": "non_existing_image_attr"
        }
    )
    assert response.status_code == 422
    assert "non_existing_image_attr" in response.text

def test_create_family_with_existing_attributes():
    # 1. Create attribute
    client.post("/api/rest/v1/attributes", json={"code": "existing_attr", "type": "pim_catalog_text"})
    
    # 2. Create family with it
    response = client.post(
        "/api/rest/v1/families",
        json={
            "code": "family_success",
            "attributes": ["existing_attr"],
            "attribute_as_label": "existing_attr"
        }
    )
    assert response.status_code == 201

def test_bulk_patch_family_with_non_existing_attribute():
    response = client.patch(
        "/api/rest/v1/families",
        headers={"Content-Type": "application/vnd.akeneo.collection+json"},
        content='{"code": "bulk_family_fail", "attributes": ["non_existing_bulk_attr"]}\n'
    )
    # Status code 200 means the request was processed, but individual items might have failed.
    assert response.status_code == 200
    # The response body should contain the error for the line
    assert '"status_code": 422' in response.text
    assert "non_existing_bulk_attr" in response.text
