CREATE TABLE IF NOT EXISTS products (
    uuid TEXT UNIQUE,
    id TEXT PRIMARY KEY,
    enabled BOOLEAN,
    family TEXT,
    categories JSONB,
    groups JSONB,
    parent TEXT,
    "values" JSONB,
    associations JSONB,
    quantified_associations JSONB,
    created TEXT,
    updated TEXT,
    metadata JSONB,
    quality_scores JSONB,
    completenesses JSONB
);

CREATE INDEX IF NOT EXISTS idx_products_uuid ON products(uuid);

CREATE TABLE IF NOT EXISTS products_uuid (
    id TEXT PRIMARY KEY,
    identifier TEXT
);

CREATE TABLE IF NOT EXISTS published_products (
    id TEXT PRIMARY KEY,
    enabled BOOLEAN,
    family TEXT,
    categories JSONB,
    groups JSONB,
    "values" JSONB,
    associations JSONB,
    quantified_associations JSONB,
    created TEXT,
    updated TEXT
);

CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    parent TEXT,
    updated TEXT,
    position INTEGER,
    labels JSONB,
    "values" JSONB,
    channel_requirements JSONB
);

CREATE TABLE IF NOT EXISTS attributes (
    id TEXT PRIMARY KEY,
    type TEXT,
    labels JSONB,
    "group" TEXT,
    group_labels JSONB,
    sort_order INTEGER,
    localizable BOOLEAN,
    scopable BOOLEAN,
    available_locales JSONB,
    "unique" BOOLEAN,
    useable_as_grid_filter BOOLEAN,
    max_characters INTEGER,
    validation_rule TEXT,
    validation_regexp TEXT,
    wysiwyg_enabled BOOLEAN,
    number_min TEXT,
    number_max TEXT,
    decimals_allowed BOOLEAN,
    negative_allowed BOOLEAN,
    metric_family TEXT,
    default_metric_unit TEXT,
    date_min TEXT,
    date_max TEXT,
    allowed_extensions JSONB,
    max_file_size TEXT,
    reference_data_name TEXT,
    default_value BOOLEAN,
    table_configuration JSONB,
    is_main_identifier BOOLEAN,
    is_mandatory BOOLEAN,
    decimal_places_strategy TEXT,
    decimal_places FLOAT
);

CREATE TABLE IF NOT EXISTS attribute_groups (
    id TEXT PRIMARY KEY,
    sort_order INTEGER,
    attributes JSONB,
    labels JSONB
);

CREATE TABLE IF NOT EXISTS families (
    id TEXT PRIMARY KEY,
    attribute_as_label TEXT,
    attribute_as_image TEXT,
    attributes JSONB,
    attribute_requirements JSONB,
    labels JSONB
);

CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    locales JSONB,
    currencies JSONB,
    category_tree TEXT,
    conversion_units JSONB,
    labels JSONB
);

CREATE TABLE IF NOT EXISTS locales (
    id TEXT PRIMARY KEY,
    enabled BOOLEAN
);

CREATE TABLE IF NOT EXISTS currencies (
    id TEXT PRIMARY KEY,
    enabled BOOLEAN,
    label TEXT
);

CREATE TABLE IF NOT EXISTS measure_families (
    id TEXT PRIMARY KEY,
    standard TEXT,
    units JSONB
);

CREATE TABLE IF NOT EXISTS measurement_families (
    id TEXT PRIMARY KEY,
    labels JSONB,
    standard_unit_code TEXT,
    units JSONB
);

CREATE TABLE IF NOT EXISTS association_types (
    id TEXT PRIMARY KEY,
    labels JSONB,
    is_quantified BOOLEAN,
    is_two_way BOOLEAN
);

CREATE TABLE IF NOT EXISTS reference_entities (
    id TEXT PRIMARY KEY,
    labels JSONB,
    image TEXT
);

CREATE TABLE IF NOT EXISTS asset_families (
    id TEXT PRIMARY KEY,
    updated TEXT,
    data JSONB
);

CREATE TABLE IF NOT EXISTS product_models (
    id TEXT PRIMARY KEY,
    family TEXT,
    family_variant TEXT,
    parent TEXT,
    categories JSONB,
    "values" JSONB,
    associations JSONB,
    quantified_associations JSONB,
    created TEXT,
    updated TEXT,
    metadata JSONB,
    quality_scores JSONB
);

CREATE TABLE IF NOT EXISTS deprecated_assets (
    id TEXT PRIMARY KEY,
    updated TEXT,
    data JSONB
);

CREATE TABLE IF NOT EXISTS deprecated_asset_categories (
    id TEXT PRIMARY KEY,
    updated TEXT,
    data JSONB
);

CREATE TABLE IF NOT EXISTS deprecated_asset_tags (
    id TEXT PRIMARY KEY,
    updated TEXT,
    data JSONB
);

CREATE TABLE IF NOT EXISTS subscribers (
    id TEXT PRIMARY KEY,
    updated TEXT,
    data JSONB
);

CREATE TABLE IF NOT EXISTS attribute_options (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    updated TEXT,
    data JSONB
);

CREATE INDEX IF NOT EXISTS idx_attribute_options_parent_id ON attribute_options(parent_id);

CREATE TABLE IF NOT EXISTS family_variants (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    updated TEXT,
    data JSONB
);

CREATE INDEX IF NOT EXISTS idx_family_variants_parent_id ON family_variants(parent_id);

CREATE TABLE IF NOT EXISTS reference_entity_records (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    updated TEXT,
    data JSONB
);

CREATE INDEX IF NOT EXISTS idx_reference_entity_records_parent_id ON reference_entity_records(parent_id);

CREATE TABLE IF NOT EXISTS reference_entity_attributes (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    updated TEXT,
    data JSONB
);

CREATE INDEX IF NOT EXISTS idx_reference_entity_attributes_parent_id ON reference_entity_attributes(parent_id);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    updated TEXT,
    data JSONB
);

CREATE INDEX IF NOT EXISTS idx_assets_parent_id ON assets(parent_id);

CREATE TABLE IF NOT EXISTS asset_attributes (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    updated TEXT,
    data JSONB
);

CREATE INDEX IF NOT EXISTS idx_asset_attributes_parent_id ON asset_attributes(parent_id);

CREATE TABLE IF NOT EXISTS subscriptions (
    pk TEXT PRIMARY KEY,
    id TEXT,
    parent_id TEXT,
    data JSONB
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_id ON subscriptions(id);

CREATE INDEX IF NOT EXISTS idx_subscriptions_parent_id ON subscriptions(parent_id);

TRUNCATE TABLE products, products_uuid, published_products, categories, attributes, attribute_groups, families, channels, locales, currencies, measure_families, measurement_families, association_types, reference_entities, asset_families, product_models, deprecated_assets, deprecated_asset_categories, deprecated_asset_tags, subscribers, attribute_options, family_variants, reference_entity_records, reference_entity_attributes, assets, asset_attributes, subscriptions;
