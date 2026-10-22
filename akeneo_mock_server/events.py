import copy
import hashlib
import hmac
import json
import re
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from akeneo_mock_server import database
from akeneo_mock_server.common import safe_loads

PLATFORM_PREFIX = "com.akeneo.pim.v1"
SCHEMA_BASE_URL = "https://event.prd.sdk.akeneo.cloud/spec"
MOCK_AUTHOR = {"identifier": "mock-author", "type": "api"}
RESERVED_HEADERS = {"content-type", "user-agent", "x-correlation-id", "host", "authorization", "cookie"}
MAX_FILTER_LENGTH = 500

EVENT_SAMPLES: dict[str, dict[str, Any]] = json.loads(
    (Path(__file__).parent / "event_samples.json").read_text(encoding="utf-8")
)
PLATFORM_EVENT_TYPES: list[str] = sorted(EVENT_SAMPLES)

LEGACY_EVENT_TYPES: list[str] = [
    f"{kind}.{action}" for kind in ("product", "product_model") for action in ("created", "updated", "removed")
]
LEGACY_ACTIONS = {"created": "created", "updated": "updated", "deleted": "removed"}
LEGACY_KINDS = {"product": "product", "product-model": "product_model"}

DELIVERY_LOGS: dict[str | None, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=1000))


@dataclass(frozen=True)
class EventEntity:
    kind: str
    data_key: str
    reference: Callable[[dict[str, Any], str | None], dict[str, Any]]
    delta: bool = False


def _code_reference(resource: dict[str, Any], parent: str | None) -> dict[str, Any]:
    return {"code": resource.get("code")}


def _parent_reference(parent_key: str) -> Callable[[dict[str, Any], str | None], dict[str, Any]]:
    def reference(resource: dict[str, Any], parent: str | None) -> dict[str, Any]:
        return {"code": resource.get("code"), parent_key: {"code": parent or resource.get("parent_id")}}

    return reference


def _product_reference(resource: dict[str, Any], parent: str | None) -> dict[str, Any]:
    return {"uuid": resource.get("uuid"), "identifier": resource.get("identifier")}


EVENT_ENTITIES: dict[str, EventEntity] = {
    "products": EventEntity("product", "product", _product_reference, delta=True),
    "products-uuid": EventEntity("product", "product", _product_reference, delta=True),
    "product-models": EventEntity("product-model", "product_model", _code_reference, delta=True),
    "categories": EventEntity("category", "category", _code_reference, delta=True),
    "attributes": EventEntity("attribute", "attribute", _code_reference),
    "attribute-groups": EventEntity("attribute-group", "attribute_group", _code_reference),
    "families": EventEntity("family", "family", _code_reference),
    "attributes/attribute-options": EventEntity(
        "attribute-option", "attribute_option", _parent_reference("attribute"), delta=True
    ),
    "families/family-variants": EventEntity("family-variant", "family_variant", _parent_reference("family")),
    "reference-entities/records": EventEntity(
        "reference-entity-record", "reference_entity_record", _parent_reference("reference_entity"), delta=True
    ),
    "asset-families/assets": EventEntity("asset", "asset", _parent_reference("asset_family"), delta=True),
}


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
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def platform_event_type(kind: str, action: str) -> str:
    return f"{PLATFORM_PREFIX}.{kind}.{action}"


def known_event_types() -> set[str]:
    return set(PLATFORM_EVENT_TYPES) | set(LEGACY_EVENT_TYPES)


def infer_value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "multiselect"
    if isinstance(value, dict) and "amount" in value:
        return "price"
    if isinstance(value, dict) and "unit" in value:
        return "metric"
    return "text"


def _scalar_change(previous: Any, current: Any) -> dict[str, Any] | None:
    if previous == current:
        return None
    return {"previous": previous, "new": current}


