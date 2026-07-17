# Kiến trúc kỹ thuật Pricebot hiện tại

Tài liệu này mô tả mã nguồn đang có trong repository: trách nhiệm của từng file backend, quan hệ giữa các module, schema phục vụ, luồng đồng bộ MinIO/Hudi, cách frontend hoạt động và toàn bộ vòng đời một câu hỏi chatbot.

> Phạm vi: mã nguồn hiện tại trong `backend/app/`, `backend/tests/` và các file liên quan trong `frontend/app/`. Đây là mô tả “as-is”, không phải kiến trúc mục tiêu trong tương lai.

## 1. Tóm tắt hệ thống

Pricebot có ba lớp chính:

1. **Lớp dữ liệu**: Data Engineering publish các bảng Gold Hudi lên MinIO. Backend dùng Spark đọc snapshot Hudi, chuẩn hóa và ghi sang PostgreSQL.
2. **Lớp ứng dụng**: FastAPI cung cấp API khám phá ưu đãi, tìm kiếm, so sánh, tối ưu giỏ hàng, chatbot SSE và đồng bộ dữ liệu.
3. **Lớp giao diện**: Next.js hiển thị trang ưu đãi, chi tiết sản phẩm, giỏ hàng và chatbot. Giỏ hàng được lưu tại trình duyệt.

```text
MinIO / Gold Hudi
        │
        │ Spark + Hudi
        ▼
backend/app/sync.py
        │
        │ chuẩn hóa + thay snapshot serving
        ▼
PostgreSQL
  ├─ offers_current, offer_price_history và các dimension/promotion
  ├─ offer_search_embeddings_current
  ├─ conversations/messages
  └─ sync_runs
        │
        ▼
backend/app/repository.py
        │
        ├───────────────┐
        ▼               ▼
FastAPI REST        Chat SSE
        │               │
        └───────┬───────┘
                ▼
        Next.js frontend
  trang ưu đãi + popup chatbot trực tiếp + giỏ hàng local
```

Điểm cần hiểu đúng về chatbot hiện tại:

- Ollama **không sinh SQL** và **không trực tiếp viết câu trả lời cuối**.
- Ollama được dùng để hỗ trợ tách tên sản phẩm/thương hiệu/retailer từ câu hỏi và tạo embedding.
- Bộ lọc quan trọng như giá, phần trăm giảm, đơn vị, chất lượng dữ liệu và thao tác giỏ hàng được parse bằng rule cục bộ.
- `main.py` tạo lời tư vấn theo rule từ facts đã truy vấn: lựa chọn giá tốt, chênh lệch với lựa chọn kế tiếp, đơn giá, cảnh báo chất lượng và biến động giá lịch sử cùng nhà bán lẻ.
- Khi người dùng nêu quy cách (ví dụ `1L`), backend bắt buộc đối chiếu `package_total_base_quantity`; kết quả gần đúng như `80ml` không được dùng làm khuyến nghị.
- Câu trả lời cuối là template của backend dựa trên dữ liệu truy vấn được từ PostgreSQL.
- Nếu Ollama hoặc embedding lỗi, tìm kiếm lexical và phần lớn chức năng vẫn tiếp tục hoạt động.

## 2. Sơ đồ phụ thuộc giữa các module backend

```text
config.py
  ├─> database.py
  ├─> intent.py
  ├─> search_index.py
  └─> sync.py

database.py
  ├─> main.py
  ├─> repository.py
  ├─> search_index.py
  └─> sync.py

matching.py
  ├─> intent.py          (normalize_text)
  ├─> repository.py      (normalize_text)
  └─> sync.py            (signature)

search_index.py
  ├─> repository.py      (semantic_scores, import lười)
  └─> sync.py            (refresh_embeddings)

repository.py
  └─> main.py            (toàn bộ truy vấn nghiệp vụ)

sync.py
  └─> main.py            (run_sync)

main.py
  └─> là composition root: khởi tạo FastAPI, nối tất cả module và public API
```

## 3. Chi tiết từng file backend

### 3.1. `backend/app/__init__.py`

File đánh dấu `app` là Python package. Hiện không có logic runtime.

### 3.2. `backend/app/config.py`

Trách nhiệm: ánh xạ biến môi trường thành một object cấu hình dùng chung.

| Thành phần | Chức năng |
|---|---|
| `Settings` | Pydantic settings model; đọc `.env`, bỏ qua biến dư. |
| `database_url` | Chuỗi kết nối PostgreSQL qua psycopg. |
| Nhóm `minio_*` | Endpoint, access key, secret, bucket và prefix MinIO. |
| `ollama_base_url`, `ollama_model` | Ollama dùng cho intent extraction. |
| `embedding_model`, `embedding_batch_size`, `embedding_timeout_seconds`, `embedding_sync_limit` | Điều khiển quá trình tạo semantic index. |
| `cors_origins` / `origins` | Chuỗi origin từ môi trường và property chuyển thành danh sách cho FastAPI CORS. |
| `hudi_packages` | Maven coordinates cho Hudi Spark bundle và Hadoop AWS. |
| `get_settings()` | Tạo `Settings` một lần nhờ `lru_cache`; các module dùng cùng cấu hình trong một process. |

