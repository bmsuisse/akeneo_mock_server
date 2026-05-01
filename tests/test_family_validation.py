"""Test to understand family attribute validation requirements"""
from fastapi.testclient import TestClient
from akeneo_mock_server.app import app

client = TestClient(app)

def test_product_update_with_attribute_not_in_family_should_fail():
    """A product update should fail if an attribute is not part of the product's family"""
    family_code = "test-family-1"
    attr_code_1 = "attr-in-family"
    attr_code_2 = "attr-not-in-family"
    product_code = "product-1"

    r = client.post("/api/rest/v1/attributes", json={"code": attr_code_1, "type": "pim_catalog_text"})
    assert r.status_code == 201
    
    r = client.post("/api/rest/v1/attributes", json={"code": attr_code_2, "type": "pim_catalog_text"})
    assert r.status_code == 201

    r = client.post(
        "/api/rest/v1/families",
        json={
            "code": family_code,
            "attributes": [attr_code_1],
            "attribute_as_label": attr_code_1
        }
    )
    assert r.status_code == 201

    r = client.post(
        "/api/rest/v1/products",
        json={
            "identifier": product_code,
            "family": family_code,
            "values": {
                attr_code_1: [{"data": "test value", "locale": None, "scope": None}]
            }
        }
    )
    assert r.status_code == 201

    r = client.patch(
        f"/api/rest/v1/products/{product_code}",
        json={
            "values": {
                attr_code_2: [{"data": "value for attr not in family", "locale": None, "scope": None}]
            }
        }
    )
    print(f"Response status: {r.status_code}")
    print(f"Response body: {r.text}")
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"

def test_products_uuid_update_with_attribute_not_in_family_should_fail():
    """A products-uuid update should fail if an attribute is not part of the product's family"""
    family_code = "test-family-2"
    attr_code_1 = "attr-in-family-2"
    attr_code_2 = "attr-not-in-family-2"
    product_uuid = "12345678-1234-1234-1234-123456789012"
    product_identifier = "product-uuid-1"

    r = client.post("/api/rest/v1/attributes", json={"code": attr_code_1, "type": "pim_catalog_text"})
    assert r.status_code == 201
    
    r = client.post("/api/rest/v1/attributes", json={"code": attr_code_2, "type": "pim_catalog_text"})
    assert r.status_code == 201

    r = client.post(
        "/api/rest/v1/families",
        json={
            "code": family_code,
            "attributes": [attr_code_1],
            "attribute_as_label": attr_code_1
        }
    )
    assert r.status_code == 201

    r = client.post(
        "/api/rest/v1/products-uuid",
        json={
            "uuid": product_uuid,
            "identifier": product_identifier,
            "family": family_code,
            "values": {
                attr_code_1: [{"data": "test value", "locale": None, "scope": None}]
            }
        }
    )
    assert r.status_code == 201

    r = client.patch(
        f"/api/rest/v1/products-uuid/{product_uuid}",
        json={
            "values": {
                attr_code_2: [{"data": "value for attr not in family", "locale": None, "scope": None}]
            }
        }
    )
    print(f"Response status: {r.status_code}")
    print(f"Response body: {r.text}")
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
