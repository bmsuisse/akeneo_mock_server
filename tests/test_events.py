import hashlib
import hmac
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from akeneo_mock_server.events import DELIVERY_LOGS
from fastapi.testclient import TestClient

from akeneo_mock_server.app import app

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
        events = ["com.akeneo.pim.v1.product.created"]
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
                "events": ["com.akeneo.pim.v1.product.created"],
            },
        )
        assert res.status_code == 201

    def test_get_subscription(self):
        """GET /subscribers/{id}/subscriptions/{sub_id} retrieves a subscription."""
        _create_subscriber()
        _create_subscription()
        res = client.get("/api/v1/subscribers/sub-1/subscriptions/hook-1")
        assert res.status_code == 200
        assert "com.akeneo.pim.v1.product.created" in res.json()["events"]

    def test_list_subscriptions(self):
        """GET /subscribers/{id}/subscriptions lists all subscriptions."""
        _create_subscriber()
        _create_subscription(sub_scription_id="h1")
        _create_subscription(sub_scription_id="h2", events=["com.akeneo.pim.v1.product.updated"])
        res = client.get("/api/v1/subscribers/sub-1/subscriptions")
        assert res.status_code == 200
        assert len(res.json()["items"]) == 2

    def test_patch_subscription(self):
        """PATCH /subscribers/{id}/subscriptions/{sub_id} updates events."""
        _create_subscriber()
        _create_subscription()
        client.patch(
            "/api/v1/subscribers/sub-1/subscriptions/hook-1",
            json={"events": ["com.akeneo.pim.v1.product.deleted"]},
        )
        res = client.get("/api/v1/subscribers/sub-1/subscriptions/hook-1")
        assert "com.akeneo.pim.v1.product.deleted" in res.json()["events"]

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


@pytest.fixture(autouse=True)
def clear_delivery_logs():
    DELIVERY_LOGS.clear()


PRODUCT = "com.akeneo.pim.v1.product"
PRODUCT_MODEL = "com.akeneo.pim.v1.product-model"
SECRET = "super-secret-primary-0123456789"


class Captured:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @property
    def payloads(self) -> list[dict[str, Any]]:
        return [json.loads(call["body"]) for call in self.calls]


@contextmanager
def capture_webhooks(status_code: int = 200) -> Iterator[Captured]:
    captured = Captured()

    async def fake_post(self: Any, url: str, *args: Any, **kwargs: Any) -> MagicMock:
        captured.calls.append({"url": url, "body": kwargs["content"], "headers": kwargs["headers"]})
        response = MagicMock()
        response.status_code = status_code
        return response

    with patch("httpx.AsyncClient.post", new=fake_post):
        yield captured


def subscribe(events: list[str], **extra: Any) -> dict[str, Any]:
    _create_subscriber()
    payload = {
        "id": "hook-1",
        "type": "https",
        "events": events,
        "config": {"url": WEBHOOK_URL, "secret": {"primary": SECRET}},
        **extra,
    }
    res = client.post("/api/v1/subscribers/sub-1/subscriptions", json=payload)
    assert res.status_code == 201
    return payload