Quan hệ:

- `database.py` lấy `database_url` khi module được import để tạo SQLAlchemy engine.
- `main.py` lấy settings toàn cục để cấu hình CORS, Ollama, tìm kiếm và sync.
- `sync.py` nhận `Settings` để tạo MinIO client và Spark session.
- `search_index.py` nhận `Settings` để gọi Ollama embedding.

### 3.3. `backend/app/database.py`

Trách nhiệm: tạo SQLAlchemy engine và khởi tạo schema PostgreSQL.

#### Thành phần chính

- `engine`: engine dùng chung, bật `pool_pre_ping=True` để phát hiện connection chết trước khi sử dụng.
- `DDL`: chuỗi SQL tạo extension, bảng, cột bổ sung và index.
- `init_db()`: tách `DDL` theo dấu `;`, chạy từng statement trong một transaction.

`main.py` gọi `init_db()` trong FastAPI lifespan, vì vậy schema được kiểm tra mỗi lần backend khởi động.

#### Extension và index tìm kiếm

- `pg_trgm`: cung cấp `similarity` và `word_similarity` cho tìm kiếm gần đúng.
- `unaccent`: đã được tạo nhưng truy vấn hiện tại chủ yếu dựa trên cột được normalize trong Python.
- GIN trigram index trên `normalized_name` và `normalized_brand`.
- Full-text GIN index trên tên, thương hiệu và category.
- B-tree index theo retailer/price, canonical product, unit price và data quality.

#### Lưu ý hiện trạng

- Dự án chưa dùng migration framework như Alembic; DDL khởi động đang đóng vai trò migration đơn giản.
- DDL hiện có lệnh xóa `auth_sessions`, `users` và cột `conversations.user_id`. Nghĩa là phiên bản đang chạy là chat ẩn danh, không có user ownership.
- Thay đổi schema phức tạp nên được chuyển sang migration có version để dễ rollback và audit.

### 3.4. `backend/app/matching.py`

Trách nhiệm: chuẩn hóa text và xây “chữ ký sản phẩm” từ tên/thương hiệu/quy cách.

| Hàm/lớp | Chức năng |
|---|---|
| `ProductSignature` | Dataclass bất biến gồm tên chuẩn hóa, brand, lượng, đơn vị và số gói. |
| `normalize_text()` | Bỏ dấu tiếng Việt, chuyển thường, thay ký tự đặc biệt bằng khoảng trắng. |
| `extract_package()` | Đọc quy cách như `2L`, `1000ml`, `6 x 180ml`; đổi kg → g và lít → ml. |
| `signature()` | Kết hợp normalize text, brand và package thành `ProductSignature`. |
| `match_confidence()` | Tính điểm dựa trên độ giống tên, brand và package; trả 0 nếu brand/quy cách xung đột. |
| `is_reliable_match()` | Coi hai signature đáng tin nếu điểm từ `0.78` trở lên. |

Trong production hiện tại:

- `sync.prepare_offers()` dùng `signature()` để tạo `normalized_name`, `normalized_brand` và các trường package serving.
- `intent.py` và `repository.py` dùng `normalize_text()`.
- So sánh chính xác giữa các retailer trong `repository.compare_offers()` **không dùng heuristic này làm bằng chứng cuối**; nó chỉ tin canonical mapping từ Gold. Đây là lựa chọn an toàn để không tuyên bố nhầm hai SKU là cùng sản phẩm.

### 3.5. `backend/app/intent.py`

Trách nhiệm: chuyển câu hỏi tự nhiên thành `Intent` có cấu trúc.

#### Mô hình `Intent`

`Intent` chứa:

- `name`: `product_search`, `compare_prices`, `deals`, `clarification` hoặc `basket`.
- `query`: cụm từ sản phẩm đã làm sạch.
- `retailers`: danh sách retailer ID được nhắc rõ.
- bộ lọc: brand, giá min/max, giảm tối thiểu, đơn vị so sánh, quality.
- `sort`, `promotion_only`.
- `basket_action`: `none`, `add`, `view`, `optimize`.
- thông tin clarification.

Hai method quan trọng:

- `filters()`: tạo dictionary bộ lọc đưa xuống repository.
- `context_payload()`: tạo state nhỏ, an toàn để lưu cùng assistant message cho câu hỏi nối tiếp.

#### Nhóm parser deterministic

