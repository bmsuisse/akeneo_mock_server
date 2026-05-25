import json
import pytest
import psycopg
from fastapi.testclient import TestClient
from akeneo_mock_server.app import app
from akeneo_mock_server.database import get_db_url

client = TestClient(app)

CATEGORIES = [
    {"code": "flooring"},
    {"code": "clothing"},
]

FAMILIES = [
    {"code": "flooring"},
    {"code": "tshirts"},
]

ATTRIBUTES = [
    {"code": "description", "type": "pim_catalog_text"},
    {"code": "price_group", "type": "pim_catalog_text"},
    {"code": "gtin", "type": "pim_catalog_text"},
]

PRODUCTS = [
    {
        "identifier": "FLOOR-001",
        "family": "flooring",
        "categories": ["flooring"],
        "values": {
            "description": [{"data": "Natural Oak Herringbone Parquet", "locale": None, "scope": None}],
            "gtin": [{"data": "4006975001001", "locale": None, "scope": None}],
        },
    },
]


@pytest.fixture
def db_conn():
    conn = psycopg.connect(get_db_url())
    yield conn
    conn.close()


def test_seed_flow_categories(db_conn):
    for category in CATEGORIES:
        code = category["code"]
        # Create
        res = client.post("/api/rest/v1/categories", json=category)
        assert res.status_code in (201, 409)  # 409 if already exists from previous test run if fresh_db not working

        # Verify API
        res = client.get(f"/api/rest/v1/categories/{code}")
        assert res.status_code == 200
        assert res.json()["code"] == code

        # Verify DB directly
        with db_conn.cursor() as cur:
            cur.execute("SELECT id FROM categories WHERE id = %s", (code,))
            row = cur.fetchone()
            assert row is not None
            assert row[0] == code


def test_seed_flow_families(db_conn):
    for family in FAMILIES:
        code = family["code"]
        res = client.post("/api/rest/v1/families", json=family)
        assert res.status_code in (201, 409)

        res = client.get(f"/api/rest/v1/families/{code}")
        assert res.status_code == 200
        assert res.json()["code"] == code

        with db_conn.cursor() as cur:
            cur.execute("SELECT id FROM families WHERE id = %s", (code,))
            row = cur.fetchone()
            assert row is not None
            assert row[0] == code


def test_seed_flow_attributes(db_conn):
    for attr in ATTRIBUTES:
        code = attr["code"]
        res = client.post("/api/rest/v1/attributes", json=attr)
        assert res.status_code in (201, 409)

        res = client.get(f"/api/rest/v1/attributes/{code}")
        assert res.status_code == 200
        assert res.json()["code"] == code

        with db_conn.cursor() as cur:
            cur.execute("SELECT id FROM attributes WHERE id = %s", (code,))
            row = cur.fetchone()
            assert row is not None
            assert row[0] == code


def test_seed_flow_products_ndjson(db_conn):
    # First ensure family and category exist for the product
    client.post("/api/rest/v1/categories", json={"code": "flooring"})
    client.post("/api/rest/v1/families", json={"code": "flooring"})

    payload = "\n".join(json.dumps(p) for p in PRODUCTS) + "\n"
    headers = {"Content-Type": "application/vnd.akeneo.collection+json"}

    # PATCH NDJSON
    res = client.patch("/api/rest/v1/products", content=payload, headers=headers)
    assert res.status_code == 200

    # Verify Read
    for p in PRODUCTS:
        identifier = p["identifier"]
        res = client.get(f"/api/rest/v1/products/{identifier}")
        assert res.status_code == 200
        assert res.json()["identifier"] == identifier

        # Verify DB directly
        with db_conn.cursor() as cur:
            cur.execute("SELECT id FROM products WHERE id = %s", (identifier,))
            row = cur.fetchone()
            assert row is not None
            assert row[0] == identifier
