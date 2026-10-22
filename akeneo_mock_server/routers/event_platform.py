import psycopg
from psycopg.types.json import Jsonb
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from akeneo_mock_server.common import safe_json_body, safe_loads
from akeneo_mock_server.database import get_db
from akeneo_mock_server.events import DELIVERY_LOGS, now_iso

router = APIRouter(prefix="/api/v1", tags=["event-platform"])

REDACTED = "***redacted***"


def present_subscription(data: dict[str, Any]) -> dict[str, Any]:
    config = data.get("config")
    if not isinstance(config, dict) or not isinstance(config.get("headers"), dict):
        return data
    redacted_headers = {name: REDACTED for name in config["headers"]}
    return {**data, "config": {**config, "headers": redacted_headers}}


def with_subscription_defaults(data: dict[str, Any], subscriber_id: str) -> dict[str, Any]:
    timestamp = now_iso()
    return {
        "source": "pim",
        "type": "https",
        "status": "active",
        "send_product_identifier": False,
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "status_changed_at": timestamp,
        **data,
        "subscriber_id": subscriber_id,
    }


@router.get("/subscribers")
def get_subscribers(db: psycopg.Connection = Depends(get_db)) -> dict[str, list[dict[str, Any]]]:
    rows = db.execute("SELECT * FROM subscribers").fetchall()
    return {"items": [safe_loads(row["data"]) for row in rows]}


