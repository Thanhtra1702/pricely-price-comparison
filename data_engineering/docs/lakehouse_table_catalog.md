# Data dictionary cho pipeline so sanh gia khuyen mai

Tai lieu nay la catalog day du cho kien truc trong `lakehouse_hudi_pipeline_design.md`.
Moi bang phai co grain, khoa va use case ro rang. Khong tao bang chi vi mot cong nghe ho tro no.

## 1. Quy uoc

| Nhan | Y nghia |
|---|---|
| `MVP` | Can de crawl, audit va so sanh gia chinh xac |
| `Derived` | Tao tu bang MVP khi can BI, alert hoac query nhanh |
| `Later` | Chi tao khi da co du lieu/traffic cho recommendation, search hoac chatbot |

Kieu du lieu dung theo Spark/Hudi: `string`, `boolean`, `int`, `long`, `decimal(18,2)`,
`date`, `timestamp`, `array<string>`, `map<string,string>`. Tien VND van luu
`decimal(18,2)` de schema dung duoc cho retailer/quoc gia khac.

## 2. Nguyen tac grain va khoa

| Nhom | Grain |
|---|---|
| Raw record | Mot record goc tu mot source trong mot lan crawl |
| Product observation | Mot SKU/UOM tai mot store va mot thoi diem quan sat |
| Promotion | Mot chuong trinh tai mot store trong mot khoang hieu luc |
| Promotion item | Mot san pham tham gia promotion voi vai tro dieu kien/qua tang |
| Daily price fact | Gia cuoi ngay cua mot SKU/UOM tai mot store |
| Price comparison | Mot canonical product tai mot store trong mot ngay |

Khong dung ten san pham lam khoa. `source_product_id` dinh danh san pham trong mot retailer;
`canonical_product_id` dinh danh cung san pham sau khi match cross-retailer.

## 3. PostgreSQL operational metadata

PostgreSQL khong chua lich su gia lam source of truth. No chua config va state de Airflow/scraper
biet phai chay cai gi, o dau va ket qua van hanh ra sao.

### 3.1. `ops.retailers` - MVP

Grain: mot retailer.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `retailer_id` | string | Co | PK, vi du `winmart` |
| `retailer_name` | string | Co | Ten hien thi |
| `base_url` | string | Co | Domain chinh |
| `timezone` | string | Co | Mac dinh `Asia/Ho_Chi_Minh` |
| `currency` | string | Co | Mac dinh `VND` |
| `is_active` | boolean | Co | Co duoc lap lich crawl khong |
| `created_at` | timestamp | Co | Audit |
| `updated_at` | timestamp | Co | Audit |

Nhu cau: quan ly source tap trung, tat mot retailer ma khong sua DAG.

### 3.2. `ops.stores` - MVP

Grain: mot chi nhanh retailer.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `store_id` | string | Co | PK noi bo |
| `retailer_id` | string | Co | FK retailer |
| `source_store_code` | string | Co | Ma cua website, vi du `1682` |
| `source_store_group_code` | string | Khong | Ma nhom store neu source co |
| `store_name` | string | Khong | Ten chi nhanh |
| `address_raw` | string | Khong | Dia chi goc |
| `province_code` | string | Khong | Ma tinh chuan hoa |
| `district_code` | string | Khong | Ma quan/huyen chuan hoa |
| `latitude` | decimal(10,7) | Khong | Tim store gan user |
| `longitude` | decimal(10,7) | Khong | Tim store gan user |
| `is_active` | boolean | Co | Trang thai crawl |
| `valid_from` | timestamp | Co | Bat dau hieu luc metadata |
| `valid_to` | timestamp | Khong | Ket thuc hieu luc |

Nhu cau: gia va ton kho phu thuoc store; location cho phep ung dung tim uu dai gan nguoi dung.

### 3.3. `ops.crawl_sources` - MVP

Grain: mot URL/API/category duoc lap lich tai mot store.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `source_id` | string | Co | PK |
| `retailer_id` | string | Co | FK retailer |
| `store_id` | string | Co | FK store |
| `source_type` | string | Co | `api`, `category_page`, `product_detail` |
| `category_slug` | string | Khong | Danh muc nguon |
| `url_template` | string | Co | URL chua bien store/page |
| `scraper_name` | string | Co | Entry point scraper |
| `schedule_cron` | string | Khong | Lich mong muon |
| `priority` | int | Co | Uu tien crawl |
| `rate_limit_per_minute` | int | Khong | Gioi han request |
| `is_active` | boolean | Co | Bat/tat source |
| `config_json` | string | Khong | Tham so source-specific |
| `updated_at` | timestamp | Co | Audit |

Nhu cau: URL thay doi duoc cap nhat bang config, khong hard-code vao DAG.

### 3.4. `ops.crawl_runs` - MVP

