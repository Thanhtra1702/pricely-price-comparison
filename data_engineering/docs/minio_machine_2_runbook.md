# Runbook Máy 2: Truy cập Hudi trên MinIO

Tài liệu này dành cho máy phân tích dữ liệu Windows, không ghi dữ liệu vào Hudi.

## 1. Thông tin kết nối

Thay đổi các giá trị nếu máy 1 dùng cấu hình khác:

```text
Máy MinIO: 192.168.199.73 (Fedora)
Máy phân tích: 192.168.199.120 (Windows)
S3 API:    http://192.168.199.73:9020
Bucket:    supermarket-lakehouse
Prefix:    gold/fact_price_snapshot_daily
```

Máy 2 cần kết nối cùng LAN hoặc VPN với máy 1.

## 2. Kiểm tra mạng trên Windows

Mở PowerShell trên máy `192.168.199.120`:

```powershell
ping 192.168.199.73
Test-NetConnection 192.168.199.73 -Port 9020
curl.exe http://192.168.199.73:9020/minio/health/live
```

Kết quả mong đợi của lệnh `curl`:

```text
OK
```

Nếu ping được nhưng `curl` lỗi, kiểm tra firewall hoặc port mapping trên máy 1.

## 3. Truy cập bằng MinIO Client trên Windows

Máy 2 cần Docker Desktop, bật Linux containers. Có thể dùng Docker để tránh nhầm với GNU Midnight Commander đang dùng lệnh `mc`:

Trong PowerShell, ký tự nối dòng là dấu backtick `` ` ``; nếu lệnh nhiều dòng báo lỗi, chạy trên một dòng hoặc thay `\\` cuối dòng bằng `` ` ``.

```powershell
docker run --rm --network host \
  -v "$HOME/.minio-mc:/root/.mc" \
  minio/mc alias set \
  remote http://192.168.199.73:9020 \
  minioadmin \
  change-this-password
```

Kiểm tra alias và bucket:

```powershell
docker run --rm --network host \
  -v "$HOME/.minio-mc:/root/.mc" \
  minio/mc alias list

docker run --rm --network host \
  -v "$HOME/.minio-mc:/root/.mc" \
  minio/mc ls remote
```

Kiểm tra Hudi files:

```powershell
docker run --rm --network host \
  -v "$HOME/.minio-mc:/root/.mc" \
  minio/mc ls --recursive \
  remote/supermarket-lakehouse/gold/fact_price_snapshot_daily
```

Cần thấy cả các thành phần như:

```text
.hoodie/
manifest.json
*.parquet
```

## 4. Chuẩn bị Spark trên máy 2 Windows

Dùng Spark 3.5.x và Hudi bundle cùng version với máy 1. Có thể chạy Spark bằng WSL2 hoặc Docker Desktop:

```bash
spark-submit \
  --packages \
  org.apache.hudi:hudi-spark3.5-bundle_2.12:1.2.0,\
  org.apache.hadoop:hadoop-aws:3.3.4 \
  --conf spark.hadoop.fs.s3a.endpoint=http://192.168.199.73:9020 \
  --conf spark.hadoop.fs.s3a.access.key=minioadmin \
  --conf spark.hadoop.fs.s3a.secret.key=change-this-password \
  --conf spark.hadoop.fs.s3a.path.style.access=true \
  --conf spark.hadoop.fs.s3a.connection.ssl.enabled=false \
  --conf spark.hadoop.fs.s3a.impl=org.apache.hadoop.fs.s3a.S3AFileSystem \
  your_analysis.py
```

Trong môi trường thật, không truyền credential trực tiếp trên command line; dùng secret manager, IAM role hoặc file cấu hình được bảo vệ.

## 5. Đọc một Hudi table

Trong `your_analysis.py`:

```python
from pyspark.sql import SparkSession

spark = (
    SparkSession.builder
    .appName("read_supermarket_hudi")
    .config("spark.hadoop.fs.s3a.endpoint", "http://192.168.199.73:9020")
    .config("spark.hadoop.fs.s3a.access.key", "minioadmin")
    .config("spark.hadoop.fs.s3a.secret.key", "change-this-password")
    .config("spark.hadoop.fs.s3a.path.style.access", "true")
    .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
    .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
    .getOrCreate()
)

path = (
    "s3a://supermarket-lakehouse/gold/"
    "fact_price_snapshot_daily/store=go/date=2026-07-14/"
    "run_id=20260714_084309/price_snapshot_daily_hudi"
)

df = spark.read.format("hudi").load(path)
df.printSchema()
df.show(20, truncate=False)
print("rows:", df.count())

spark.stop()
```

## 6. Đọc tất cả retailer

```python
from functools import reduce
from pyspark.sql import DataFrame

base = "s3a://supermarket-lakehouse/gold/fact_price_snapshot_daily"
retailers = ["bachhoaxanh", "go", "lottemart", "mmvietnam", "winmart"]

frames = []
for retailer in retailers:
    path = f"{base}/store={retailer}/date=2026-07-14"
    frames.append(spark.read.format("hudi").load(path))

all_prices = reduce(DataFrame.unionByName, frames)
all_prices.groupBy("retailer_id").count().show()
```

## 7. Validate dữ liệu sau khi đọc

```python
from pyspark.sql import functions as F

assert all_prices.filter(F.col("price_snapshot_id").isNull()).count() == 0

duplicate_groups = (
    all_prices
    .groupBy(
        "snapshot_date",
        "retailer_id",
        "store_code",
        "retailer_product_id",
    )
    .count()
    .filter(F.col("count") > 1)
)

assert duplicate_groups.count() == 0

all_prices.select(
    "retailer_id",
    "product_name",
    "current_price",
    "discount_percent",
    "is_on_promotion",
).show(20, truncate=False)
```

## 8. Xử lý lỗi thường gặp

### Ping được nhưng curl không được

Trên máy 1:

```bash
docker ps --filter "name=minio-local"
sudo firewall-cmd --add-port=9020/tcp --permanent
sudo firewall-cmd --reload
```

### Access denied

Kiểm tra lại username, password và bucket policy. Máy 2 chỉ nên dùng user read-only khi chuyển sang môi trường ổn định.

### Không tìm thấy Hudi table

Kiểm tra prefix có đủ `.hoodie` hay không:

```bash
docker run --rm --network host \
  -v "$HOME/.minio-mc:/root/.mc" \
  minio/mc ls --recursive \
  remote/supermarket-lakehouse/gold/fact_price_snapshot_daily/store=go
```

Không chỉ upload Parquet; Hudi cần metadata trong `.hoodie` để đọc timeline và table state.

### Spark không tìm thấy `s3a`

Thêm dependency:

```text
org.apache.hadoop:hadoop-aws:3.3.4
```

và bảo đảm version Hadoop tương thích với Spark image đang dùng.

## 9. Quyền của máy 2

Máy 2 chỉ nên có quyền:

```text
ListBucket
GetObject
```

Không cấp:

```text
PutObject
DeleteObject
```

Máy 2 chỉ phân tích dữ liệu; máy 1 là writer duy nhất của Hudi table.
