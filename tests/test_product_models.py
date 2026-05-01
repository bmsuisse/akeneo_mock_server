import json

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


class TestProductModels:
    def test_create_product_model_returns_201(self):
        _setup_family_variant("pm-fam-1", "pm-fam-1-color", ["color"])
        res = client.post(
            "/api/rest/v1/product-models",
            json={"code": "pm-1", "family": "pm-fam-1", "family_variant": "pm-fam-1-color"},
        )
        assert res.status_code == 201

    def test_get_product_model_by_code(self):
        _setup_family_variant("pm-fam-2", "pm-fam-2-size", ["size"])
        client.post(
            "/api/rest/v1/product-models",
            json={"code": "pm-2", "family": "pm-fam-2", "family_variant": "pm-fam-2-size"},
        )
        res = client.get("/api/rest/v1/product-models/pm-2")
        assert res.status_code == 200
        body = res.json()
        assert body["code"] == "pm-2"
        assert body["family"] == "pm-fam-2"
        assert body["family_variant"] == "pm-fam-2-size"

    def test_get_product_model_not_found(self):
        res = client.get("/api/rest/v1/product-models/nonexistent-pm")
        assert res.status_code == 404

    def test_list_product_models(self):
        _setup_family_variant("pm-fam-3", "pm-fam-3-v", ["color"])
        client.post(
            "/api/rest/v1/product-models",
            json={"code": "pm-list-a", "family": "pm-fam-3", "family_variant": "pm-fam-3-v"},
        )
        client.post(
            "/api/rest/v1/product-models",
            json={"code": "pm-list-b", "family": "pm-fam-3", "family_variant": "pm-fam-3-v"},
        )
        res = client.get("/api/rest/v1/product-models")
        assert res.status_code == 200
        codes = {item["code"] for item in res.json()["_embedded"]["items"]}
        assert "pm-list-a" in codes
        assert "pm-list-b" in codes

    def test_create_product_model_with_categories_and_values(self):
        _setup_family_variant("pm-fam-4", "pm-fam-4-v", ["color"])
        payload = {
            "code": "pm-4",
            "family": "pm-fam-4",
            "family_variant": "pm-fam-4-v",
            "categories": ["master"],
            "values": {"name": [{"locale": "en_US", "scope": None, "data": "My Model"}]},
        }
        client.post("/api/rest/v1/product-models", json=payload)

        body = client.get("/api/rest/v1/product-models/pm-4").json()
        assert body["categories"] == ["master"]
        assert body["values"]["name"][0]["data"] == "My Model"

    def test_create_product_model_with_parent(self):
        _setup_family_variant("pm-fam-5", "pm-fam-5-v", ["color"])
        client.post(
            "/api/rest/v1/product-models",
            json={"code": "pm-5-root", "family": "pm-fam-5", "family_variant": "pm-fam-5-v"},
        )
        client.post(
            "/api/rest/v1/product-models",
            json={
                "code": "pm-5-child",
                "family": "pm-fam-5",
                "family_variant": "pm-fam-5-v",
                "parent": "pm-5-root",
            },
        )
        body = client.get("/api/rest/v1/product-models/pm-5-child").json()
        assert body["parent"] == "pm-5-root"

    def test_patch_product_model_updates_values(self):
        _setup_family_variant("pm-fam-6", "pm-fam-6-v", ["color"])
        client.post(
            "/api/rest/v1/product-models",
            json={
                "code": "pm-6",
                "family": "pm-fam-6",
                "family_variant": "pm-fam-6-v",
                "values": {"name": [{"locale": "en_US", "scope": None, "data": "Original"}]},
            },
        )
        res = client.patch(
            "/api/rest/v1/product-models/pm-6",
            json={"values": {"name": [{"locale": "en_US", "scope": None, "data": "Updated"}]}},
        )
        assert res.status_code == 204
        body = client.get("/api/rest/v1/product-models/pm-6").json()
        assert body["values"]["name"][0]["data"] == "Updated"

    def test_patch_product_model_merges_values(self):
        _setup_family_variant("pm-fam-7", "pm-fam-7-v", ["color"])
        client.post(
            "/api/rest/v1/product-models",
            json={
                "code": "pm-7",
                "family": "pm-fam-7",
                "family_variant": "pm-fam-7-v",
                "values": {
                    "name": [{"locale": "en_US", "scope": None, "data": "Name EN"}],
                    "description": [{"locale": "en_US", "scope": None, "data": "Desc"}],
                },
            },
        )
        client.patch(
            "/api/rest/v1/product-models/pm-7",
            json={"values": {"name": [{"locale": "fr_FR", "scope": None, "data": "Name FR"}]}},
        )
        body = client.get("/api/rest/v1/product-models/pm-7").json()
        name_locales = {v["locale"] for v in body["values"]["name"]}
        assert "en_US" in name_locales
        assert "fr_FR" in name_locales
        assert "description" in body["values"]

    def test_duplicate_product_model_code_returns_conflict(self):
        _setup_family_variant("pm-fam-8", "pm-fam-8-v", ["color"])
        payload = {"code": "pm-dup", "family": "pm-fam-8", "family_variant": "pm-fam-8-v"}
        assert client.post("/api/rest/v1/product-models", json=payload).status_code == 201
        assert client.post("/api/rest/v1/product-models", json=payload).status_code == 409


