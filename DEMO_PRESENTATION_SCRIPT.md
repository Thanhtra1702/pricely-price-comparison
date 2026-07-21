# 🎤 Kịch Bản Thuyết Trình Demo Sản Phẩm PriceLy

> Tài liệu này là kịch bản lời thoại dành cho người thuyết trình. Cấu trúc được chia theo từng tính năng, mỗi tính năng gồm 2 phần: **Giới thiệu chức năng (Mặt người dùng)** và **Giải thích kỹ thuật (Under the hood)**.

---

## 📌 MỞ ĐẦU
**🗣️ Lời thoại:** 
"Kính chào thầy cô và các bạn. Hôm nay em xin đại diện nhóm trình bày sản phẩm **PriceLy** — Nền tảng so sánh giá & săn ưu đãi siêu thị thời gian thực bằng AI. Giải pháp của chúng em giúp người tiêu dùng Việt Nam tìm kiếm, so sánh giá và tối ưu chi phí mua sắm tạp hóa hàng ngày trên các chuỗi siêu thị lớn nhất hiện nay gồm Bách Hóa Xanh, GO!, Lotte Mart, WinMart và MM Mega Market."

---

## 🎯 TÍNH NĂNG 1: DEALS EXPLORER (KHÁM PHÁ ƯU ĐÃI)
*(Vừa nói vừa lướt trang chủ, trỏ vào các thẻ sản phẩm và dùng bộ lọc)*

### 1. Giới thiệu chức năng
**🗣️ Lời thoại:** 
"Giao diện đầu tiên quý vị nhìn thấy là **Deals Explorer**. Tại đây, hệ thống liên tục cập nhật các chương trình khuyến mãi, giảm giá từ các siêu thị. Mỗi thẻ sản phẩm đều hiển thị minh bạch giá hiện tại, giá gốc, phần trăm giảm giá và đặc biệt là **đơn giá chuẩn** (tính theo đ/g hoặc đ/ml) để người mua dễ dàng nhận biết đâu là deal thật sự hời. Người dùng có thể dễ dàng lọc sản phẩm theo siêu thị, khoảng giá hoặc mức phần trăm giảm giá mong muốn với tốc độ phản hồi tức thì."

### 2. Yếu tố kỹ thuật
**🗣️ Lời thoại:** 
"Để có được dữ liệu mượt mà và đầy đủ thế này, đằng sau PriceLy là một hệ thống **Data Lakehouse (Medallion Architecture)** mạnh mẽ:
* Dữ liệu được thu thập tự động hàng ngày bằng các Playwright crawlers.
* Chuyển qua các bước xử lý làm sạch (Bronze $\rightarrow$ Silver $\rightarrow$ Gold) thông qua PySpark & Apache Hudi, lưu trữ trên MinIO S3 Storage.
* Cuối cùng, dữ liệu sạch được đẩy lên PostgreSQL 16. Việc tìm kiếm diễn ra tức thì nhờ tận dụng sức mạnh của Full-Text Search trong Postgres."

---

## 🤖 TÍNH NĂNG 2: TRỢ LÝ AI SO SÁNH GIÁ THÔNG MINH
*(Mở Chatbot lên, thử gõ: "tôi muốn mua chả giò", sau đó "So sánh giá sữa Vinamilk 1L giữa WinMart và GO")*

### 1. Giới thiệu chức năng
**🗣️ Lời thoại:** 
"Điểm nổi bật nhất của PriceLy chính là **Trợ lý AI Chatbot**. Người dùng không cần bấm tìm thủ công mà chỉ cần chat bằng ngôn ngữ tự nhiên Tiếng Việt. 
Ví dụ, khi em gõ *'tôi muốn mua chả giò'*, chatbot lập tức trả về danh sách xếp theo giá từ thấp đến cao, kèm ngày cập nhật dữ liệu. Khi em yêu cầu khó hơn: *'So sánh giá sữa Vinamilk 1L giữa WinMart và GO'* — hệ thống bắt buộc kiểm tra đúng dung tích 1L, trả về câu trả lời tự nhiên, thân thiện và kèm theo phân tích xu hướng giá 7 ngày gần nhất để xem giá đang tăng hay giảm."

