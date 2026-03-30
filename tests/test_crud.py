import pytest
from fastapi.testclient import TestClient
from akeneo_mock_server import database
from akeneo_mock_server.app import app
from akeneo_mock_server.database import init_db

client = TestClient(app)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


class TestProducts:
    def test_list_products_empty(self):
        """GET /products on an empty DB returns an empty items list."""
        res = client.get("/api/rest/v1/products")
        assert res.status_code == 200
        body = res.json()
        assert "_embedded" in body
        assert body["_embedded"]["items"] == []

    def test_create_product(self):
        """POST /products creates a product and returns 201."""
        payload = {"identifier": "test-product-1", "family": "shoes", "enabled": True}
        res = client.post("/api/rest/v1/products", json=payload)
        assert res.status_code == 201
        assert res.headers["location"] == "/api/rest/v1/products/test-product-1"

    def test_get_product_after_create(self):
        """GET /products/{code} returns the product that was just created."""
        payload = {"identifier": "my-product", "family": "tshirts"}
        client.post("/api/rest/v1/products", json=payload)

        res = client.get("/api/rest/v1/products/my-product")
        assert res.status_code == 200
        body = res.json()
        assert body["identifier"] == "my-product"
        assert body["family"] == "tshirts"

    def test_list_products_after_create(self):
        """GET /products returns the created product in the list."""
        client.post("/api/rest/v1/products", json={"identifier": "product-a"})
        client.post("/api/rest/v1/products", json={"identifier": "product-b"})

        res = client.get("/api/rest/v1/products")
        assert res.status_code == 200
        items = res.json()["_embedded"]["items"]
        codes = [p["identifier"] for p in items]
        assert "product-a" in codes
        assert "product-b" in codes

    def test_patch_product(self):
        """PATCH /products/{code} updates an existing product."""
        client.post("/api/rest/v1/products", json={"identifier": "to-patch", "family": "old"})

        res = client.patch("/api/rest/v1/products/to-patch", json={"family": "new", "enabled": False})
        assert res.status_code == 204

        get_res = client.get("/api/rest/v1/products/to-patch")
        assert get_res.status_code == 200
        body = get_res.json()
        assert body["family"] == "new"
        assert body["enabled"] is False

    def test_create_product_with_values(self):
        payload = {
            "identifier": "values-create",
            "family": "shoes",
            "values": {
                "name": [{"locale": None, "scope": None, "data": "Runner"}],
                "description": [{"locale": "en_US", "scope": "ecommerce", "data": "Light shoe"}],
            },
        }

        res = client.post("/api/rest/v1/products", json=payload)
        assert res.status_code == 201

        get_res = client.get("/api/rest/v1/products/values-create")
        assert get_res.status_code == 200
        body = get_res.json()
        assert body["values"]["name"][0]["data"] == "Runner"
        assert body["values"]["description"][0]["data"] == "Light shoe"

    def test_products_and_products_uuid_are_same_resource(self):
        payload = {
            "identifier": "shared-product",
            "family": "shoes",
        }
        create_res = client.post("/api/rest/v1/products", json=payload)
        assert create_res.status_code == 201

        product_res = client.get("/api/rest/v1/products/shared-product")
        assert product_res.status_code == 200
        product_uuid = product_res.json()["uuid"]

        uuid_res = client.get(f"/api/rest/v1/products-uuid/{product_uuid}")
        assert uuid_res.status_code == 200
        assert uuid_res.json()["identifier"] == "shared-product"

    def test_create_via_products_uuid_is_readable_via_products(self):
        payload = {
            "uuid": "shared-uuid-1",
            "identifier": "shared-identifier-1",
            "family": "shoes",
        }
        create_res = client.post("/api/rest/v1/products-uuid", json=payload)
        assert create_res.status_code == 201

        product_res = client.get("/api/rest/v1/products/shared-identifier-1")
        assert product_res.status_code == 200
        assert product_res.json()["uuid"] == "shared-uuid-1"

    def test_uuid_must_be_unique_across_products_endpoints(self):
        first = {
            "uuid": "unique-uuid-1",
            "identifier": "unique-identifier-1",
        }
        second = {
            "identifier": "unique-identifier-2",
            "uuid": "unique-uuid-1",
        }
        assert client.post("/api/rest/v1/products-uuid", json=first).status_code == 201
        assert client.post("/api/rest/v1/products", json=second).status_code == 409

    def test_identifier_must_be_unique_across_products_endpoints(self):
        first = {
            "identifier": "unique-identifier-3",
            "family": "coats",
        }
        second = {
            "uuid": "unique-uuid-3",
            "identifier": "unique-identifier-3",
        }
        assert client.post("/api/rest/v1/products", json=first).status_code == 201
        assert client.post("/api/rest/v1/products-uuid", json=second).status_code == 409

    def test_patch_product_values_merges_instead_of_replacing(self):
        client.post(
            "/api/rest/v1/products",
            json={
                "identifier": "values-merge",
                "values": {
                    "name": [{"locale": None, "scope": None, "data": "Old Name"}],
                    "description": [
                        {
                            "locale": "en_US",
                            "scope": "ecommerce",
                            "data": "Old Description",
                        }
                    ],
                },
            },
        )

        patch_res = client.patch(
            "/api/rest/v1/products/values-merge",
            json={
                "values": {
                    "name": [{"locale": None, "scope": None, "data": "New Name"}],
                    "color": [{"locale": None, "scope": None, "data": "blue"}],
                }
            },
        )
        assert patch_res.status_code == 204

        get_res = client.get("/api/rest/v1/products/values-merge")
        assert get_res.status_code == 200
        body = get_res.json()
        assert body["values"]["name"][0]["data"] == "New Name"
        assert body["values"]["description"][0]["data"] == "Old Description"
        assert body["values"]["color"][0]["data"] == "blue"

    def test_patch_product_without_values_keeps_existing_values(self):
        client.post(
            "/api/rest/v1/products",
            json={
                "identifier": "values-keep",
                "values": {
                    "name": [{"locale": None, "scope": None, "data": "Keep Me"}],
                },
            },
        )

        patch_res = client.patch("/api/rest/v1/products/values-keep", json={"enabled": False})
        assert patch_res.status_code == 204

        get_res = client.get("/api/rest/v1/products/values-keep")
        assert get_res.status_code == 200
        body = get_res.json()
        assert body["enabled"] is False
        assert body["values"]["name"][0]["data"] == "Keep Me"

    def test_patch_product_values_non_dict_returns_422(self):
        client.post(
            "/api/rest/v1/products",
            json={
                "identifier": "values-type-mismatch",
                "values": {
                    "name": [{"locale": None, "scope": None, "data": "Keep"}],
                },
            },
        )

        patch_res = client.patch("/api/rest/v1/products/values-type-mismatch", json={"values": []})
        assert patch_res.status_code == 422

        get_res = client.get("/api/rest/v1/products/values-type-mismatch")
        assert get_res.status_code == 200
        assert get_res.json()["values"]["name"][0]["data"] == "Keep"

    def test_patch_product_values_locale_scope_merge(self):
        client.post(
            "/api/rest/v1/products",
            json={
                "identifier": "multi-locale",
                "values": {
                    "name": [
                        {"locale": "en_US", "scope": None, "data": "Mug"},
                        {"locale": "fr_FR", "scope": None, "data": "Tasse"},
                    ],
                    "short_description": [
                        {
                            "locale": "en_US",
                            "scope": None,
                            "data": "This mug is a must-have!",
                        }
                    ],
                },
            },
        )

        patch_res = client.patch(
            "/api/rest/v1/products/multi-locale",
            json={
                "values": {
                    "name": [
                        {
                            "locale": "fr_FR",
                            "scope": None,
                            "data": "Tasse extraordinaire",
                        }
                    ]
                }
            },
        )
        assert patch_res.status_code == 204

        get_res = client.get("/api/rest/v1/products/multi-locale")
        assert get_res.status_code == 200
        body = get_res.json()
        name_by_locale = {v["locale"]: v["data"] for v in body["values"]["name"]}
        assert name_by_locale["en_US"] == "Mug"
        assert name_by_locale["fr_FR"] == "Tasse extraordinaire"
        assert body["values"]["short_description"][0]["data"] == "This mug is a must-have!"

    def test_patch_null_for_object_field_returns_422(self):
        client.post(
            "/api/rest/v1/products",
            json={
                "identifier": "null-labels",
                "values": {"name": [{"locale": None, "scope": None, "data": "x"}]},
            },
        )

        patch_res = client.patch("/api/rest/v1/products/null-labels", json={"values": None})
        assert patch_res.status_code == 422

    def test_patch_product_upserts_if_not_found(self):
        """PATCH on a non-existent product creates it (upsert behaviour)."""
        res = client.patch("/api/rest/v1/products/new-via-patch", json={"family": "upserted"})
        assert res.status_code == 204

        get_res = client.get("/api/rest/v1/products/new-via-patch")
        assert get_res.status_code == 200
        assert get_res.json()["family"] == "upserted"

    def test_create_duplicate_product_returns_409(self):
        """POST with a duplicate identifier returns 409 Conflict."""
        client.post("/api/rest/v1/products", json={"identifier": "dup"})
        res = client.post("/api/rest/v1/products", json={"identifier": "dup"})
        assert res.status_code == 409

    def test_get_nonexistent_product_returns_404(self):
        """GET /products/{code} for an unknown product returns 404."""
        res = client.get("/api/rest/v1/products/doesnt-exist")
        assert res.status_code == 404

    def test_create_product_missing_identifier_returns_422(self):
        """POST without 'identifier' field returns 422."""
        res = client.post("/api/rest/v1/products", json={"family": "shoes"})
        assert res.status_code == 422

    def test_create_product_null_identifier_returns_422(self):
        """POST with null identifier returns 422 (not a 500 crash)."""
        res = client.post("/api/rest/v1/products", json={"identifier": None})
        assert res.status_code == 422

    def test_create_product_invalid_json_returns_415(self):
        """POST with non-JSON body returns 415."""
        res = client.post(
            "/api/rest/v1/products",
            content=b"not-json-at-all",
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code in (415, 422)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


class TestCategories:
    def test_create_and_get_category(self):
        """POST then GET round-trip for a category."""
        payload = {"code": "cat-shoes", "labels": {"en_US": "Shoes"}}
        res = client.post("/api/rest/v1/categories", json=payload)
        assert res.status_code == 201

        get_res = client.get("/api/rest/v1/categories/cat-shoes")
        assert get_res.status_code == 200
        assert get_res.json()["code"] == "cat-shoes"

    def test_list_categories(self):
        """GET /categories returns all created categories."""
        client.post("/api/rest/v1/categories", json={"code": "cat-a"})
        client.post("/api/rest/v1/categories", json={"code": "cat-b"})

        res = client.get("/api/rest/v1/categories")
        assert res.status_code == 200
        items = res.json()["_embedded"]["items"]
        assert len(items) >= 2

    def test_patch_category(self):
        """PATCH updates an existing category's labels."""
        client.post("/api/rest/v1/categories", json={"code": "c1", "labels": {"en_US": "Old"}})
        client.patch("/api/rest/v1/categories/c1", json={"labels": {"en_US": "New"}})

        res = client.get("/api/rest/v1/categories/c1")
        assert res.status_code == 200
        assert res.json()["labels"]["en_US"] == "New"

    def test_patch_category_labels_merges_locales(self):
        client.post(
            "/api/rest/v1/categories",
            json={"code": "boots", "labels": {"en_US": "Boots", "fr_FR": "Bottes"}},
        )

        patch_res = client.patch("/api/rest/v1/categories/boots", json={"labels": {"de_DE": "Stiefel"}})
        assert patch_res.status_code == 204

        res = client.get("/api/rest/v1/categories/boots")
        assert res.status_code == 200
        labels = res.json()["labels"]
        assert labels["en_US"] == "Boots"
        assert labels["fr_FR"] == "Bottes"
        assert labels["de_DE"] == "Stiefel"


class TestAssociationTypes:
    def test_patch_association_type_uses_path_code(self):
        client.post(
            "/api/rest/v1/association-types",
            json={"code": "upsell", "labels": {"en_US": "Upsell"}, "is_quantified": False, "is_two_way": False},
        )

        patch_res = client.patch(
            "/api/rest/v1/association-types/upsell",
            json={"code": "", "labels": {"fr_FR": "Vente incitative"}},
        )

        assert patch_res.status_code == 204
        get_res = client.get("/api/rest/v1/association-types/upsell")
        assert get_res.status_code == 200
        body = get_res.json()
        assert body["code"] == "upsell"
        assert body["labels"]["en_US"] == "Upsell"
        assert body["labels"]["fr_FR"] == "Vente incitative"

    def test_patch_association_type_coerces_boolean_values(self):
        client.post(
            "/api/rest/v1/association-types",
            json={"code": "cross-sell", "labels": {}, "is_quantified": False, "is_two_way": False},
        )

        patch_res = client.patch(
            "/api/rest/v1/association-types/cross-sell",
            json={"is_quantified": 1, "is_two_way": 0},
        )

        assert patch_res.status_code == 204
        get_res = client.get("/api/rest/v1/association-types/cross-sell")
        assert get_res.status_code == 200
        body = get_res.json()
        assert body["is_quantified"] is True
        assert body["is_two_way"] is False

    def test_patch_category_labels_null_returns_422(self):
        client.post(
            "/api/rest/v1/categories",
            json={
                "code": "boots-null",
                "labels": {"en_US": "Boots", "fr_FR": "Bottes"},
            },
        )

        patch_res = client.patch("/api/rest/v1/categories/boots-null", json={"labels": None})
        assert patch_res.status_code == 422

        get_res = client.get("/api/rest/v1/categories/boots-null")
        assert get_res.json()["labels"]["en_US"] == "Boots"


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------


class TestAttributes:
    def test_create_and_get_attribute(self):
        """POST then GET for an attribute."""
        payload = {"code": "attr-color", "type": "pim_catalog_text"}
        res = client.post("/api/rest/v1/attributes", json=payload)
        assert res.status_code == 201

        res = client.get("/api/rest/v1/attributes/attr-color")
        assert res.status_code == 200
        assert res.json()["code"] == "attr-color"

    def test_list_attributes(self):
        """GET /attributes returns all created attributes."""
        client.post("/api/rest/v1/attributes", json={"code": "a1", "type": "pim_catalog_text"})
        res = client.get("/api/rest/v1/attributes")
        assert res.status_code == 200
        items = res.json()["_embedded"]["items"]
        assert any(i["code"] == "a1" for i in items)


# ---------------------------------------------------------------------------
# Families (sub-entity: variants)
# ---------------------------------------------------------------------------


class TestFamilies:
    def test_create_family_and_list(self):
        """POST + GET /families."""
        client.post("/api/rest/v1/families", json={"code": "fam-summer"})
        res = client.get("/api/rest/v1/families")
        assert res.status_code == 200
        items = res.json()["_embedded"]["items"]
        assert any(i["code"] == "fam-summer" for i in items)

    def test_create_family_variant(self):
        """POST /families/{code}/variants creates a variant."""
        client.post("/api/rest/v1/families", json={"code": "fam-x"})
        res = client.post(
            "/api/rest/v1/families/fam-x/variants",
            json={"code": "var-1", "variant_attribute_sets": []},
        )
        assert res.status_code == 201

        get_res = client.get("/api/rest/v1/families/fam-x/variants")
        assert get_res.status_code == 200
        items = get_res.json()["_embedded"]["items"]
        assert any(i["code"] == "var-1" for i in items)
