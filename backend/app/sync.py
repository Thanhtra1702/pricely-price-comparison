import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from pyspark.sql import SparkSession
from sqlalchemy import text

from .config import Settings
from .database import engine
from .matching import signature
from .search_index import refresh_embeddings


RETAILERS = ("bachhoaxanh", "go", "lottemart", "mmvietnam", "winmart")
RUN_MANIFEST = re.compile(r"^pipeline_runs/date=(?P<date>[^/]+)/run_id=(?P<run>[^/]+)/manifest\.json$")

# These are the current Gold Hudi tables materialized by DE. Store-scoped paths are
# distinct Hudi tables; reading their common parent would not return a valid snapshot.
GLOBAL_TABLES = {
    "dates": "gold/dim_date_hudi",
    "products": "gold/dim_product_hudi",
    "retailers": "gold/dim_retailer_hudi",
    "stores": "gold/dim_store_hudi",
    "retailer_products": "gold/dim_retailer_product_hudi",
}
STORE_TABLES = {
    "offers": "gold/fact_price_snapshot_daily_hudi/store={retailer}",
    "promotions": "gold/dim_promotion_hudi/store={retailer}",
    "promotion_items": "gold/fact_promotion_item_hudi/store={retailer}",
}


def minio_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def minio_uses_tls(endpoint: str) -> bool:
    return urlparse(endpoint).scheme.lower() == "https"


def latest_successful_run(settings: Settings) -> dict | None:
    """Return the latest successful global pipeline manifest published by DE."""
    client = minio_client(settings)
    selected: dict | None = None
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=settings.minio_bucket,
        Prefix="pipeline_runs/",
    ):
        for item in page.get("Contents", []):
            match = RUN_MANIFEST.match(item["Key"])
            if not match:
                continue
            manifest = json.loads(
                client.get_object(Bucket=settings.minio_bucket, Key=item["Key"])["Body"].read()
            )
            if manifest.get("status") != "success":
                continue
            candidate = {**match.groupdict(), "manifest": manifest, "key": item["Key"]}
            if selected is None or (candidate["date"], candidate["run"]) > (selected["date"], selected["run"]):
                selected = candidate
    return selected


# Kept as a compatibility alias for callers/tests written before the global manifest.
def latest_manifests(settings: Settings) -> dict[str, dict]:
    run = latest_successful_run(settings)
    if not run:
        return {}
    retailers = [value for value in run["manifest"].get("retailers_completed", []) if value in RETAILERS]
    return {retailer: run for retailer in retailers}


def build_spark(settings: Settings) -> SparkSession:
    return (
        SparkSession.builder.appName("pricebot-sync").master("local[*]")
        .config("spark.ui.enabled", "false")
        .config("spark.jars.packages", settings.hudi_packages)
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.blockManager.port", "0")
        .config("spark.hadoop.fs.s3a.endpoint", settings.minio_endpoint)
        .config("spark.hadoop.fs.s3a.access.key", settings.minio_access_key)
        .config("spark.hadoop.fs.s3a.secret.key", settings.minio_secret_key)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", str(minio_uses_tls(settings.minio_endpoint)).lower())
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .getOrCreate()
    )


def read_hudi_rows(spark: SparkSession, settings: Settings, root: str) -> list[dict]:
    path = f"s3a://{settings.minio_bucket}/{root}"
    return [row.asDict(recursive=True) for row in spark.read.format("hudi").load(path).toLocalIterator()]


def row_version(row: dict) -> tuple[str, str, str, str]:
    """Prefer the newest DE source run, then observed/build/Hudi commit timestamps."""
    return tuple(str(row.get(field) or "") for field in ("source_run_id", "observed_at", "built_at", "_hoodie_commit_time"))


def latest_rows(rows: list[dict], key) -> list[dict]:
    selected: dict[str, dict] = {}
    for row in rows:
        value = key(row)
        if value is None:
            continue
        identifier = str(value)
        if identifier not in selected or row_version(row) >= row_version(selected[identifier]):
            selected[identifier] = row
    return list(selected.values())


