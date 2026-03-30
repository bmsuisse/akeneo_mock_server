import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from akeneo_mock_server import database
from akeneo_mock_server.app import app
from akeneo_mock_server.database import init_db

client = TestClient(app)

WEBHOOK_URL = "https://example.com/webhook"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_subscriber(sub_id: str = "sub-1", url: str = WEBHOOK_URL) -> dict:
    payload = {"id": sub_id, "contact_email": "dev@example.com", "url": url}
    res = client.post("/api/v1/subscribers", json=payload)
    assert res.status_code == 201
    return payload


def _create_subscription(
    sub_id: str = "sub-1",
    sub_scription_id: str = "hook-1",
    events: list | None = None,
) -> dict:
    if events is None:
        events = ["akeneo.pim.v1.product.created"]
    payload = {
        "id": sub_scription_id,
        "destination": {"type": "https", "url": WEBHOOK_URL},
        "events": events,
    }
    res = client.post(f"/api/v1/subscribers/{sub_id}/subscriptions", json=payload)
    assert res.status_code == 201
    return payload


# ---------------------------------------------------------------------------
# Subscriber CRUD
# ---------------------------------------------------------------------------


class TestSubscribers:
    def test_create_subscriber(self):
        """POST /subscribers creates a subscriber and returns 201 with Location."""
        res = client.post(
            "/api/v1/subscribers",
            json={"id": "app-1", "contact_email": "x@y.com"},
        )
        assert res.status_code == 201
        assert "/api/v1/subscribers/app-1" in res.headers["location"]

    def test_get_subscriber(self):
        """GET /subscribers/{id} returns the subscriber."""
        _create_subscriber("s1")
        res = client.get("/api/v1/subscribers/s1")
        assert res.status_code == 200
        assert res.json()["id"] == "s1"
        assert res.json()["contact_email"] == "dev@example.com"

    def test_list_subscribers(self):
        """GET /subscribers returns all registered subscribers."""
        _create_subscriber("s1")
        _create_subscriber("s2")
        res = client.get("/api/v1/subscribers")
        assert res.status_code == 200
        assert len(res.json()["items"]) == 2

    def test_patch_subscriber(self):
        """PATCH /subscribers/{id} updates fields on an existing subscriber."""
        _create_subscriber("s1")
        client.patch("/api/v1/subscribers/s1", json={"contact_email": "new@x.com"})
        res = client.get("/api/v1/subscribers/s1")
        assert res.json()["contact_email"] == "new@x.com"

    def test_delete_subscriber(self):
        """DELETE /subscribers/{id} removes the subscriber; subsequent GET returns 404."""
        _create_subscriber("s1")
        res = client.delete("/api/v1/subscribers/s1")
        assert res.status_code == 204
        res = client.get("/api/v1/subscribers/s1")
        assert res.status_code == 404

    def test_duplicate_subscriber_returns_409(self):
        """Creating a second subscriber with the same id returns 409."""
        _create_subscriber("s1")
        res = client.post("/api/v1/subscribers", json={"id": "s1"})
        assert res.status_code == 409

    def test_get_nonexistent_subscriber_returns_404(self):
        """GET on an unknown subscriber id returns 404."""
        res = client.get("/api/v1/subscribers/nobody")
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# Subscription CRUD
# ---------------------------------------------------------------------------


class TestSubscriptions:
    def test_create_subscription(self):
        """POST /subscribers/{id}/subscriptions creates a subscription."""
        _create_subscriber()
        res = client.post(
            "/api/v1/subscribers/sub-1/subscriptions",
            json={
                "id": "hook-1",
                "destination": {"type": "https", "url": WEBHOOK_URL},
                "events": ["akeneo.pim.v1.product.created"],
            },
        )
        assert res.status_code == 201

    def test_get_subscription(self):
        """GET /subscribers/{id}/subscriptions/{sub_id} retrieves a subscription."""
        _create_subscriber()
        _create_subscription()
        res = client.get("/api/v1/subscribers/sub-1/subscriptions/hook-1")
        assert res.status_code == 200
        assert "akeneo.pim.v1.product.created" in res.json()["events"]

    def test_list_subscriptions(self):
        """GET /subscribers/{id}/subscriptions lists all subscriptions."""
        _create_subscriber()
        _create_subscription(sub_scription_id="h1")
        _create_subscription(sub_scription_id="h2", events=["akeneo.pim.v1.product.updated"])
        res = client.get("/api/v1/subscribers/sub-1/subscriptions")
        assert res.status_code == 200
        assert len(res.json()["items"]) == 2

    def test_patch_subscription(self):
        """PATCH /subscribers/{id}/subscriptions/{sub_id} updates events."""
        _create_subscriber()
        _create_subscription()
        client.patch(
            "/api/v1/subscribers/sub-1/subscriptions/hook-1",
            json={"events": ["akeneo.pim.v1.product.deleted"]},
        )
        res = client.get("/api/v1/subscribers/sub-1/subscriptions/hook-1")
        assert "akeneo.pim.v1.product.deleted" in res.json()["events"]

    def test_delete_subscription(self):
        """DELETE /subscribers/{id}/subscriptions/{sub_id} removes a subscription."""
        _create_subscriber()
        _create_subscription()
        res = client.delete("/api/v1/subscribers/sub-1/subscriptions/hook-1")
        assert res.status_code == 204
        res = client.get("/api/v1/subscribers/sub-1/subscriptions/hook-1")
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# Event dispatch (webhook firing)
# ---------------------------------------------------------------------------


