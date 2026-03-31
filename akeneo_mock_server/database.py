import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, NullConnectionPool
from typing import Any, Generator
from pydantic import BaseModel, Field
from pathlib import Path
import time

import os

SCHEMA_SQL_PATH = Path(__file__).with_name("schema.sql")
_db_pool: ConnectionPool | None = None
_db_pool_url: str | None = None


def get_db_url():
    return os.environ.get("AKENEO_DATABASE_URL", "postgresql://akeneo:akeneo@localhost:54327/akeneo")


def get_db_pool() -> ConnectionPool:
    global _db_pool
    global _db_pool_url

    db_url = get_db_url()
    if _db_pool is not None and _db_pool_url == db_url:
        return _db_pool

    if _db_pool is not None:
        _db_pool.close()

    pool_min_size = int(os.environ.get("AKENEO_POOL_MIN_SIZE", "1"))
    pool_max_size = int(os.environ.get("AKENEO_POOL_MAX_SIZE", "20"))
    pool_kwargs: dict[str, Any] = {"row_factory": dict_row}
    if os.environ.get("AKENEO_POOL_NULL"):
        _db_pool = NullConnectionPool(
            conninfo=db_url,
            max_size=pool_max_size,
            kwargs=pool_kwargs,
            open=True,
        )
    else:
        _db_pool = ConnectionPool(
            conninfo=db_url,
            min_size=pool_min_size,
            max_size=pool_max_size,
            kwargs=pool_kwargs,
            open=True,
        )
    _db_pool_url = db_url
    return _db_pool


def close_db_pool() -> None:
    global _db_pool
    global _db_pool_url

    if _db_pool is not None:
        _db_pool.close()
    _db_pool = None
    _db_pool_url = None


def get_connection():
    conn = psycopg.connect(get_db_url(), row_factory=dict_row)
    return conn


class EntityBase(BaseModel):
    id: str | None = None
    code: str | None = None
    data: str | None = "{}"
    updated: Any | None = None


class SubEntityBase(BaseModel):
    id: str | None = None
    code: str | None = None
    parent_id: str | None = None
    data: str | None = "{}"
    updated: Any | None = None


# Explicit Models (now Pydantic models for validation/typing, not ORM)


class ProductModel(BaseModel):
    uuid: str | None = None
    identifier: str
    enabled: bool | None = True
    family: str | None = None
    categories: list[str] | None = Field(default_factory=list)
    groups: list[str] | None = Field(default_factory=list)
    parent: str | None = None
    values: dict[str, Any] | None = Field(default_factory=dict)
    associations: dict[str, Any] | None = Field(default_factory=dict)
    quantified_associations: dict[str, Any] | None = Field(default_factory=dict)
    created: str | None = None
    updated: str | None = None
    metadata_info: dict[str, Any] | None = Field(default=None, alias="metadata")
    quality_scores: Any | None = None
    completenesses: Any | None = None


class ProductUuidModel(BaseModel):
    uuid: str
    identifier: str | None = None


class PublishedProductModel(BaseModel):
    identifier: str
    enabled: bool | None = True
    family: str | None = None
    categories: list[str] | None = Field(default_factory=list)
    groups: list[str] | None = Field(default_factory=list)
    values: dict[str, Any] | None = Field(default_factory=dict)
    associations: dict[str, Any] | None = Field(default_factory=dict)
    quantified_associations: dict[str, Any] | None = Field(default_factory=dict)
    created: str | None = None
    updated: str | None = None


class CategoryModel(BaseModel):
    code: str
    parent: str | None = None
    updated: str | None = None
    position: int | None = None
    labels: dict[str, Any] | None = Field(default_factory=dict)
    values: dict[str, Any] | None = Field(default_factory=dict)
    channel_requirements: list[str] | None = Field(default_factory=list)