class TestPlatformProductEvents:
    def test_created_is_a_cloudevent(self):
        subscribe([f"{PRODUCT}.created"])
        with capture_webhooks() as captured:
            res = client.post("/api/rest/v1/products", json={"identifier": "shoe-1", "family": "shoes"})
        assert res.status_code == 201
        assert len(captured.calls) == 1
        assert captured.calls[0]["url"] == WEBHOOK_URL
        event = captured.payloads[0]
        assert event["specversion"] == "1.0"
        assert event["type"] == f"{PRODUCT}.created"
        assert event["source"] == "pim"
        assert event["subject"] == "hook-1"
        assert event["datacontenttype"] == "application/json"
        assert event["dataschema"].endswith(f"{PRODUCT}.created.schema.json")
        assert event["id"] and event["time"].endswith("Z")
        assert event["data"]["author"]["type"] == "api"
        assert "uuid" in event["data"]["product"]

    def test_identifier_hidden_by_default(self):
        subscribe([f"{PRODUCT}.created"])
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "hidden"})
        assert "identifier" not in captured.payloads[0]["data"]["product"]

    def test_identifier_sent_when_flag_set(self):
        subscribe([f"{PRODUCT}.created"], send_product_identifier=True)
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "shown"})
        assert captured.payloads[0]["data"]["product"]["identifier"] == "shown"

    def test_event_ids_are_unique(self):
        subscribe([f"{PRODUCT}.created"])
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "a"})
            client.post("/api/rest/v1/products", json={"identifier": "b"})
        ids = {event["id"] for event in captured.payloads}
        assert len(ids) == 2

    def test_updated_fires_on_patch(self):
        subscribe([f"{PRODUCT}.updated"])
        client.post("/api/rest/v1/products", json={"identifier": "shoe-2"})
        with capture_webhooks() as captured:
            res = client.patch("/api/rest/v1/products/shoe-2", json={"family": "boots"})
        assert res.status_code == 204
        assert [e["type"] for e in captured.payloads] == [f"{PRODUCT}.updated"]

    def test_patch_creating_a_product_emits_created(self):
        subscribe([f"{PRODUCT}.created", f"{PRODUCT}.updated"])
        with capture_webhooks() as captured:
            client.patch("/api/rest/v1/products/brand-new", json={"family": "shoes"})
        assert [e["type"] for e in captured.payloads] == [f"{PRODUCT}.created"]

    def test_deleted_fires_with_uuid_and_identifier(self):
        subscribe([f"{PRODUCT}.deleted"], send_product_identifier=True)
        client.post("/api/rest/v1/products", json={"identifier": "gone"})
        with capture_webhooks() as captured:
            res = client.delete("/api/rest/v1/products/gone")
        assert res.status_code == 204
        event = captured.payloads[0]
        assert event["type"] == f"{PRODUCT}.deleted"
        assert event["data"]["product"]["identifier"] == "gone"
        assert event["data"]["product"]["uuid"]

    def test_uuid_endpoints_fire_the_same_events(self):
        subscribe([f"{PRODUCT}.created", f"{PRODUCT}.updated", f"{PRODUCT}.deleted"])
        product_uuid = "11111111-2222-4333-8444-555555555555"
        with capture_webhooks() as captured:
            client.patch(f"/api/rest/v1/products-uuid/{product_uuid}", json={"identifier": "by-uuid"})
            client.patch(f"/api/rest/v1/products-uuid/{product_uuid}", json={"family": "x"})
            client.delete(f"/api/rest/v1/products-uuid/{product_uuid}")
        assert [e["type"] for e in captured.payloads] == [
            f"{PRODUCT}.created",
            f"{PRODUCT}.updated",
            f"{PRODUCT}.deleted",
        ]
        assert {e["data"]["product"]["uuid"] for e in captured.payloads} == {product_uuid}

    def test_batch_patch_fires_one_event_per_product(self):
        subscribe([f"{PRODUCT}.created", f"{PRODUCT}.updated"])
        client.post("/api/rest/v1/products", json={"identifier": "batch-existing"})
        with capture_webhooks() as captured:
            res = client.patch(
                "/api/rest/v1/products",
                content='{"identifier":"batch-existing","family":"f"}\n{"identifier":"batch-new"}\n',
                headers={"content-type": "application/vnd.akeneo.collection+json"},
            )
        assert res.status_code == 200
        assert sorted(e["type"] for e in captured.payloads) == [f"{PRODUCT}.created", f"{PRODUCT}.updated"]


class TestDeltaEvents:
    def _price_values(self, data: str) -> dict[str, Any]:
        return {"name": [{"locale": "en_US", "scope": None, "data": data}]}

    def test_delta_contains_previous_and_new(self):
        subscribe([f"{PRODUCT}.updated.delta"])
        client.post("/api/rest/v1/products", json={"identifier": "d1"})
        with capture_webhooks() as captured:
            client.patch("/api/rest/v1/products/d1", json={"values": self._price_values("Old")})
            client.patch("/api/rest/v1/products/d1", json={"values": self._price_values("New")})
        assert len(captured.payloads) == 2
        first, second = captured.payloads
        assert first["type"] == f"{PRODUCT}.updated.delta"
        assert first["data"]["product"]["changes"]["values"] == {
            "name": [{"previous": None, "new": "Old", "type": "text", "locale": "en_US", "scope": None}]
        }
        assert second["data"]["product"]["changes"]["values"] == {
            "name": [{"previous": "Old", "new": "New", "type": "text", "locale": "en_US", "scope": None}]
        }
        assert first["data"]["product"]["updated_at"]["timezone"] == "UTC"

    def test_delta_not_sent_to_plain_updated_subscription(self):
        subscribe([f"{PRODUCT}.updated"])
        client.post("/api/rest/v1/products", json={"identifier": "d2"})
        with capture_webhooks() as captured:
            client.patch("/api/rest/v1/products/d2", json={"values": self._price_values("x")})
        assert [e["type"] for e in captured.payloads] == [f"{PRODUCT}.updated"]
        assert "changes" not in captured.payloads[0]["data"]["product"]

    def test_both_updated_and_delta_subscribed_get_two_events(self):
        subscribe([f"{PRODUCT}.updated", f"{PRODUCT}.updated.delta"])
        client.post("/api/rest/v1/products", json={"identifier": "d3"})
        with capture_webhooks() as captured:
            client.patch("/api/rest/v1/products/d3", json={"values": self._price_values("x")})
        assert sorted(e["type"] for e in captured.payloads) == [f"{PRODUCT}.updated", f"{PRODUCT}.updated.delta"]

    def test_attribute_filter_applies_to_delta(self):
        subscribe([f"{PRODUCT}.updated.delta"], filter='attribute = "description"')
        client.post("/api/rest/v1/products", json={"identifier": "d4"})
        with capture_webhooks() as captured:
            client.patch("/api/rest/v1/products/d4", json={"values": self._price_values("x")})
        assert captured.calls == []


