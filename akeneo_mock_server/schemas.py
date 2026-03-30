from pydantic import BaseModel, ConfigDict, Field


class EntityListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search: str | None = None
    search_locale: str | None = None
    search_scope: str | None = None
    attributes: str | None = None
    locales: str | None = None
    scope: str | None = None
    pagination_type: str | None = None
    page: int = 1
    search_after: str | None = None
    limit: int = 10
    with_count: bool = False


class SubEntityListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pagination_type: str | None = None
    page: int = 1
    search_after: str | None = None
    limit: int = 10
    with_count: bool = False


class SearchProductsUuidQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search: str | None = None
    search_locale: str | None = None
    search_scope: str | None = None
    attributes: str | None = None
    locales: str | None = None
    scope: str | None = None
    search_after: str | None = None
    limit: int = Field(default=10, ge=1, le=100)


class GenericPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
