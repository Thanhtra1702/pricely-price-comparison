# Runbook: đọc Hudi từ MinIO

Tài liệu này dành cho máy phân tích chỉ đọc dữ liệu từ MinIO. Không ghi endpoint nội bộ, IP, access key hoặc secret key vào Git.

## 1. Chuẩn bị biến môi trường

Lấy các giá trị từ secret manager hoặc quản trị hệ thống. Tài khoản MinIO phải chỉ có quyền `ListBucket` và `GetObject` cho prefix `gold/` của bucket cần đọc.

```powershell
$env:MINIO_ENDPOINT = "https://minio.example.internal"
$env:MINIO_ACCESS_KEY = "<read-only-access-key>"
$env:MINIO_SECRET_KEY = "<read-only-secret-key>"
$env:MINIO_BUCKET = "supermarket-lakehouse"
```

Ưu tiên endpoint HTTPS có chứng chỉ hợp lệ. Máy phân tích phải kết nối qua LAN/VPN được cấp quyền; không mở MinIO ra Internet công khai nếu không có lớp bảo vệ phù hợp.

## 2. Kiểm tra kết nối

```powershell
$minioHost = ([uri]$env:MINIO_ENDPOINT).Host
Test-NetConnection $minioHost -Port 443
curl.exe "$env:MINIO_ENDPOINT/minio/health/live"
```

Kết quả health check mong đợi là `OK`. Nếu lỗi, kiểm tra VPN/firewall/chứng chỉ TLS cùng quản trị hệ thống.

## 3. Dùng MinIO Client trong Docker

Không truyền key trực tiếp trên command line vì có thể bị lưu vào shell history. Lệnh dưới đây đọc biến môi trường của phiên PowerShell hiện tại:

```powershell
docker run --rm `
  -e MINIO_ENDPOINT -e MINIO_ACCESS_KEY -e MINIO_SECRET_KEY `
  --entrypoint /bin/sh minio/mc -c 'mc alias set remote "$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"; mc ls remote/'
```

Để kiểm tra Gold Hudi files:

```powershell
docker run --rm `
  -e MINIO_ENDPOINT -e MINIO_ACCESS_KEY -e MINIO_SECRET_KEY -e MINIO_BUCKET `
  --entrypoint /bin/sh minio/mc -c 'mc alias set remote "$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"; mc ls --recursive "remote/$MINIO_BUCKET/gold"'
```

## 4. Đọc một Hudi table bằng Spark

Spark cần bundle Hudi/Hadoop tương thích. Đặt các biến môi trường ở bước 1 trước khi chạy script.

```python
import os
from pyspark.sql import SparkSession

spark = (
    SparkSession.builder
    .appName("read_supermarket_hudi")
    .config("spark.hadoop.fs.s3a.endpoint", os.environ["MINIO_ENDPOINT"])
    .config("spark.hadoop.fs.s3a.access.key", os.environ["MINIO_ACCESS_KEY"])
    .config("spark.hadoop.fs.s3a.secret.key", os.environ["MINIO_SECRET_KEY"])
    .config("spark.hadoop.fs.s3a.path.style.access", "true")
    .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "true")
    .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
    .getOrCreate()
)

path = "s3a://supermarket-lakehouse/gold/fact_price_snapshot_daily_hudi/store=go"
df = spark.read.format("hudi").load(path)
df.show(20, truncate=False)
spark.stop()
```

Hudi cần thư mục `.hoodie/`; không chỉ tải riêng các file Parquet.

## 5. Bảo mật vận hành

- Dùng service account read-only, scope nhỏ nhất cần thiết, và xoay vòng key định kỳ.
- Lưu biến môi trường trong secret manager/CI secrets, không trong notebook, `.env`, source code hay shell history.
- Nếu bắt buộc dùng HTTP trong môi trường development cô lập, chỉ dùng trên mạng riêng; production cần HTTPS.