class TestProductModelEvents:
    def test_lifecycle(self):
        subscribe([f"{PRODUCT_MODEL}.created", f"{PRODUCT_MODEL}.updated", f"{PRODUCT_MODEL}.deleted"])
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/product-models", json={"code": "pm-1", "family_variant": "fv"})
            client.patch("/api/rest/v1/product-models/pm-1", json={"family_variant": "fv2"})
            client.delete("/api/rest/v1/product-models/pm-1")
        assert [e["type"] for e in captured.payloads] == [
            f"{PRODUCT_MODEL}.created",
            f"{PRODUCT_MODEL}.updated",
            f"{PRODUCT_MODEL}.deleted",
        ]
        assert all(e["data"]["product_model"] == {"code": "pm-1"} for e in captured.payloads)

    def test_delta(self):
        subscribe([f"{PRODUCT_MODEL}.updated.delta"])
        client.post("/api/rest/v1/product-models", json={"code": "pm-2", "family_variant": "fv"})
        with capture_webhooks() as captured:
            client.patch(
                "/api/rest/v1/product-models/pm-2",
                json={"values": {"name": [{"locale": None, "scope": None, "data": "n"}]}},
            )
        changes = captured.payloads[0]["data"]["product_model"]["changes"]
        assert changes["values"]["name"][0]["new"] == "n"
        assert "enabled" not in changes and "family" not in changes


class TestSubscriptionRouting:
    def test_not_fired_if_event_not_subscribed(self):
        subscribe([f"{PRODUCT}.deleted"])
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "no-fire"})
        assert captured.calls == []

    def test_other_entities_do_not_fire(self):
        subscribe([f"{PRODUCT}.created", f"{PRODUCT}.updated", f"{PRODUCT}.deleted"])
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/categories", json={"code": "cat-1"})
            client.post("/api/rest/v1/families", json={"code": "fam-1"})
        assert captured.calls == []

    def test_subscriber_without_any_url_is_skipped(self):
        client.post("/api/v1/subscribers", json={"id": "no-url-sub"})
        client.post(
            "/api/v1/subscribers/no-url-sub/subscriptions",
            json={"id": "hook-1", "type": "https", "events": [f"{PRODUCT}.created"]},
        )
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "p1"})
        assert captured.calls == []

    def test_subscriber_level_url_is_a_fallback_target(self):
        _create_subscriber(url="https://fallback.example.com/hook")
        client.post(
            "/api/v1/subscribers/sub-1/subscriptions",
            json={"id": "hook-1", "events": [f"{PRODUCT}.created"]},
        )
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "fb"})
        assert captured.calls[0]["url"] == "https://fallback.example.com/hook"

    def test_non_https_subscription_types_are_not_posted(self):
        subscribe([f"{PRODUCT}.created"], type="pubsub")
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "ps"})
        assert captured.calls == []

    def test_each_subscription_gets_its_own_event_with_its_subject(self):
        _create_subscriber()
        for hook in ("hook-a", "hook-b"):
            client.post(
                "/api/v1/subscribers/sub-1/subscriptions",
                json={"id": hook, "type": "https", "events": [f"{PRODUCT}.created"], "config": {"url": WEBHOOK_URL}},
            )
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "multi"})
        assert sorted(e["subject"] for e in captured.payloads) == ["hook-a", "hook-b"]

    def test_delivery_failure_does_not_crash_api(self):
        subscribe([f"{PRODUCT}.created"])

        async def fake_post(*args: Any, **kwargs: Any) -> None:
            raise ConnectionError("Target is down")

        with patch("httpx.AsyncClient.post", new=fake_post):
            res = client.post("/api/rest/v1/products", json={"identifier": "resilient"})
        assert res.status_code == 201