| Hàm | Chức năng |
|---|---|
| `_retailers_in()` | Map alias như `BHX`, `Lotte`, `MM` sang retailer ID. |
| `_tokens()` / `clean_query()` | Loại từ giao tiếp, từ mô tả yêu cầu và retailer khỏi product query. |
| `_money_mentions()` / `_price_bounds()` | Parse `dưới 150k`, `từ 50k đến 100k`, `trên 20.000đ`. |
| `_package()` | Parse package đơn giản như `1kg`, `500ml`, `2 lít`. |
| `_unit_filter()` | Nhận biết yêu cầu giá theo g/ml/cái và bật `unit_price_only`. |
| `_data_quality()` | Nhận biết yêu cầu `valid` hoặc `warning`. |
| `_discount_threshold()` | Parse giảm tối thiểu theo phần trăm. |
| `_basket_action()` | Nhận biết yêu cầu xem/thêm/tối ưu giỏ hàng. |
| `infer_name()` | Xác định loại intent bằng rule. |
| `fallback_intent()` | Tạo intent hoàn chỉnh mà không cần Ollama. |

#### Vai trò của Ollama trong `parse_intent()`

1. Backend luôn tạo `deterministic = fallback_intent(message)` trước.
2. Gửi prompt đến `POST /api/generate` của Ollama, yêu cầu JSON cố định.
3. Nếu JSON lỗi, gọi Ollama thêm một lần để sửa JSON.
4. Nếu vẫn lỗi, dùng hoàn toàn deterministic intent.
5. Product query do model trả về chỉ được chấp nhận nếu có token giao với query deterministic; điều này chặn hallucination đổi sang sản phẩm không liên quan.
6. Rule deterministic thắng khi model phân loại intent khác.

Như vậy Ollama chỉ làm sạch/tăng chất lượng extraction; quyền quyết định nghiệp vụ vẫn nằm ở rule.

#### Context hội thoại

`apply_conversation_context()` dùng `context` trong assistant payload gần nhất, không gửi toàn bộ lịch sử sang LLM. Ví dụ:

```text
User: So sánh dầu ăn Neptune 2L ở GO
Bot lưu context: query=dau an neptune 2l, retailer=go

User: Còn Lotte thì sao?
→ dùng lại query trước, thay retailer thành lottemart

User: Chỉ lấy loại 1kg
→ dùng query trước, thay package 2l bằng 1kg
```

### 3.6. `backend/app/search_index.py`

Trách nhiệm: semantic index nhẹ bằng Ollama embeddings + NumPy, không yêu cầu pgvector.

| Hàm | Chức năng |
|---|---|
| `offer_search_text()` | Ghép tên, canonical name, brand, category, measurement và unit thành document embedding. |
| `content_hash()` | SHA-256 để biết nội dung offer có thay đổi hay không. |
| `_embed()` | Gọi `POST /api/embed` của Ollama theo batch. |
| `invalidate_cache()` | Xóa cache vector và query score trong process. |
| `_cache_marker()` | Dùng số record + `max(updated_at)` để nhận biết index DB đã thay đổi. |
| `_load_cache()` | Đọc mảng `real[]` từ PostgreSQL, chuyển thành ma trận NumPy và normalize vector. |
| `semantic_scores()` | Embed query, tính cosine similarity với toàn bộ offer; lỗi nào cũng trả `{}` để fallback lexical. |
| `refresh_embeddings()` | Incremental upsert embedding cho offer mới/đổi, xóa embedding của offer không còn tồn tại. |

Index được lưu trong `offer_search_embeddings_current`; NumPy matrix chỉ là cache trong RAM của từng backend process.

`repository._semantic_rerank()` trộn thứ hạng lexical và semantic bằng reciprocal-rank fusion. Semantic search chỉ rerank candidate đã qua lexical search, không tự ý đưa sản phẩm ngoài candidate pool vào kết quả.

### 3.7. `backend/app/repository.py`

Đây là data access/business query layer lớn nhất. File này chứa truy vấn hội thoại, tìm kiếm, ưu đãi, insight, so sánh và giỏ hàng.

#### Hội thoại

| Hàm | Chức năng |
|---|---|
| `save_conversation()` | Tạo conversation UUID nếu chat mới, hoặc kiểm tra UUID tồn tại; lưu user message. |
| `save_assistant()` | Lưu assistant message và payload JSON. |
| `conversation_context()` | Đọc `context` từ assistant payload gần nhất. |

Conversation hiện không gắn user. UUID đóng vai trò định danh để tiếp tục hội thoại, không phải cơ chế xác thực.

#### Tìm kiếm và duyệt ưu đãi

| Thành phần | Chức năng |
|---|---|
| `CURRENT_OFFER_FILTER` | Chỉ lấy giá hiện tại hợp lệ về trạng thái run. |
| `PROMOTION_FILTER` | Xác định offer có giảm giá, promo mechanic, promotion flag hoặc promotion item. |
| `PROMOTION_LATERAL` | Gom promotion text/type/date liên quan vào từng offer. |
| `_add_common_offer_filters()` | Ghép query parameterized cho retailer, query, brand, giá, discount, unit và quality. |
| `_promotion_type_filter()` | Lọc `discount`, `mechanic`, `flag`. |
| `search_offers()` | Tìm strict theo tất cả token; nếu rỗng thì relaxed multi-token; sau đó optional semantic rerank. |
| `browse_deals()` | Phân trang ưu đãi, sort và filter cho marketplace. |
| `autocomplete_offers()` | Gợi ý sản phẩm/brand, ưu tiên quality và loại trùng. |

