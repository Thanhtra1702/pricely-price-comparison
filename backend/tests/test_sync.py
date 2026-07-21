import io
import json
from types import SimpleNamespace
from app import sync


class FakePaginator:
    def paginate(self, **_):
        return [{"Contents": [
            {"Key": "pipeline_runs/date=2026-07-13/run_id=one/manifest.json"},
            {"Key": "pipeline_runs/date=2026-07-14/run_id=two/manifest.json"},
            {"Key": "pipeline_runs/date=2026-07-15/run_id=failed/manifest.json"},
        ]}]


class FakeClient:
    def get_paginator(self, _): return FakePaginator()
    def get_object(self, **kwargs):
        status = "failed" if "failed" in kwargs["Key"] else "success"
        return {"Body": io.BytesIO(json.dumps({"status": status, "retailers_completed": ["go", "winmart"]}).encode())}


def test_selects_latest_successful_global_manifest(monkeypatch):
    monkeypatch.setattr(sync.boto3, "client", lambda *_, **__: FakeClient())
    settings = SimpleNamespace(minio_endpoint="http://minio", minio_access_key="a", minio_secret_key="b", minio_bucket="bucket")
    manifests = sync.latest_manifests(settings)
    assert set(manifests) == {"go", "winmart"}
    assert manifests["go"]["date"] == "2026-07-14"
    assert manifests["go"]["run"] == "two"


def test_current_hudi_paths_are_store_scoped():
    assert sync.GLOBAL_TABLES["products"] == "gold/dim_product_hudi"
    assert sync.STORE_TABLES["offers"].format(retailer="go") == "gold/fact_price_snapshot_daily_hudi/store=go"


def test_keeps_latest_source_run_before_serving_chatbot():
    rows = [
        {"source_run_id": "20260714_084309", "price_snapshot_id": "old"},
        {"source_run_id": "20260716_085935", "price_snapshot_id": "new"},
    ]
    assert sync.latest_source_run_rows(rows) == [rows[1]]


def test_history_preserves_each_daily_price_snapshot():
    price_rows = [
        {
            "price_snapshot_id": "go-neptune-20260714",
            "snapshot_date": "2026-07-14",
            "retailer_id": "go",
            "store_code": "go-1",
            "retailer_product_id": "neptune-2l",
            "retailer_product_key": "go-neptune-2l",
            "canonical_product_id": "neptune-2l",
            "product_name": "Dầu ăn Neptune 2L",
            "current_price": 70000,
            "source_run_id": "20260714_084309",
        },
        {
            "price_snapshot_id": "go-neptune-20260715",
            "snapshot_date": "2026-07-15",
            "retailer_id": "go",
            "store_code": "go-1",
            "retailer_product_id": "neptune-2l",
            "retailer_product_key": "go-neptune-2l",
            "canonical_product_id": "neptune-2l",
            "product_name": "Dầu ăn Neptune 2L",
            "current_price": 68000,
            "source_run_id": "20260715_084309",
        },
    ]
    retailer_products = [{
        "retailer_product_key": "go-neptune-2l",
        "retailer_product_id": "neptune-2l",
        "retailer_id": "go",
        "canonical_product_id": "neptune-2l",
        "product_name": "Dầu ăn Neptune 2L",
    }]
    products = [{"canonical_product_id": "neptune-2l", "canonical_name": "Dầu ăn Neptune 2L", "brand": "Neptune"}]

    history = sync.prepare_offers(price_rows, retailer_products, products, history=True)

    assert [row["price_snapshot_id"] for row in history] == ["go-neptune-20260714", "go-neptune-20260715"]
    assert [row["current_price"] for row in history] == [70000, 68000]


def test_latest_snapshot_date_helper():
    from app.repository import latest_snapshot_date
    res = latest_snapshot_date()
    assert res is None or isinstance(res, str)
