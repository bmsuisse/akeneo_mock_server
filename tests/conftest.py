import psycopg
import pytest


@pytest.fixture(scope="session", autouse=True)
def init_db_once():
    """Start PGlite and initialize the schema once per test session."""
    from akeneo_mock_server.database import init_db, close_db_pool

    init_db()
    yield
    close_db_pool()


@pytest.fixture(autouse=True)
def fresh_db(init_db_once):
    from akeneo_mock_server.database import get_connection, MODELS, SUB_MODELS

    conn = get_connection()
    tables = {config["table"] for config in MODELS.values()}
    tables.update({config["table"] for config in SUB_MODELS.values()})
    tables.add("subscribers")
    tables.add("subscriptions")
    tables.add("erp_articles")
    tables.add("erp_field_definitions")
    tables.add("erp_startt")

    for table in tables:
        conn.execute("SAVEPOINT trunc")
        try:
            conn.execute(f'TRUNCATE TABLE "{table}" CASCADE')
            conn.execute("RELEASE SAVEPOINT trunc")
        except psycopg.errors.UndefinedTable:
            conn.execute("ROLLBACK TO SAVEPOINT trunc")
            conn.execute("RELEASE SAVEPOINT trunc")
    conn.commit()
    yield