Grain: mot lan chay logical cho mot retailer/store.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `run_id` | string | Co | PK va correlation ID |
| `dag_run_id` | string | Khong | ID Airflow |
| `retailer_id` | string | Co | Source |
| `store_id` | string | Co | Store crawl |
| `started_at` | timestamp | Co | Bat dau |
| `ended_at` | timestamp | Khong | Ket thuc |
| `status` | string | Co | `running`, `success`, `partial`, `failed`, `blocked` |
| `expected_sources` | int | Khong | So source phai crawl |
| `successful_sources` | int | Khong | So source thanh cong |
| `raw_record_count` | long | Khong | So record raw |
| `product_count` | long | Khong | So product |
| `promotion_count` | long | Khong | So promotion |
| `error_summary` | string | Khong | Tom tat loi |
| `output_path` | string | Khong | Thu muc raw run |

Nhu cau: biet mot snapshot co day du khong; ngan app hien thi du lieu cua run that bai nhu du lieu moi.

### 3.5. `ops.crawl_task_runs` - MVP

Grain: mot step/source trong mot crawl run.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `task_run_id` | string | Co | PK |
| `run_id` | string | Co | FK crawl run |
| `source_id` | string | Khong | FK crawl source |
| `task_name` | string | Co | `config_api`, `promo_cards`, `hydrate`, `merge` |
| `attempt_no` | int | Co | Lan thu |
| `started_at` | timestamp | Co | Bat dau |
| `ended_at` | timestamp | Khong | Ket thuc |
| `status` | string | Co | Trang thai step |
| `http_status` | int | Khong | Neu co |
| `records_written` | long | Khong | Output step |
| `error_type` | string | Khong | Timeout, blocked, parse error |
| `error_message` | string | Khong | Noi dung rut gon |
| `log_path` | string | Khong | Structured log |

Nhu cau: retry rieng tung source, bao do dung cho task loi thay vi lam mat ket qua cac retailer khac.

### 3.6. `ops.product_match_reviews` - Derived

Grain: mot quyet dinh review cho mot cap retailer product - canonical product.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `review_id` | string | Co | PK |
| `retailer_product_id` | string | Co | San pham can review |
| `candidate_canonical_product_id` | string | Khong | Candidate |
| `decision` | string | Co | `pending`, `accepted`, `rejected`, `new_product` |
| `reviewer` | string | Khong | User/service |
| `reason` | string | Khong | Ly do |
| `created_at` | timestamp | Co | Audit |
| `reviewed_at` | timestamp | Khong | Audit |

Nhu cau: product matching sai se lam so sanh gia sai; can human-in-the-loop cho candidate thap.

## 4. Bronze Hudi

Bronze la ban sao bat bien cua du lieu da thu thap. Khong chuan hoa product name, gia hay promotion
o layer nay. Table type: `COPY_ON_WRITE`, operation: `insert`/`bulk_insert`.

### 4.1. `bronze.crawl_runs` - MVP

Grain: mot snapshot metadata cua crawl run tai luc ingest.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `run_id` | string | Co | Record key |
| `dag_run_id` | string | Khong | Airflow correlation |
| `retailer_id` | string | Co | Retailer |
| `store_code` | string | Khong | Store goc |
| `region_raw` | string | Khong | Region tu config |
| `crawl_started_at` | timestamp | Co | Bat dau crawl |
| `crawl_ended_at` | timestamp | Khong | Ket thuc crawl |
| `run_status` | string | Co | Ket qua |
| `scraper_version` | string | Khong | Git SHA/version |
| `config_snapshot` | string | Co | JSON config tai luc chay |
| `output_path` | string | Co | Raw run path |
| `ingested_at` | timestamp | Co | Luc vao Bronze |
| `ingest_date` | date | Co | Partition |

Nhu cau: tai hien scraper/config va danh gia completeness cua moi batch.

### 4.2. `bronze.raw_records` - MVP

Grain: mot JSON/DOM record goc.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `raw_record_id` | string | Co | Hash `run_id + source + ordinal + raw_hash` |
| `run_id` | string | Co | Crawl run |
| `retailer_id` | string | Co | Retailer |
| `store_code` | string | Khong | Store goc |
| `record_type` | string | Co | `product`, `promo_card`, `store`, `category`, `other` |
| `source_product_id` | string | Khong | ID goc neu parse duoc |
| `source_category` | string | Khong | Category goc |
| `source_url` | string | Co | Nguon record |
| `source_type` | string | Co | `api_json`, `network_json`, `dom`, `next_data` |
| `raw_record` | string | Co | JSON raw/serialized DOM fragment |
| `raw_hash` | string | Co | Kiem tra trung va integrity |
| `ordinal` | long | Co | Vi tri record trong payload |
| `crawl_timestamp` | timestamp | Co | Luc quan sat |
| `raw_payload_path` | string | Co | File payload goc |
| `parse_status` | string | Co | `parsed`, `partial`, `failed` |
| `ingest_date` | date | Co | Partition |