Lexical score kết hợp:

- số token khớp;
- trigram `similarity`;
- `word_similarity`;
- full-text `ts_rank_cd`;
- data quality;
- giá/sort được yêu cầu.

#### Insight và so sánh

| Hàm | Chức năng |
|---|---|
| `_current_offer()` | Lấy một offer hiện tại kèm promotion. |
| `_with_price_deltas()` | Tính chênh lệch tiền và phần trăm so với giá thấp nhất. |
| `offer_insights()` | Tách rõ `same_product_offers` và `similar_offers`. |
| `price_history()` | Trả daily snapshot retained theo canonical product hoặc retailer product khi chưa map canonical. |
| `seeded_offers()` | Từ một card/price snapshot, lấy các offer cùng canonical ID để handoff sang chat. |
| `compare_offers()` | Chọn canonical group có nhiều retailer nhất làm nhóm so sánh chính xác. |

Quy tắc quan trọng:

- `same_product_offers`: bắt buộc cùng `canonical_product_id`, confidence = 1.0.
- `similar_offers`: chỉ là lựa chọn gần giống; không được gắn confidence chính xác.
- Nếu không có canonical group phủ ít nhất hai retailer, chatbot không khẳng định có so sánh chính xác.
- `price_history()`: chỉ gộp nhiều retailer khi có `canonical_product_id`; offer chưa map chỉ trả history của retailer product đó.

#### Tối ưu giỏ hàng

| Hàm | Chức năng |
|---|---|
| `_offers_for_snapshot_ids()` | Nạp các item người dùng đã chọn. |
| `_canonical_candidates()` | Nạp mọi offer cùng canonical ID. |
| `_best_candidate()` | Chọn giá tốt trong một retailer, ưu tiên bản ghi `valid`. |
| `_cheapest_candidate()` | Chọn giá tuyệt đối thấp nhất cho split plan; quality chỉ tie-break. |
| `_offer_line()` | Chuẩn hóa một dòng kết quả giỏ hàng. |
| `optimize_basket()` | Tạo phương án một retailer và phương án chia đơn rẻ nhất. |

`optimize_basket()` trả về:

- giá và dòng sản phẩm người dùng đang chọn;
- `single_retailer_options`: chỉ tạo khi mọi item có canonical mapping và cùng có mặt tại retailer đó;
- `split_order`: mỗi item chọn offer canonical rẻ nhất trên toàn hệ thống;
- `unavailable_items`: offer đã biến mất hoặc chưa có canonical mapping;
- cảnh báo nếu phương án dùng dữ liệu quality `warning`.

#### Theo dõi sync

- `latest_sync()` trả lần sync gần nhất từ `sync_runs` cho health endpoint.

#### Lưu ý kỹ thuật trong file

`search_offers()` và `browse_deals()` dùng chung các helper lọc, ranking và promotion để kết quả của marketplace và chatbot nhất quán.

### 3.8. `backend/app/sync.py`

Trách nhiệm: đọc Gold Hudi từ MinIO, thay snapshot serving hiện tại và upsert lịch sử giá theo ngày trong PostgreSQL.

#### Nguồn dữ liệu

Global tables:

- `gold/dim_date_hudi`
- `gold/dim_product_hudi`
- `gold/dim_retailer_hudi`
- `gold/dim_store_hudi`
- `gold/dim_retailer_product_hudi`

Store-scoped tables cho từng retailer:

- `gold/fact_price_snapshot_daily_hudi/store={retailer}`
- `gold/dim_promotion_hudi/store={retailer}`
- `gold/fact_promotion_item_hudi/store={retailer}`

#### Nhóm hàm

| Hàm | Chức năng |
|---|---|
| `minio_client()` | Tạo boto3 S3 client dùng path-style addressing. |
| `latest_successful_run()` | Quét `pipeline_runs/.../manifest.json`, chọn run success mới nhất. |
| `latest_manifests()` | Compatibility alias trả manifest theo retailer hoàn tất. |
| `build_spark()` | Tạo local Spark session, cấu hình Hudi và S3A/MinIO. |
| `read_hudi_rows()` | Đọc Hudi table và chuyển Spark Row thành Python dict. |
| `row_version()` / `latest_rows()` | Chọn phiên bản mới nhất theo source run, observed time, built time và Hudi commit. |
| `latest_source_run_rows()` | Chỉ giữ source run ID lớn nhất trong một table read. |
| `prepare_offers()` | Join fact giá với retailer product/canonical product; ở chế độ history giữ từng `price_snapshot_id`. |
| `table_rows()` / `insert_rows()` / `upsert_rows()` | Deduplicate, bulk insert và upsert idempotent theo khóa. |
| `replace_serving_data()` | Thay dữ liệu current/dimension và upsert `offer_price_history` trong một transaction. |
| `update_sync_progress()` | Ghi stage, percent và message vào `sync_runs.details`. |
| `run_sync()` | Orchestrate toàn bộ pipeline sync và cập nhật trạng thái cuối. |