### 2. Yếu tố kỹ thuật
**🗣️ Lời thoại:** 
"Về mặt kỹ thuật, xử lý ngôn ngữ tự nhiên luôn có rủi ro mô hình tự 'bịa' ra giá (Hallucination). Để giải quyết triệt để, chúng em thiết kế một **LLM Pipeline** khép kín với cơ chế **Grounded LLM**:
1. **Intent Parser (Phân loại ý định):** Bóc tách chính xác ý định và bộ lọc của người dùng trước khi truy vấn DB.
2. **Grounded Generation:** Mô hình LLM (Ollama) chỉ được dùng để 'diễn đạt' lại các sự thật (Facts) đã được backend truy xuất từ database, không được tự suy diễn.
3. **LLM-as-a-Judge & Fallback:** Trước khi hiển thị cho người dùng, một mô hình LLM đóng vai trò 'Giám khảo' sẽ chấm điểm độ chính xác và văn phong của câu trả lời. Nếu phát hiện bịa đặt hoặc quá thời gian xử lý, hệ thống kích hoạt cơ chế Fallback an toàn (Template_based) — đảm bảo **0% Hallucination**."

---

## 🛒 TÍNH NĂNG 3: BỘ TỐI ƯU HÓA GIỎ HÀNG (BASKET OPTIMIZER)
*(Thêm vài sản phẩm vào giỏ, mở giỏ hàng và ấn Tối ưu hóa)*

### 1. Giới thiệu chức năng
**🗣️ Lời thoại:** 
"Khi người dùng chuẩn bị danh sách mua sắm cho tuần mới, họ chỉ cần thêm các món hàng vào Giỏ hàng. Bài toán đặt ra là: Mua ở đâu rẻ nhất? Tính năng **Basket Optimizer** sẽ đưa ra 2 phương án:
* **Phương án 1 (Mua tại 1 siêu thị):** Giúp người dùng chọn ra đúng 1 siêu thị duy nhất có tổng hóa đơn rẻ nhất cho toàn bộ danh sách, tiết kiệm công sức đi lại.
* **Phương án 2 (Chia đơn tiết kiệm nhất):** Hệ thống tự động tách các món hàng sang từng siêu thị đang bán rẻ nhất để tối ưu chi phí tuyệt đối."

### 2. Yếu tố kỹ thuật
**🗣️ Lời thoại:** 
"Điểm khó nhất của tính năng này là các siêu thị thường đặt tên sản phẩm khác nhau (ví dụ: 'Mì Hảo Hảo Tôm Chua Cay 75g' và 'Mì ăn liền Hảo Hảo 75g'). Để matching chúng, hệ thống sử dụng **Vector Embedding (`bge-m3`)** chạy cục bộ. Bằng cách tính độ tương đồng của Vector khoảng cách và kết hợp các quy tắc so sánh dung tích/khối lượng, hệ thống gom nhóm chính xác các sản phẩm tương đương trên các sàn khác nhau, từ đó thuật toán tối ưu hóa mới có thể tính toán chính xác."

---

## 🚀 TỔNG KẾT & Q&A
**🗣️ Lời thoại:** 
"Tóm lại, với Frontend là Next.js 15 và Backend FastAPI Python bất đồng bộ, kết hợp hạ tầng dữ liệu Data Lakehouse tiên tiến, PriceLy không chỉ là một trang web so sánh giá, mà là một **trợ lý mua sắm thông minh toàn diện**.

Em xin chân thành cảm ơn thầy cô và các bạn đã chú ý theo dõi. Em xin sẵn sàng nhận các câu hỏi góp ý ạ!"
