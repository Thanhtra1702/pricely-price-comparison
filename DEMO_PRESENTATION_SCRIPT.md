# 🎤 Kịch Bản Thuyết Trình Song Song Demo Sản Phẩm PriceLy

> Tài liệu này được thiết kế để bạn vừa trình chiếu/thao tác giao diện (Demo), vừa nói (Lời thoại) theo kịch bản từng bước chuyên nghiệp.

---

## 📌 Tổng Quan Chương Trình Thuyết Trình

* **Tên sản phẩm:** PriceLy — Nền tảng so sánh giá & săn ưu đãi siêu thị thời gian thực bằng AI.
* **Thời lượng kiến nghị:** 5 – 10 phút.
* **Chuẩn bị môi trường trước khi Demo:**
  1. Đã bật Docker backend + PostgreSQL + Frontend (`http://localhost:3000`).
  2. Đã bật Ollama (Qwen 2.5 3B).
  3. Mở sẵn trình duyệt ở trang chủ `http://localhost:3000`.

---

## 🎬 Kịch Bản Chi Tiết (Thao Tác + Lời Thoại)

### 🟢 PHẦN 1: Mở đầu & Khám phá Ưu đãi (Deals Explorer)
⏱ **Thời lượng:** 1 - 2 phút

| Thao tác trên màn hình | 🗣️ Lời thoại thuyết trình |
| :--- | :--- |
| **1.** Mở trang chủ `http://localhost:3000`. Lướt chuột qua Banner carousel của các siêu thị. | *"Kính chào thầy cô và các bạn. Hôm nay em xin đại diện nhóm trình bày sản phẩm **PriceLy** — giải pháp giúp người tiêu dùng Việt Nam tìm kiếm, so sánh giá và tối ưu chi phí mua sắm tạp hóa hàng ngày trên các chuỗi siêu thị lớn nhất hiện nay gồm Bách Hóa Xanh, GO!, Lotte Mart, WinMart và MM Mega Market."* |
| **2.** Trỏ vào các thẻ sản phẩm (Product Cards) trên Deals Explorer. | *"Giao diện đầu tiên quý vị nhìn thấy là **Deals Explorer**. Tại đây, hệ thống liên tục cập nhật các chương trình khuyến mãi, giảm giá từ các siêu thị. Mỗi thẻ sản phẩm đều hiển thị minh bạch giá hiện tại, giá gốc, phần trăm giảm giá và đặc biệt là **đơn giá chuẩn** (tính theo đ/g hoặc đ/ml) để người mua dễ dàng nhận biết đâu là deal thật sự hời."* |
| **3.** Thử chọn các bộ lọc: Chọn siêu thị GO!, lọc giảm giá trên 10%. | *"Người dùng có thể dễ dàng lọc sản phẩm theo siêu thị, thương hiệu, khoảng giá hoặc mức phần trăm giảm giá mong muốn với tốc độ phản hồi tức thì."* |

---

### 🔵 PHẦN 2: Trợ Lý AI Chatbot So Sánh Giá Thông Minh
⏱ **Thời lượng:** 2 - 3 phút

