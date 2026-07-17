# Simple Summary: Data Lakehouse for Price Comparison

This document summarizes these two files:

- `lakehouse_hudi_pipeline_design.md`
- `lakehouse_table_catalog.md`

The goal is to explain the system in a simple way.

## 1. Main Goal

Build a data platform for a price comparison and promotion system.

The system should:

- Crawl product prices, promotions, stock, stores, and categories from retailers.
- Compare the same product across many retailers.
- Track price changes over time.
- Keep raw data for audit and reprocessing.
- Prepare clean data for BI dashboards, data science, recommendation, and chatbot later.

Retailers can include:

- WinMart
- Co.opmart
- GO!/Big C
- Lotte Mart
- Bach Hoa Xanh
- AEON

## 2. Big Architecture

The recommended architecture is:

```text
Scraper
-> Raw files
-> Bronze Hudi
-> Silver Hudi
-> Gold Hudi
-> BI / API / Data Science / Chatbot
```

Airflow controls the workflow:

```text
Crawl data
-> Validate raw data
-> Ingest to Bronze
-> Clean and normalize to Silver
-> Check data quality
-> Build Gold tables
```

PostgreSQL is only used for operational metadata, such as:

- Retailer configuration
- Store configuration
- Crawl schedule
- Crawl run status
- Manual product matching review

PostgreSQL is not the source of truth for price history.

The source of truth is the lakehouse with Apache Hudi.

## 3. Why Use Apache Hudi?

Apache Hudi is useful because price data changes often.

It supports:

- Insert and update on data lake tables
- Incremental processing
- Rollback and audit history
- Reading from Spark, Trino, Presto, and Hive
- Handling repeated crawls of the same product/store/date

Recommended Hudi table types:

| Layer | Table Type | Reason |
|---|---|---|
| Bronze | Copy-on-write | Raw data is mostly append-only |
| Silver | Copy-on-write first | Easier and stable for MVP |
| Gold | Copy-on-write | Fast read for BI and apps |
| Streaming later | Merge-on-read | Better for frequent writes |

## 4. Medallion Layers

The lakehouse has three main layers.

### Bronze: Raw and Audit Layer

Bronze stores raw data from crawlers.

Purpose:

- Keep original payloads
- Allow reprocessing if parser logic is wrong
- Audit what was crawled
- Track crawl run status and data quality

Important tables:

- `bronze.crawl_runs`
- `bronze.raw_records`
- `bronze.raw_payload_manifest`
- `bronze.data_quality_results`

Bronze should not be used directly by the app.

### Silver: Clean Business Data

Silver stores cleaned and normalized data.

Purpose:

- Store products, stores, categories, prices, and promotions in a reliable format
- Separate product master data from price observations
- Support product matching across retailers later
- Keep invalid records in quarantine instead of silently publishing bad data

Important MVP tables:

- `silver.retailers`
- `silver.stores`
- `silver.categories`
- `silver.retailer_products`
- `silver.product_observations`
- `silver.promotions`
- `silver.promotion_items`
- `silver.quarantine_records`

Important idea:

`retailer_products` describes the product itself.

`product_observations` describes the price, stock, and promotion status at a store and time.

These should not be mixed.

### Gold: Business and Serving Layer

Gold stores data that is ready for BI, APIs, dashboards, and apps.

Purpose:

- Provide daily price snapshots
- Provide promotion snapshots
- Support price comparison
- Support best deals, recommendation, and chatbot later

Important tables:

- `gold.dim_date`
- `gold.dim_retailer`
- `gold.dim_store`
- `gold.dim_product`
- `gold.fact_price_snapshot_daily`
- `gold.fact_promotion_snapshot_daily`
- `gold.fact_price_change`
- `gold.mart_price_comparison`
- `gold.mart_best_deals`
- `gold.mart_promotion_feed`
- `gold.mart_recommendation_features`

Gold should only be published after data quality checks pass.

## 5. Main Data Model Ideas

### Do Not Use Product Name as Key

Product names can be different across retailers.

Use stronger keys such as:

- `retailer_id`
- `store_id`
- `source_product_id`
- `sku`
- `barcode`
- `uom`

For cross-retailer comparison, use:

- `canonical_product_id`
- normalized brand
- normalized product name
- package size
- barcode

### Keep Snapshot and Event Data

The system should store both:

- Snapshot: current price at crawl time
- Event: price changed from previous crawl

Example tables:

- `silver.product_observations`
- `silver.price_change_events`
- `gold.fact_price_snapshot_daily`
- `gold.fact_price_change`

### Promotions Need Their Own Tables