class TestSubscriptionLifecycle:
    def test_defaults_are_filled(self):
        subscribe([f"{PRODUCT}.created"])
        body = client.get("/api/v1/subscribers/sub-1/subscriptions/hook-1").json()
        assert body["status"] == "active"
        assert body["source"] == "pim"
        assert body["send_product_identifier"] is False
        assert body["subscriber_id"] == "sub-1"
        assert body["createdAt"] and body["updatedAt"]

    def test_suspend_stops_delivery_and_resume_restarts_it(self):
        subscribe([f"{PRODUCT}.created"])
        res = client.post("/api/v1/subscribers/sub-1/subscriptions/hook-1/suspend")
        assert res.status_code == 202
        assert res.json()["status"] == "suspended"
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "while-suspended"})
        assert captured.calls == []

        res = client.post("/api/v1/subscribers/sub-1/subscriptions/hook-1/resume")
        assert res.status_code == 202
        assert res.json()["status"] == "active"
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "after-resume"})
        assert len(captured.calls) == 1

    def test_suspend_twice_conflicts(self):
        subscribe([f"{PRODUCT}.created"])
        client.post("/api/v1/subscribers/sub-1/subscriptions/hook-1/suspend")
        res = client.post("/api/v1/subscribers/sub-1/subscriptions/hook-1/suspend")
        assert res.status_code == 409

    def test_resume_active_conflicts(self):
        subscribe([f"{PRODUCT}.created"])
        res = client.post("/api/v1/subscribers/sub-1/subscriptions/hook-1/resume")
        assert res.status_code == 409

    def test_suspend_unknown_is_404(self):
        _create_subscriber()
        res = client.post("/api/v1/subscribers/sub-1/subscriptions/nope/suspend")
        assert res.status_code == 404

    def test_deleted_subscription_does_not_fire(self):
        subscribe([f"{PRODUCT}.created"])
        client.delete("/api/v1/subscribers/sub-1/subscriptions/hook-1")
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "post-delete"})
        assert captured.calls == []

    def test_patch_events_changes_routing(self):
        subscribe([f"{PRODUCT}.created"])
        client.patch("/api/v1/subscribers/sub-1/subscriptions/hook-1", json={"events": [f"{PRODUCT}.deleted"]})
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "rerouted"})
        assert captured.calls == []


class TestSigningAndHeaders:
    def test_primary_signature_is_hmac_of_body(self):
        subscribe([f"{PRODUCT}.created"])
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "sig"})
        call = captured.calls[0]
        expected = hmac.new(SECRET.encode(), call["body"], hashlib.sha256).hexdigest()
        assert call["headers"]["X-AKENEO-SIGNATURE-PRIMARY"] == expected
        assert call["headers"]["X-AKENEO-SIGNATURE-ALGORITHM"] == "HmacSHA256"
        assert "X-AKENEO-SIGNATURE-SECONDARY" not in call["headers"]

    def test_secondary_signature_for_rotation(self):
        secondary = "secondary-secret-0123456789"
        subscribe(
            [f"{PRODUCT}.created"],
            config={"url": WEBHOOK_URL, "secret": {"primary": SECRET, "secondary": secondary}},
        )
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "rot"})
        call = captured.calls[0]
        assert (
            call["headers"]["X-AKENEO-SIGNATURE-SECONDARY"]
            == hmac.new(secondary.encode(), call["body"], hashlib.sha256).hexdigest()
        )

    def test_custom_headers_sent_but_reserved_ones_dropped_and_redacted_in_api(self):
        subscribe(
            [f"{PRODUCT}.created"],
            config={
                "url": WEBHOOK_URL,
                "secret": {"primary": SECRET},
                "headers": {"X-API-Key": "k", "Authorization": "bad", "X-AKENEO-SIGNATURE-PRIMARY": "forged"},
            },
        )
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "hdr"})
        headers = captured.calls[0]["headers"]
        assert headers["X-API-Key"] == "k"
        assert "Authorization" not in headers
        assert headers["X-AKENEO-SIGNATURE-PRIMARY"] != "forged"
        listed = client.get("/api/v1/subscribers/sub-1/subscriptions/hook-1").json()
        assert listed["config"]["headers"]["X-API-Key"] == "***redacted***"


class TestFilters:
    def test_user_type_filter_matches(self):
        subscribe([f"{PRODUCT}.created"], filter='user_type = "api"')
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "f1"})
        assert len(captured.calls) == 1

    def test_user_type_filter_excludes(self):
        subscribe([f"{PRODUCT}.created"], filter='user_type in ("user", "job")')
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "f2"})
        assert captured.calls == []

    def test_not_operator(self):
        subscribe([f"{PRODUCT}.created"], filter='not user_type = "api"')
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "f3"})
        assert captured.calls == []

    def test_and_or_with_parentheses(self):
        subscribe([f"{PRODUCT}.created"], filter='(user_type = "user" or user_type = "api") and user = "mock-author"')
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "f4"})
        assert len(captured.calls) == 1

    def test_delta_filter_on_attribute_and_locale(self):
        subscribe([f"{PRODUCT}.updated.delta"], filter='attribute in ("name") and locale = "en_US"')
        client.post("/api/rest/v1/products", json={"identifier": "f5"})
        with capture_webhooks() as captured:
            client.patch(
                "/api/rest/v1/products/f5",
                json={"values": {"name": [{"locale": "en_US", "scope": None, "data": "x"}]}},
            )
        assert len(captured.calls) == 1


