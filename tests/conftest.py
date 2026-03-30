import os
import time
import pytest
import psycopg

_DEFAULT_DB_URL = "postgresql://akeneo:akeneo@localhost:54327/akeneo?connect_timeout=10"


def _try_connect(db_url: str) -> bool:
    try:
        conn = psycopg.connect(db_url)
        conn.close()
        return True
    except Exception:
        return False


def _start_docker_container() -> tuple[object, str]:
    import docker
    from docker.errors import DockerException, NotFound

    try:
        client = docker.from_env()
        client.ping()
    except DockerException as exc:
        pytest.skip(f"Docker daemon unavailable: {exc}")

    container_name = "akeneo-test-postgres"
    try:
        existing = client.containers.get(container_name)
        existing.stop()
        existing.remove()
    except NotFound:
        pass

    print("\nStarting PostgreSQL container...")
    try:
        container = client.containers.run(
            "postgres:15",
            name=container_name,
            environment={
                "POSTGRES_DB": "akeneo",
                "POSTGRES_USER": "akeneo",
                "POSTGRES_PASSWORD": "akeneo",
            },
            ports={"5432/tcp": 54327},
            detach=True,
            auto_remove=True,
        )
    except DockerException as exc:
        pytest.skip(f"Unable to start Docker container: {exc}")

    container.reload()
    host_port = container.ports["5432/tcp"][0]["HostPort"]
    db_url = f"postgresql://akeneo:akeneo@localhost:{host_port}/akeneo"

    retries = 30
    while retries > 0:
        if _try_connect(db_url):
            print(f"PostgreSQL is ready on port {host_port}!")
            return container, db_url
        retries -= 1
        time.sleep(1)

    container.stop()
    pytest.fail("PostgreSQL container failed to start in time.")


@pytest.fixture(scope="session", autouse=True)
def postgres_container():
    # Use an already-running postgres if available (e.g. CI or local install)
    existing_url = os.environ.get("AKENEO_DATABASE_URL", _DEFAULT_DB_URL)
    if not "connect_timeout" in existing_url:
            existing_url += ("&" if "?" in existing_url else "?") + "connect_timeout=10"
    if _try_connect(existing_url):
        os.environ["AKENEO_DATABASE_URL"] = existing_url
        yield None
        return

    container, db_url = _start_docker_container()
    os.environ["AKENEO_DATABASE_URL"] = db_url
    try:
        yield container
    finally:
        print("\nStopping PostgreSQL container...")
        container.stop()


@pytest.fixture(scope="session", autouse=True)
def init_db_once(postgres_container):
    """Create tables/indexes once per session to avoid per-test DDL lock contention."""
    from akeneo_mock_server.database import init_db

    init_db()


@pytest.fixture(autouse=True)
def fresh_db(init_db_once):
    from akeneo_mock_server.database import get_db_url, MODELS, SUB_MODELS
    db_url = get_db_url()
    conn = psycopg.connect(db_url)
    try:
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
        yield
    finally:
        conn.close()