Promotions are more complex than just a discount price.

Examples:

- Buy 2 get 1
- Buy 5 pay 4
- Bundle price
- Member-only price
- Gift product

So the design separates:

- `silver.promotions`
- `silver.promotion_items`

This avoids incorrect modeling when product A gives product B as a gift.

## 6. Data Quality Rules

Data quality is very important because wrong prices can create wrong comparisons.

Examples of checks:

- Price must not be negative.
- Currency should be `VND`.
- Required fields must not be null.
- Duplicate key rate must be below threshold.
- Promotion type and promotion item role must be valid.
- Gold price snapshot must have only one latest row per product/store/date.
- Large price changes should be flagged as anomaly.

Bad records should go to:

```text
silver.quarantine_records
```

The pipeline should not fail the whole batch because of a few bad records.

## 7. MVP Scope

The MVP should be simple and batch-based.

Recommended MVP flow:

```text
Python scraper
-> raw JSONL/HTML files
-> Spark batch job
-> Hudi Bronze
-> Hudi Silver
-> Hudi Gold
-> Trino / Superset / Notebook
```

MVP should include:

### PostgreSQL

- `retailers`
- `stores`
- `crawl_sources`
- `crawl_runs`
- `crawl_task_runs`

### Bronze

- `crawl_runs`
- `raw_records`
- `raw_payload_manifest`
- `data_quality_results`

### Silver

- `retailers`
- `stores`
- `categories`
- `retailer_products`
- `product_observations`
- `promotions`
- `promotion_items`
- `quarantine_records`

### Gold

- `dim_date`
- `dim_retailer`
- `dim_store`
- `fact_price_snapshot_daily`
- `fact_promotion_snapshot_daily`

Only add cross-retailer comparison after there are at least two retailers and product matching is reliable.

## 8. What Is Not Needed in MVP

These are not needed at the beginning:

- Kafka
- Real-time streaming
- Vector database
- Recommendation model
- Chatbot
- Feature store
- Full data warehouse
- NoSQL database just to store JSON

They can be added later when there is a clear use case.

## 9. Recommendation and Chatbot

Recommendation should come after Silver and Gold are stable.

Simple recommendation can start with rules:

```text
discount score
+ price rank
+ freshness
+ stock status
+ user preference
```

Chatbot should be an interface, not the core data system.

The chatbot should query Gold marts or a recommendation API.

It should answer questions like:

- Where is this product cheapest today?
- Which products are buy 2 get 1 near me?
- Compare this product between WinMart and Co.opmart.

The chatbot should include:

- Source retailer
- Store
- Crawl timestamp
- Source link

## 10. Real-Time Decision

Real-time is not needed for MVP.

Most retailer prices and promotions change by campaign, hour, or day, not by second.

Recommended latency:

| Use Case | Latency | Approach |
|---|---:|---|
| Daily BI report | 1 day | Daily batch |
| Price comparison | 1-6 hours | Scheduled batch |
| Hot product alert | 15-60 minutes | Triggered batch |
| Flash sale stock/price | 5-15 minutes | Limited polling |
| User clickstream | Near real-time | Kafka later |

## 11. Suggested Implementation Roadmap

### Phase 1: Raw Lakehouse MVP

- Keep current scrapers.
- Save raw JSONL/HTML to object storage.
- Use Airflow to run crawler tasks.
- Load raw data into Bronze Hudi.
- Build Silver product, price, promotion tables.
- Store bad records in quarantine.

### Phase 2: BI and Data Science

- Add a second retailer.
- Build canonical product matching.
- Build Gold dimensions and daily facts.
- Create dashboards.
- Use notebooks for price trend and anomaly analysis.

### Phase 3: Recommendation

- Build best-deal ranking.
- Start with rule-based recommendation.
- Add ML later when user behavior data exists.

### Phase 4: Chatbot

- Let chatbot query Gold marts and recommendation API.
- Add RAG only for sanitized promotion terms or raw documents.
- Always return source and crawl timestamp.

### Phase 5: Near Real-Time

- Add Kafka only when needed.
- Use Spark Structured Streaming for user events or high-frequency updates.
- Use Hudi merge-on-read for high-write tables.

## 12. Final Recommendation

Use Apache Hudi with a medallion lakehouse architecture.

Start with batch processing, not streaming.

Use PostgreSQL for crawler and operational metadata.

Use Bronze for raw audit data.

Use Silver for clean product, price, store, and promotion data.

Use Gold for BI, API, dashboards, and app serving.

Add recommendation, chatbot, NoSQL, vector database, and streaming later only when the core pipeline is stable.
