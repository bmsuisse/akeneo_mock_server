from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from akeneo_mock_server.database import (
    _get_db_name,
    ensure_db_exists,
    init_db,
    get_admin_url,
    _db_pools,
    destroy_all_databases,
)
import psycopg
import secrets

router = APIRouter(prefix="/_admin", tags=["admin"])


class BackupRequest(BaseModel):
    backup_to: str | None = None


class RestoreRequest(BaseModel):
    restore_from: str


@router.get("/status")
async def status():
    """Check if the server is running and the database is accessible."""
    try:
        with psycopg.connect(get_admin_url(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"status": "ok", "database": _get_db_name()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {exc}")


@router.post("/ensure_db")
async def ensure_db():
    db_name = _get_db_name()
    ensure_db_exists(db_name)
    return {"message": f"Database '{db_name}' ensured"}


@router.post("/init_db")
async def init_db_endpoint():
    from akeneo_mock_server.database import init_db

    db_name = _get_db_name()
    ensure_db_exists(db_name)
    init_db()
    return {"message": f"Database '{db_name}' initialized"}


@router.post("/destroy_all")
async def destroy_all():
    """Drop all databases managed by the mock server (starting with 'akeneo')."""
    dropped = destroy_all_databases()
    return {"message": "All databases destroyed", "dropped": dropped}


@router.post("/clear")
async def clear_database():
    """Completely clear the current database and re-initialize it."""
    init_db()
    return {"message": f"Database '{_get_db_name()}' cleared"}


@router.post("/backup")
async def backup_database(request: BackupRequest):
    """Backup the current database to a new database."""
    current_db = _get_db_name()
    target_db = request.backup_to or f"akeneo_{secrets.token_hex(4)}"
    admin_url = get_admin_url()

    with psycopg.connect(admin_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Check if target exists
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail=f"Target database '{target_db}' already exists")

            # Terminate connections to source to allow it to be used as a template
            if current_db in _db_pools:
                _db_pools[current_db].close()
                del _db_pools[current_db]

            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (current_db,),
            )

            cur.execute(f'CREATE DATABASE "{target_db}" WITH TEMPLATE "{current_db}"')

    return {
        "message": "Database backup successful",
        "backup_from": current_db,
        "backup_to": target_db,
    }


@router.post("/restore")
async def restore_database(request: RestoreRequest):
    """Restore the current database from a backup."""
    current_db = _get_db_name()
    source_db = request.restore_from
    admin_url = get_admin_url()

    with psycopg.connect(admin_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Check if source exists
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (source_db,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"Backup database '{source_db}' not found")

            # Close all pools for current_db
            if current_db in _db_pools:
                _db_pools[current_db].close()
                del _db_pools[current_db]

            # Terminate connections to current_db
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (current_db,),
            )

            cur.execute(f'DROP DATABASE "{current_db}"')
            cur.execute(f'CREATE DATABASE "{current_db}" WITH TEMPLATE "{source_db}"')

    return {
        "message": "Database restoration successful",
        "restore_from": source_db,
        "restore_to": current_db,
    }