#### Luồng `run_sync()`

```text
1. Ghi stage=manifest
2. Tìm manifest success mới nhất
3. Lấy retailers_completed
4. Khởi tạo Spark
5. Đọc 5 global Hudi tables
6. Với từng retailer:
   ├─ đọc price snapshots
   ├─ prepare_offers(history=True) → upsert toàn bộ daily snapshot
   ├─ latest_source_run_rows() + prepare_offers() → offers_current
   ├─ đọc promotions
   └─ đọc promotion items
7. Dừng Spark trong finally
8. replace_serving_data() vào PostgreSQL
9. refresh_embeddings() với giới hạn cấu hình
10. Ghi status success hoặc partial + thống kê
```

Nếu embedding lỗi, sync serving data vẫn hoàn tất và `search_index.status` được đánh dấu `degraded`. Nếu một số bảng/retailer lỗi, trạng thái cuối là `partial`; nếu không đọc được product dimensions bắt buộc hoặc không có retailer price nào, sync thất bại.

### 3.9. `backend/app/main.py`

Đây là composition root và API layer.

#### Khởi tạo ứng dụng

- `lifespan()` gọi `init_db()` trước khi nhận request.
- `FastAPI(title="Pricebot API")` tạo app và Swagger mặc định.
- CORS lấy origin từ `settings.origins`.
- Pydantic models validate chat request và giỏ hàng; số lượng hợp lệ từ 1 đến 99, tối đa 50 dòng.

#### Helper

| Hàm | Chức năng |
|---|---|
| `event()` | Serialize một SSE event theo format `event:` + `data:`. |
| `snapshot_context()` | Thu ngày snapshot từ offer để đưa vào câu trả lời. |
| `_filter_chat_offers()` | Lớp bảo vệ cuối, áp lại filter intent lên result/seed result. |
| `_search_for_intent()` | Gọi repository search mới; fallback signature cũ khi test double/legacy không nhận keyword args. |
| `_browse_for_intent()` | Browse deal rộng khi intent không có query. |
| `_offer_ids()` | Lưu tối đa 10 offer ID vào context cho follow-up/basket. |

#### Endpoint

| Method | Path | Hàm | Chức năng |
|---|---|---|---|
| GET | `/api/health` | `health()` | Kiểm tra DB, Ollama và latest sync. |
| GET | `/api/deals` | `deals()` | Danh sách deal có phân trang, filter, sort. |
| GET | `/api/deals/overview` | `deals_overview()` | Lấy tối đa 15 offer cho từng retailer. |
| GET | `/api/deals/autocomplete` | `deals_autocomplete()` | Gợi ý tìm kiếm. |
| GET | `/api/deals/{id}/insights` | `deal_insights()` | Chi tiết, exact comparison và similar alternatives. |
| GET | `/api/deals/{id}/history?days=90` | `deal_price_history()` | Daily history cho chart, trend và các chức năng time series. |
| POST | `/api/basket/optimize` | `basket_optimize()` | Tối ưu giỏ hàng bằng canonical mapping. |
| POST | `/api/chat/stream` | `chat()` | Chatbot SSE. |
| POST | `/api/admin/sync` | `start_sync()` | Tạo sync run và chạy background worker. |
| GET | `/api/admin/sync/{run_id}` | `sync_status()` | Trả trạng thái/progress sync. |

`start_sync()` dùng PostgreSQL advisory transaction lock và unique partial index để chỉ cho một run có status `running` tại một thời điểm.

## 4. Schema PostgreSQL và quan hệ dữ liệu

### 4.1. Nhóm serving

| Bảng | Khóa chính | Vai trò |
|---|---|---|
| `offers_current` | `price_snapshot_id` | Snapshot giá hiện tại đã denormalize để tìm kiếm nhanh. |
| `offer_price_history` | `price_snapshot_id` | Lịch sử daily snapshot được upsert từ Gold Hudi; dùng cho trend, alert và time series. |
| `products_current` | `canonical_product_id` | Sản phẩm canonical từ Gold. |
| `retailer_products_current` | `retailer_product_key` | Sản phẩm theo retailer và mapping sang canonical. |
| `retailers_current` | `retailer_id` | Dimension nhà bán lẻ. |
| `stores_current` | `store_key` | Dimension cửa hàng/store group/region. |
| `date_dimension_current` | `date_key` | Dimension ngày. |
| `promotions_current` | `promotion_key` | Nội dung và thời gian chương trình khuyến mãi. |
| `promotion_items_current` | `promotion_item_fact_id` | Liên kết promotion với sản phẩm retailer và mức giá. |