class TestLegacyEventsApi:
    def test_legacy_names_deliver_batch_envelope(self):
        subscribe(["product.created", "product.updated", "product.removed"])
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "legacy", "family": "f"})
            client.patch("/api/rest/v1/products/legacy", json={"family": "g"})
            client.delete("/api/rest/v1/products/legacy")
        assert [e["events"][0]["action"] for e in captured.payloads] == [
            "product.created",
            "product.updated",
            "product.removed",
        ]
        created, updated, removed = (e["events"][0] for e in captured.payloads)
        assert created["data"]["resource"]["identifier"] == "legacy"
        assert updated["data"]["resource"]["family"] == "g"
        assert set(removed["data"]["resource"]) == {"identifier", "uuid"}
        for event in (created, updated, removed):
            assert event["author_type"] == "api"
            assert event["event_id"] and event["event_datetime"] and event["pim_source"]

    def test_legacy_product_model_events(self):
        subscribe(["product_model.created", "product_model.removed"])
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/product-models", json={"code": "lpm", "family_variant": "fv"})
            client.delete("/api/rest/v1/product-models/lpm")
        actions = [e["events"][0]["action"] for e in captured.payloads]
        assert actions == ["product_model.created", "product_model.removed"]
        assert captured.payloads[1]["events"][0]["data"]["resource"] == {"code": "lpm"}

    def test_legacy_signature_uses_timestamp_and_body(self):
        _create_subscriber(url=WEBHOOK_URL)
        client.patch("/api/v1/subscribers/sub-1", json={"secret": "legacy-secret"})
        client.post(
            "/api/v1/subscribers/sub-1/subscriptions",
            json={"id": "hook-1", "events": ["product.created"]},
        )
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "legacy-sig"})
        call = captured.calls[0]
        timestamp = call["headers"]["X-Akeneo-Request-Timestamp"]
        expected = hmac.new(b"legacy-secret", timestamp.encode() + b"." + call["body"], hashlib.sha256).hexdigest()
        assert call["headers"]["X-Akeneo-Request-Signature"] == expected


class TestLogs:
    def test_delivery_is_logged(self):
        subscribe([f"{PRODUCT}.created"])
        with capture_webhooks():
            client.post("/api/rest/v1/products", json={"identifier": "logged"})
        items = client.get("/api/v1/logs", params={"subscription_id": "hook-1"}).json()["items"]
        assert items[-1]["operation"] == "deliver_event"
        assert items[-1]["event_type"] == f"{PRODUCT}.created"
        assert items[-1]["status_code"] == 200
        assert items[-1]["log_type"] == "action"

    def test_failed_delivery_is_logged_as_error(self):
        subscribe([f"{PRODUCT}.created"])
        with capture_webhooks(status_code=500):
            client.post("/api/rest/v1/products", json={"identifier": "failing"})
        items = client.get("/api/v1/logs", params={"subscription_id": "hook-1", "log_type": "error"}).json()["items"]
        assert items[-1]["status_code"] == 500


class TestCatalogue:
    def test_all_documented_event_types_are_listed(self):
        items = client.get("/api/v1/mock/events").json()["items"]
        assert len(items) >= 53
        for expected in (
            "com.akeneo.pim.v1.product.became-complete",
            "com.akeneo.pim.v1.job.import.status-changed",
            "com.akeneo.pim.v1.workflow.task.created",
            "com.akeneo.pim.v1.reference-entity-record.updated.delta",
            "com.akeneo.pim.v1.app.deleted",
        ):
            assert expected in items

    def test_unknown_event_type_is_rejected(self):
        _create_subscriber()
        res = client.post(
            "/api/v1/subscribers/sub-1/subscriptions",
            json={"id": "bad", "events": ["com.akeneo.pim.v1.nonsense.created"]},
        )
        assert res.status_code == 422

    def test_invalid_filter_is_rejected_on_create_and_patch(self):
        subscribe([f"{PRODUCT}.created"])
        res = client.post(
            "/api/v1/subscribers/sub-1/subscriptions",
            json={"id": "bad", "events": [f"{PRODUCT}.created"], "filter": 'user_type = "api'},
        )
        assert res.status_code == 422
        res = client.patch("/api/v1/subscribers/sub-1/subscriptions/hook-1", json={"filter": "user_type ~ api"})
        assert res.status_code == 422

    @pytest.mark.parametrize("event_type", sorted(__import__("akeneo_mock_server.events").events.EVENT_SAMPLES))
    def test_every_event_can_be_emitted_with_its_documented_sample(self, event_type: str):
        subscribe([event_type])
        with capture_webhooks() as captured:
            res = client.post("/api/v1/mock/events", json={"type": event_type})
        assert res.status_code == 200
        assert res.json() == {"delivered": 1}
        event = captured.payloads[0]
        assert event["type"] == event_type
        assert event["specversion"] == "1.0"
        assert event["data"]

    def test_emit_with_custom_data(self):
        subscribe(["com.akeneo.pim.v1.product.became-complete"])
        data = {"product": {"uuid": "u-1", "identifier": "x", "complete_on": [{"locale": "en_US", "scope": "web"}]}}
        with capture_webhooks() as captured:
            client.post(
                "/api/v1/mock/events", json={"type": "com.akeneo.pim.v1.product.became-complete", "data": data}
            )
        assert captured.payloads[0]["data"] == data

    def test_emit_unknown_type_is_422(self):
        res = client.post("/api/v1/mock/events", json={"type": "nope"})
        assert res.status_code == 422

    def test_emit_without_subscription_delivers_nothing(self):
        res = client.post("/api/v1/mock/events", json={"type": "com.akeneo.pim.v1.app.deleted"})
        assert res.json() == {"delivered": 0}