class AttributeModel(BaseModel):
    code: str
    type: str = ""
    labels: dict[str, Any] | None = Field(default_factory=dict)
    group: str = ""
    group_labels: dict[str, Any] | None = Field(default_factory=dict)
    sort_order: int | None = 0
    localizable: bool | None = False
    scopable: bool | None = False
    available_locales: list[str] | None = Field(default_factory=list)
    unique: bool | None = False
    useable_as_grid_filter: bool | None = False
    max_characters: int | None = None
    validation_rule: str | None = None
    validation_regexp: str | None = None
    wysiwyg_enabled: bool | None = False
    number_min: str | None = None
    number_max: str | None = None
    decimals_allowed: bool | None = False
    negative_allowed: bool | None = False
    metric_family: str | None = None
    default_metric_unit: str | None = None
    date_min: str | None = None
    date_max: str | None = None
    allowed_extensions: list[str] | None = Field(default_factory=list)
    max_file_size: str | None = None
    reference_data_name: str | None = None
    default_value: bool | None = None
    table_configuration: Any | None = None
    is_main_identifier: bool | None = False
    is_mandatory: bool | None = False
    decimal_places_strategy: str | None = None
    decimal_places: float | None = None


class AttributeGroupModel(BaseModel):
    code: str
    sort_order: int | None = 0
    attributes: list[str] | None = Field(default_factory=list)
    labels: dict[str, Any] | None = Field(default_factory=dict)


class FamilyModel(BaseModel):
    code: str
    attribute_as_label: str = ""
    attribute_as_image: str | None = None
    attributes: list[str] | None = Field(default_factory=list)
    attribute_requirements: dict[str, Any] | None = Field(default_factory=dict)
    labels: dict[str, Any] | None = Field(default_factory=dict)


class ChannelModel(BaseModel):
    code: str
    locales: list[str] = Field(default_factory=list)
    currencies: list[str] = Field(default_factory=list)
    category_tree: str = ""
    conversion_units: dict[str, Any] | None = Field(default_factory=dict)
    labels: dict[str, Any] | None = Field(default_factory=dict)


class LocaleModel(BaseModel):
    code: str
    enabled: bool | None = False


class CurrencyModel(BaseModel):
    code: str
    enabled: bool | None = False
    label: str | None = None


class MeasureFamilyModel(BaseModel):
    code: str
    standard: str | None = None
    units: list[dict[str, Any]] | None = Field(default_factory=list)


class MeasurementFamilyModel(BaseModel):
    code: str
    labels: dict[str, Any] | None = Field(default_factory=dict)
    standard_unit_code: str = ""
    units: dict[str, Any] = Field(default_factory=dict)


class AssociationTypeModel(BaseModel):
    code: str
    labels: dict[str, Any] | None = Field(default_factory=dict)
    is_quantified: bool | None = False
    is_two_way: bool | None = False


class ReferenceEntityModel(BaseModel):
    code: str
    labels: dict[str, Any] | None = Field(default_factory=dict)
    image: str | None = None


class AssetFamilyModel(EntityBase):
    pass


class ProductModelEntityModel(BaseModel):
    code: str
    family: str | None = None
    family_variant: str = ""
    parent: str | None = None
    categories: list[str] | None = Field(default_factory=list)
    values: dict[str, Any] | None = Field(default_factory=dict)
    associations: dict[str, Any] | None = Field(default_factory=dict)
    quantified_associations: dict[str, Any] | None = Field(default_factory=dict)
    created: str | None = None
    updated: str | None = None
    metadata_info: dict[str, Any] | None = Field(default=None, alias="metadata")
    quality_scores: Any | None = None


class DeprecatedAssetModel(EntityBase):
    pass


class DeprecatedAssetCategoryModel(EntityBase):
    pass


class DeprecatedAssetTagModel(EntityBase):
    pass


class SubscriberModel(EntityBase):
    pass


class AttributeOptionModel(BaseModel):
    code: str
    parent_id: str
    attribute: str | None = None
    sort_order: int | None = None
    labels: dict[str, Any] | None = Field(default_factory=dict)


class FamilyVariantModel(SubEntityBase):
    pass


class ReferenceEntityRecordModel(SubEntityBase):
    pass


class ReferenceEntityAttributeModel(SubEntityBase):
    pass


class AssetModel(SubEntityBase):
    pass


class AssetAttributeModel(SubEntityBase):
    pass


class SubscriptionModel(BaseModel):
    pk: str = ""
    id: str
    parent_id: str
    data: str = "{}"


