from typing import Any
import httpx
from akeneo_mock_server import database
from akeneo_mock_server.common import safe_loads

def get_entity_event_name(entity_name: str, action: str) -> str:
    singular = entity_name.rstrip("s")
    if singular.endswith("ie"):
        singular = singular[:-2] + "y"
    return f"akeneo.pim.v1.{singular}.{action}"

async def dispatch_event(event_name: str, resource_data: dict[str, Any]) -> None:
    with database.get_connection() as conn:
        subscribers = conn.execute("SELECT * FROM subscribers").fetchall()
        for sub in subscribers:
            sub_data = safe_loads(sub["data"])
            sub_url = sub_data.get("url")
            if not isinstance(sub_url, str) or not sub_url:
                continue

            subscriptions = conn.execute("SELECT * FROM subscriptions WHERE parent_id = %s", (sub["id"],)).fetchall()
            flat_events = []
            for subscription in subscriptions:
                s_data = safe_loads(subscription["data"])
                flat_events.extend(s_data.get("events", []))

            if event_name not in flat_events:
                continue

            event_id = resource_data.get("identifier", resource_data.get("code", "?"))
            payload = {
                "events": [
                    {
                        "action": event_name.split(".")[-1],
                        "event_id": f"evt-{event_id}",
                        "event_date": "2026-03-04T12:00:00Z",
                        "author": "mock-author",
                        "data": {"resource": resource_data},
                    }
                ]
            }
            try:
                async with httpx.AsyncClient(trust_env=False) as client:
                    await client.post(sub_url, json=payload, timeout=2.0)
            except (httpx.HTTPError, ConnectionError, TimeoutError):
                continue