| Thao tác trên màn hình | 🗣️ Lời thoại thuyết trình |
| :--- | :--- |
| **1.** Nhấp vào Mascot Trợ lý PriceLy ở góc dưới bên phải để mở **Chatbot Overlay Panel**. | *"Điểm nổi bật nhất của PriceLy chính là **Trợ lý AI So Sánh Giá Thông Minh**. Thay vì phải tìm kiếm thủ công, người dùng có thể trò chuyện bằng ngôn ngữ tự nhiên Tiếng Việt."* |
| **2.** Gõ câu hỏi: **`tôi muốn mua chả giò`** hoặc nhấp vào suggestion card. Press Enter. | *"Em xin demo với một câu hỏi quen thuộc: 'tôi muốn mua chả giò'. Hệ thống sử dụng bộ lọc ý định (Intent Parser) hai lớp thông minh. Chatbot tự động loại bỏ các từ giao tiếp thừa, nhận diện chính xác tên sản phẩm 'chả giò' mà không bị nuốt từ hay nhầm lẫn với các từ ngắn khác."* |
| **3.** Chỉ vào kết quả trả về: Danh sách Chả Giò xếp theo giá tăng dần, kèm ngày Snapshot. | *"Ngay lập tức, Chatbot truy vấn cơ sở dữ liệu serving, sắp xếp các lựa chọn chả giò từ giá thấp nhất đến cao nhất. Đồng thời, hệ thống minh bạch thời điểm cập nhật dữ liệu (Snapshot date) để người dùng yên tâm trước khi đi mua."* |
| **4.** Gõ câu hỏi tiếp theo (Follow-up): **`So sánh giá sữa Vinamilk 1L giữa WinMart và GO`** | *"Chatbot cũng hỗ trợ so sánh giá chính xác giữa các siêu thị cụ thể với quy cách nghiêm ngặt. Hệ thống sẽ áp dụng bộ quy tắc để đảm bảo chỉ so sánh đúng dung tích 1L."* |
| **5.** Gõ câu hỏi về ưu đãi: **`có khuyến mãi nào giảm trên 20% không?`** | *"Để tìm kiếm các cơ hội săn sale, khi em hỏi 'có khuyến mãi nào giảm trên 20% không?', chatbot sẽ ngay lập tức truy xuất mức giảm giá lớn nhất, tự động làm tròn số (như 25%) và trả lời người dùng một cách thân thiện, lễ phép với cấu trúc chuẩn 'Dạ em'."* |
| **6.** Chỉ vào chỉ báo xu hướng giá (**Price Trend Alerts**): *"Giá thấp nhất ghi nhận đang giữ nguyên so với 2026-07-17"*. | *"Ngoài ra, Chatbot còn phân tích chuỗi lịch sử giá 7 ngày gần nhất để đưa ra cảnh báo xu hướng — giúp người dùng biết giá sản phẩm đang tăng, giảm hay giữ nguyên."* |

> 💡 **Điểm nhấn kĩ thuật cần nhấn mạnh (LLM Pipeline):** *"Hệ thống áp dụng cơ chế **Grounded LLM với mô hình Đánh Giá Tự Động (LLM-as-a-Judge)**. 
> 1. Mô hình ngôn ngữ chỉ đóng vai trò diễn đạt câu trả lời từ các sự thật (Facts) đã được backend xác minh 100%. 
> 2. Trước khi hiển thị cho người dùng, một mô hình LLM thứ hai sẽ đóng vai trò Giám Khảo (Judge) để chấm điểm câu trả lời về tính chính xác (Grounding) và văn phong (Tone). 
> 3. Nếu điểm dưới chuẩn hoặc xảy ra quá thời gian (Timeout), hệ thống có cơ chế Fallback tự động trả về câu trả lời an toàn, đảm bảo tuyệt đối không bao giờ bịa đặt hay ảo giác giá cả (0% Hallucination)."*

---

### 🟡 PHẦN 3: Tối Ưu Hóa Giỏ Hàng Nhiều Siêu Thị (Basket Optimizer)
⏱ **Thời lượng:** 2 phút

| Thao tác trên màn hình | 🗣️ Lời thoại thuyết trình |
| :--- | :--- |
| **1.** Nhấp nút **"+ Thêm vào giỏ"** tại 2 - 3 sản phẩm trên màn hình chat hoặc thẻ sản phẩm. | *"Khi người dùng muốn chuẩn bị danh sách mua sắm cho tuần mới, họ chỉ cần thêm các món hàng cần mua vào Giỏ hàng."* |
| **2.** Mở Modal **Giỏ Hàng (Basket Optimizer)** từ thanh Navigation hoặc câu lệnh Chat *"Tối ưu giỏ hàng"*. | *"Tính năng **Basket Optimizer** sẽ giải bài toán tối ưu chi phí mua sắm phức tạp bằng thuật toán phân tích:"* |
| **3.** Chỉ vào phương án **"Mua tại 1 siêu thị" (Single-Retailer Option)**. | *"**Phương án 1 - Mua tại 1 siêu thị:** Giúp người dùng chọn ra đúng 1 siêu thị duy nhất có tổng hóa đơn rẻ nhất cho toàn bộ danh sách hàng hóa — tiết kiệm tối đa thời gian và công sức di chuyển."* |
| **4.** Chỉ vào phương án **"Chia đơn rẻ nhất" (Split-Order Option)**. | *"**Phương án 2 - Chia đơn tiết kiệm nhất:** Hệ thống sẽ tự động tách danh sách món hàng sang từng siêu thị đang bán món đó với giá rẻ nhất — giúp tối ưu chi phí tuyệt đối."* |