def deduplicate(rows: list[dict], key: str) -> list[dict]:
    return latest_rows(rows, lambda row: row.get(key))


def latest_source_run_rows(rows: list[dict]) -> list[dict]:
    source_runs = [str(row["source_run_id"]) for row in rows if row.get("source_run_id")]
    if not source_runs:
        return rows
    latest_run = max(source_runs)
    return [row for row in rows if str(row.get("source_run_id") or "") == latest_run]


def prepare_offers(
    price_rows: list[dict],
    retailer_products: list[dict],
    products: list[dict],
    *,
    history: bool = False,
) -> list[dict]:
    product_by_key = {row.get("retailer_product_key"): row for row in retailer_products if row.get("retailer_product_key")}
    product_by_id = {
        (row.get("retailer_id"), row.get("retailer_product_id")): row
        for row in retailer_products
        if row.get("retailer_id") and row.get("retailer_product_id")
    }
    canonical_by_id = {row.get("canonical_product_id"): row for row in products if row.get("canonical_product_id")}
    result: list[dict] = []
    for row in price_rows:
        if not row.get("price_snapshot_id") or row.get("current_price") is None:
            continue
        source_product = product_by_key.get(row.get("retailer_product_key")) or product_by_id.get(
            (row.get("retailer_id"), row.get("retailer_product_id"))
        ) or {}
        canonical_id = row.get("canonical_product_id") or source_product.get("canonical_product_id")
        canonical = canonical_by_id.get(canonical_id, {})
        product_name = row.get("product_name") or source_product.get("product_name")
        if not product_name:
            continue
        product_signature = signature(product_name, row.get("brand") or canonical.get("brand"))
        result.append(
            {
                "price_snapshot_id": row["price_snapshot_id"],
                "snapshot_date": row.get("snapshot_date"),
                "retailer_id": row.get("retailer_id"),
                "store_code": row.get("store_code") or "unknown_store",
                "store_group_code": row.get("store_group_code"),
                "region": row.get("region"),
                "retailer_product_id": row.get("retailer_product_id"),
                "retailer_product_key": row.get("retailer_product_key") or source_product.get("retailer_product_key"),
                "canonical_product_id": canonical_id,
                "product_key": row.get("product_key") or canonical.get("product_key"),
                "canonical_name": canonical.get("canonical_name"),
                "product_name": product_name,
                "brand": row.get("brand") or canonical.get("brand"),
                "category_raw": row.get("category_raw"),
                "listed_price": row.get("listed_price"),
                "promo_price": row.get("promo_price"),
                "current_price": row.get("current_price"),
                "currency": row.get("currency") or "VND",
                "effective_unit_price": row.get("effective_unit_price"),
                "comparison_unit": row.get("comparison_unit"),
                "measurement_type": row.get("measurement_type") or canonical.get("measurement_type"),
                "package_total_base_quantity": row.get("package_total_base_quantity") or canonical.get("package_total_base_quantity"),
                "unit_price_publishable": bool(row.get("unit_price_publishable")),
                "discount_amount": row.get("discount_amount"),
                "discount_percent": row.get("discount_percent"),
                "availability_status": row.get("availability_status"),
                "is_on_promotion": bool(row.get("is_on_promotion")),
                "is_price_discount": bool(row.get("is_price_discount")),
                "has_promo_mechanic": bool(row.get("has_promo_mechanic")),
                "observed_at": row.get("observed_at"),
                "source_run_id": row.get("source_run_id"),
                "built_at": row.get("built_at"),
                "run_status": row.get("run_status"),
                "silver_data_quality_status": row.get("silver_data_quality_status"),
                "image_url": source_product.get("image_url") or canonical.get("canonical_image_url"),
                "source_url": source_product.get("source_url"),
                "normalized_name": product_signature.normalized_name,
                "normalized_brand": product_signature.normalized_brand,
                "package_quantity": product_signature.quantity,
                "package_unit": product_signature.unit,
                "package_multiplier": product_signature.multiplier,
            }
        )
    if history:
        # The Gold fact grain includes the snapshot date in its record key. Preserve
        # every daily snapshot and only collapse duplicate materializations of that
        # exact fact record.
        return latest_rows(result, lambda row: row.get("price_snapshot_id"))
    # DE can materialize a newer source run for the same snapshot date. Keep one
    # current observation per retailer/product/store instead of showing both runs.
    return latest_rows(
        result,
        lambda row: (row.get("retailer_id"), row.get("store_code"), row.get("retailer_product_id") or row.get("retailer_product_key")),
    )


