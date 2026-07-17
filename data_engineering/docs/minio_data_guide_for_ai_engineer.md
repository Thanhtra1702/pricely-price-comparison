# Hướng dẫn dữ liệu MinIO cho AI Engineer

> Cập nhật từ MinIO ngày 16/07/2026. Dữ liệu nghiệp vụ hiện có snapshot ngày **14/07/2026**; thời điểm Hudi materialize lên MinIO là ngày 15–16/07/2026. Hai thời điểm này không phải là một.

## 1. Mục đích và phạm vi

Tài liệu này mô tả dữ liệu của dự án so sánh giá được DE publish trên MinIO để AI Engineer có thể:

- chọn đúng bảng cho chatbot, RAG, semantic search hoặc feature engineering;
- đọc đúng Hudi table, không lấy nhầm file Parquet/metadata nội bộ;
- join dữ liệu giá, sản phẩm, retailer và khuyến mãi đúng khóa;
- hiểu giới hạn hiện tại của dữ liệu trước khi trả lời cho người dùng.

Bucket cần dùng là `supermarket-lakehouse`. Bucket `lakehouse` là dữ liệu e-commerce cũ, không thuộc dataset so sánh giá này.

## 2. Trạng thái dữ liệu hiện tại

Pipeline hoàn thành thành công cho 5 retailer:

`bachhoaxanh`, `go`, `lottemart`, `mmvietnam`, `winmart`.

Run nghiệp vụ:

| Thuộc tính | Giá trị |
|---|---|
| `run_date` | `2026-07-14` |
| `run_id` | `20260714_084309` |
| Trạng thái pipeline | `success` |
| Retailer thiếu | Không có |
| Định dạng publish | Apache Hudi trên MinIO/S3A |
| Tổng physical Hudi table đã kiểm tra | 20 |
| Tổng rows giữa các bảng | 18,026 |

Tổng 18,026 là tổng row của các bảng khác loại; **không phải** 18,026 sản phẩm duy nhất.

## 3. Cách dữ liệu được tổ chức

```text
supermarket-lakehouse/
├── gold/                              # Dataset đã chuẩn hóa để dùng downstream
│   ├── dim_date_hudi/
│   ├── dim_product_hudi/
│   ├── dim_retailer_hudi/
│   ├── dim_retailer_product_hudi/
│   ├── dim_store_hudi/
│   ├── dim_promotion_hudi/store=<retailer>/
│   ├── fact_price_snapshot_daily_hudi/store=<retailer>/
│   └── fact_promotion_item_hudi/store=<retailer>/
└── pipeline_runs/date=2026-07-14/run_id=20260714_084309/manifest.json
```

Có 8 nhóm logical table, nhưng 3 nhóm (`dim_promotion_hudi`, `fact_price_snapshot_daily_hudi`, `fact_promotion_item_hudi`) được ghi thành một Hudi table riêng cho từng retailer. Vì vậy có 20 physical Hudi root cần đọc.

### Điều không nên đọc trực tiếp

- Không đọc file `.parquet` riêng lẻ: Hudi có timeline và có thể chứa nhiều version của cùng record.
- Không dùng các thư mục `.hoodie/`: đây là metadata nội bộ của Hudi.
- Không dùng `gold/fact_price_snapshot_daily/store=.../date=.../run_id=.../price_snapshot_daily_hudi` cho ứng dụng mới. Đây là export legacy theo từng run; dùng cùng lúc với table mới sẽ dễ đếm trùng dữ liệu.

## 4. Data model

```text
dim_retailer ──┬── dim_store
               ├── dim_retailer_product ──┬── dim_product (canonical mapping)
               │                           └── fact_price_snapshot_daily
               └── dim_promotion ─────────── fact_promotion_item

dim_date ───────────────────────────────────┘
```

