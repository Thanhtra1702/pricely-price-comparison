from sqlalchemy import create_engine, text
from .config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)

DDL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE TABLE IF NOT EXISTS offers_current (
 price_snapshot_id text PRIMARY KEY, snapshot_date date, retailer_id text NOT NULL, store_code text NOT NULL, region text,
 retailer_product_id text, product_name text NOT NULL, brand text, category_raw text, listed_price numeric, promo_price numeric,
 current_price numeric NOT NULL, currency text, effective_unit_price numeric, comparison_unit text, discount_amount numeric,
 discount_percent numeric, availability_status text, is_on_promotion boolean NOT NULL DEFAULT false, is_price_discount boolean NOT NULL DEFAULT false,
 has_promo_mechanic boolean NOT NULL DEFAULT false, observed_at timestamptz, source_run_id text, built_at timestamptz,
 normalized_name text NOT NULL, normalized_brand text NOT NULL DEFAULT '', package_quantity numeric, package_unit text, package_multiplier int NOT NULL DEFAULT 1
);
ALTER TABLE offers_current ADD COLUMN IF NOT EXISTS retailer_product_key text;
ALTER TABLE offers_current ADD COLUMN IF NOT EXISTS canonical_product_id text;
ALTER TABLE offers_current ADD COLUMN IF NOT EXISTS product_key text;
ALTER TABLE offers_current ADD COLUMN IF NOT EXISTS canonical_name text;
ALTER TABLE offers_current ADD COLUMN IF NOT EXISTS image_url text;
ALTER TABLE offers_current ADD COLUMN IF NOT EXISTS source_url text;
ALTER TABLE offers_current ADD COLUMN IF NOT EXISTS store_group_code text;
ALTER TABLE offers_current ADD COLUMN IF NOT EXISTS measurement_type text;
ALTER TABLE offers_current ADD COLUMN IF NOT EXISTS package_total_base_quantity numeric;
ALTER TABLE offers_current ADD COLUMN IF NOT EXISTS unit_price_publishable boolean NOT NULL DEFAULT false;
ALTER TABLE offers_current ADD COLUMN IF NOT EXISTS run_status text;
ALTER TABLE offers_current ADD COLUMN IF NOT EXISTS silver_data_quality_status text;
CREATE INDEX IF NOT EXISTS offers_name_trgm_idx ON offers_current USING gin (normalized_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS offers_brand_trgm_idx ON offers_current USING gin (normalized_brand gin_trgm_ops);
CREATE INDEX IF NOT EXISTS offers_search_fts_idx ON offers_current USING gin (
 to_tsvector('simple', coalesce(normalized_name, '') || ' ' || coalesce(normalized_brand, '') || ' ' || coalesce(category_raw, ''))
);
CREATE INDEX IF NOT EXISTS offers_retailer_idx ON offers_current (retailer_id, current_price);
CREATE INDEX IF NOT EXISTS offers_canonical_product_idx ON offers_current (canonical_product_id);
CREATE INDEX IF NOT EXISTS offers_unit_price_idx ON offers_current (comparison_unit, effective_unit_price) WHERE unit_price_publishable = true;
CREATE INDEX IF NOT EXISTS offers_quality_idx ON offers_current (silver_data_quality_status, current_price);
CREATE TABLE IF NOT EXISTS offer_price_history (
 price_snapshot_id text PRIMARY KEY, snapshot_date date, retailer_id text NOT NULL, store_code text NOT NULL, region text,
 retailer_product_id text, retailer_product_key text, canonical_product_id text, product_key text, canonical_name text,
 product_name text NOT NULL, brand text, category_raw text, listed_price numeric, promo_price numeric, current_price numeric NOT NULL,
 currency text, effective_unit_price numeric, comparison_unit text, measurement_type text, package_total_base_quantity numeric,
 unit_price_publishable boolean NOT NULL DEFAULT false, discount_amount numeric, discount_percent numeric, availability_status text,
 is_on_promotion boolean NOT NULL DEFAULT false, is_price_discount boolean NOT NULL DEFAULT false,
 has_promo_mechanic boolean NOT NULL DEFAULT false, observed_at timestamptz, source_run_id text, built_at timestamptz,
 run_status text, silver_data_quality_status text, image_url text, source_url text, store_group_code text,
 normalized_name text NOT NULL, normalized_brand text NOT NULL DEFAULT '', package_quantity numeric, package_unit text,
 package_multiplier int NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS offer_history_canonical_date_idx ON offer_price_history (canonical_product_id, snapshot_date DESC) WHERE canonical_product_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS offer_history_retailer_product_date_idx ON offer_price_history (retailer_product_key, snapshot_date DESC) WHERE retailer_product_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS offer_history_retailer_date_idx ON offer_price_history (retailer_id, snapshot_date DESC);
CREATE TABLE IF NOT EXISTS offer_search_embeddings_current (
 price_snapshot_id text PRIMARY KEY,
 content_hash text NOT NULL,
 model text NOT NULL,
 search_text text NOT NULL,
 embedding real[] NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS offer_search_embeddings_model_idx ON offer_search_embeddings_current (model);
CREATE TABLE IF NOT EXISTS date_dimension_current (
 date_key integer PRIMARY KEY, calendar_date date, day integer, day_of_week integer, month integer, year integer, is_weekend boolean, source_run_id text, built_at timestamptz
);
CREATE TABLE IF NOT EXISTS products_current (
 canonical_product_id text PRIMARY KEY, product_key text, canonical_name text, brand text, product_type text, measurement_type text,
 measurement_base_unit text, package_total_base_quantity numeric, canonical_image_url text, source_run_id text, built_at timestamptz
);
CREATE TABLE IF NOT EXISTS retailers_current (
 retailer_id text PRIMARY KEY, retailer_key text, retailer_name text, is_active boolean, source_run_id text, built_at timestamptz
);
CREATE TABLE IF NOT EXISTS stores_current (
 store_key text PRIMARY KEY, retailer_id text, store_code text, store_group_code text, region text, is_active boolean, source_run_id text, built_at timestamptz
);
CREATE TABLE IF NOT EXISTS retailer_products_current (
 retailer_product_key text PRIMARY KEY, retailer_product_id text, retailer_id text, canonical_product_id text, product_name text, barcode text,
 image_url text, source_url text, source_run_id text, built_at timestamptz
);
CREATE INDEX IF NOT EXISTS retailer_products_canonical_idx ON retailer_products_current (canonical_product_id);
CREATE TABLE IF NOT EXISTS promotions_current (
 promotion_key text PRIMARY KEY, promotion_id text, retailer_id text, store_code text, observation_date date, promotion_scope text,
 promotion_type text, offer_text_raw text, offer_text_available boolean, promotion_start_date date, promotion_end_date date, source_run_id text, built_at timestamptz
);
CREATE INDEX IF NOT EXISTS promotions_retailer_date_idx ON promotions_current (retailer_id, observation_date);
CREATE TABLE IF NOT EXISTS promotion_items_current (
 promotion_item_fact_id text PRIMARY KEY, promotion_key text, promotion_id text, retailer_id text, retailer_product_id text, retailer_product_key text,
 store_code text, observation_date date, promotion_type text, listed_price numeric, promo_price numeric, current_price numeric, currency text,
 source_run_id text, source_bronze_record_key text, built_at timestamptz
);
CREATE INDEX IF NOT EXISTS promotion_items_product_idx ON promotion_items_current (retailer_product_key, retailer_id);
CREATE TABLE IF NOT EXISTS sync_runs (id uuid PRIMARY KEY, status text NOT NULL, started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, details jsonb NOT NULL DEFAULT '{}'::jsonb);
CREATE UNIQUE INDEX IF NOT EXISTS sync_one_running_idx ON sync_runs ((status)) WHERE status = 'running';
CREATE TABLE IF NOT EXISTS conversations (id uuid PRIMARY KEY, title text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS messages (id bigserial PRIMARY KEY, conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, role text NOT NULL, content text NOT NULL, payload jsonb, created_at timestamptz NOT NULL DEFAULT now());
DROP TABLE IF EXISTS auth_sessions;
DROP INDEX IF EXISTS conversations_user_updated_idx;
ALTER TABLE conversations DROP COLUMN IF EXISTS user_id;
DROP TABLE IF EXISTS users;
"""


def init_db() -> None:
    with engine.begin() as conn:
        for statement in DDL.split(";"):
            if statement.strip():
                conn.execute(text(statement))