class TestOtherEntityEvents:
    def _events(self, kind: str, *suffixes: str) -> list[str]:
        return [f"com.akeneo.pim.v1.{kind}.{suffix}" for suffix in suffixes]

    @pytest.mark.parametrize(
        ("path", "kind", "data_key"),
        [
            ("categories", "category", "category"),
            ("attributes", "attribute", "attribute"),
            ("attribute-groups", "attribute-group", "attribute_group"),
            ("families", "family", "family"),
        ],
    )
    def test_top_level_entity_lifecycle(self, path: str, kind: str, data_key: str):
        subscribe(self._events(kind, "created", "updated", "deleted"))
        body = {"code": "e-1", "type": "pim_catalog_text"} if kind == "attribute" else {"code": "e-1"}
        with capture_webhooks() as captured:
            assert client.post(f"/api/rest/v1/{path}", json=body).status_code == 201
            assert client.patch(f"/api/rest/v1/{path}/e-1", json={"labels": {"en_US": "One"}}).status_code == 204
            assert client.delete(f"/api/rest/v1/{path}/e-1").status_code == 204
        assert [e["type"] for e in captured.payloads] == self._events(kind, "created", "updated", "deleted")
        assert all(e["data"][data_key] == {"code": "e-1"} for e in captured.payloads)
        assert all(e["data"]["author"]["type"] == "api" for e in captured.payloads)

    def test_category_delta_has_labels_and_parent(self):
        subscribe(self._events("category", "updated.delta"))
        client.post("/api/rest/v1/categories", json={"code": "root"})
        client.post("/api/rest/v1/categories", json={"code": "child", "labels": {"en_US": "Old"}})
        with capture_webhooks() as captured:
            client.patch("/api/rest/v1/categories/child", json={"parent": "root", "labels": {"en_US": "New"}})
        changes = captured.payloads[0]["data"]["category"]["changes"]
        assert changes["parent"] == {"previous": None, "new": "root"}
        assert changes["labels"] == {"en_US": {"previous": "Old", "new": "New"}}

    def test_attribute_option_events_reference_parent_attribute(self):
        subscribe(self._events("attribute-option", "created", "updated", "updated.delta"))
        client.post("/api/rest/v1/attributes", json={"code": "color", "type": "pim_catalog_simpleselect"})
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/attributes/color/options", json={"code": "red", "sort_order": 1})
            client.patch("/api/rest/v1/attributes/color/options/red", json={"sort_order": 5})
        created, updated, delta = captured.payloads
        assert created["type"].endswith("attribute-option.created")
        assert created["data"]["attribute_option"] == {"code": "red", "attribute": {"code": "color"}}
        assert updated["type"].endswith("attribute-option.updated")
        assert delta["data"]["attribute_option"]["changes"]["sort_order"] == {"previous": 1, "new": 5}

    def test_attribute_option_bulk_patch_emits_events(self):
        subscribe(self._events("attribute-option", "created", "updated"))
        client.post("/api/rest/v1/attributes", json={"code": "size", "type": "pim_catalog_simpleselect"})
        with capture_webhooks() as captured:
            client.patch(
                "/api/rest/v1/attributes/size/options",
                content='{"code":"s"}\n{"code":"m"}\n',
                headers={"content-type": "application/vnd.akeneo.collection+json"},
            )
            client.patch(
                "/api/rest/v1/attributes/size/options",
                content='{"code":"s","sort_order":3}\n',
                headers={"content-type": "application/vnd.akeneo.collection+json"},
            )
        assert [e["type"].rsplit(".", 1)[1] for e in captured.payloads] == ["created", "created", "updated"]

    def test_family_variant_events_reference_family(self):
        subscribe(self._events("family-variant", "created", "updated"))
        for code in ("fa-axis", "fa-other"):
            client.post("/api/rest/v1/attributes", json={"code": code, "type": "pim_catalog_simpleselect"})
        client.post(
            "/api/rest/v1/families",
            json={"code": "shirts", "attributes": ["fa-axis", "fa-other"], "attribute_as_label": "fa-axis"},
        )
        variant = {"code": "by-axis", "variant_attribute_sets": [{"level": 1, "axes": ["fa-axis"], "attributes": []}]}
        with capture_webhooks() as captured:
            assert client.post("/api/rest/v1/families/shirts/variants", json=variant).status_code == 201
            client.patch("/api/rest/v1/families/shirts/variants/by-axis", json={"labels": {"en_US": "Axis"}})
        assert [e["type"].rsplit(".", 1)[1] for e in captured.payloads] == ["created", "updated"]
        assert captured.payloads[0]["data"]["family_variant"] == {"code": "by-axis", "family": {"code": "shirts"}}

    def test_reference_entity_record_delta_uses_channel(self):
        subscribe(self._events("reference-entity-record", "created", "updated.delta"))
        client.post("/api/rest/v1/reference-entities", json={"code": "brand"})
        values = {"label": [{"locale": "en_US", "channel": None, "data": "Acme"}]}
        with capture_webhooks() as captured:
            client.patch("/api/rest/v1/reference-entities/brand/records/acme", json={"code": "acme"})
            client.patch("/api/rest/v1/reference-entities/brand/records/acme", json={"values": values})
        created, delta = captured.payloads
        assert created["data"]["reference_entity_record"] == {"code": "acme", "reference_entity": {"code": "brand"}}
        record = delta["data"]["reference_entity_record"]
        assert record["changes"]["values"]["label"] == [
            {"previous": None, "new": "Acme", "type": "text", "locale": "en_US", "channel": None}
        ]
        assert record["updated_at"]["timezone"] == "UTC"

    def test_asset_events_reference_asset_family(self):
        subscribe(self._events("asset", "created", "updated.delta"))
        client.patch("/api/rest/v1/asset-families/packshots", json={"code": "packshots"})
        values = {"alt": [{"locale": None, "channel": "web", "data": "text"}]}
        with capture_webhooks() as captured:
            client.patch("/api/rest/v1/asset-families/packshots/assets/a1", json={"code": "a1"})
            client.patch("/api/rest/v1/asset-families/packshots/assets/a1", json={"values": values})
        created, delta = captured.payloads
        assert created["data"]["asset"] == {"code": "a1", "asset_family": {"code": "packshots"}}
        assert delta["data"]["asset"]["changes"]["values"]["alt"][0]["channel"] == "web"

    def test_entities_without_platform_events_do_not_fire(self):
        subscribe(self._events("category", "created"))
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/channels", json={"code": "web"})
            client.post("/api/rest/v1/association-types", json={"code": "UPSELL"})
        assert captured.calls == []


