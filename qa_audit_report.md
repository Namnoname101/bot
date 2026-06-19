# Báo Cáo Kiểm Thử & Đánh Giá Chất Lượng Dự Án (QA Audit Report)

Báo cáo này chứa kết quả phân tích, kiểm thử và đánh giá chi tiết mã nguồn của hệ thống **Sober Bot Telegram** từ góc độ kiểm thử phần mềm chuyên sâu (Quality Assurance). Các lỗi và rủi ro được phân loại theo mức độ nghiêm trọng từ **Thấp (Low)** đến **Nghiêm Trọng (Critical)** kèm theo phân tích nguyên nhân và phương án khắc phục.

---

## 📌 Tóm Tắt Đánh Giá (Executive Summary)

*   **Độ ổn định hệ thống**: Khá (với tải thấp). Tuy nhiên sẽ gặp vấn đề lớn khi số lượng nhân viên tăng lên hoặc khi chạy thực tế lâu dài.
*   **Điểm nghẽn hiệu năng (Performance Bottleneck)**: **Nghiêm trọng**. Bot đang gọi các hàm đồng bộ (synchronous) của thư viện `gspread` trực tiếp bên trong các hàm xử lý không đồng bộ (`async def`). Việc này gây nghẽn toàn bộ Event Loop của asyncio, làm bot bị đơ (freeze) khi đang thực hiện giao dịch với Google Sheets.
*   **Lỗi logic nghiệp vụ (Business Logic Issues)**: Phát hiện lỗi phân tách tên nhân viên bằng khoảng trắng dẫn đến nhận diện sai tên, thiếu chuẩn hóa Unicode Tiếng Việt gây lệch dữ liệu và rủi ro cộng trùng thưởng khi nhập trùng tên trong tin nhắn báo cáo.

---

## 🚨 Các Lỗi Cực Kỳ Nghiêm Trọng (Critical & High Issues)