class TestEventDispatch:
    def _setup_webhook(self, events: list | None = None) -> None:
        """Helper: register a subscriber + subscription and create a product."""
        if events is None:
            events = ["akeneo.pim.v1.product.created"]
        _create_subscriber(url=WEBHOOK_URL)
        _create_subscription(events=events)

    def test_product_created_fires_webhook(self):
        """Creating a product dispatches a webhook to the subscriber URL."""
        self._setup_webhook(["akeneo.pim.v1.product.created"])

        captured: list[dict] = []

        async def fake_post(self_or_url, *args, **kwargs):
            # Patching unbound method: self_or_url = AsyncClient, args[0] = url
            url = args[0] if args else kwargs.get("url", "")
            captured.append({"url": url, "payload": kwargs.get("json")})
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            return mock_resp

        with patch("httpx.AsyncClient.post", new=fake_post):
            res = client.post(
                "/api/rest/v1/products",
                json={"identifier": "shoe-1", "family": "shoes"},
            )
            assert res.status_code == 201

        # Background task should have fired the webhook
        assert len(captured) == 1
        assert captured[0]["url"] == WEBHOOK_URL
        payload = captured[0]["payload"]
        assert "events" in payload
        evt = payload["events"][0]
        assert evt["action"] == "created"
        assert "shoe-1" in evt["event_id"]
        assert evt["data"]["resource"]["identifier"] == "shoe-1"

    def test_product_updated_fires_webhook(self):
        """PATCHing a product dispatches an 'updated' webhook event."""
        self._setup_webhook(["akeneo.pim.v1.product.updated"])
        client.post("/api/rest/v1/products", json={"identifier": "shoe-2"})

        captured: list[dict] = []

        async def fake_post(self_or_url, *args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            captured.append({"url": url, "payload": kwargs.get("json")})
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            return mock_resp

        with patch("httpx.AsyncClient.post", new=fake_post):
            res = client.patch("/api/rest/v1/products/shoe-2", json={"family": "boots"})
            assert res.status_code == 204

        assert len(captured) == 1
        evt = captured[0]["payload"]["events"][0]
        assert evt["action"] == "updated"

    def test_webhook_not_fired_if_event_not_subscribed(self):
        """Webhook is NOT dispatched if the subscription does not include the triggered event."""
        # Subscribe only to delete, then create a product — should not fire
        self._setup_webhook(["akeneo.pim.v1.product.deleted"])

        captured: list[dict] = []

        async def fake_post(url: str, json: dict = None, **kwargs):  # type: ignore[override]
            captured.append({"url": url, "payload": json})
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            return mock_resp

        with patch("httpx.AsyncClient.post", new=fake_post):
            client.post("/api/rest/v1/products", json={"identifier": "no-fire"})

        assert len(captured) == 0, "Webhook should NOT have fired for an unsubscribed event"

    def test_webhook_not_fired_if_no_url_on_subscriber(self):
        """Subscriber without a URL field is skipped during dispatch."""
        # Create subscriber WITHOUT a url field
        client.post(
            "/api/v1/subscribers",
            json={"id": "no-url-sub", "contact_email": "x@y.com"},
        )
        client.post(
            "/api/v1/subscribers/no-url-sub/subscriptions",
            json={
                "id": "hook-1",
                "destination": {"type": "https"},
                "events": ["akeneo.pim.v1.product.created"],
            },
        )

        captured: list[dict] = []

        async def fake_post(url: str, json: dict = None, **kwargs):  # type: ignore[override]
            captured.append({"url": url})
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            return mock_resp

        with patch("httpx.AsyncClient.post", new=fake_post):
            client.post("/api/rest/v1/products", json={"identifier": "p1"})

        assert len(captured) == 0, "Should not dispatch to subscriber without a URL"

    def test_webhook_delivery_failure_does_not_crash_api(self):
        """If webhook delivery throws, the API response is still 201, not 500."""
        self._setup_webhook(["akeneo.pim.v1.product.created"])

        async def fake_post(*args, **kwargs):
            raise ConnectionError("Target is down")

        with patch("httpx.AsyncClient.post", new=fake_post):
            res = client.post(
                "/api/rest/v1/products",
                json={"identifier": "resilient"},
            )
        assert res.status_code == 201