Hudi: key `raw_record_id`, partition `ingest_date/retailer_id`, precombine `crawl_timestamp`.

Nhu cau: reprocess khi parser sai ma khong crawl lai; audit gia/text promo dung theo website.

### 4.3. `bronze.raw_payload_manifest` - MVP

Grain: mot file HTTP response/HTML/screenshot.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `payload_id` | string | Co | Hash path/content |
| `run_id` | string | Co | Crawl run |
| `retailer_id` | string | Co | Retailer |
| `request_url` | string | Co | URL request |
| `http_method` | string | Co | Thuong la GET |
| `http_status` | int | Khong | Response status |
| `content_type` | string | Khong | MIME type |
| `payload_path` | string | Co | Object storage path |
| `content_hash` | string | Co | Integrity/dedupe |
| `content_length` | long | Khong | Kich thuoc |
| `captured_at` | timestamp | Co | Luc capture |
| `is_sanitized` | boolean | Co | Da xoa cookie/token chua |
| `ingest_date` | date | Co | Partition |

Nhu cau: lineage den file goc va kiem soat raw payload ma khong nhan doi binary/HTML trong moi record.

### 4.4. `bronze.data_quality_results` - MVP

Grain: mot rule DQ cho mot dataset/run.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `dq_result_id` | string | Co | PK |
| `run_id` | string | Co | Run duoc test |
| `dataset_name` | string | Co | Dataset/table/file |
| `rule_name` | string | Co | Ten rule |
| `severity` | string | Co | `info`, `warning`, `error` |
| `status` | string | Co | `pass`, `fail`, `skipped` |
| `observed_value` | string | Khong | Gia tri do duoc |
| `expected_value` | string | Khong | Threshold |
| `failed_record_count` | long | Khong | So dong fail |
| `sample_record_ids` | array<string> | Khong | Mau de debug |
| `checked_at` | timestamp | Co | Luc test |
| `ingest_date` | date | Co | Partition |

Nhu cau: Airflow dung gate de quyet dinh co publish Silver/Gold hay danh dau partial.

## 5. Silver Hudi

Silver chua entity chuan hoa va lich su quan sat. MVP bat dau bang COW; chi doi bang ghi tan suat cao
sang MOR khi metric cho thay can thiet.

### 5.1. `silver.retailers` - MVP

Grain: mot retailer chuan hoa.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `retailer_id` | string | Co | Record key |
| `retailer_name` | string | Co | Ten chuan |
| `domain` | string | Co | Domain |
| `currency` | string | Co | Tien te |
| `timezone` | string | Co | Mui gio |
| `is_active` | boolean | Co | Trang thai |
| `updated_at` | timestamp | Co | Precombine |

Nhu cau: dimension dung chung cho query, khong de dashboard phu thuoc PostgreSQL operational.

### 5.2. `silver.stores` - MVP

Grain: mot version cua store (SCD2 khi dia chi/ten thay doi).

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `store_version_id` | string | Co | Record key |
| `store_id` | string | Co | Business ID |
| `retailer_id` | string | Co | Retailer |
| `source_store_code` | string | Co | Ma source |
| `store_name` | string | Khong | Ten chuan |
| `address` | string | Khong | Dia chi chuan |
| `province_code` | string | Khong | Tinh/thanh |
| `district_code` | string | Khong | Quan/huyen |
| `latitude` | decimal(10,7) | Khong | Vi tri |
| `longitude` | decimal(10,7) | Khong | Vi tri |
| `valid_from` | timestamp | Co | SCD2 start |
| `valid_to` | timestamp | Khong | SCD2 end |
| `is_current` | boolean | Co | Version hien tai |
| `source_run_id` | string | Co | Lineage |

Nhu cau: so sanh dung dia diem va ho tro truy van "gan toi".

### 5.3. `silver.categories` - MVP

Grain: mot category chuan hoa.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `category_id` | string | Co | Record key |
| `category_name` | string | Co | Ten chuan |
| `parent_category_id` | string | Khong | Cay category |
| `category_level` | int | Co | Level |
| `category_path` | string | Co | Full path |
| `is_active` | boolean | Co | Trang thai |
| `updated_at` | timestamp | Co | Precombine |

Nhu cau: loc/aggregate cung nhom hang khi taxonomy retailer khac nhau.

### 5.4. `silver.retailer_products` - MVP

