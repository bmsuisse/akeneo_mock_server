from fastapi import APIRouter, HTTPException
from akeneo_mock_server.database import (
    db_name_var,
    init_db,
    get_admin_url,
    _db_pools,
)
import psycopg

router = APIRouter(prefix="/_admin", tags=["admin"])


@router.post("/clear")
async def clear_database():
    """Completely clear the current database and re-initialize it."""
    init_db()
    return {"message": f"Database '{db_name_var.get()}' cleared"}


@router.post("/backup")
async def backup_database(name: str):
    """Backup the current database to a new database with the given name."""
    current_db = db_name_var.get()
    admin_url = get_admin_url()

    with psycopg.connect(admin_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Drop if exists
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cur.fetchone():
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                    (name,),
                )
                cur.execute(f'DROP DATABASE "{name}"')

            # Terminate connections to source to allow it to be used as a template
            # (PostgreSQL requires no active connections to the template database)
            if current_db in _db_pools:
                _db_pools[current_db].close()
                del _db_pools[current_db]

            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (current_db,),
            )

            cur.execute(f'CREATE DATABASE "{name}" WITH TEMPLATE "{current_db}"')

    return {"message": f"Database '{current_db}' backed up to '{name}'"}


@router.post("/restore")
async def restore_database(name: str):
    """Restore the current database from a backup with the given name."""
    current_db = db_name_var.get()
    admin_url = get_admin_url()

    with psycopg.connect(admin_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Check if source exists
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"Backup database '{name}' not found")

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
            cur.execute(f'CREATE DATABASE "{current_db}" WITH TEMPLATE "{name}"')

    return {"message": f"Database '{current_db}' restored from '{name}'"}


@router.post("/fork")
async def fork_database(name: str):
    """Create a new database 'name' as a fork of the current database."""
    return await backup_database(name)
