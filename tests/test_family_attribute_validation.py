from fastapi.testclient import TestClient
from akeneo_mock_server.app import app

client = TestClient(app)


def test_create_family_with_non_existing_attribute():
    # Attempt to create a family with an attribute that does not exist
    response = client.post(
        "/api/rest/v1/families",
        json={"code": "family_with_non_existing_attribute", "attributes": ["non_existing_attribute"]},
    )
    # According to the requirement, this should fail.
    # Currently it probably returns 201 Created.
    assert response.status_code == 422
    assert "non_existing_attribute" in response.text


def test_patch_family_with_non_existing_attribute():
    # 1. Create a valid family
    client.post("/api/rest/v1/families", json={"code": "valid_family", "attributes": []})

    # 2. Patch it with a non-existing attribute
    response = client.patch(
        "/api/rest/v1/families/valid_family", json={"attributes": ["another_non_existing_attribute"]}
    )
    assert response.status_code == 422
    assert "another_non_existing_attribute" in response.text