---

### 🟣 PHẦN 4: Kiến Trúc Hạ Tầng & Data Pipeline (Under the Hood)
⏱ **Thời lượng:** 1 phút

| Thao tác trên màn hình | 🗣️ Lời thoại thuyết trình |
| :--- | :--- |
| **1.** Chiếu Slide hoặc sơ đồ hệ thống trong `README.md` / `SYSTEM_ARCHITECTURE.md`. | *"Về mặt kỹ thuật, PriceLy được xây dựng trên hạ tầng dữ liệu hiện đại:* |
| **2.** Giải thích ngắn gọn các tầng công nghệ. | *- **Data Lakehouse (Medallion Architecture):** Dữ liệu thu thập tự động qua Playwright crawlers, xử lý làm sạch qua PySpark & Apache Hudi (Bronze $\rightarrow$ Silver $\rightarrow$ Gold) lưu trữ trên MinIO S3 Storage.*<br/>*- **Serving Layer:** PostgreSQL 16 kết hợp Full-Text Search và Vector Embedding (`bge-m3`).*<br/>*- **Backend & Frontend:** FastAPI Python async kết hợp Next.js 15 App Router đem lại trải nghiệm mượt mà, phản hồi tức thì."* |

---

### 🔴 PHẦN 5: Kết Luận & Q&A
⏱ **Thời lượng:** 30 giây

| Thao tác trên màn hình | 🗣️ Lời thoại thuyết trình |
| :--- | :--- |
| Quay lại màn hình giao diện PriceLy. | *"Tóm lại, PriceLy không chỉ là một công cụ so sánh giá, mà là một trợ lý mua sắm thông minh toàn diện giúp người tiêu dùng tiết kiệm thời gian và tiền bạc. Em xin chân thành cảm ơn thầy cô và các bạn đã chú ý theo dõi. Em xin sẵn sàng nhận các câu hỏi góp ý ạ!"* |

---

## 🛠️ Bộ Câu Hỏi Q&A Thường Gặp & Cách Trả Lời

1. **Q: Chatbot có bị ảo giác (hallucination) tự bịa ra giá sai không?**
   * **A:** *"Dạ không. Chatbot của PriceLy tuân thủ nguyên tắc Grounded AI. Backend thực hiện lọc SQL và xếp hạng giá trước, sau đó chỉ gửi đúng các dòng Fact verified sang cho LLM diễn đạt lại. Nếu LLM lỗi hoặc trả về giá khác dữ liệu thực, backend sẽ tự động chuyển sang câu trả lời TemplateFallback đảm bảo chính xác 100%."*

2. **Q: Nếu siêu thị đổi giá trong ngày thì dữ liệu có cập nhật không?**
   * **A:** *"Dạ dữ liệu được cập nhật theo các phiên đồng bộ (Snapshot) hàng ngày. Mỗi câu trả lời của Chatbot đều đính kèm ngày Snapshot dữ liệu để người dùng chủ động kiểm tra."*

3. **Q: Người dùng gõ Tiếng Việt không dấu Chatbot có hiểu không?**
   * **A:** *"Dạ hiểu hoàn toàn. Hệ thống có bộ chuẩn hóa `normalize_text` xử lý cả 2 chuẩn mã hóa Unicode (NFC/NFD) và chuyển về dạng ASCII khi truy vấn, nên người dùng gõ có dấu hay không dấu đều nhận được kết quả chính xác như nhau."*