def table_rows(rows: list[dict], columns: tuple[str, ...], key: str) -> list[dict]:
    return deduplicate([{column: row.get(column) for column in columns} for row in rows], key)


def insert_rows(conn, table: str, columns: tuple[str, ...], rows: list[dict]) -> None:
    if not rows:
        return
    names = ", ".join(columns)
    params = ", ".join(f":{column}" for column in columns)
    conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({params})"), rows)


def upsert_rows(conn, table: str, columns: tuple[str, ...], rows: list[dict], key: str) -> None:
    """Persist append-only history idempotently when a MinIO sync is rerun."""
    if not rows:
        return
    names = ", ".join(columns)
    params = ", ".join(f":{column}" for column in columns)
    updates = ", ".join(f"{column}=EXCLUDED.{column}" for column in columns if column != key)
    conn.execute(
        text(f"INSERT INTO {table} ({names}) VALUES ({params}) ON CONFLICT ({key}) DO UPDATE SET {updates}"),
        rows,
    )


def replace_serving_data(
    global_data: dict[str, list[dict]],
    offers_by_retailer: dict[str, list[dict]],
    history_by_retailer: dict[str, list[dict]],
    promotions_by_retailer: dict[str, list[dict]],
    promotion_items_by_retailer: dict[str, list[dict]],
) -> None:
    global_specs = {
        "dates": ("date_dimension_current", ("date_key", "calendar_date", "day", "day_of_week", "month", "year", "is_weekend", "source_run_id", "built_at"), "date_key"),
        "products": ("products_current", ("canonical_product_id", "product_key", "canonical_name", "brand", "product_type", "measurement_type", "measurement_base_unit", "package_total_base_quantity", "canonical_image_url", "source_run_id", "built_at"), "canonical_product_id"),
        "retailers": ("retailers_current", ("retailer_id", "retailer_key", "retailer_name", "is_active", "source_run_id", "built_at"), "retailer_id"),
        "stores": ("stores_current", ("store_key", "retailer_id", "store_code", "store_group_code", "region", "is_active", "source_run_id", "built_at"), "store_key"),
        "retailer_products": ("retailer_products_current", ("retailer_product_key", "retailer_product_id", "retailer_id", "canonical_product_id", "product_name", "barcode", "image_url", "source_url", "source_run_id", "built_at"), "retailer_product_key"),
    }
    offer_columns = (
        "price_snapshot_id", "snapshot_date", "retailer_id", "store_code", "region", "retailer_product_id", "retailer_product_key", "canonical_product_id", "product_key", "canonical_name", "product_name", "brand", "category_raw", "listed_price", "promo_price", "current_price", "currency", "effective_unit_price", "comparison_unit", "measurement_type", "package_total_base_quantity", "unit_price_publishable", "discount_amount", "discount_percent", "availability_status", "is_on_promotion", "is_price_discount", "has_promo_mechanic", "observed_at", "source_run_id", "built_at", "run_status", "silver_data_quality_status", "image_url", "source_url", "store_group_code", "normalized_name", "normalized_brand", "package_quantity", "package_unit", "package_multiplier",
    )
    promotion_columns = ("promotion_key", "promotion_id", "retailer_id", "store_code", "observation_date", "promotion_scope", "promotion_type", "offer_text_raw", "offer_text_available", "promotion_start_date", "promotion_end_date", "source_run_id", "built_at")
    promotion_item_columns = ("promotion_item_fact_id", "promotion_key", "promotion_id", "retailer_id", "retailer_product_id", "retailer_product_key", "store_code", "observation_date", "promotion_type", "listed_price", "promo_price", "current_price", "currency", "source_run_id", "source_bronze_record_key", "built_at")

    with engine.begin() as conn:
        for name, (table, columns, key) in global_specs.items():
            if name not in global_data:
                continue
            conn.execute(text(f"DELETE FROM {table}"))
            insert_rows(conn, table, columns, table_rows(global_data[name], columns, key))
        for retailer, rows in offers_by_retailer.items():
            conn.execute(text("DELETE FROM offers_current WHERE retailer_id=:retailer"), {"retailer": retailer})
            insert_rows(conn, "offers_current", offer_columns, rows)
        for rows in history_by_retailer.values():
            upsert_rows(conn, "offer_price_history", offer_columns, rows, "price_snapshot_id")
        for retailer, rows in promotions_by_retailer.items():
            conn.execute(text("DELETE FROM promotions_current WHERE retailer_id=:retailer"), {"retailer": retailer})
            insert_rows(conn, "promotions_current", promotion_columns, table_rows(rows, promotion_columns, "promotion_key"))
        for retailer, rows in promotion_items_by_retailer.items():
            conn.execute(text("DELETE FROM promotion_items_current WHERE retailer_id=:retailer"), {"retailer": retailer})
            insert_rows(conn, "promotion_items_current", promotion_item_columns, table_rows(rows, promotion_item_columns, "promotion_item_fact_id"))


