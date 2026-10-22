import hashlib
import hmac
import json
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import httpx

from akeneo_mock_server import database
from akeneo_mock_server.common import safe_loads

PLATFORM_PREFIX = "com.akeneo.pim.v1"
SCHEMA_BASE_URL = "https://event.prd.sdk.akeneo.cloud/spec"
MOCK_AUTHOR = {"identifier": "mock-author", "type": "api"}
RESERVED_HEADERS = {"content-type", "user-agent", "x-correlation-id", "host", "authorization", "cookie"}

ENTITY_KINDS: dict[str, str] = {
    "products": "product",
    "products-uuid": "product",
    "product-models": "product-model",
}

PLATFORM_EVENT_TYPES: list[str] = [
    f"{PLATFORM_PREFIX}.{kind}.{suffix}"
    for kind in ("product", "product-model")
    for suffix in ("created", "updated", "updated.delta", "deleted")
]

LEGACY_ACTIONS = {"created": "created", "updated": "updated", "deleted": "removed"}

DELIVERY_LOGS: deque[dict[str, Any]] = deque(maxlen=1000)


def uuid7() -> str:
    millis = int(time.time() * 1000)
    rand = uuid.uuid4().int
    value = (millis & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= ((rand >> 64) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= rand & ((1 << 62) - 1)
    return str(uuid.UUID(int=value))


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_entity_kind(entity_name: str) -> str | None:
    return ENTITY_KINDS.get(entity_name)


def platform_event_type(kind: str, action: str) -> str:
    return f"{PLATFORM_PREFIX}.{kind}.{action}"


def legacy_event_type(kind: str, action: str) -> str:
    return f"{kind.replace('-', '_')}.{LEGACY_ACTIONS[action]}"


def _value_index(values: dict[str, Any]) -> dict[tuple[str, Any, Any], Any]:
    index: dict[tuple[str, Any, Any], Any] = {}
    for attribute, entries in values.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                index[(attribute, entry.get("locale"), entry.get("scope"))] = entry.get("data")
    return index


def compute_changes(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, Any]]:
    before = _value_index((previous or {}).get("values") or {})
    after = _value_index(current.get("values") or {})
    changes: list[dict[str, Any]] = []
    for key in list(after) + [k for k in before if k not in after]:
        if before.get(key) == after.get(key) and key in before and key in after:
            continue
        attribute, locale, scope = key
        changes.append(
            {
                "attribute": attribute,
                "locale": locale,
                "scope": scope,
                "previous": before.get(key),
                "new": after.get(key),
            }
        )
    return changes


def build_cloudevent(
    event_type: str,
    kind: str,
    subscription: dict[str, Any],
    resource: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if kind == "product":
        product: dict[str, Any] = {"uuid": resource.get("uuid")}
        if subscription.get("send_product_identifier") and resource.get("identifier") is not None:
            product["identifier"] = resource["identifier"]
        data["product"] = product
    else:
        data["product_model"] = {"code": resource.get("code")}
    data["author"] = MOCK_AUTHOR
    if event_type.endswith(".updated.delta"):
        changes = compute_changes(previous, resource)
        data["changes"] = changes
    return {
        "specversion": "1.0",
        "id": uuid7(),
        "source": "pim",
        "type": event_type,
        "subject": subscription.get("id"),
        "datacontenttype": "application/json",
        "dataschema": f"{SCHEMA_BASE_URL}/{event_type}.schema.json",
        "time": now_iso(),
        "data": data,
    }


def legacy_removed_resource(kind: str, resource: dict[str, Any]) -> dict[str, Any]:
    if kind == "product":
        return {"identifier": resource.get("identifier"), "uuid": resource.get("uuid")}
    return {"code": resource.get("code")}


def build_legacy_payload(action: str, kind: str, resource: dict[str, Any]) -> dict[str, Any]:
    body = legacy_removed_resource(kind, resource) if action == "deleted" else resource
    return {
        "events": [
            {
                "action": legacy_event_type(kind, action),
                "event_id": str(uuid.uuid4()),
                "event_datetime": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "author": MOCK_AUTHOR["identifier"],
                "author_type": "api",
                "pim_source": "http://localhost:8000",
                "data": {"resource": body},
            }
        ]
    }


def hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def platform_signature_headers(config: dict[str, Any], body: bytes) -> dict[str, str]:
    secret = config.get("secret")
    if not isinstance(secret, dict) or not secret.get("primary"):
        return {}
    headers = {
        "X-AKENEO-SIGNATURE-PRIMARY": hmac_hex(secret["primary"], body),
        "X-AKENEO-SIGNATURE-ALGORITHM": "HmacSHA256",
    }
    if secret.get("secondary"):
        headers["X-AKENEO-SIGNATURE-SECONDARY"] = hmac_hex(secret["secondary"], body)
    return headers


def legacy_signature_headers(secret: str, body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signature = hmac_hex(secret, timestamp.encode() + b"." + body)
    return {"X-Akeneo-Request-Signature": signature, "X-Akeneo-Request-Timestamp": timestamp}


def custom_headers(config: dict[str, Any]) -> dict[str, str]:
    headers = config.get("headers")
    if not isinstance(headers, dict):
        return {}
    return {
        name: value
        for name, value in headers.items()
        if isinstance(value, str)
        and name.lower() not in RESERVED_HEADERS
        and not name.upper().startswith("X-AKENEO-SIGNATURE-")
    }


_TOKEN_RE = re.compile(r'\s*(\(|\)|"[^"]*"|[A-Za-z_]+|=|,)')


def _tokenize(expression: str) -> list[str]:
    tokens: list[str] = []
    position = 0
    while position < len(expression):
        match = _TOKEN_RE.match(expression, position)
        if match is None:
            if expression[position:].strip() == "":
                break
            raise ValueError(f"Invalid filter near '{expression[position:]}'")
        tokens.append(match.group(1))
        position = match.end()
    return tokens


class _FilterParser:
    def __init__(self, tokens: list[str], facts: dict[str, list[Any]]) -> None:
        self.tokens = tokens
        self.facts = facts
        self.position = 0

    def peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self) -> str:
        token = self.tokens[self.position]
        self.position += 1
        return token

    def expect(self, expected: str) -> None:
        if self.peek() != expected:
            raise ValueError(f"Expected '{expected}' in filter")
        self.take()

    def parse_or(self) -> bool:
        result = self.parse_and()
        while self.peek() == "or":
            self.take()
            right = self.parse_and()
            result = result or right
        return result

    def parse_and(self) -> bool:
        result = self.parse_not()
        while self.peek() == "and":
            self.take()
            right = self.parse_not()
            result = result and right
        return result

    def parse_not(self) -> bool:
        if self.peek() == "not":
            self.take()
            return not self.parse_not()
        return self.parse_atom()

    def parse_atom(self) -> bool:
        if self.peek() == "(":
            self.take()
            result = self.parse_or()
            self.expect(")")
            return result
        field = self.take()
        operator = self.take()
        if operator == "=":
            allowed = [self.parse_string()]
        elif operator == "in":
            self.expect("(")
            allowed = [self.parse_string()]
            while self.peek() == ",":
                self.take()
                allowed.append(self.parse_string())
            self.expect(")")
        else:
            raise ValueError(f"Unsupported operator '{operator}' in filter")
        if field == "channel":
            field = "scope"
        if field not in self.facts:
            return False
        return any(fact in allowed or (fact is None and operator == "in") for fact in self.facts[field])

    def parse_string(self) -> str:
        token = self.take()
        if not (token.startswith('"') and token.endswith('"')):
            raise ValueError("Filter values must be double quoted")
        return token[1:-1]


def filter_matches(expression: str | None, facts: dict[str, list[Any]]) -> bool:
    if not expression:
        return True
    parser = _FilterParser(_tokenize(expression), facts)
    return parser.parse_or()


def filter_facts(event_type: str, changes: list[dict[str, Any]]) -> dict[str, list[Any]]:
    facts: dict[str, list[Any]] = {"user": [MOCK_AUTHOR["identifier"]], "user_type": [MOCK_AUTHOR["type"]]}
    if event_type.endswith(".updated.delta"):
        facts["attribute"] = [change["attribute"] for change in changes]
        facts["locale"] = [change["locale"] for change in changes]
        facts["scope"] = [change["scope"] for change in changes]
    return facts


def _record_log(entry: dict[str, Any]) -> None:
    DELIVERY_LOGS.append({"log_id": uuid7(), "timestamp": now_iso(), **entry})


async def _post(url: str, body: bytes, headers: dict[str, str]) -> int | None:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, content=body, headers=headers, timeout=2.0)
    except (httpx.HTTPError, ConnectionError, TimeoutError):
        return None
    return response.status_code


def _target_url(subscription: dict[str, Any], subscriber: dict[str, Any]) -> str | None:
    config = subscription.get("config")
    candidates = [
        config.get("url") if isinstance(config, dict) else None,
        subscription.get("destination", {}).get("url") if isinstance(subscription.get("destination"), dict) else None,
        subscriber.get("url"),
    ]
    return next((candidate for candidate in candidates if isinstance(candidate, str) and candidate), None)


async def dispatch_event(
    entity_name: str,
    action: str,
    resource: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> None:
    kind = get_entity_kind(entity_name)
    if kind is None:
        return
    candidates = {platform_event_type(kind, action), legacy_event_type(kind, action)}
    if action == "updated":
        candidates.add(platform_event_type(kind, "updated.delta"))

    conn = database.get_connection()
    try:
        subscribers = conn.execute("SELECT * FROM subscribers").fetchall()
        deliveries: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any], str]] = []
        for subscriber_row in subscribers:
            subscriber = safe_loads(subscriber_row["data"])
            subscription_rows = conn.execute(
                "SELECT * FROM subscriptions WHERE parent_id = %s", (subscriber_row["id"],)
            ).fetchall()
            for subscription_row in subscription_rows:
                subscription = safe_loads(subscription_row["data"])
                if subscription.get("status", "active") != "active":
                    continue
                if subscription.get("type", "https") != "https":
                    continue
                url = _target_url(subscription, subscriber)
                if url is None:
                    continue
                subscribed = [e for e in subscription.get("events", []) if e in candidates]
                for event_type in subscribed:
                    deliveries.append((event_type, subscriber, subscription, resource, url))
    finally:
        conn.close()

    for event_type, subscriber, subscription, delivered_resource, url in deliveries:
        await _deliver(event_type, kind, action, subscriber, subscription, delivered_resource, previous, url)


