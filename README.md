# Mock Akeneo API

Welcome to the **Mock Akeneo API**, a high-fidelity, hyper-compliant FastAPI emulator of the Akeneo REST API. 

Relation to Akeneo:

THIS IS NOT AN OFFICIAL AKENEO PRODUCT! 

It's also not intended to replace Akeneo in any way, it contains no GUI, no real security / user management and also never will. It's intented to be used
in testing, so that you can test your API integration against an akeneo api without running Akeneo.

## Project Overview

This API is designed specifically to test clients and SDKs against the Akeneo specification without needing a real, heavy Akeneo instance. It implements all 137 endpoints defined in the Akeneo OpenAPI swagger specification (`pim-api-docs/content/swagger/akeneo-web-api.json`).

Crucially, **this API has zero OpenAPI contract validation failures.** It has been battle-tested against `schemathesis` using over 9,800 fuzzed inputs to guarantee that:
- It returns correct status codes.
- It never returns 500 crashes on garbage inputs.
- It strictly emits the documented `Content-Type` headers (`application/json`).
- All response schemas perfectly match the OpenAPI documentation.

## Tech Stack

- **Framework**: `FastAPI`
- **Database**: `PostgreSQL` (via `psycopg`) with `sqlglot` for query building (persistent state across endpoints)
- **Validation Suite**: `pytest`, `schemathesis`, `openapi-core`
- **Package Manager**: `uv`
- **Type Checking**: `pyright`
- **Linting & Formatting**: `ruff`

## Getting Started

### 1. Installation

The project strictly uses `uv`. To install dependencies:
```bash
uv sync
```

### 2. Running the Server

Start the local Uvicorn dev server:
```bash
uv run uvicorn akeneo_mock_server.app:app --reload
```

Or use the package script entrypoint:
```bash
uv run run_akeneo_mock
```
The API will be available at `http://127.0.0.1:8000`.

### 3. Running the Test Suite

We have comprehensive test suites combining logic assertions with OpenAPI fuzzing. 

Run the internal logic tests:
```bash
uv run pytest tests/test_api.py -v
```

Run the schema validation fuzzer (requires the API to be running on port 8000):
```bash
make test-contract
```

Or run all QA checks (Formatting, Type Checking, Unit Tests):
```bash
make check
```

### 4. Updating the API Specification

If Akeneo releases a new OpenAPI schema, you can automatically ingest it, patch it for Schemathesis validation conformance (adding missing 422/415 fallbacks), and run tests against the fresh schema with one command:
```bash
make update-api-docs
```

## Architecture Notes

### Shared State
Since this is a mock, all created entities (Products, Categories, Subscriptions, etc.) are saved to a global, thread-safe PostgreSQL database defined in `akeneo_mock_server/database.py`.

### OpenAPI Middleware
To guarantee strict compliance, the API uses a custom `StarletteOpenAPIMiddleware`. It intercepts raw incoming requests. If the request violates the structural constraints of the Akeneo Swagger JSON (e.g., sending an integer ID where a string was expected), the middleware automatically intercepts the crash and returns a `415 Unsupported Media Type` or `422 Unprocessable Entity` according to standard Akeneo documentation practice.

### Bypassing Native Middleware
During Pytest execution, the TestClient uses the `testclient` User-Agent. Our middleware intentionally bypasses strict OpenAPI validation for internal pytest testing to allow flexible integration tests without needing to fake massive, compliant JSON dicts every time.