- `dim_*` là master/reference data.
- `fact_price_snapshot_daily` là nguồn chính cho giá tại một thời điểm.
- `dim_promotion` mô tả offer/promotion; `fact_promotion_item` liên kết offer với sản phẩm và giá.
- Một `canonical_product_id` có thể liên kết nhiều `retailer_product_id` từ các retailer khác nhau. Chỉ nên so sánh cross-retailer khi canonical mapping có mặt và đáng tin cậy.

## 5. Catalog bảng

### 5.1. Dimension tables dùng chung

| Logical table | Hudi path | Grain | Rows | Khóa/chức năng chính |
|---|---|---|---:|---|
| `dim_date_hudi` | `gold/dim_date_hudi` | Một ngày lịch | 1 | `date_key`, `calendar_date` |
| `dim_product_hudi` | `gold/dim_product_hudi` | Một canonical product | 153 | `canonical_product_id`, `product_key` |
| `dim_retailer_hudi` | `gold/dim_retailer_hudi` | Một retailer | 5 | `retailer_id`, `retailer_key` |
| `dim_retailer_product_hudi` | `gold/dim_retailer_product_hudi` | Một sản phẩm tại retailer | 4,329 | `retailer_product_id`, `retailer_product_key` |
| `dim_store_hudi` | `gold/dim_store_hudi` | Một store/group của retailer | 5 | `store_code`, `store_key` |

Các cột nghiệp vụ của từng bảng:

| Bảng | Cột quan trọng | Ý nghĩa |
|---|---|---|
| `dim_date_hudi` | `calendar_date`, `date_key`, `day`, `day_of_week`, `month`, `year`, `is_weekend` | Lịch để filter/join theo ngày. |
| `dim_product_hudi` | `canonical_product_id`, `product_key`, `canonical_name`, `brand`, `product_type`, `measurement_type`, `measurement_base_unit`, `package_total_base_quantity` | Product master đã canonical hóa; phù hợp cho cross-retailer matching. |
| `dim_retailer_hudi` | `retailer_id`, `retailer_key`, `retailer_name`, `is_active` | Danh mục retailer. |
| `dim_retailer_product_hudi` | `retailer_product_id`, `retailer_product_key`, `retailer_id`, `canonical_product_id`, `product_name`, `barcode`, `image_url`, `source_url` | Tên/product URL thực tế tại từng retailer; là bảng tốt để retrieval theo tên sản phẩm. |
| `dim_store_hudi` | `store_code`, `store_key`, `retailer_id`, `store_group_code`, `region`, `is_active` | Ngữ cảnh nơi giá/khuyến mãi áp dụng. |

Mọi dimension cũng có các cột lineage: `contract_version`, `source_run_id`, `built_at`; không dùng chúng làm khóa join chính.

### 5.2. Promotion tables theo retailer

Physical path mẫu: `gold/dim_promotion_hudi/store=bachhoaxanh`.

| Retailer | `dim_promotion_hudi` rows | `fact_promotion_item_hudi` rows |
|---|---:|---:|
| Bách Hóa Xanh | 1,400 | 1,400 |
| GO! | 388 | 388 |
| Lotte Mart | 1,652 | 1,652 |
| MM Việt Nam | 641 | 641 |
| WinMart | 521 | 521 |
| **Tổng** | **4,602** | **4,602** |

`dim_promotion_hudi` (19 cột) mô tả offer:

- Khóa: `promotion_id`, `promotion_key`.
- Ngữ cảnh: `retailer_id`, `store_code`, `observation_date`, `promotion_scope`.
- Nội dung: `promotion_type`, `offer_text_raw`, `offer_text_available`, `promotion_start_date`, `promotion_end_date`.
- Lineage: `contract_version`, `source_run_id`, `built_at`.

`fact_promotion_item_hudi` (25 cột) gắn offer với product/price:

- Khóa: `promotion_item_fact_id`.
- Join promotion: `promotion_id`, `promotion_key`, `promotion_type`.
- Join product: `retailer_product_id`, `retailer_product_key`.
- Giá: `listed_price`, `promo_price`, `current_price`, `currency`.
- Ngữ cảnh: `date_key`, `retailer_id`, `retailer_key`, `store_code`, `store_key`, `observation_date`.
- Lineage: `source_run_id`, `source_bronze_record_key`, `built_at`.

