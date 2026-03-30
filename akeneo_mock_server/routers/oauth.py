from fastapi import APIRouter

router = APIRouter(prefix="/api/oauth/v1", tags=["oauth"])


@router.post("/token")
def get_oauth_token() -> dict[str, str | int]:
    return {
        "access_token": "mock-access-token",
        "expires_in": 3600,
        "token_type": "bearer",
        "scope": "null",
        "refresh_token": "mock-refresh-token",
    }