class TestProductDeltaDetails:
    def test_property_relationship_and_association_changes(self):
        subscribe([f"{PRODUCT}.updated.delta"])
        client.post(
            "/api/rest/v1/products",
            json={
                "identifier": "pd-1",
                "enabled": True,
                "family": "old-fam",
                "categories": ["c1", "c2"],
                "groups": ["g1"],
                "associations": {"UPSELL": {"products": ["p1"], "product_models": [], "groups": []}},
            },
        )
        with capture_webhooks() as captured:
            client.patch(
                "/api/rest/v1/products/pd-1",
                json={
                    "enabled": False,
                    "family": "new-fam",
                    "categories": ["c2", "c3"],
                    "groups": [],
                    "associations": {"UPSELL": {"products": ["p2"], "product_models": [], "groups": []}},
                },
            )
        changes = captured.payloads[0]["data"]["product"]["changes"]
        assert changes["enabled"] == {"previous": True, "new": False}
        assert changes["family"] == {"previous": "old-fam", "new": "new-fam"}
        assert changes["categories"] == {"added": ["c3"], "removed": ["c1"]}
        assert changes["groups"] == {"added": [], "removed": ["g1"]}
        assert changes["associations"]["UPSELL"] == {
            "added": {"products": ["p2"]},
            "removed": {"products": ["p1"]},
        }

    def test_unchanged_properties_are_omitted(self):
        subscribe([f"{PRODUCT}.updated.delta"])
        client.post("/api/rest/v1/products", json={"identifier": "pd-2", "enabled": True, "family": "f"})
        with capture_webhooks() as captured:
            client.patch("/api/rest/v1/products/pd-2", json={"enabled": True})
        assert captured.payloads[0]["data"]["product"]["changes"] == {}

    def test_removed_value_has_null_new(self):
        subscribe([f"{PRODUCT}.updated.delta"])
        values = {"name": [{"locale": "en_US", "scope": None, "data": "x"}]}
        client.post("/api/rest/v1/products", json={"identifier": "pd-3", "values": values})
        with capture_webhooks() as captured:
            client.patch("/api/rest/v1/products/pd-3", json={"values": {"name": None}})
        entry = captured.payloads[0]["data"]["product"]["changes"]["values"]["name"][0]
        assert entry["previous"] == "x"
        assert entry["new"] is None

    def test_value_types_are_inferred(self):
        subscribe([f"{PRODUCT}.updated.delta"])
        client.post("/api/rest/v1/products", json={"identifier": "pd-4"})
        values = {
            "flag": [{"locale": None, "scope": None, "data": True}],
            "count": [{"locale": None, "scope": None, "data": 3}],
            "tags": [{"locale": None, "scope": None, "data": ["a"]}],
            "cost": [{"locale": None, "scope": None, "data": [{"amount": "1", "currency": "EUR"}]}],
        }
        with capture_webhooks() as captured:
            client.patch("/api/rest/v1/products/pd-4", json={"values": values})
        changes = captured.payloads[0]["data"]["product"]["changes"]["values"]
        assert changes["flag"][0]["type"] == "boolean"
        assert changes["count"][0]["type"] == "number"
        assert changes["tags"][0]["type"] == "multiselect"