### 1. Phân Tách Tên Nhân Viên Bằng Khoảng Trắng (Logic Bug)
*   **Vị trí**: [validators.py](file:///E:/Du An/Python/Sober/Bot/utils/validators.py#L22)
    ```python
    employees = [n.strip().lower() for n in re.split(r'[,]+|\s+', raw_nvs) if n.strip()]
    ```
*   **Mô tả**: Regex `re.split(r'[,]+|\s+', raw_nvs)` sẽ cắt chuỗi tên nhân viên bằng dấu phẩy **HOẶC** bằng bất kỳ khoảng trắng nào. 
*   **Hậu quả**: 
    *   Nếu nhân viên báo cáo ghi tên có dấu cách (ví dụ: `NV: anh tuyet, quoc bao`), hàm sẽ phân tích thành 4 nickname độc lập: `['anh', 'tuyet', 'quoc', 'bao']`.
    *   Hệ thống sẽ báo lỗi không tìm thấy nhân viên `anh`, `tuyet` trên bảng tính `SoDuThuong` và từ chối báo cáo ngay lập tức, dù tên đúng là `anh tuyet`.
*   **Phương án sửa đổi**: Chỉ phân tách bằng dấu phẩy `,` và giữ nguyên khoảng trắng bên trong tên (chỉ cắt khoảng trắng thừa hai đầu bằng `strip()`).
    ```python
    # Sửa thành:
    employees = [n.strip().lower() for n in raw_nvs.split(',') if n.strip()]
    ```

---

### 2. Sự Cố Nghẽn Event Loop - Đơ Bot Khi Gọi Google Sheets (Performance Bottleneck)
*   **Vị trí**: [approve_handler.py](file:///E:/Du An/Python/Sober/Bot/handlers/approve_handler.py#L30-L39) và [reward_handler.py](file:///E:/Du An/Python/Sober/Bot/handlers/reward_handler.py#L20-L26)
*   **Mô tả**: Thư viện `gspread` và `google-api-python-client` là thư viện chạy đồng bộ (blocking I/O). Trong khi đó, `python-telegram-bot` chạy trên nền tảng không đồng bộ (asyncio). Việc gọi `sheets_service.save_report` hoặc `sheets_service.update_balance` trực tiếp trong luồng `async def` sẽ chặn đứng (block) Event Loop của Python.
*   **Hậu quả**: Khi có thao tác ghi hoặc đọc Sheets (mất trung bình từ 1 - 3 giây), bot sẽ không thể tiếp nhận hay xử lý bất kỳ tin nhắn nào khác từ các thành viên khác trong nhóm. Nếu có nhiều yêu cầu xử lý cùng lúc hoặc mạng chậm, bot sẽ hoàn toàn mất kết nối với Telegram (timeout).
*   **Phương án sửa đổi**: Sử dụng `asyncio.to_thread` để chạy các hàm đồng bộ này trong một Thread riêng biệt, giải phóng Event Loop.
    ```python
    # Ví dụ khi lưu báo cáo trong approve_handler.py:
    success = await asyncio.to_thread(
        sheets_service.save_report,
        date=report_data['date'], 
        employees=report_data['employees'],
        revenue=report_data['revenue'], 
        ca=report_data.get('ca')
    )
    ```

---

### 3. Vượt Quá Hạn Mức API Google Sheets (API Quota Rate Limit)
*   **Vị trí**: [google_sheets.py: get_all_balances](file:///E:/Du An/Python/Sober/Bot/google_sheets.py#L189-L200) và [update_balance](file:///E:/Du An/Python/Sober/Bot/google_sheets.py#L221-L248)
*   **Mô tả**: 
    *   Trong cơ chế Fallback của `get_all_balances`, mã nguồn đang thực hiện vòng lặp đọc giá trị ô tính bằng `ws_balance.cell(idx, col)` cho từng nhân viên.
    *   Trong `update_balance`, hệ thống gọi liên tục nhiều yêu cầu: `col_values()` $\rightarrow$ `cell().value` $\rightarrow$ `update_cell()` $\rightarrow$ `cell().value` (cho SoLyDaThuong) $\rightarrow$ `update_cell()`.
*   **Hậu quả**: Hạn mức của Google Sheets API chỉ cho phép tối đa 60 requests/phút. Nếu danh sách nhân viên có 20-30 người, chỉ cần chạy lệnh `/bangthuong` hoặc duyệt một báo cáo nhóm 3 người là bot sẽ lập tức bị lỗi `HTTP 429 Too Many Requests` và sập kết nối Sheets.
*   **Phương án sửa đổi**: 
    *   Sử dụng `ws_balance.get_all_values()` hoặc `ws_balance.get()` để tải toàn bộ dữ liệu bảng tính về bộ nhớ RAM chỉ bằng **1 API request duy nhất**, sau đó xử lý tìm kiếm và tính toán trực tiếp trên danh sách (in-memory parsing).
    *   Tối ưu hóa ghi dữ liệu bằng cách gom cụm cập nhật (Batch Update) nếu ghi nhiều dòng.

---

### 4. Thiếu Chuẩn Hóa Unicode Tiếng Việt Khi So Sánh Tên (Data Mismatch)
*   **Vị trí**: [google_sheets.py](file:///E:/Du An/Python/Sober/Bot/google_sheets.py#L152) và [report_handler.py](file:///E:/Du An/Python/Sober/Bot/handlers/report_handler.py#L82)
*   **Mô tả**: Tên nhân viên lưu trên Google Sheets (ví dụ: `hoà` dùng Unicode dựng sẵn - NFC) có thể có chuỗi nhị phân khác với tên do nhân viên gõ từ bàn phím Telegram (ví dụ: `hoà` dùng Unicode tổ hợp - NFD). So sánh chuỗi thông thường `str(v).strip().lower() == target` sẽ trả về `False` dù chữ hiển thị hoàn toàn giống nhau.
*   **Hậu quả**: Nhân viên báo cáo đúng tên của mình nhưng bot liên tục báo lỗi *"Sai tên nhân viên: hòa. Vui lòng kiểm tra lại..."* gây ức chế cho người dùng.
*   **Phương án sửa đổi**: Sử dụng thư viện `unicodedata` để đưa tất cả chuỗi so sánh về cùng một dạng chuẩn (NFC hoặc NFD) hoặc chuẩn hóa loại bỏ dấu tiếng Việt hoàn toàn khi kiểm tra nickname.
    ```python
    import unicodedata
    
    def clean_name(s: str) -> str:
        s = unicodedata.normalize('NFC', s.strip().lower())
        # Hoặc loại bỏ dấu hoàn toàn để tăng độ chính xác
        return s
    ```

---

## ⚠️ Các Rủi Ro Vừa Phải (Medium Issues)

### 5. Mất Dữ Liệu Chờ Duyệt Khi Bot Khởi Động Lại (Data Loss Risk)
*   **Vị trí**: [main.py](file:///E:/Du An/Python/Sober/Bot/main.py#L49)
*   **Mô tả**: Dữ liệu tạm thời của các báo cáo chưa được duyệt được lưu trữ hoàn toàn trong RAM (`app.bot_data['temp_reports'] = {}`).
*   **Hậu quả**: Nếu bot tự động khởi động lại (để cập nhật cấu hình, máy chủ bảo trì, lỗi mất mạng...), toàn bộ các báo cáo đang chờ duyệt sẽ bị xóa sạch. Khi Quản lý nhấn vào các nút bấm cũ trên Telegram, bot sẽ báo lỗi: *"Báo cáo này đã hết hạn hoặc bot đã khởi động lại"* và nhân viên bắt buộc phải gửi lại báo cáo từ đầu.
*   **Phương án sửa đổi**: Nên lưu trữ dữ liệu tạm thời này vào một cơ sở dữ liệu gọn nhẹ như **SQLite** (tạo file cục bộ) hoặc lưu trực tiếp vào một Sheet tạm của Google Sheets để đảm bảo không bị mất trạng thái khi bot khởi động lại.

### 6. Không Kiểm Soát Trùng Tên Nhân Viên Trong Báo Cáo (Double Reward Bug)
*   **Vị trí**: [report_handler.py](file:///E:/Du An/Python/Sober/Bot/handlers/report_handler.py#L89)
*   **Mô tả**: Nếu nhân viên ghi chú thích ảnh trùng lặp: `NV: anhuy, anhuy, anhuy - Doanh thu: 1500k`.
*   **Hậu quả**: 
    *   Hàm phân tích sẽ nhận diện danh sách nhân viên là `['anhuy', 'anhuy', 'anhuy']` (3 nhân viên).
    *   Hệ thống kiểm tra chỉ tiêu: số nhân viên = 3, doanh thu = 1.5M $\rightarrow$ Đạt chỉ tiêu thưởng 1 ly nước/người.
    *   Khi Quản lý phê duyệt, vòng lặp `for emp in employees` sẽ chạy 3 lần cho `anhuy`, dẫn đến việc nhân viên `anhuy` được cộng **3 ly thưởng** thay vì chỉ 1 ly.
*   **Phương án sửa đổi**: Sử dụng `set` hoặc hàm loại bỏ phần tử trùng trong danh sách nhân viên trước khi đưa vào phân tích và xử lý thưởng.
    ```python
    employees = list(dict.fromkeys(employees)) # Giữ nguyên thứ tự và loại bỏ trùng lặp
    ```

---

## ℹ️ Các Đóng Góp Nhỏ & Tối Ưu Khác (Low Issues)

### 7. Nhập Doanh Thu Âm hoặc Doanh Thu Quá Lớn
*   **Mô tả**: Hàm phân tích doanh thu `parse_report_text` chỉ lọc chuỗi số nhưng không chặn giá trị âm hoặc giá trị siêu lớn (ví dụ: gõ nhầm thêm nhiều chữ số không).
*   **Hậu quả**: Có thể gây tràn số trên Sheets hoặc phá hỏng tính hợp lệ của dữ liệu kế toán.
*   **Khắc phục**: Giới hạn doanh thu đầu vào phải dương và nằm trong ngưỡng thực tế (ví dụ: nhỏ hơn 100,000,000 VNĐ cho một ca làm).

### 8. Hardcoded Chat ID Mặc Định
*   **Vị trí**: [config.py](file:///E:/Du An/Python/Sober/Bot/config.py#L20-L21)
*   **Mô tả**: Giá trị fallback của `GROUP_CHAT_ID` và `ADMIN_CHAT_ID` đang được viết cứng trong mã nguồn (`6937465759` và `1853328773`).
*   **Khắc phục**: Nên loại bỏ giá trị mặc định này để buộc hệ thống phải cấu hình trong file `.env` hoặc đưa thông báo lỗi rõ ràng nếu không cấu hình nhằm tránh gửi dữ liệu nhầm sang ID của nhà phát triển cũ.

---

## 📋 Đề Xuất Kế Hoạch Cải Tiến (Action Plan)

1.  **Giai đoạn 1 (Sửa lỗi logic & Dữ liệu)**:
    *   Cập nhật hàm phân tách tên chỉ cắt theo dấu phẩy `,` tại [validators.py](file:///E:/Du An/Python/Sober/Bot/utils/validators.py).
    *   Loại bỏ nhân viên trùng tên (deduplicate) trong danh sách xử lý báo cáo.
    *   Cài đặt bộ chuẩn hóa Unicode dạng **NFC** cho mọi chuỗi văn bản so sánh tên nhân viên.
2.  **Giai đoạn 2 (Tối ưu hóa API & Tránh đơ Bot)**:
    *   Bao bọc tất cả các lời gọi hàm tương tác với Google Sheets bằng `asyncio.to_thread()`.
    *   Cải tiến [google_sheets.py](file:///E:/Du An/Python/Sober/Bot/google_sheets.py) để tải toàn bộ bảng `SoDuThuong` bằng `get_all_values()` một lần duy nhất, tránh dùng các hàm `cell()` trong vòng lặp.
3.  **Giai đoạn 3 (Bảo vệ dữ liệu)**:
    *   Tích hợp SQLite cục bộ để lưu trữ trạng thái `temp_reports`.

---
> [!TIP]
> Bạn có thể xem chi tiết báo cáo này bất kỳ lúc nào tại tệp tin: [qa_audit_report.md](file:///C:/Users/lehop/.gemini/antigravity/brain/7c0fe2f3-a852-4932-8349-88adf3b21233/qa_audit_report.md) trong thư mục lưu trữ dữ liệu.