class TestProductModelSearch:
    def _create(
        self, code: str, family: str, variant: str, values: dict | None = None, categories: list | None = None
    ):
        payload: dict = {"code": code, "family": family, "family_variant": variant}
        if values:
            payload["values"] = values
        if categories:
            payload["categories"] = categories
        client.post("/api/rest/v1/product-models", json=payload)

    def test_search_by_attribute_value_contains(self):
        _setup_family_variant("pm-sf-1", "pm-sf-1-v", ["color"])
        self._create(
            "pm-search-a",
            "pm-sf-1",
            "pm-sf-1-v",
            values={"name": [{"locale": "en_US", "scope": None, "data": "Alpha Model"}]},
        )
        self._create(
            "pm-search-b",
            "pm-sf-1",
            "pm-sf-1-v",
            values={"name": [{"locale": "en_US", "scope": None, "data": "Beta Model"}]},
        )

        res = client.get(
            "/api/rest/v1/product-models",
            params={
                "search": '{"name":[{"operator":"CONTAINS","value":"Alpha"}]}',
                "search_locale": "en_US",
            },
        )
        assert res.status_code == 200
        codes = {item["code"] for item in res.json()["_embedded"]["items"]}
        assert "pm-search-a" in codes
        assert "pm-search-b" not in codes

        res2 = client.get(
            "/api/rest/v1/product-models",
            params={
                "search": json.dumps({"code": [{"operator": "IN", "value": ["pm-search-a", "pm-search-b"]}]}),
                "search_locale": "en_US",
            },
        )
        if not res2.ok:
            print(f"Response status: {res2.status_code}")
            print(f"Response body: {res2.text}")
        assert res2.status_code == 200
        codes2 = {item["code"] for item in res2.json()["_embedded"]["items"]}
        assert "pm-search-a" in codes2
        assert "pm-search-b" in codes2
        assert len(codes2) == 2

    def test_search_by_categories(self):
        _setup_family_variant("pm-sf-2", "pm-sf-2-v", ["color"])
        self._create("pm-cat-a", "pm-sf-2", "pm-sf-2-v", categories=["winter_collection"])
        self._create("pm-cat-b", "pm-sf-2", "pm-sf-2-v", categories=["summer_collection"])

        res = client.get(
            "/api/rest/v1/product-models",
            params={"search": '{"categories":[{"operator":"IN","value":["winter_collection"]}]}'},
        )
        assert res.status_code == 200
        codes = {item["code"] for item in res.json()["_embedded"]["items"]}
        assert "pm-cat-a" in codes
        assert "pm-cat-b" not in codes

    def test_search_by_family_variant(self):
        _setup_family_variant("pm-sf-3", "pm-sf-3-va", ["color"])
        _setup_family_variant("pm-sf-3", "pm-sf-3-vb", ["size"])
        self._create("pm-fv-a", "pm-sf-3", "pm-sf-3-va")
        self._create("pm-fv-b", "pm-sf-3", "pm-sf-3-vb")

        res = client.get(
            "/api/rest/v1/product-models",
            params={"search": '{"family_variant":[{"operator":"IN","value":["pm-sf-3-va"]}]}'},
        )
        assert res.status_code == 200
        codes = {item["code"] for item in res.json()["_embedded"]["items"]}
        assert "pm-fv-a" in codes
        assert "pm-fv-b" not in codes

    def test_invalid_search_json_returns_422(self):
        res = client.get("/api/rest/v1/product-models", params={"search": "{"})
        assert res.status_code == 422