@router.get("/subscribers/{subscriber_id}")
def get_subscriber(subscriber_id: str, db: psycopg.Connection = Depends(get_db)) -> dict[str, Any]:
    row = db.execute("SELECT * FROM subscribers WHERE id = %s", (subscriber_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return safe_loads(row["data"])


@router.post("/subscribers", status_code=status.HTTP_201_CREATED)
async def create_subscriber(request: Request, db: psycopg.Connection = Depends(get_db)) -> JSONResponse:
    data = await safe_json_body(request)
    subscriber_id = data.get("id")
    if not isinstance(subscriber_id, str) or not subscriber_id:
        raise HTTPException(status_code=422, detail="Missing 'id' field in payload")
    if db.execute("SELECT 1 FROM subscribers WHERE id = %s", (subscriber_id,)).fetchone():
        raise HTTPException(status_code=409, detail="Subscriber already exists")

    db.execute("INSERT INTO subscribers (id, data) VALUES (%s, %s)", (subscriber_id, Jsonb(data)))
    db.commit()

    headers = {
        "Location": f"/api/v1/subscribers/{subscriber_id}",
        "Content-Type": "application/json",
    }
    return JSONResponse(content={}, status_code=status.HTTP_201_CREATED, headers=headers)


@router.patch("/subscribers/{subscriber_id}", status_code=status.HTTP_204_NO_CONTENT)
async def patch_subscriber(subscriber_id: str, request: Request, db: psycopg.Connection = Depends(get_db)) -> Response:
    data = await safe_json_body(request)
    row = db.execute("SELECT * FROM subscribers WHERE id = %s", (subscriber_id,)).fetchone()
    if row is None:
        data["id"] = subscriber_id
        db.execute("INSERT INTO subscribers (id, data) VALUES (%s, %s)", (subscriber_id, Jsonb(data)))
    else:
        existing = safe_loads(row["data"])
        existing.update(data)
        db.execute("UPDATE subscribers SET data = %s WHERE id = %s", (Jsonb(existing), subscriber_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/subscribers/{subscriber_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscriber(subscriber_id: str, db: psycopg.Connection = Depends(get_db)) -> Response:
    if not db.execute("SELECT 1 FROM subscribers WHERE id = %s", (subscriber_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Subscriber not found")
    db.execute("DELETE FROM subscribers WHERE id = %s", (subscriber_id,))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/subscribers/{subscriber_id}/subscriptions")
def get_subscriptions(subscriber_id: str, db: psycopg.Connection = Depends(get_db)) -> dict[str, list[dict[str, Any]]]:
    rows = db.execute("SELECT * FROM subscriptions WHERE parent_id = %s", (subscriber_id,)).fetchall()
    return {"items": [present_subscription(safe_loads(row["data"])) for row in rows]}


@router.get("/subscribers/{subscriber_id}/subscriptions/{subscription_id}")
def get_subscription(
    subscriber_id: str, subscription_id: str, db: psycopg.Connection = Depends(get_db)
) -> dict[str, Any]:
    row = db.execute(
        "SELECT * FROM subscriptions WHERE parent_id = %s AND id = %s", (subscriber_id, subscription_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return present_subscription(safe_loads(row["data"]))


@router.post(
    "/subscribers/{subscriber_id}/subscriptions",
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription(
    subscriber_id: str, request: Request, db: psycopg.Connection = Depends(get_db)
) -> JSONResponse:
    data = await safe_json_body(request)
    subscription_id = data.get("id")
    if not isinstance(subscription_id, str) or not subscription_id:
        raise HTTPException(status_code=422, detail="Missing 'id' field in payload")

    existing = db.execute(
        "SELECT 1 FROM subscriptions WHERE parent_id = %s AND id = %s", (subscriber_id, subscription_id)
    ).fetchone()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Subscription already exists")

    db.execute(
        "INSERT INTO subscriptions (pk, id, parent_id, data) VALUES (%s, %s, %s, %s)",
        (
            f"{subscriber_id}/{subscription_id}",
            subscription_id,
            subscriber_id,
            Jsonb(with_subscription_defaults(data, subscriber_id)),
        ),
    )
    db.commit()

    headers = {
        "Location": f"/api/v1/subscribers/{subscriber_id}/subscriptions/{subscription_id}",
        "Content-Type": "application/json",
    }
    return JSONResponse(content={}, status_code=status.HTTP_201_CREATED, headers=headers)


@router.patch(
    "/subscribers/{subscriber_id}/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def patch_subscription(
    subscriber_id: str,
    subscription_id: str,
    request: Request,
    db: psycopg.Connection = Depends(get_db),
) -> Response:
    data = await safe_json_body(request)
    row = db.execute(
        "SELECT * FROM subscriptions WHERE parent_id = %s AND id = %s", (subscriber_id, subscription_id)
    ).fetchone()
    if row is None:
        data["id"] = subscription_id
        db.execute(
            "INSERT INTO subscriptions (pk, id, parent_id, data) VALUES (%s, %s, %s, %s)",
            (f"{subscriber_id}/{subscription_id}", subscription_id, subscriber_id, Jsonb(data)),
        )
    else:
        existing = safe_loads(row["data"])
        existing.update(data)
        existing["updatedAt"] = now_iso()
        db.execute(
            "UPDATE subscriptions SET data = %s WHERE pk = %s", (Jsonb(existing), f"{subscriber_id}/{subscription_id}")
        )

    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/subscribers/{subscriber_id}/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_subscription(
    subscriber_id: str, subscription_id: str, db: psycopg.Connection = Depends(get_db)
) -> Response:
    row = db.execute(
        "SELECT 1 FROM subscriptions WHERE parent_id = %s AND id = %s", (subscriber_id, subscription_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    db.execute("DELETE FROM subscriptions WHERE parent_id = %s AND id = %s", (subscriber_id, subscription_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _transition_subscription(
    db: psycopg.Connection, subscriber_id: str, subscription_id: str, required: str, target: str
) -> JSONResponse:
    row = db.execute(
        "SELECT * FROM subscriptions WHERE parent_id = %s AND id = %s", (subscriber_id, subscription_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    data = safe_loads(row["data"])
    if data.get("status", "active") != required:
        raise HTTPException(status_code=409, detail=f"Subscription is not {required}")
    timestamp = now_iso()
    data.update({"status": target, "updatedAt": timestamp, "status_changed_at": timestamp})
    db.execute("UPDATE subscriptions SET data = %s WHERE pk = %s", (Jsonb(data), f"{subscriber_id}/{subscription_id}"))
    db.commit()
    return JSONResponse(content=present_subscription(data), status_code=status.HTTP_202_ACCEPTED)


@router.post("/subscribers/{subscriber_id}/subscriptions/{subscription_id}/suspend")
def suspend_subscription(
    subscriber_id: str, subscription_id: str, db: psycopg.Connection = Depends(get_db)
) -> JSONResponse:
    return _transition_subscription(db, subscriber_id, subscription_id, "active", "suspended")


@router.post("/subscribers/{subscriber_id}/subscriptions/{subscription_id}/resume")
def resume_subscription(
    subscriber_id: str, subscription_id: str, db: psycopg.Connection = Depends(get_db)
) -> JSONResponse:
    return _transition_subscription(db, subscriber_id, subscription_id, "suspended", "active")


@router.get("/logs")
def get_logs(
    subscriber_id: str | None = None,
    subscription_id: str | None = None,
    log_type: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    items = [
        log
        for log in DELIVERY_LOGS
        if (subscriber_id is None or log.get("subscriber_id") == subscriber_id)
        and (subscription_id is None or log.get("subscription_id") == subscription_id)
        and (log_type is None or log.get("log_type") == log_type)
    ]
    return {"items": items}
