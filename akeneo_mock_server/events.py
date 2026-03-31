from typing import Any
import anyio
import httpx
from akeneo_mock_server import database
from akeneo_mock_server.common import safe_loads


def get_entity_event_name(entity_name: str, action: str) -> str:
    singular = entity_name.rstrip("s")
    if singular.endswith("ie"):
        singular = singular[:-2] + "y"
    return f"akeneo.pim.v1.{singular}.{action}"


async def dispatch_event(event_name: str, resource_data: dict[str, Any]) -> None:
    def _collect_subscribers() -> list[tuple[str, str, Any]]:
        with database.get_db_pool().connection() as conn:
            subscribers = conn.execute("SELECT * FROM subscribers").fetchall()
            result = []
            for sub in subscribers:
                sub_data = safe_loads(sub["data"])
                sub_url = sub_data.get("url")
                if not isinstance(sub_url, str) or not sub_url:
                    continue
                subscriptions = conn.execute(
                    "SELECT * FROM subscriptions WHERE parent_id = %s", (sub["id"],)
                ).fetchall()
                flat_events: list[str] = []
                for subscription in subscriptions:
                    s_data = safe_loads(subscription["data"])
                    flat_events.extend(s_data.get("events", []))
                if event_name in flat_events:
                    result.append(sub_url)
            return result

    matching_urls = await anyio.to_thread.run_sync(_collect_subscribers)

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
    for sub_url in matching_urls:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(sub_url, json=payload, timeout=2.0)
        except (httpx.HTTPError, ConnectionError, TimeoutError):
            continue