Quan hệ logic quan trọng:

```text
products_current.canonical_product_id
       ▲
       ├── retailer_products_current.canonical_product_id
       ├── offers_current.canonical_product_id
       └── offer_price_history.canonical_product_id

offers_current.retailer_product_key
       │
       ├── retailer_products_current.retailer_product_key
       ├── offer_price_history.retailer_product_key
       └── promotion_items_current.retailer_product_key
                    │
                    └── promotions_current.promotion_key
```

Không phải mọi quan hệ đều có foreign key vật lý; repository join bằng business key để giữ quá trình replace snapshot đơn giản.

### 4.2. Nhóm semantic search

`offer_search_embeddings_current` lưu một vector `real[]` cho mỗi `price_snapshot_id`, kèm model, content hash, search text và thời điểm cập nhật.

### 4.3. Nhóm chat

- `conversations`: UUID, title lấy từ 80 ký tự đầu của câu hỏi đầu tiên, created/updated time.
- `messages`: user/assistant message, payload JSON và foreign key cascade tới conversation.

Context hội thoại nằm trong `messages.payload.context`, không có bảng context riêng.

### 4.4. Nhóm vận hành

`sync_runs` lưu trạng thái `running`, `success`, `partial` hoặc `failed`; `details` chứa progress và thống kê JSON.

## 5. Luồng hoạt động của chatbot

### 5.1. Từ frontend đến SSE

```text
User nhập câu hỏi
  │
  ▼
frontend/app/chat-panel.tsx -> send()
  │ POST /api/chat/stream
  │ {message, conversation_id?, seed_price_snapshot_id?}
  ▼
main.chat()
  ├─ save_conversation()
  ├─ event: conversation
  ├─ conversation_context()
  ├─ parse_intent()
  ├─ apply_conversation_context()
  ├─ search/browse/seeded_offers() + filter quy cách bắt buộc
  ├─ compare/sort
  ├─ tạo khuyến nghị có căn cứ + đọc history 7 ngày của retailer được chọn
  ├─ save_assistant()
  ├─ event: answer
  ├─ event: results
  └─ event: done
  │
  ▼
Frontend đọc ReadableStream, parse từng block SSE và render OfferCards
```

### 5.2. Nhánh theo intent

#### `clarification`

Backend không query sản phẩm; trả câu hỏi làm rõ, lưu context và kết thúc stream.

#### `basket`

Backend không giữ giỏ hàng thật. Nó chỉ trả action:

- `add`: nếu context trước chỉ có một offer, gợi ý ID để client thêm.
- `view`: yêu cầu client mở drawer giỏ hàng.
- `optimize`: yêu cầu client mở drawer và gọi API optimize.

#### `product_search`

Tìm offer theo query/filter, fallback query deterministic nếu model query không có kết quả, sau đó sort giá tăng dần.

#### `deals`

Nếu có query thì search promotion-only; nếu không có query thì browse deal rộng. Kết quả ưu tiên discount percent.

#### `compare_prices`

`compare_offers()` tìm canonical group phủ từ hai retailer trở lên:

- có group: trả exact results, sort giá tăng dần;
- không có group nhưng có candidate: trả near matches với cảnh báo chưa đủ bằng chứng;
- không có candidate: trả thông báo chưa tìm thấy.

### 5.3. SSE events

| Event | Payload chính | Ý nghĩa |
|---|---|---|
| `conversation` | `conversation_id` | Frontend giữ UUID cho câu hỏi tiếp theo. |
| `answer` | `content` | Lời tư vấn quyết định mua theo facts đã xác minh; không sinh giá hoặc điều kiện ngoài dữ liệu. |
| `results` | offers, filters, context, near/exact matches | Dữ liệu có cấu trúc để render UI. |
| `done` | `{}` | Đánh dấu stream hoàn tất. |

Frontend hiện chỉ thêm assistant message sau khi đọc xong stream; nội dung `answer` không được stream từng token.

## 6. Luồng tìm kiếm hiện tại

```text
Câu hỏi
  │
  ├─ deterministic intent/filter
  └─ Ollama extraction có kiểm chứng
          │
          ▼
query tokens + filters
          │
          ▼
PostgreSQL lexical candidate pool
  ├─ LIKE trên normalized name/brand
  ├─ pg_trgm similarity
  ├─ full-text rank
  └─ quality + price/sort
          │
          ▼
optional semantic_scores()
          │
          ▼
reciprocal-rank fusion
          │
          ▼
top N offers
```

Fallback:

- Strict token matching không có kết quả → yêu cầu khớp tối thiểu 1 hoặc 2 token.
- Ollama intent lỗi → deterministic parser.
- Semantic index/Ollama embedding lỗi → giữ nguyên lexical ranking.
- Model query không có kết quả → thử lại `clean_query()` từ câu người dùng.

