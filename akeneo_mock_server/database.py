import psycopg
from psycopg.rows import dict_row
from py_pglite import PGliteManager, PGliteConfig
from typing import Any, Generator
from pydantic import BaseModel, Field
from pathlib import Path
import threading

SCHEMA_SQL_PATH = Path(__file__).with_name("schema.sql")
_PGLITE_WORK_DIR = Path(__file__).parent.parent / "py-pglite-work"

_pglite_manager: PGliteManager | None = None
_db_connection: psycopg.Connection | None = None
_init_lock = threading.Lock()


def _ensure_initialized() -> psycopg.Connection:
    global _pglite_manager, _db_connection
    if _db_connection is not None:
        return _db_connection

    with _init_lock:
        if _db_connection is not None:
            return _db_connection

        config = PGliteConfig(work_dir=_PGLITE_WORK_DIR, use_tcp=True, tcp_port=15432)
        manager = PGliteManager(config=config)
        manager.start()

        uri = manager.get_psycopg_uri()
        conn = psycopg.connect(uri, row_factory=dict_row)

        statements = SCHEMA_SQL_PATH.read_text(encoding="utf-8").split(";")
        for statement in statements:
            normalized = statement.strip()
            if normalized:
                conn.execute(normalized)
        conn.commit()

        _pglite_manager = manager
        _db_connection = conn
        return conn


def close_db_pool() -> None:
    global _pglite_manager, _db_connection
    if _db_connection is not None:
        try:
            _db_connection.close()
        except Exception:
            pass
        _db_connection = None
    if _pglite_manager is not None:
        try:
            _pglite_manager.stop()
        except Exception:
            pass
        _pglite_manager = None


def get_connection() -> psycopg.Connection:
    return _ensure_initialized()


def init_db() -> None:
    _ensure_initialized()


def get_db() -> Generator[psycopg.Connection, None, None]:
    conn = _ensure_initialized()
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


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
    "asset-categories": {"model": DeprecatedAssetCategoryModel, "pk_field": "code", "table": "deprecated_asset_categories"},
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


# Helper for Session-like behavior if needed, but we'll use raw connections.
class SessionShim:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def exec(self, query: Any):
        pass

    def add(self, item: Any):
        pass

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()