def update_sync_progress(run_id: str, *, completed: int, total: int, stage: str, message: str) -> dict:
    progress = {
        "completed": completed,
        "total": total,
        "percent": round((completed / total) * 100) if total else 0,
        "stage": stage,
        "message": message,
    }
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE sync_runs SET details=jsonb_build_object('progress',CAST(:progress AS jsonb)) WHERE id=:id AND status='running'"),
            {"id": run_id, "progress": json.dumps(progress, ensure_ascii=False)},
        )
    return progress


def run_sync(settings: Settings, run_id: str) -> dict:
    update_sync_progress(run_id, completed=0, total=0, stage="manifest", message="Đang tìm pipeline manifest mới nhất trên MinIO…")
    run = latest_successful_run(settings)
    if not run:
        raise RuntimeError("Không tìm thấy pipeline manifest thành công trên MinIO")
    retailers = [value for value in run["manifest"].get("retailers_completed", []) if value in RETAILERS]
    if not retailers:
        raise RuntimeError("Manifest thành công nhưng không có retailer hoàn tất")

    total_steps = 3 + len(GLOBAL_TABLES) + len(retailers) * len(STORE_TABLES)
    completed_steps = 1
    progress = update_sync_progress(
        run_id,
        completed=completed_steps,
        total=total_steps,
        stage="manifest",
        message=f"Đã tìm thấy run {run['run']} ({len(retailers)} retailer). Đang khởi tạo Spark…",
    )
    spark = build_spark(settings)
    spark.sparkContext.setLogLevel("ERROR")
    global_data: dict[str, list[dict]] = {}
    offers_by_retailer: dict[str, list[dict]] = {}
    history_by_retailer: dict[str, list[dict]] = {}
    promotions_by_retailer: dict[str, list[dict]] = {}
    promotion_items_by_retailer: dict[str, list[dict]] = {}
    failed: dict[str, str] = {}
    try:
        for name, root in GLOBAL_TABLES.items():
            update_sync_progress(run_id, completed=completed_steps, total=total_steps, stage="dimensions", message=f"Đang đọc {name} từ MinIO…")
            try:
                global_data[name] = latest_source_run_rows(read_hudi_rows(spark, settings, root))
            except Exception as exc:
                failed[name] = str(exc)
            completed_steps += 1
            progress = update_sync_progress(run_id, completed=completed_steps, total=total_steps, stage="dimensions", message=f"Đã xử lý {name}.")
        if "retailer_products" not in global_data or "products" not in global_data:
            raise RuntimeError("Không đọc được product dimensions cần để tạo serving data")

        for retailer in retailers:
            update_sync_progress(run_id, completed=completed_steps, total=total_steps, stage="prices", message=f"Đang đọc giá {retailer}…")
            try:
                price_rows = read_hudi_rows(spark, settings, STORE_TABLES["offers"].format(retailer=retailer))
                history_by_retailer[retailer] = prepare_offers(
                    price_rows,
                    global_data["retailer_products"],
                    global_data["products"],
                    history=True,
                )
                offers_by_retailer[retailer] = prepare_offers(
                    latest_source_run_rows(price_rows),
                    global_data["retailer_products"],
                    global_data["products"],
                )
            except Exception as exc:
                failed[f"offers/{retailer}"] = str(exc)
            completed_steps += 1
            progress = update_sync_progress(run_id, completed=completed_steps, total=total_steps, stage="prices", message=f"Đã xử lý giá {retailer}.")
            if retailer not in offers_by_retailer:
                continue
            for name, target in (("promotions", promotions_by_retailer), ("promotion_items", promotion_items_by_retailer)):
                update_sync_progress(run_id, completed=completed_steps, total=total_steps, stage="promotions", message=f"Đang đọc {name} của {retailer}…")
                try:
                    target[retailer] = latest_source_run_rows(read_hudi_rows(spark, settings, STORE_TABLES[name].format(retailer=retailer)))
                except Exception as exc:
                    failed[f"{name}/{retailer}"] = str(exc)
                completed_steps += 1
                progress = update_sync_progress(run_id, completed=completed_steps, total=total_steps, stage="promotions", message=f"Đã xử lý {name} của {retailer}.")
    finally:
        spark.stop()

    if not offers_by_retailer:
        raise RuntimeError("Không đọc được fact_price_snapshot_daily_hudi cho bất kỳ retailer nào")
    update_sync_progress(run_id, completed=completed_steps, total=total_steps, stage="serving", message="Đang ghi dữ liệu vào PostgreSQL phục vụ chatbot…")
    replace_serving_data(global_data, offers_by_retailer, history_by_retailer, promotions_by_retailer, promotion_items_by_retailer)
    completed_steps += 1
    search_index: dict[str, object]
    update_sync_progress(run_id, completed=completed_steps, total=total_steps, stage="search_index", message="Đang cập nhật chỉ mục tìm kiếm thông minh…")
    try:
        search_index = refresh_embeddings(settings, limit=settings.embedding_sync_limit)
    except Exception as exc:
        # A local embedding model is an optional enrichment. Fresh MinIO serving data
        # must stay available even if it is temporarily unavailable.
        search_index = {"status": "degraded", "error": str(exc), "indexed": 0}
    completed_steps += 1
    progress = update_sync_progress(run_id, completed=completed_steps, total=total_steps, stage="complete", message="Đồng bộ dữ liệu hoàn tất.")
    succeeded = {retailer: len(rows) for retailer, rows in offers_by_retailer.items()}
    details = {
        "run_date": run["date"],
        "source_run_id": run["run"],
        "succeeded": succeeded,
        "history": {retailer: len(rows) for retailer, rows in history_by_retailer.items()},
        "global_tables": {name: len(rows) for name, rows in global_data.items()},
        "promotions": {retailer: len(rows) for retailer, rows in promotions_by_retailer.items()},
        "promotion_items": {retailer: len(rows) for retailer, rows in promotion_items_by_retailer.items()},
        "search_index": search_index,
        "failed": failed,
        "progress": progress,
    }
    status = "success" if not failed else "partial"
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE sync_runs SET status=:status,finished_at=now(),details=CAST(:details AS jsonb) WHERE id=:id"),
            {"id": run_id, "status": status, "details": json.dumps(details, ensure_ascii=False)},
        )
    return {"status": status, **details}
