import json
from fastapi.testclient import TestClient
from akeneo_mock_server.app import app

client = TestClient(app)


def test_get_family_by_code_returns_code_field():
    client.post("/api/rest/v1/families", json={"code": "test-fam-get"})
    res = client.get("/api/rest/v1/families/test-fam-get")
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == "test-fam-get"


def test_get_family_by_code_not_found():
    res = client.get("/api/rest/v1/families/nonexistent-family")
    assert res.status_code == 404


def test_patch_family_by_code():
    client.post("/api/rest/v1/families", json={"code": "test-fam-patch"})
    res = client.patch("/api/rest/v1/families/test-fam-patch", json={"labels": {"en_US": "Patched"}})
    assert res.status_code == 204
    body = client.get("/api/rest/v1/families/test-fam-patch").json()
    assert body["code"] == "test-fam-patch"
    assert body.get("labels", {}).get("en_US") == "Patched"


def test_filter_families_by_code_in():
    client.post("/api/rest/v1/families", json={"code": "fam-filter-a"})
    client.post("/api/rest/v1/families", json={"code": "fam-filter-b"})
    client.post("/api/rest/v1/families", json={"code": "fam-filter-c"})

    search = json.dumps({"code": [{"operator": "IN", "value": ["fam-filter-a", "fam-filter-b"]}]})
    res = client.get(f"/api/rest/v1/families?search={search}")
    assert res.status_code == 200
    items = res.json()["_embedded"]["items"]
    codes = {item["code"] for item in items}
    assert codes == {"fam-filter-a", "fam-filter-b"}
    assert "fam-filter-c" not in codes


def test_filter_families_by_code_equals():
    client.post("/api/rest/v1/families", json={"code": "fam-eq-x"})
    client.post("/api/rest/v1/families", json={"code": "fam-eq-y"})

    search = json.dumps({"code": [{"operator": "=", "value": "fam-eq-x"}]})
    res = client.get(f"/api/rest/v1/families?search={search}")
    assert res.status_code == 200
    items = res.json()["_embedded"]["items"]
    assert len(items) == 1
    assert items[0]["code"] == "fam-eq-x"


# ---------------------------------------------------------------------------
# Family variants — variant_attribute_sets persistence
# ---------------------------------------------------------------------------


def _ensure_attribute(code: str) -> None:
    client.post("/api/rest/v1/attributes", json={"code": code, "type": "pim_catalog_simpleselect"})


def _create_family(code: str, attributes: list[str] | None = None) -> None:
    for attr in attributes or []:
        _ensure_attribute(attr)
    client.post("/api/rest/v1/families", json={"code": code, "attributes": attributes or []})


def test_create_family_variant_persists_variant_attribute_sets():
    _create_family("fam-var-1", ["color", "size"])
    payload = {
        "code": "fam-var-1-color",
        "labels": {"en_US": "By Color"},
        "variant_attribute_sets": [{"level": 1, "axes": ["color"], "attributes": ["color", "size"]}],
    }
    res = client.post("/api/rest/v1/families/fam-var-1/variants", json=payload)
    assert res.status_code == 201

    res = client.get("/api/rest/v1/families/fam-var-1/variants/fam-var-1-color")
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == "fam-var-1-color"
    assert body["variant_attribute_sets"] == [{"level": 1, "axes": ["color"], "attributes": ["color", "size"]}]


def test_create_family_variant_persists_labels():
    _create_family("fam-var-2", ["size"])
    payload = {
        "code": "fam-var-2-size",
        "labels": {"en_US": "By Size", "fr_FR": "Par Taille"},
        "variant_attribute_sets": [{"level": 1, "axes": ["size"], "attributes": ["size"]}],
    }
    client.post("/api/rest/v1/families/fam-var-2/variants", json=payload)

    body = client.get("/api/rest/v1/families/fam-var-2/variants/fam-var-2-size").json()
    assert body["labels"] == {"en_US": "By Size", "fr_FR": "Par Taille"}


def test_list_family_variants_includes_variant_attribute_sets():
    _create_family("fam-var-3", ["attr1", "attr2"])
    for i in range(1, 3):
        client.post(
            "/api/rest/v1/families/fam-var-3/variants",
            json={
                "code": f"fam-var-3-v{i}",
                "variant_attribute_sets": [{"level": 1, "axes": [f"attr{i}"], "attributes": [f"attr{i}"]}],
            },
        )

    res = client.get("/api/rest/v1/families/fam-var-3/variants")
    assert res.status_code == 200
    items = res.json()["_embedded"]["items"]
    by_code = {item["code"]: item for item in items}
    assert by_code["fam-var-3-v1"]["variant_attribute_sets"][0]["axes"] == ["attr1"]
    assert by_code["fam-var-3-v2"]["variant_attribute_sets"][0]["axes"] == ["attr2"]


def test_create_family_variant_with_multiple_levels():
    _create_family("fam-var-4", ["color", "size", "weight"])
    payload = {
        "code": "fam-var-4-multi",
        "variant_attribute_sets": [
            {"level": 1, "axes": ["color"], "attributes": ["color"]},
            {"level": 2, "axes": ["size"], "attributes": ["size", "weight"]},
        ],
    }
    client.post("/api/rest/v1/families/fam-var-4/variants", json=payload)

    body = client.get("/api/rest/v1/families/fam-var-4/variants/fam-var-4-multi").json()
    sets = {s["level"]: s for s in body["variant_attribute_sets"]}
    assert sets[1]["axes"] == ["color"]
    assert sets[2]["axes"] == ["size"]
    assert sets[2]["attributes"] == ["size", "weight"]


def test_patch_family_variant_updates_variant_attribute_sets():
    _create_family("fam-var-5", ["color", "size"])
    client.post(
        "/api/rest/v1/families/fam-var-5/variants",
        json={
            "code": "fam-var-5-v1",
            "variant_attribute_sets": [{"level": 1, "axes": ["color"], "attributes": ["color"]}],
        },
    )

    res = client.patch(
        "/api/rest/v1/families/fam-var-5/variants/fam-var-5-v1",
        json={"variant_attribute_sets": [{"level": 1, "axes": ["size"], "attributes": ["size"]}]},
    )
    assert res.status_code == 204

    body = client.get("/api/rest/v1/families/fam-var-5/variants/fam-var-5-v1").json()
    assert body["variant_attribute_sets"][0]["axes"] == ["size"]
