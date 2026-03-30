import uvicorn
from akeneo_mock_server.database import init_db


def main() -> None:
    init_db()
    uvicorn.run("akeneo_mock_server.app:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