MODELS: dict[str, dict[str, Any]] = {
    "products": {"model": ProductModel, "pk_field": "identifier", "table": "products"},
    "products-uuid": {"model": ProductModel, "pk_field": "uuid", "table": "products"},
    "published-products": {"model": PublishedProductModel, "pk_field": "identifier", "table": "published_products"},
    "categories": {"model": CategoryModel, "pk_field": "code", "table": "categories"},
    "attributes": {"model": AttributeModel, "pk_field": "code", "table": "attributes"},
    "attribute-groups": {"model": AttributeGroupModel, "pk_field": "code", "table": "attribute_groups"},
    "families": {"model": FamilyModel, "pk_field": "code", "table": "families"},
    "channels": {"model": ChannelModel, "pk_field": "code", "table": "channels"},
    "locales": {"model": LocaleModel, "pk_field": "code", "table": "locales"},
    "currencies": {"model": CurrencyModel, "pk_field": "code", "table": "currencies"},
    "measure-families": {"model": MeasureFamilyModel, "pk_field": "code", "table": "measure_families"},
    "measurement-families": {"model": MeasurementFamilyModel, "pk_field": "code", "table": "measurement_families"},
    "association-types": {"model": AssociationTypeModel, "pk_field": "code", "table": "association_types"},
    "reference-entities": {"model": ReferenceEntityModel, "pk_field": "code", "table": "reference_entities"},
    "asset-families": {"model": AssetFamilyModel, "pk_field": "code", "table": "asset_families"},
    "product-models": {"model": ProductModelEntityModel, "pk_field": "code", "table": "product_models"},
    "assets": {"model": DeprecatedAssetModel, "pk_field": "code", "table": "deprecated_assets"},
    "asset-categories": {
        "model": DeprecatedAssetCategoryModel,
        "pk_field": "code",
        "table": "deprecated_asset_categories",
    },
    "asset-tags": {"model": DeprecatedAssetTagModel, "pk_field": "code", "table": "deprecated_asset_tags"},
}

SUB_MODELS = {
    "attributes/attribute-options": {
        "parent_entity": "attributes",
        "nested_path": "options",
        "model": AttributeOptionModel,
        "pk_field": "code",
        "table": "attribute_options",
    },
    "families/family-variants": {
        "parent_entity": "families",
        "nested_path": "variants",
        "model": FamilyVariantModel,
        "pk_field": "code",
        "table": "family_variants",
    },
    "reference-entities/records": {
        "parent_entity": "reference-entities",
        "nested_path": "records",
        "model": ReferenceEntityRecordModel,
        "pk_field": "code",
        "table": "reference_entity_records",
    },
    "reference-entities/attributes": {
        "parent_entity": "reference-entities",
        "nested_path": "attributes",
        "model": ReferenceEntityAttributeModel,
        "pk_field": "code",
        "table": "reference_entity_attributes",
    },
    "asset-families/assets": {
        "parent_entity": "asset-families",
        "nested_path": "assets",
        "model": AssetModel,
        "pk_field": "code",
        "table": "assets",
    },
    "asset-families/attributes": {
        "parent_entity": "asset-families",
        "nested_path": "attributes",
        "model": AssetAttributeModel,
        "pk_field": "code",
        "table": "asset_attributes",
    },
}


def init_db():
    retries = 10
    conn = None
    while retries > 0:
        try:
            conn = get_connection()
            break
        except Exception as e:
            print(f"PostgreSQL not ready, retrying ({retries} left)... {e}")
            retries -= 1
            time.sleep(2)

    if conn is None:
        raise Exception("Could not connect to PostgreSQL")

    statements = SCHEMA_SQL_PATH.read_text(encoding="utf-8").split(";")
    for statement in statements:
        normalized_statement = statement.strip()
        if normalized_statement:
            conn.execute(normalized_statement)

    conn.commit()
    conn.close()


def get_db() -> Generator[psycopg.Connection, None, None]:
    with get_db_pool().connection() as conn:
        yield conn


# Helper for Session-like behavior if needed, but we'll use raw connections.
class SessionShim:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def exec(self, query: Any):
        # This will be updated to handle sqlglot queries
        pass

    def add(self, item: Any):
        pass

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()