class TestFilterSyntax:
    def test_square_bracket_membership(self):
        subscribe([f"{PRODUCT}.created"], filter='user_type in ["api", "job"]')
        with capture_webhooks() as captured:
            client.post("/api/rest/v1/products", json={"identifier": "sb"})
        assert len(captured.calls) == 1

    def test_null_locale_matches_equality(self):
        subscribe([f"{PRODUCT}.updated.delta"], filter='locale = "en_US" and scope = "ecommerce"')
        client.post("/api/rest/v1/products", json={"identifier": "nl"})
        values = {"sku_note": [{"locale": None, "scope": None, "data": "x"}]}
        with capture_webhooks() as captured:
            client.patch("/api/rest/v1/products/nl", json={"values": values})
        assert len(captured.calls) == 1

    def test_non_matching_locale_is_excluded(self):
        subscribe([f"{PRODUCT}.updated.delta"], filter='locale = "fr_FR"')
        client.post("/api/rest/v1/products", json={"identifier": "nm"})
        values = {"name": [{"locale": "en_US", "scope": None, "data": "x"}]}
        with capture_webhooks() as captured:
            client.patch("/api/rest/v1/products/nm", json={"values": values})
        assert captured.calls == []

    def test_overlong_filter_is_rejected(self):
        _create_subscriber()
        res = client.post(
            "/api/v1/subscribers/sub-1/subscriptions",
            json={"id": "long", "events": [f"{PRODUCT}.created"], "filter": 'user = "' + "a" * 600 + '"'},
        )
        assert res.status_code == 422


class TestDeliveryIsolation:
    def test_invalid_url_does_not_block_other_subscriptions(self):
        _create_subscriber()
        bad = {"id": "bad", "events": [f"{PRODUCT}.created"], "config": {"url": "https://host:notaport/x"}}
        good = {"id": "good", "events": [f"{PRODUCT}.created"], "config": {"url": WEBHOOK_URL}}
        client.post("/api/v1/subscribers/sub-1/subscriptions", json=bad)
        client.post("/api/v1/subscribers/sub-1/subscriptions", json=good)
        seen: list[str] = []

        async def fake_post(self: Any, url: str, *args: Any, **kwargs: Any) -> MagicMock:
            if "notaport" in url:
                raise httpx.InvalidURL("bad port")
            seen.append(url)
            response = MagicMock()
            response.status_code = 200
            return response

        with patch("httpx.AsyncClient.post", new=fake_post):
            res = client.post("/api/rest/v1/products", json={"identifier": "iso"})
        assert res.status_code == 201
        assert seen == [WEBHOOK_URL]

    def test_non_string_secret_does_not_crash_delivery(self):
        subscribe(
            [f"{PRODUCT}.created"],
            config={"url": WEBHOOK_URL, "secret": {"primary": 12345}},
        )
        with capture_webhooks() as captured:
            res = client.post("/api/rest/v1/products", json={"identifier": "ns"})
        assert res.status_code == 201
        assert len(captured.calls) == 1
        assert "X-AKENEO-SIGNATURE-PRIMARY" not in captured.calls[0]["headers"]

    def test_logs_are_partitioned_per_database(self):
        subscribe([f"{PRODUCT}.created"])
        with capture_webhooks():
            client.post("/api/rest/v1/products", json={"identifier": "db-a"})
        from akeneo_mock_server import database

        token = database.db_name_var.set("other_db_for_logs")
        try:
            from akeneo_mock_server.events import get_delivery_logs

            assert get_delivery_logs() == []
        finally:
            database.db_name_var.reset(token)
        assert len(client.get("/api/v1/logs").json()["items"]) == 1