## 7. Cách web frontend hoạt động

### 7.1. Route hiện tại

| Route | Component | Chức năng |
|---|---|---|
| `/` | `app/page.tsx` | Redirect server-side đến `/deals`. |
| `/deals` | `app/deals/page.tsx` | Trang marketplace chính, chứa popup chatbot. |

### 7.2. `frontend/app/deals-client.tsx`

Đây là component marketplace chính.

Chức năng:

- gọi `/api/deals/overview` để lấy section theo retailer;
- autocomplete có debounce 220 ms;
- quick filter và advanced filter;
- gọi `/api/deals` để “xem thêm” từng retailer;
- mở drawer insight và gọi `/api/deals/{id}/insights`;
- quản lý drawer giỏ hàng và gọi `/api/basket/optimize`;
- bắt đầu sync, poll mỗi 1.2 giây và reload overview khi thành công;
- render `ChatPanel` trực tiếp trong popup;
- nhận callback trực tiếp từ chatbot để mở hoặc tối ưu giỏ hàng.

Các state `filters` và `appliedFilters` được tách riêng: người dùng có thể chỉnh form mà chỉ reload khi submit/apply.

### 7.3. `frontend/app/chat-panel.tsx`

`ChatPanel` là UI chatbot được render trực tiếp bên trong popup của `DealsClient`, không có route hoặc iframe riêng. Component này:

- giữ message list trong React state;
- giữ `conversationId` trong memory;
- gọi `/api/chat/stream` và tự parse SSE bằng `ReadableStream`;
- render offer dạng grid hoặc table;
- hỗ trợ thêm offer vào giỏ hàng;
- hiển thị câu hỏi gợi ý để bắt đầu tìm giá, ưu đãi hoặc lọc theo ngân sách;
- nhận `resetKey` để tạo chat mới;
- gọi callback `onOpenBasket()` để mở hoặc tối ưu giỏ hàng.

Hiện conversation ID không được persist sau refresh. `startNew()` cũng reset ID và message state. Database vẫn lưu message cũ, nhưng frontend chưa có API/UI tải danh sách lịch sử chat.

### 7.4. `frontend/app/basket.ts`

Giỏ hàng là client-side state dùng key `pricely_basket_v1` trong `localStorage`.

| Hàm | Chức năng |
|---|---|
| `getBasket()` | Đọc, parse và sanitize dữ liệu local. |
| `setBasket()` | Ghi localStorage và phát custom event. |
| `addBasketItem()` | Thêm item hoặc tăng quantity nếu đã tồn tại. |
| `removeBasketItem()` | Xóa theo snapshot ID. |
| `updateBasketQuantity()` | Tăng/giảm; quantity 0 sẽ xóa item. |
| `clearBasket()` | Xóa toàn bộ. |
| `subscribeBasket()` | Nghe custom event trong tab và storage event giữa các tab. |

### 7.5. Giao tiếp trực tiếp giữa deals page và chatbot

```text
DealsClient
  ├─ resetKey ────────────────> ChatPanel tạo chat mới
  ├─ onOpenBasket(optimize) <── ChatPanel yêu cầu mở/tối ưu giỏ hàng
  └─ subscribeBasket() <────── basket.ts phát event sau khi thêm sản phẩm
```

Không còn `iframe`, `postMessage` hoặc route `/chat`. Backend vẫn hỗ trợ `seed_price_snapshot_id` cho API integration trong tương lai, nhưng giao diện hiện tại không phát handoff card-specific.

### 7.6. Các file frontend còn lại

| File | Vai trò |
|---|---|
| `app/page.tsx` | Redirect route gốc sang `/deals`. |
| `app/layout.tsx` | Root HTML layout, metadata và import CSS chung. |
| `app/deals/page.tsx` | Route wrapper cho marketplace. |
| `app/globals.css` | Toàn bộ style chính cho deals, chat, drawer và responsive. |

## 8. Luồng đồng bộ từ giao diện

```text
User bấm “Cập nhật dữ liệu”
  │
  ▼
POST /api/admin/sync
  ├─ advisory lock
  ├─ kiểm tra sync đang running
  ├─ INSERT sync_runs(status=running)
  └─ BackgroundTasks.add_task(worker)
  │
  ▼
Frontend poll GET /api/admin/sync/{run_id} mỗi 1200 ms
  │
  ├─ hiển thị details.progress
  └─ khi success: deals page gọi lại /api/deals/overview
```

Endpoint mang prefix `admin`, nhưng code hiện tại không có dependency/middleware xác thực hoặc kiểm tra role. Trong môi trường public, cần bảo vệ endpoint này trước khi expose internet.

## 9. Kiểm thử backend