Grain: mot SKU/UOM do retailer ban; khong phu thuoc store.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `retailer_product_id` | string | Co | Hash retailer + source product + sku/uom |
| `retailer_id` | string | Co | Retailer |
| `source_product_id` | string | Co | ID goc |
| `sku` | string | Khong | SKU source |
| `barcode` | string | Khong | GTIN/EAN da validate |
| `product_name` | string | Co | Ten cleaned, chua canonical |
| `brand` | string | Khong | Brand cleaned |
| `category_id` | string | Khong | Category mapped |
| `category_raw` | string | Khong | Category nguon |
| `package_quantity` | decimal(18,4) | Khong | Vi du 900 |
| `package_unit` | string | Khong | g, ml, cai |
| `units_per_pack` | decimal(18,4) | Khong | Vi du loc 4 hop |
| `sell_uom` | string | Khong | UOM ban |
| `image_url` | string | Khong | Anh |
| `product_url` | string | Co | URL |
| `first_seen_at` | timestamp | Co | Lich su |
| `last_seen_at` | timestamp | Co | Lich su |
| `is_active` | boolean | Co | Con xuat hien khong |
| `source_run_id` | string | Co | Lineage |

Nhu cau: tach product master khoi gia theo store/thoi gian, tranh lap ten/brand trong logic matching.

### 5.5. `silver.product_observations` - MVP

Grain: mot retailer product tai mot store tai mot thoi diem crawl.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `observation_id` | string | Co | Hash grain, record key |
| `run_id` | string | Co | Crawl run |
| `retailer_product_id` | string | Co | FK product |
| `retailer_id` | string | Co | Partition/filter |
| `store_id` | string | Co | Store |
| `observed_at` | timestamp | Co | Thoi diem gia co hieu luc quan sat |
| `observation_date` | date | Co | Partition |
| `listed_price` | decimal(18,2) | Khong | Gia niem yet |
| `promo_price` | decimal(18,2) | Khong | Gia giam truc tiep |
| `current_price` | decimal(18,2) | Co | Gia mua mot don vi tai thoi diem crawl |
| `currency` | string | Co | VND |
| `discount_amount` | decimal(18,2) | Khong | listed - promo |
| `discount_percent` | decimal(7,4) | Khong | Ty le tinh lai |
| `stock_quantity` | decimal(18,4) | Khong | Neu source co |
| `availability_status` | string | Khong | `in_stock`, `out_of_stock`, `unknown` |
| `is_price_discount` | boolean | Co | Giam gia truc tiep |
| `has_promo_mechanic` | boolean | Co | Co chuong trinh mua/tang/combo |
| `is_on_promotion` | boolean | Co | OR cua hai field tren |
| `source_url` | string | Co | Lineage |
| `raw_record_id` | string | Co | FK Bronze |
| `data_quality_status` | string | Co | `valid`, `warning`, `quarantined` |

Hudi: key `observation_id`, partition `retailer_id/observation_date`, precombine `observed_at`.

Nhu cau: day la fact goc de theo doi lich su gia, so sanh store va tao snapshot.

### 5.6. `silver.promotions` - MVP

Grain: mot offer/promotion tai mot store va mot time window. Khong buoc promotion vao mot product duy nhat.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `promotion_id` | string | Co | ID source hoac hash noi dung + store + window |
| `retailer_id` | string | Co | Retailer |
| `store_id` | string | Co | Noi ap dung |
| `source_promotion_code` | string | Khong | Ma chuong trinh |
| `promotion_name` | string | Khong | Ten chuong trinh |
| `promotion_text_raw` | string | Co | Text goc |
| `promotion_type` | string | Co | `direct_discount`, `bundle_price`, `buy_x_get_y`, `buy_x_pay_y`, `member_price`, `unknown` |
| `buy_quantity` | decimal(18,4) | Khong | Dieu kien mua |
| `pay_quantity` | decimal(18,4) | Khong | So luong tinh tien |
| `gift_quantity` | decimal(18,4) | Khong | So luong tang |
| `bundle_quantity` | decimal(18,4) | Khong | So luong combo |
| `bundle_price` | decimal(18,2) | Khong | Gia combo |
| `member_only` | boolean | Co | Chi hoi vien |
| `minimum_spend` | decimal(18,2) | Khong | Don toi thieu |
| `limit_quantity` | decimal(18,4) | Khong | Gioi han moi don |
| `starts_at` | timestamp | Khong | Bat dau |
| `ends_at` | timestamp | Khong | Ket thuc |
| `observed_at` | timestamp | Co | Luc crawl thay offer |
| `source_url` | string | Co | Lineage |
| `raw_record_id` | string | Co | FK Bronze |
| `parse_confidence` | decimal(5,4) | Co | Do tin cay parser |
| `parse_status` | string | Co | `parsed`, `partial`, `unknown` |

Nhu cau: luu dieu kien mua that; `promo_price` mot minh khong mo ta duoc mua 5 tang 1.

### 5.7. `silver.promotion_items` - MVP

