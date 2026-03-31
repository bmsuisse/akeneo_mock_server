import os
import socket
import sys

sys.modules.setdefault("psycopg_binary", None)  # type: ignore[assignment]
sys.modules.setdefault("psycopg_binary._psycopg", None)  # type: ignore[assignment]

import psycopg
import pytest

from py_pglite.config import PGliteConfig
from py_pglite.manager import PGliteManager


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _try_connect(db_url: str) -> bool:
    try:
        conn = psycopg.connect(db_url)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def postgres_container():
    existing_url = os.environ.get("AKENEO_DATABASE_URL")
    if existing_url:
        if "connect_timeout" not in existing_url:
            existing_url += ("&" if "?" in existing_url else "?") + "connect_timeout=10"
        if _try_connect(existing_url):
            os.environ["AKENEO_DATABASE_URL"] = existing_url
            yield None
            return

    port = _find_free_port()
    config = PGliteConfig(use_tcp=True, tcp_host="127.0.0.1", tcp_port=port)
    manager = PGliteManager(config)
    manager.start()
    manager.wait_for_ready()

    os.environ["AKENEO_DATABASE_URL"] = config.get_psycopg_uri()

    try:
        yield manager
    finally:
        manager.stop()


@pytest.fixture(scope="session", autouse=True)
def init_db_once(postgres_container):
    """Create tables/indexes once per session to avoid per-test DDL lock contention."""
    os.environ["AKENEO_POOL_MIN_SIZE"] = "0"
    os.environ["AKENEO_POOL_MAX_SIZE"] = "1"
    from akeneo_mock_server.database import init_db

    init_db()


@pytest.fixture(autouse=True)
def fresh_db(init_db_once):
    from akeneo_mock_server.database import MODELS, SUB_MODELS, get_db_pool

    pool = get_db_pool()
    conn = pool.getconn()
    cursor = conn.cursor()
    tables = {config["table"] for config in MODELS.values()}
    tables.update({config["table"] for config in SUB_MODELS.values()})
    tables.add("subscribers")
    tables.add("subscriptions")
    tables.add("erp_articles")
    tables.add("erp_field_definitions")
    tables.add("erp_startt")

    for table in tables:
        cursor.execute("SAVEPOINT trunc")
        try:
            cursor.execute(f'TRUNCATE TABLE "{table}" CASCADE')
            cursor.execute("RELEASE SAVEPOINT trunc")
        except psycopg.errors.UndefinedTable:
            cursor.execute("ROLLBACK TO SAVEPOINT trunc")
            cursor.execute("RELEASE SAVEPOINT trunc")
    conn.commit()
    pool.putconn(conn)
    yield