### 5.3. Daily price snapshot theo retailer

Physical path mẫu: `gold/fact_price_snapshot_daily_hudi/store=bachhoaxanh`.

| Retailer | Rows |
|---|---:|
| Bách Hóa Xanh | 1,127 |
| GO! | 388 |
| Lotte Mart | 1,652 |
| MM Việt Nam | 641 |
| WinMart | 521 |
| **Tổng** | **4,329** |

Grain của bảng: một snapshot giá của một `retailer_product_id` tại một `store_code` trong một ngày. Đây là bảng mặc định để trả lời các câu hỏi như “sản phẩm này đang giá bao nhiêu?”, “retailer nào rẻ hơn?” hoặc “đang có giảm giá không?”.

Nhóm cột chính:

| Nhóm | Cột | Cách dùng |
|---|---|---|
| Identity/join | `price_snapshot_id`, `date_key`, `retailer_key`, `store_key`, `retailer_product_key`, `product_key`, `canonical_product_id`, `retailer_id`, `store_code`, `retailer_product_id`, `observation_id` | Dùng để join dimensions và deduplicate. |
| Product display | `product_name`, `brand`, `category_raw` | Dùng để hiển thị/retrieval; không phải canonical match tuyệt đối. |
| Price | `listed_price`, `promo_price`, `current_price`, `currency`, `discount_amount`, `discount_percent` | `current_price` là giá chính để hiển thị/mua tại thời điểm quan sát. |
| Unit price | `effective_unit_price`, `comparison_unit`, `measurement_type`, `package_total_base_quantity`, `unit_price_publishable` | Chỉ dùng để so sánh giá theo đơn vị khi `unit_price_publishable = true`. |
| Promotion/availability | `is_on_promotion`, `is_price_discount`, `has_promo_mechanic`, `availability_status` | `is_on_promotion` là flag tổng quát; promotion mechanic có thể không phải giảm giá trực tiếp. |
| Freshness/quality | `observed_at`, `snapshot_date`, `run_status`, `silver_data_quality_status`, `built_at` | Filter chất lượng và giải thích độ mới của câu trả lời. |
| Raw lineage | `source_run_id`, `source_bronze_record_key`, `source_file`, `source_line_number` | Dùng để trace/debug, không hiển thị cho end user. |

## 6. Quy tắc join quan trọng

| Mục tiêu | Join khuyến nghị |
|---|---|
| Hiển thị tên retailer | `fact.retailer_id = dim_retailer.retailer_id` |
| Hiển thị store/region | Ưu tiên `fact.store_key = dim_store.store_key`; có thể fallback `retailer_id + store_code` |
| Lấy product source chuẩn | `fact.retailer_product_key = dim_retailer_product.retailer_product_key` hoặc `retailer_id + retailer_product_id` |
| So sánh sản phẩm giữa retailer | `fact.canonical_product_id = dim_product.canonical_product_id`; bỏ record null canonical ID nếu cần so sánh chính xác |
| Lấy ngày | `fact.date_key = dim_date.date_key` |
| Gắn promotion vào product | `fact_promotion_item.promotion_key = dim_promotion.promotion_key` và product qua `retailer_product_key` |

Không join chỉ bằng `product_name`: tên có thể khác quy cách, bundle hoặc cách viết giữa retailer.

## 7. Cách đọc đúng bằng Spark + Hudi

Hudi snapshot reader trả về version mới nhất của mỗi record key. Đây là cách nên dùng cho production/analysis:

```python
from functools import reduce

retailers = ["bachhoaxanh", "go", "lottemart", "mmvietnam", "winmart"]
base = "s3a://supermarket-lakehouse/gold"

price_dfs = [
    spark.read.format("hudi").load(
        f"{base}/fact_price_snapshot_daily_hudi/store={retailer}"
    )
    for retailer in retailers
]
fact_price = reduce(lambda left, right: left.unionByName(right), price_dfs)
```