Grain: mot product tham gia mot promotion voi mot vai tro.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `promotion_item_id` | string | Co | Record key |
| `promotion_id` | string | Co | FK promotion |
| `retailer_product_id` | string | Khong | FK product neu match duoc |
| `source_product_id` | string | Khong | ID goc |
| `item_role` | string | Co | `qualifying`, `reward`, `bundle_component` |
| `required_quantity` | decimal(18,4) | Khong | So luong dieu kien |
| `reward_quantity` | decimal(18,4) | Khong | So luong tang |
| `uom` | string | Khong | Don vi |
| `product_name_raw` | string | Khong | Ten qua tang neu chua match |
| `match_status` | string | Co | `matched`, `unmatched`, `ambiguous` |
| `source_run_id` | string | Co | Lineage |

Nhu cau: mo hinh hoa dung truong hop mua san pham A tang san pham B; khong gan qua tang nham vao A.

### 5.8. `silver.canonical_products` - MVP khi co tu hai retailer

Grain: mot san pham vat ly/quy cach co the so sanh cross-retailer.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `canonical_product_id` | string | Co | Record key |
| `canonical_name` | string | Co | Ten chuan |
| `brand` | string | Khong | Brand chuan |
| `category_id` | string | Khong | Category chuan |
| `barcode` | string | Khong | Barcode tin cay |
| `net_quantity` | decimal(18,4) | Khong | Quy cach chuan |
| `net_unit` | string | Khong | g/ml/cai |
| `units_per_pack` | decimal(18,4) | Khong | So don vi/gioi |
| `comparison_unit` | string | Khong | kg/l/cai |
| `status` | string | Co | `active`, `needs_review`, `retired` |
| `created_at` | timestamp | Co | Audit |
| `updated_at` | timestamp | Co | Precombine |

Nhu cau: khong co bang nay thi "cung san pham" giua WinMart va Lotte chi la so khop ten mong manh.

### 5.9. `silver.product_identity_map` - MVP khi co tu hai retailer

Grain: mot mapping hien tai cua retailer product sang canonical product.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `identity_map_id` | string | Co | Record key |
| `retailer_product_id` | string | Co | FK retailer product |
| `canonical_product_id` | string | Co | FK canonical product |
| `match_method` | string | Co | `barcode`, `rule`, `ml`, `manual` |
| `match_score` | decimal(5,4) | Co | Confidence |
| `match_status` | string | Co | `confirmed`, `auto_accepted`, `rejected` |
| `valid_from` | timestamp | Co | Hieu luc |
| `valid_to` | timestamp | Khong | Ket thuc |
| `review_id` | string | Khong | Link review |
| `updated_at` | timestamp | Co | Precombine |

Nhu cau: mapping co version, co the sua sai ma khong ghi de lich su.

### 5.10. `silver.product_identity_candidates` - Derived

Grain: mot cap candidate retailer product - canonical product.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `candidate_id` | string | Co | Record key |
| `retailer_product_id` | string | Co | Product can match |
| `candidate_canonical_product_id` | string | Co | Candidate |
| `barcode_score` | decimal(5,4) | Khong | Feature |
| `name_score` | decimal(5,4) | Khong | Feature |
| `brand_score` | decimal(5,4) | Khong | Feature |
| `package_score` | decimal(5,4) | Khong | Feature |
| `overall_score` | decimal(5,4) | Co | Ranking |
| `candidate_rank` | int | Co | Thu hang |
| `decision` | string | Co | `pending`, `accepted`, `rejected` |
| `model_version` | string | Khong | Reproducibility |
| `generated_at` | timestamp | Co | Audit |

Nhu cau: DS danh gia matching va dua candidate kho vao hang doi review.

### 5.11. `silver.price_change_events` - Derived

Grain: mot thay doi gia cua product/store giua hai observation lien tiep.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `price_change_id` | string | Co | Record key |
| `retailer_product_id` | string | Co | Product |
| `retailer_id` | string | Co | Retailer |
| `store_id` | string | Co | Store |
| `previous_observation_id` | string | Co | Observation truoc |
| `current_observation_id` | string | Co | Observation moi |
| `previous_price` | decimal(18,2) | Co | Gia cu |
| `current_price` | decimal(18,2) | Co | Gia moi |
| `change_amount` | decimal(18,2) | Co | Chenh lech |
| `change_percent` | decimal(9,4) | Khong | Ty le |
| `change_type` | string | Co | `increase`, `decrease`, `promo_start`, `promo_end` |
| `changed_at` | timestamp | Co | Thoi diem phat hien |
| `is_anomaly` | boolean | Co | Co vuot nguong khong |

Nhu cau: alert va trend query nhanh; co the tinh lai tu observations nen khong bat buoc ngay dau.

### 5.12. `silver.quarantine_records` - MVP