| File test | Phạm vi |
|---|---|
| `test_api.py` | SSE trả dữ liệu thật, overview theo retailer, seeded chat và chặn khuyến nghị sai quy cách (ví dụ 1L/80ml). |
| `test_discovery_api.py` | Extended filters, autocomplete, insights, history endpoint và validation giỏ hàng. |
| `test_intent.py` | Intent, query cleanup, model repair, hallucination guard, filter và follow-up context. |
| `test_matching.py` | Normalize tiếng Việt, package conversion, confidence và canonical comparison. |
| `test_search_index.py` | Nội dung document embedding và hash ổn định. |
| `test_sync.py` | Chọn manifest success mới nhất, Hudi path, source run mới nhất và giữ daily history. |
| `test_basket_optimizer.py` | Split plan không thay offer rẻ hơn bằng offer `valid` đắt hơn. |
| `test_conversation_repository.py` | Tiếp tục conversation bằng UUID. |

Chạy test:

```powershell
pytest backend/tests
```

Test hiện chủ yếu là unit/API test có monkeypatch. Chưa có integration test đầy đủ với PostgreSQL + MinIO + Spark + Ollama thật.

## 10. Tính chịu lỗi và giới hạn hiện tại

### Cơ chế chịu lỗi đã có

- PostgreSQL connection dùng `pool_pre_ping`.
- Intent có deterministic fallback khi Ollama lỗi.
- JSON model lỗi được thử repair một lần.
- Model output bị kiểm tra token để giảm hallucination.
- Semantic search là optional enrichment; lexical search luôn là nguồn fallback.
- Sync dừng Spark trong `finally`.
- Sync lưu progress và có trạng thái `partial`.
- Chỉ một sync `running` được phép tại một thời điểm.
- So sánh exact chỉ dùng canonical mapping.
- Chatbot và giỏ hàng giao tiếp qua callback/component state, không qua iframe message.

### Giới hạn/cần lưu ý

1. `/api/admin/sync` chưa được xác thực dù mang tên admin.
2. Chat hiện ẩn danh; không có user/session ownership.
3. Conversation history được lưu DB nhưng không có API/UI để tải lại.
4. Conversation ID chỉ nằm trong React memory, mất khi refresh.
5. Giỏ hàng chỉ nằm trong localStorage, không đồng bộ theo tài khoản.
6. Lời tư vấn hiện là rule/template dựa trên facts, chưa cá nhân hóa theo hồ sơ, lịch sử mua hoặc sở thích người dùng.
7. Schema dùng startup DDL, chưa có migration versioning.
8. Semantic matrix được nạp toàn bộ vào RAM; phù hợp vài nghìn offer nhưng cần thiết kế khác nếu dữ liệu tăng lớn.
9. `latest_source_run_rows()` chọn `max(source_run_id)` theo chuỗi, nên format run ID phải giữ khả năng sắp xếp thời gian.
10. `offers_current` vẫn dùng delete + insert snapshot, còn `offer_price_history` dùng upsert; transaction giúp nhất quán nhưng thời gian ghi sẽ tăng theo số ngày lịch sử.
11. Frontend CSS và các component lớn đang tập trung trong vài file dài, khó tách test và bảo trì.

## 11. Hướng dẫn lần theo code khi sửa tính năng

### Thêm bộ lọc mới

```text
frontend DealFilters + requestParams
  -> main.py Query parameter
  -> repository._add_common_offer_filters
  -> nếu dùng trong chat: Intent + fallback_intent + Intent.filters
  -> test_intent.py + test_discovery_api.py
```

### Thêm field dữ liệu Gold mới

```text
sync.py prepare_offers/table specs
  -> database.py DDL/ALTER
  -> repository SELECT/output
  -> frontend Offer type + UI
  -> test sync/repository/API
```

### Đổi logic chatbot

```text
intent.py               phân loại và filter
main.py chat()          orchestration + SSE + khuyến nghị có căn cứ
repository.py           dữ liệu, ranking và price history
frontend chat-panel.tsx parse/render kết quả + câu hỏi gợi ý
backend/tests           xác nhận fallback và payload
```

### Đổi logic so sánh/giỏ hàng

```text
Gold canonical mapping
  -> sync.prepare_offers
  -> offers_current.canonical_product_id
  -> repository.offer_insights / compare_offers / optimize_basket
  -> deals-client drawers
```

## 12. Kết luận

Kiến trúc hiện tại ưu tiên tính xác định và khả năng fallback: PostgreSQL lexical search là nền tảng, Ollama chỉ tăng chất lượng extraction/ranking, canonical mapping là nguồn sự thật cho so sánh, còn frontend sở hữu giỏ hàng. Cách phân lớp đã khá rõ giữa sync, repository, intent và API; các việc nên ưu tiên nếu đưa lên môi trường thật là bảo vệ sync endpoint, bổ sung user/session ownership, chuyển DDL sang migration và tách các file repository/frontend lớn thành module nhỏ hơn.