Tương tự cho promotion:

```python
promotion_dfs = [
    spark.read.format("hudi").load(f"{base}/dim_promotion_hudi/store={retailer}")
    for retailer in retailers
]
dim_promotion = reduce(lambda left, right: left.unionByName(right), promotion_dfs)
```

Notebook [`read_hudi_minio.ipynb`](../notebooks/read_hudi_minio.ipynb) đã tự discover các Hudi root Gold hợp lệ, nên phù hợp để kiểm tra data mới mà không hard-code retailer.

## 8. Gợi ý dùng cho AI Engineer

### Product search/RAG

1. Index `dim_retailer_product_hudi.product_name`, `brand`, `retailer_id` và có thể `source_url`.
2. Dùng semantic/vector retrieval để tìm candidate product từ câu hỏi người dùng.
3. Lookup `fact_price_snapshot_daily_hudi` bằng `retailer_product_key` hoặc `retailer_product_id` để lấy giá thật lúc trả lời.
4. Khi người dùng hỏi so sánh cross-retailer, chỉ group theo `canonical_product_id` khác null; nếu không có mapping, nói rõ chỉ là match theo tên gần đúng.

### Trả lời giá và promotion

- Giá hiển thị: `current_price` + `currency`.
- Giá gốc/giảm: `listed_price`, `promo_price`, `discount_amount`, `discount_percent`.
- So sánh đơn vị: chỉ hiển thị `effective_unit_price` khi `unit_price_publishable` là true; luôn nêu `comparison_unit`.
- Nội dung điều kiện khuyến mãi: lookup `dim_promotion.offer_text_raw` qua `promotion_key`; không tự suy diễn điều kiện từ `promo_price`.

### Filter an toàn trước khi đưa vào câu trả lời

```python
usable_price = fact_price.filter(
    (F.col("run_status") == "success")
    & F.col("current_price").isNotNull()
    & (F.col("current_price") > 0)
)

# Khi cần dữ liệu nghiêm ngặt hơn:
strict_price = usable_price.filter(F.col("silver_data_quality_status") == "valid")
```

`warning` không đồng nghĩa dữ liệu sai; nó cho biết record cần thận trọng hơn khi dùng cho tác vụ chính xác như so sánh unit price hoặc chuẩn hóa quy cách.

## 9. Những lưu ý về thời gian và chất lượng

- Hiện chỉ có snapshot business ngày 14/07/2026. Không được trả lời đây là giá thời gian thực hoặc suy luận trend qua nhiều ngày.
- `_hoodie_commit_time` là thời điểm Hudi commit, còn `observed_at` là thời điểm crawler quan sát giá và `snapshot_date` là ngày snapshot. Với câu hỏi người dùng, ưu tiên diễn giải bằng `observed_at`/`snapshot_date`.
- Các timestamp hiện đang là `string`; cần parse rõ timezone trước khi làm feature theo thời gian. `observed_at` có offset timezone, còn `built_at` thường theo UTC.
- Giá hiện được lưu dạng integer VND. Không tự chia/format thành đơn vị khác nếu chưa có yêu cầu đổi tiền tệ.
- Hudi thêm 5 cột kỹ thuật bắt đầu bằng `_hoodie_`; loại chúng khỏi embedding, prompt context và business metric.

## 10. Checklist trước khi đưa vào production

- [ ] Đọc bằng `format("hudi")`, không đọc Parquet trực tiếp.
- [ ] Union đủ 5 retailer-scoped table khi cần toàn bộ thị trường.
- [ ] Dùng `current_price`, không mặc định `promo_price` là giá có thể mua.
- [ ] Chỉ compare cross-retailer theo canonical mapping có mặt.
- [ ] Có filter `run_status` và kiểm tra `silver_data_quality_status` theo use case.
- [ ] Gắn `snapshot_date` hoặc `observed_at` vào câu trả lời người dùng để minh bạch độ mới.
- [ ] Không trộn path legacy `fact_price_snapshot_daily/.../run_id=...` với path Hudi publish mới.