Grain: mot record khong dat DQ va chua duoc publish.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `quarantine_id` | string | Co | Record key |
| `run_id` | string | Co | Crawl run |
| `raw_record_id` | string | Co | FK Bronze |
| `target_table` | string | Co | Bang dang normalize |
| `error_codes` | array<string> | Co | Rule fail |
| `error_details` | string | Khong | JSON chi tiet |
| `quarantined_at` | timestamp | Co | Audit |
| `resolution_status` | string | Co | `open`, `fixed`, `ignored` |
| `resolved_at` | timestamp | Khong | Audit |

Nhu cau: khong lam fail ca batch vi mot so dong xau, nhung cung khong am tham dua du lieu sai vao Gold.

## 6. Gold Hudi

Gold la semantic/business layer. Table type COW, toi uu read. Chi publish tu Silver dat DQ.

### 6.1. `gold.dim_date` - MVP

Grain: mot ngay.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `date_key` | int | Co | YYYYMMDD, record key |
| `full_date` | date | Co | Ngay |
| `day_of_week` | int | Co | 1-7 |
| `week_of_year` | int | Co | Tuan |
| `month` | int | Co | Thang |
| `quarter` | int | Co | Quy |
| `year` | int | Co | Nam |
| `is_weekend` | boolean | Co | Cuoi tuan |
| `is_public_holiday` | boolean | Co | Neu co calendar |

Nhu cau: BI theo ngay/tuan/thang ma khong lap logic calendar.

### 6.2. `gold.dim_retailer` - MVP

Grain: mot retailer.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `retailer_key` | long | Co | Surrogate key |
| `retailer_id` | string | Co | Natural key |
| `retailer_name` | string | Co | Ten hien thi |
| `domain` | string | Co | Domain |
| `currency` | string | Co | Currency |
| `is_active` | boolean | Co | Trang thai |

Nhu cau: dimension on dinh cho BI.

### 6.3. `gold.dim_store` - MVP

Grain: mot version cua store.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `store_key` | long | Co | Surrogate key |
| `store_id` | string | Co | Natural key |
| `retailer_key` | long | Co | FK retailer |
| `store_code` | string | Co | Ma source |
| `store_name` | string | Khong | Ten |
| `address` | string | Khong | Dia chi |
| `province_code` | string | Khong | Tinh |
| `district_code` | string | Khong | Quan/huyen |
| `latitude` | decimal(10,7) | Khong | Vi tri |
| `longitude` | decimal(10,7) | Khong | Vi tri |
| `valid_from` | timestamp | Co | SCD2 |
| `valid_to` | timestamp | Khong | SCD2 |
| `is_current` | boolean | Co | Version hien tai |

Nhu cau: loc theo khu vuc va giu lich su khi store doi ten/dia chi.

### 6.4. `gold.dim_product` - MVP khi so sanh cross-retailer

Grain: mot canonical product.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `product_key` | long | Co | Surrogate key |
| `canonical_product_id` | string | Co | Natural key |
| `canonical_name` | string | Co | Ten hien thi |
| `brand` | string | Khong | Brand |
| `category_id` | string | Khong | Category |
| `barcode` | string | Khong | Barcode |
| `net_quantity` | decimal(18,4) | Khong | Quy cach |
| `net_unit` | string | Khong | Don vi |
| `units_per_pack` | decimal(18,4) | Khong | So luong/goi |
| `comparison_unit` | string | Khong | Don vi so sanh |
| `is_active` | boolean | Co | Trang thai |

Nhu cau: dashboard va app cung dung mot ten/quy cach sau khi match.

### 6.5. `gold.fact_price_snapshot_daily` - MVP

Grain: latest valid price cua mot retailer product/store/ngay.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `price_snapshot_id` | string | Co | Record key |
| `date_key` | int | Co | FK date |
| `retailer_key` | long | Co | FK retailer |
| `store_key` | long | Co | FK store |
| `product_key` | long | Khong | FK canonical product |
| `retailer_product_id` | string | Co | Chi tiet source |
| `observation_id` | string | Co | Observation duoc chon |
| `listed_price` | decimal(18,2) | Khong | Gia niem yet |
| `current_price` | decimal(18,2) | Co | Gia hien tai |
| `effective_unit_price` | decimal(18,4) | Khong | Gia/so don vi tieu chuan |
| `comparison_unit` | string | Khong | kg/l/cai |
| `discount_amount` | decimal(18,2) | Khong | So tien giam |
| `discount_percent` | decimal(7,4) | Khong | Ty le giam |
| `availability_status` | string | Khong | Ton kho |
| `is_on_promotion` | boolean | Co | Co KM |
| `observed_at` | timestamp | Co | Do moi |
| `run_status` | string | Co | Completeness cua run |
| `source_coverage` | decimal(7,4) | Khong | Ty le source thanh cong trong run |

Nhu cau: bang fact chinh cho trend va snapshot; khong query toan bo observations cho moi dashboard.

### 6.6. `gold.fact_promotion_snapshot_daily` - MVP

