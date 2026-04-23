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