def _list_change(previous: list[Any] | None, current: list[Any] | None) -> dict[str, list[Any]] | None:
    before, after = previous or [], current or []
    added = [item for item in after if item not in before]
    removed = [item for item in before if item not in after]
    if not added and not removed:
        return None
    return {"added": added, "removed": removed}


def _value_index(values: dict[str, Any]) -> dict[tuple[str, Any, Any], Any]:
    index: dict[tuple[str, Any, Any], Any] = {}
    for attribute, entries in values.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                index[(attribute, entry.get("locale"), entry.get("scope", entry.get("channel")))] = entry.get("data")
    return index


def values_changes(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    scope_key: str,
    attribute_types: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    known_types = attribute_types or {}
    before = _value_index((previous or {}).get("values") or {})
    after = _value_index(current.get("values") or {})
    changes: dict[str, list[dict[str, Any]]] = {}
    for key in list(after) + [k for k in before if k not in after]:
        if key in before and key in after and before[key] == after[key]:
            continue
        attribute, locale, scope = key
        sample = after.get(key) if after.get(key) is not None else before.get(key)
        changes.setdefault(attribute, []).append(
            {
                "previous": before.get(key),
                "new": after.get(key),
                "type": known_types.get(attribute) or infer_value_type(sample),
                "locale": locale,
                scope_key: scope,
            }
        )
    return changes


def _association_changes(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    before = (previous or {}).get("associations") or {}
    after = current.get("associations") or {}
    changes: dict[str, Any] = {}
    for association_type in set(before) | set(after):
        added: dict[str, list[Any]] = {}
        removed: dict[str, list[Any]] = {}
        for target in ("products", "product_models", "groups"):
            change = _list_change(
                (before.get(association_type) or {}).get(target), (after.get(association_type) or {}).get(target)
            )
            if change is not None:
                added[target], removed[target] = change["added"], change["removed"]
        if added or removed:
            changes[association_type] = {"added": added, "removed": removed}
    return changes


def _labels_changes(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    before = (previous or {}).get("labels") or {}
    after = current.get("labels") or {}
    changes: dict[str, Any] = {}
    for locale in set(before) | set(after):
        change = _scalar_change(before.get(locale), after.get(locale))
        if change is not None:
            changes[locale] = change
    return changes


def _set_if(changes: dict[str, Any], key: str, change: Any) -> None:
    if change:
        changes[key] = change


def compute_delta_changes(
    kind: str,
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    attribute_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if kind in ("product", "product-model"):
        if kind == "product":
            _set_if(changes, "enabled", _scalar_change((previous or {}).get("enabled"), current.get("enabled")))
            _set_if(changes, "family", _scalar_change((previous or {}).get("family"), current.get("family")))
            _set_if(changes, "groups", _list_change((previous or {}).get("groups"), current.get("groups")))
        _set_if(changes, "categories", _list_change((previous or {}).get("categories"), current.get("categories")))
        _set_if(changes, "parent", _scalar_change((previous or {}).get("parent"), current.get("parent")))
        _set_if(changes, "values", values_changes(previous, current, "scope", attribute_types))
        _set_if(changes, "associations", _association_changes(previous, current))
    elif kind == "category":
        _set_if(changes, "parent", _scalar_change((previous or {}).get("parent"), current.get("parent")))
        _set_if(changes, "labels", _labels_changes(previous, current))
        _set_if(changes, "values", values_changes(previous, current, "scope", attribute_types))
    elif kind == "attribute-option":
        _set_if(changes, "sort_order", _scalar_change((previous or {}).get("sort_order"), current.get("sort_order")))
        _set_if(changes, "labels", _labels_changes(previous, current))
    else:
        _set_if(changes, "values", values_changes(previous, current, "channel"))
    return changes


def build_event_data(
    entity: EventEntity,
    action: str,
    event_type: str,
    subscription: dict[str, Any],
    resource: dict[str, Any],
    previous: dict[str, Any] | None,
    parent: str | None,
    attribute_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    reference = entity.reference(resource, parent)
    if entity.kind == "product" and not subscription.get("send_product_identifier"):
        reference.pop("identifier", None)
    if event_type.endswith(".updated.delta"):
        reference["changes"] = compute_delta_changes(entity.kind, previous, resource, attribute_types)
        if entity.kind in ("product", "product-model", "reference-entity-record"):
            reference["updated_at"] = {
                "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.000000"),
                "timezone": "UTC",
            }
    return {entity.data_key: reference, "author": dict(MOCK_AUTHOR)}


def wrap_cloudevent(event_type: str, subscription: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
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


def build_legacy_payload(action: str, kind: str, resource: dict[str, Any]) -> dict[str, Any]:
    legacy_kind = LEGACY_KINDS[kind]
    if action == "deleted":
        body = (
            {"identifier": resource.get("identifier"), "uuid": resource.get("uuid")}
            if kind == "product"
            else {"code": resource.get("code")}
        )
    else:
        body = resource
    return {
        "events": [
            {
                "action": f"{legacy_kind}.{LEGACY_ACTIONS[action]}",
                "event_id": str(uuid.uuid4()),
                "event_datetime": datetime.now(UTC).isoformat(timespec="seconds"),
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
    if not isinstance(secret, dict) or not isinstance(secret.get("primary"), str) or not secret["primary"]:
        return {}
    headers = {
        "X-AKENEO-SIGNATURE-PRIMARY": hmac_hex(secret["primary"], body),
        "X-AKENEO-SIGNATURE-ALGORITHM": "HmacSHA256",
    }
    if isinstance(secret.get("secondary"), str) and secret["secondary"]:
        headers["X-AKENEO-SIGNATURE-SECONDARY"] = hmac_hex(secret["secondary"], body)
    return headers


def legacy_signature_headers(secret: str, body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signature = hmac_hex(secret, timestamp.encode() + b"." + body)
    return {"X-Akeneo-Request-Signature": signature, "X-Akeneo-Request-Timestamp": timestamp}


HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,128}$")
HEADER_VALUE_RE = re.compile(r"^[\x20-\x7e]{0,256}$")


def custom_headers(config: dict[str, Any]) -> dict[str, str]:
    headers = config.get("headers")
    if not isinstance(headers, dict):
        return {}
    return {
        name: value
        for name, value in headers.items()
        if isinstance(value, str)
        and HEADER_NAME_RE.match(name)
        and HEADER_VALUE_RE.match(value)
        and name.lower() not in RESERVED_HEADERS
        and not name.upper().startswith("X-AKENEO-SIGNATURE-")
    }


_TOKEN_RE = re.compile(r'\s*(\(|\)|\[|\]|"[^"]*"|[A-Za-z_]+|=|,)')
_NULLABLE_FIELDS = {"locale", "scope"}


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
        if self.position >= len(self.tokens):
            raise ValueError("Unexpected end of filter")
        token = self.tokens[self.position]
        self.position += 1
        return token

    def expect(self, *expected: str) -> str:
        token = self.take()
        if token not in expected:
            raise ValueError(f"Expected '{expected[0]}' in filter")
        return token

    def parse(self) -> bool:
        result = self.parse_or()
        if self.peek() is not None:
            raise ValueError(f"Unexpected '{self.peek()}' in filter")
        return result

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
            closing = {"(": ")", "[": "]"}[self.expect("(", "[")]
            allowed = [self.parse_string()]
            while self.peek() == ",":
                self.take()
                allowed.append(self.parse_string())
            self.expect(closing)
        else:
            raise ValueError(f"Unsupported operator '{operator}' in filter")
        if field == "channel":
            field = "scope"
        if field not in self.facts:
            return False
        return any(fact in allowed or (fact is None and field in _NULLABLE_FIELDS) for fact in self.facts[field])

    def parse_string(self) -> str:
        token = self.take()
        if not (token.startswith('"') and token.endswith('"') and len(token) >= 2):
            raise ValueError("Filter values must be double quoted")
        return token[1:-1]


def filter_matches(expression: str | None, facts: dict[str, list[Any]]) -> bool:
    if not expression:
        return True
    return _FilterParser(_tokenize(expression), facts).parse()


def validate_filter(expression: Any) -> None:
    if expression in (None, ""):
        return
    if not isinstance(expression, str):
        raise ValueError("Filter must be a string")
    if len(expression) > MAX_FILTER_LENGTH:
        raise ValueError(f"Filter must not exceed {MAX_FILTER_LENGTH} characters")
    _FilterParser(_tokenize(expression), {}).parse()


def filter_facts(event_type: str, data: dict[str, Any], entity: EventEntity | None) -> dict[str, list[Any]]:
    author = data.get("author") or MOCK_AUTHOR
    facts: dict[str, list[Any]] = {"user": [author.get("identifier")], "user_type": [author.get("type")]}
    if entity is None or not event_type.endswith(".updated.delta"):
        return facts
    values = (data.get(entity.data_key) or {}).get("changes", {}).get("values", {})
    entries = [entry for items in values.values() for entry in items]
    facts["attribute"] = list(values)
    facts["locale"] = [entry.get("locale") for entry in entries]
    facts["scope"] = [entry.get("scope", entry.get("channel")) for entry in entries]
    return facts


def validate_subscription(data: dict[str, Any]) -> None:
    events = data.get("events")
    if events is not None:
        if not isinstance(events, list) or not all(isinstance(event, str) for event in events):
            raise ValueError("'events' must be a list of event type names")
        unknown = sorted(set(events) - known_event_types())
        if unknown:
            raise ValueError(f"Unknown event types: {', '.join(unknown)}")
    validate_filter(data.get("filter"))


def resolve_attribute_types(resource: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, str]:
    codes = set((resource.get("values") or {}).keys()) | set(((previous or {}).get("values") or {}).keys())
    if not codes:
        return {}
    conn = database.get_connection()
    try:
        rows = conn.execute("SELECT id, type FROM attributes WHERE id = ANY(%s)", (sorted(codes),)).fetchall()
    finally:
        conn.close()
    return {row["id"]: row["type"] for row in rows if row["type"]}


def _record_log(entry: dict[str, Any]) -> None:
    DELIVERY_LOGS[database.db_name_var.get()].append({"log_id": uuid7(), "timestamp": now_iso(), **entry})


def get_delivery_logs() -> list[dict[str, Any]]:
    return list(DELIVERY_LOGS[database.db_name_var.get()])


async def _post(url: str, body: bytes, headers: dict[str, str]) -> int | None:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, content=body, headers=headers, timeout=2.0)
    except (httpx.HTTPError, httpx.InvalidURL, ConnectionError, TimeoutError):
        return None
    return response.status_code


def _target_url(subscription: dict[str, Any], subscriber: dict[str, Any]) -> str | None:
    config = subscription.get("config")
    destination = subscription.get("destination")
    candidates = [
        config.get("url") if isinstance(config, dict) else None,
        destination.get("url") if isinstance(destination, dict) else None,
        subscriber.get("url"),
    ]
    return next((candidate for candidate in candidates if isinstance(candidate, str) and candidate), None)


@dataclass(frozen=True)
class Delivery:
    event_type: str
    subscriber: dict[str, Any]
    subscription: dict[str, Any]
    url: str


def find_deliveries(event_types: set[str]) -> list[Delivery]:
    conn = database.get_connection()
    try:
        deliveries: list[Delivery] = []
        for subscriber_row in conn.execute("SELECT * FROM subscribers").fetchall():
            subscriber = safe_loads(subscriber_row["data"])
            for subscription_row in conn.execute(
                "SELECT * FROM subscriptions WHERE parent_id = %s", (subscriber_row["id"],)
            ).fetchall():
                subscription = safe_loads(subscription_row["data"])
                if subscription.get("status", "active") != "active" or subscription.get("type", "https") != "https":
                    continue
                url = _target_url(subscription, subscriber)
                if url is None:
                    continue
                for event_type in subscription.get("events", []):
                    if event_type in event_types:
                        deliveries.append(Delivery(event_type, subscriber, subscription, url))
        return deliveries
    finally:
        conn.close()


def _subscription_config(subscription: dict[str, Any]) -> dict[str, Any]:
    config = subscription.get("config")
    return config if isinstance(config, dict) else {}


def _filter_allows(subscription: dict[str, Any], facts: dict[str, list[Any]]) -> bool:
    try:
        return filter_matches(subscription.get("filter"), facts)
    except ValueError:
        return False


async def _send(delivery: Delivery, payload: dict[str, Any], platform: bool) -> None:
    config = _subscription_config(delivery.subscription)
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", **custom_headers(config)}
    if platform:
        headers.update(platform_signature_headers(config, body))
    else:
        secret = delivery.subscriber.get("secret")
        if isinstance(secret, str) and secret:
            headers.update(legacy_signature_headers(secret, body))
    status_code = await _post(delivery.url, body, headers)
    _record_log(
        {
            "log_type": "action" if status_code is not None and status_code < 400 else "error",
            "operation": "deliver_event",
            "subscriber_id": delivery.subscriber.get("id"),
            "subscription_id": delivery.subscription.get("id"),
            "event_type": delivery.event_type,
            "status_code": status_code,
        }
    )


async def dispatch_event(
    entity_name: str,
    action: str,
    resource: dict[str, Any],
    previous: dict[str, Any] | None = None,
    parent: str | None = None,
) -> None:
    entity = EVENT_ENTITIES.get(entity_name)
    if entity is None:
        return
    event_types = {platform_event_type(entity.kind, action)}
    if action == "updated" and entity.delta:
        event_types.add(platform_event_type(entity.kind, "updated.delta"))
    if entity.kind in LEGACY_KINDS:
        event_types.add(f"{LEGACY_KINDS[entity.kind]}.{LEGACY_ACTIONS[action]}")

    deliveries = find_deliveries(event_types)
    attribute_types = (
        resolve_attribute_types(resource, previous)
        if entity.delta and any(d.event_type.endswith(".updated.delta") for d in deliveries)
        else {}
    )
    for delivery in deliveries:
        if delivery.event_type.startswith(f"{PLATFORM_PREFIX}."):
            data = build_event_data(
                entity,
                action,
                delivery.event_type,
                delivery.subscription,
                resource,
                copy.deepcopy(previous),
                parent,
                attribute_types,
            )
            if not _filter_allows(delivery.subscription, filter_facts(delivery.event_type, data, entity)):
                continue
            await _send(delivery, wrap_cloudevent(delivery.event_type, delivery.subscription, data), True)
            continue
        await _send(delivery, build_legacy_payload(action, entity.kind, resource), False)


def _entity_for_event_data(data: dict[str, Any]) -> EventEntity | None:
    return next((entity for entity in EVENT_ENTITIES.values() if entity.data_key in data), None)


async def dispatch_raw_event(event_type: str, data: dict[str, Any]) -> int:
    entity = _entity_for_event_data(data)
    sent = 0
    for delivery in find_deliveries({event_type}):
        delivered = copy.deepcopy(data)
        product = delivered.get("product")
        if isinstance(product, dict) and not delivery.subscription.get("send_product_identifier"):
            product.pop("identifier", None)
        if not _filter_allows(delivery.subscription, filter_facts(event_type, data, entity)):
            continue
        await _send(delivery, wrap_cloudevent(event_type, delivery.subscription, delivered), True)
        sent += 1
    return sent
