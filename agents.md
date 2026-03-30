# Mock Akeneo API - Agent Instructions

Hello, fellow AI Agent! If you are reading this, you are working in the `MockAkeneo` repository. This document outlines the critical rules, architecture patterns, and tools you must use when maintaining this project.

## 🚨 CRITICAL DIRECTIVES 🚨

1. **Test-Driven Development**: You MUST run tests before committing.
   - Run **logic tests**: `uv run pytest tests/test_api.py -v`
   - Run **API contract tests** (Schemathesis): `make test-contract`
   - Run **formatting & typing**: `make check`
2. **Zero Failures**: The API currently has 0 contract validation failures against `pim-api-docs/content/swagger/akeneo-web-api.json`. **Do not merge or commit code that reintroduces Schemathesis failures.**
3. **Automated Schema Updates**: If requested to update the Akeneo specification, use `make update-api-docs`. This will pull the latest commit from the `pim-api-docs` submodule, automatically run `patch_schema.py` to inject 415/422 status codes (preventing undocumented status crashes), and re-run Schemathesis.
4. **Toolchain Discipline**:
   - Use `uv` for all Python package management.
   - Use `pyright` for type checking.
   - Use `ruff` for formatting and linting.
   - You MUST add type hints in Python. Use the `typing` module extensively.
5. **API Docs** The REST-API is described under `pim-api-docs/content/rest-api` 

## Code Style

- **No comments in code.** Code must be self-explanatory through naming. Remove all inline comments, section separators (`# ---`), and explanatory prose.
- **No docstrings** on functions, classes, or modules unless absolutely part of a public API contract. Prefer clear naming over documentation.
- **No defensive try/except.** Only catch specific exceptions you can actually handle. Never catch `Exception` to silently swallow errors; never wrap JSON parsing in a try block when you want FastAPI to return the error naturally.
- **Pyright-clean typing.** Every function must have full type annotations. Run `uv run pyright` before committing — zero errors required.
- **Flat control flow.** Prefer early `return` over nested `if/else`. Avoid deeply nested blocks.

## Architecture Guidelines

### Database (`database.py`)
- We use `sqlite3` (built-in) with `sqlglot` for query building.
- All endpoints share this state. To add a new entity, update the schema in `database.py`.
- A global `get_db()` dependency injects the connection.

### The OpenAPI Middleware Barrier
- A custom `CustomStarletteOpenAPIMiddleware` wraps the FastAPI application to intercept native `openapi_core.exceptions.OpenAPIError` crashes. 
- It maps validation failures to `415` or `422` HTTP responses. 
- **CRITICAL EXCEPTION:** This middleware strictly looks for `b"testclient"` in the `User-Agent`. If it detects the internal Pytest suite is querying the API, it BYPASSES validation. This allows testing basic logic without typing massive 1,000-line Akeneo schemas into pytest arrays. 
- If you are testing via `Schemathesis`, the middleware WILL enforce compliance. 

### Response Formatting
- Schemathesis strictly expects `Content-Type: application/json` on all `201 Created` responses. Never return `Response(status_code=201)`. Use `JSONResponse(content={}, status_code=201)`.
- HTTP 204 No Content MUST NOT HAVE A BODY. Return `Response(status_code=204)`. Do not use `JSONResponse`.

## Safe Commit Workflow

When wrapping up a feature, execute the following to verify the repository:
```bash
uv run ruff format .
uv run pyright main.py database.py tests/test_api.py
uv run pytest tests/test_api.py -v
git add .
git commit -m "style: describe your changes"
git push origin <branch_name>
```

Always create a new branch for each feature request. Do not push directly to main unless specifically authorized. 

Happy coding!