Grain: mot promotion-product-store con hieu luc/duoc quan sat trong ngay.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `promo_snapshot_id` | string | Co | Record key |
| `date_key` | int | Co | FK date |
| `promotion_id` | string | Co | FK Silver promotion |
| `retailer_key` | long | Co | FK retailer |
| `store_key` | long | Co | FK store |
| `product_key` | long | Khong | San pham dieu kien |
| `retailer_product_id` | string | Khong | Product source |
| `promotion_type` | string | Co | Loai promotion |
| `promotion_text` | string | Co | Text hien thi |
| `effective_unit_price` | decimal(18,4) | Khong | Neu tinh duoc |
| `saving_amount` | decimal(18,2) | Khong | Muc tiet kiem |
| `saving_percent` | decimal(7,4) | Khong | Ty le tiet kiem |
| `requires_bulk_purchase` | boolean | Co | Co phai mua nhieu |
| `member_only` | boolean | Co | Chi hoi vien |
| `starts_at` | timestamp | Khong | Hieu luc |
| `ends_at` | timestamp | Khong | Hieu luc |
| `observed_at` | timestamp | Co | Do moi |
| `run_status` | string | Co | Completeness cua run |
| `source_coverage` | decimal(7,4) | Khong | Ty le source thanh cong trong run |

Nhu cau: app hien thi dung promotion va BI dem chuong trinh theo loai.

### 6.7. `gold.fact_price_change` - Derived

Grain: mot price change event.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `price_change_id` | string | Co | Record key |
| `date_key` | int | Co | FK date |
| `retailer_key` | long | Co | FK retailer |
| `store_key` | long | Co | FK store |
| `product_key` | long | Khong | FK product |
| `retailer_product_id` | string | Co | Source product |
| `previous_price` | decimal(18,2) | Co | Gia cu |
| `current_price` | decimal(18,2) | Co | Gia moi |
| `change_amount` | decimal(18,2) | Co | Chenh lech |
| `change_percent` | decimal(9,4) | Khong | Ty le |
| `change_type` | string | Co | Loai thay doi |
| `changed_at` | timestamp | Co | Luc thay doi |
| `is_anomaly` | boolean | Co | Flag bat thuong |

Nhu cau: alert gia va phan tich tan suat thay doi.

### 6.8. `gold.mart_price_comparison` - MVP khi co tu hai retailer

Grain: mot canonical product/store/ngay, chi gom mapping dat threshold.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `comparison_id` | string | Co | Record key |
| `snapshot_date` | date | Co | Partition |
| `product_key` | long | Co | Canonical product |
| `retailer_key` | long | Co | Retailer |
| `store_key` | long | Co | Store |
| `region_code` | string | Khong | Khu vuc |
| `current_price` | decimal(18,2) | Co | Gia ban |
| `effective_unit_price` | decimal(18,4) | Khong | Gia quy doi |
| `comparison_unit` | string | Khong | Don vi |
| `discount_percent` | decimal(7,4) | Khong | Giam gia |
| `promotion_type` | string | Khong | Loai KM tot nhat |
| `requires_bulk_purchase` | boolean | Co | Dieu kien mua nhieu |
| `price_rank_in_region` | int | Khong | Xep hang |
| `retailer_count_compared` | int | Co | Coverage |
| `match_confidence` | decimal(5,4) | Co | Tin cay matching |
| `observed_at` | timestamp | Co | Do moi |
| `source_url` | string | Co | Truy nguyen |

Nhu cau: tra loi "cung san pham o dau re hon" ma van cong khai coverage, unit va confidence.

### 6.9. `gold.mart_best_deals` - Derived

Grain: mot deal duoc xep hang theo region/category/ngay.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `deal_id` | string | Co | Record key |
| `snapshot_date` | date | Co | Ngay |
| `region_code` | string | Co | Khu vuc |
| `category_id` | string | Khong | Category |
| `product_key` | long | Khong | Canonical product |
| `retailer_key` | long | Co | Retailer |
| `store_key` | long | Co | Store |
| `current_price` | decimal(18,2) | Co | Gia |
| `effective_unit_price` | decimal(18,4) | Khong | Gia hieu dung |
| `saving_percent` | decimal(7,4) | Khong | Tiet kiem |
| `deal_score` | decimal(9,4) | Co | Diem ranking |
| `deal_rank` | int | Co | Thu hang |
| `score_version` | string | Co | Cong thuc/model |
| `observed_at` | timestamp | Co | Do moi |

Nhu cau: trang "uu dai tot" va rule-based recommendation. Khong tao neu chua dinh nghia deal score.

### 6.10. `gold.mart_promotion_feed` - Derived