async def _deliver(
    event_type: str,
    kind: str,
    action: str,
    subscriber: dict[str, Any],
    subscription: dict[str, Any],
    resource: dict[str, Any],
    previous: dict[str, Any] | None,
    url: str,
) -> None:
    config = subscription.get("config") if isinstance(subscription.get("config"), dict) else {}
    headers = {"Content-Type": "application/json", **custom_headers(config)}
    is_platform = event_type.startswith(f"{PLATFORM_PREFIX}.")
    if is_platform:
        payload = build_cloudevent(event_type, kind, subscription, resource, previous)
        if not filter_matches(
            subscription.get("filter"), filter_facts(event_type, payload["data"].get("changes", []))
        ):
            return
        body = json.dumps(payload).encode()
        headers.update(platform_signature_headers(config, body))
    else:
        payload = build_legacy_payload(action, kind, resource)
        body = json.dumps(payload).encode()
        secret = subscriber.get("secret")
        if isinstance(secret, str) and secret:
            headers.update(legacy_signature_headers(secret, body))
    status_code = await _post(url, body, headers)
    _record_log(
        {
            "log_type": "action" if status_code is not None and status_code < 400 else "error",
            "operation": "deliver_event",
            "subscriber_id": subscriber.get("id"),
            "subscription_id": subscription.get("id"),
            "event_type": event_type,
            "status_code": status_code,
        }
    )