Grain: mot promotion card app co the hien thi.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `feed_item_id` | string | Co | Record key |
| `snapshot_date` | date | Co | Partition |
| `promotion_id` | string | Co | Promotion |
| `product_key` | long | Khong | Product |
| `retailer_key` | long | Co | Retailer |
| `store_key` | long | Co | Store |
| `title` | string | Co | Tieu de da chuan hoa |
| `promotion_text` | string | Co | Noi dung |
| `image_url` | string | Khong | Anh |
| `product_url` | string | Co | Link |
| `effective_unit_price` | decimal(18,4) | Khong | Gia hieu dung |
| `starts_at` | timestamp | Khong | Hieu luc |
| `ends_at` | timestamp | Khong | Hieu luc |
| `is_active` | boolean | Co | Con hieu luc |
| `freshness_status` | string | Co | `fresh`, `stale`, `unknown` |

Nhu cau: serving app/chatbot khong phai join nhieu bang Silver va khong lo promo het han.

### 6.11. `gold.mart_recommendation_features` - Later

Grain: mot user/product/context/as_of_time hoac product/region/as_of_date cho anonymous ranking.

| Field | Type | Required | Mo ta |
|---|---|---:|---|
| `feature_row_id` | string | Co | Record key |
| `as_of_timestamp` | timestamp | Co | Chot feature, chong leakage |
| `user_id` | string | Khong | Null cho anonymous |
| `product_key` | long | Co | Candidate |
| `region_code` | string | Co | Context |
| `current_price` | decimal(18,2) | Co | Feature |
| `price_rank` | int | Khong | Feature |
| `discount_percent` | decimal(7,4) | Khong | Feature |
| `deal_score` | decimal(9,4) | Khong | Feature |
| `price_percentile_30d` | decimal(7,4) | Khong | Feature lich su |
| `promotion_freshness_hours` | decimal(18,2) | Khong | Do moi |
| `availability_score` | decimal(7,4) | Khong | Ton kho |
| `user_affinity_score` | decimal(7,4) | Khong | Can user events |
| `feature_version` | string | Co | Reproducibility |

Nhu cau: training/serving recommendation. Chua co click, favorite, cart hoac purchase thi chi can
anonymous rule-based ranking tu `mart_best_deals`, khong can bang user feature.

## 7. Ma tran bang va nghiep vu

| Nhu cau | Bang bat buoc | Bang ho tro |
|---|---|---|
| Audit scraper, parse lai | Bronze `crawl_runs`, `raw_records`, `raw_payload_manifest` | `data_quality_results` |
| So sanh gia trong mot retailer/store | `retailer_products`, `product_observations`, `stores` | `fact_price_snapshot_daily` |
| So sanh cross-retailer | `canonical_products`, `product_identity_map`, `mart_price_comparison` | `product_identity_candidates`, match review |
| Mua X tang Y/combo/member price | `promotions`, `promotion_items` | `fact_promotion_snapshot_daily`, `promotion_feed` |
| Dashboard gia theo ngay | `fact_price_snapshot_daily`, dimensions | `fact_price_change` |
| Alert gia | `price_change_events` | `fact_price_change` |
| Tim uu dai gan user | Store latitude/longitude, `promotion_feed` | Redis/geospatial index |
| Recommendation anonymous | `mart_best_deals` | `recommendation_features` product-level |
| Recommendation ca nhan | User events + `recommendation_features` | Feast/MLflow |
| Chatbot so sanh gia | `mart_price_comparison`, `promotion_feed` | Guarded SQL/RAG |

## 8. Bang nao chua can trong MVP hien tai

- Chua can `product_identity_candidates` neu moi crawl WinMart mot store.
- Chua can `mart_price_comparison` den khi co it nhat hai retailer va product matching dat quality gate.
- Chua can `price_change_events` neu chua co tu hai snapshot theo thoi gian.
- Chua can `mart_recommendation_features` neu chua co ung dung/user events.
- Chua can NoSQL chi de luu JSON; Bronze Hudi da dam nhiem raw analytical history.
- Chua can Kafka/streaming cho scheduled web crawl. Airflow batch la du.

## 9. Tap bang MVP de trien khai truoc

Thu tu nho nhat nhung van dung nghiep vu:

1. PostgreSQL: `retailers`, `stores`, `crawl_sources`, `crawl_runs`, `crawl_task_runs`.
2. Bronze: `crawl_runs`, `raw_records`, `raw_payload_manifest`, `data_quality_results`.
3. Silver: `retailers`, `stores`, `categories`, `retailer_products`, `product_observations`,
   `promotions`, `promotion_items`, `quarantine_records`.
4. Khi them retailer thu hai: `canonical_products`, `product_identity_map`,
   `product_identity_candidates`, `product_match_reviews`.
5. Gold: `dim_date`, `dim_retailer`, `dim_store`, `fact_price_snapshot_daily`,
   `fact_promotion_snapshot_daily`; sau do moi them cac mart.

Tap nay dap ung crawl co audit, luu lich su, promo mechanics va BI co ban ma khong bat dau bang
recommendation, vector database hay streaming khi chua co nhu cau.
