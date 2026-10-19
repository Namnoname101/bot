# Design Spec: Kiến trúc & Dọn dẹp Codebase (Architecture & Codebase Cleanup)

**Ngày:** 2026-10-19  
**Mục tiêu:** Chuẩn hóa môi trường kiểm thử, dọn dẹp thư mục gốc của dự án, và module hóa file `google_sheets.py` (2.600 dòng) thành kiến trúc đa tầng (Modular Mixins / Facade) mà vẫn bảo toàn 100% tương thích ngược với các handler và test hiện có.

---

## 1. Mục tiêu & Giới hạn (Goals & Non-Goals)

### Mục tiêu (Goals)
1. **Chuẩn hóa kiểm thử:** Lệnh `pytest` từ thư mục gốc chạy độc lập và vượt qua toàn bộ test trong `tests/` mà không bị gián đoạn bởi các script thử nghiệm trong `scripts/`.
2. **Dọn dẹp thư mục gốc:**
   - Di chuyển toàn bộ các script bảo trì/chạy 1 lần (`fix_*.py`, `append_*.py`, `test_*.py` ở root) vào `scripts/legacy/`.
   - Bỏ theo dõi (untrack khỏi git) các file dump/txt/zip/xlsx thừa mà không xóa dữ liệu người dùng.
   - Bổ sung quy tắc trong `.gitignore` ngăn chặn tái commit file rác.
3. **Module hóa `google_sheets.py`:**
   - Tách file 2.600 dòng thành package `services/sheets/` phân theo từng nghiệp vụ (domain).
   - `google_sheets.py` giữ vai trò Facade (hợp nhất các domain mixin) để không làm gãy bất kỳ import hay lời gọi hàm nào trong `main.py`, `handlers/`, `webapp/`, `scripts/` và `tests/`.

### Giới hạn (Non-Goals)
- Không thay đổi hành vi nghiệp vụ (business logic) của bot hay cấu trúc dữ liệu trên Google Sheets thật.
- Không thay đổi API contract của WebApp hay các lệnh Telegram hiện hành.

---

## 2. Thiết kế Chi tiết: Giai đoạn 1 - Kiểm thử & Dọn dẹp Root

### 2.1 Cấu hình `pytest.ini`
Tạo `pytest.ini` tại root dự án:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```
Đảm bảo khi gõ `pytest`, hệ thống chỉ phát hiện và chạy các bài test trong thư mục `tests/`.

### 2.2 Gom nhóm script chạy 1 lần vào `scripts/legacy/`
Tạo thư mục `scripts/legacy/` và di chuyển các file sau từ root:
- `append_handlers.py`, `append_handlers2.py`, `append_method.py`, `apply_fixes.py`
- `fix_dai.py`, `fix_names.py`, `restore_names.py`, `rename_sheets.py`
- `setup_formulas.py`, `update_formulas.py`, `update_salary_formulas.py`
- `research_sheet.py`, `generate_template.py`
- `test_advanced_audit.py`, `test_export.py`, `test_project_issues.py`, `test_salary_read.py`

### 2.3 Untrack file rác và cập nhật `.gitignore`
- Dùng `git rm --cached` với các file đã lỡ track:
  - `sober-bot-source.zip`
  - `mapping_output*.txt`, `output*.txt`, `rates_output*.txt`, `test_output*.txt`, `migration_info.txt`
- Cập nhật `.gitignore` bổ sung các pattern:
  - `*.zip`, `*.tar.gz`, `*.rar`
  - `*_output*.txt`, `output*.txt`, `mapping_output*.txt`, `rates_output*.txt`, `test_output*.txt`
  - `migration_info.txt`
  - `data/*.json` (ngoại trừ cấu hình mẫu nếu có)

---

## 3. Thiết kế Chi tiết: Giai đoạn 2 - Phân rã `google_sheets.py`

### 3.1 Cấu trúc Package `services/sheets/`
```text
services/
  __init__.py
  sheets/
    __init__.py
    base.py             # Client gspread, cache, lock, retry logic, connection
    attendance.py       # Check-in, check-out, ca trực, đi trễ, open sessions
    reward.py           # Số dư, thưởng ly, trừ thưởng, lịch sử thưởng
    revenue.py          # Báo cáo doanh thu ca, mapping cột doanh thu
    salary.py           # Bảng lương, chu kỳ lương, công thức, salary rate
    inventory.py        # Quản lý kho, nhập/xuất NVL, lịch sử kho, hàng sắp hết
    sync.py             # Đồng bộ đơn từ, đổi ca, chi vặt, công thức, account WebApp
    admin.py            # Danh sách admin, tăng ca (overtime)
```

### 3.2 Cơ chế Facade (`google_sheets.py`)
File `google_sheets.py` sẽ kế thừa toàn bộ các Mixin:
```python
from services.sheets.base import BaseSheetsService
from services.sheets.attendance import AttendanceSheetsMixin
from services.sheets.reward import RewardSheetsMixin
from services.sheets.revenue import RevenueSheetsMixin
from services.sheets.salary import SalarySheetsMixin
from services.sheets.inventory import InventorySheetsMixin
from services.sheets.sync import SyncSheetsMixin
from services.sheets.admin import AdminSheetsMixin
from utils.validators import normalize_name as _normalize_name_for_comparison

class GoogleSheetsService(
    BaseSheetsService,
    AttendanceSheetsMixin,
    RewardSheetsMixin,
    RevenueSheetsMixin,
    SalarySheetsMixin,
    InventorySheetsMixin,
    SyncSheetsMixin,
    AdminSheetsMixin,
):
    """Facade class tương thích ngược 100% với toàn bộ codebase."""
    pass
```

### 3.3 Đảm bảo tương thích ngược:
- Các hàm/phương thức tĩnh như `_column_letter`, `_current_salary_month`, `_salary_period` được giữ ở class `SalarySheetsMixin` (hoặc `GoogleSheetsService`) để test hiện tại (`tests/test_sheets_logic.py`) gọi trực tiếp `GoogleSheetsService._column_letter(27)` vẫn chạy chính xác.
- Biến toàn cục / helper cũ như `_normalize_name_for_comparison` được export tại `google_sheets.py`.

---

## 4. Kế hoạch Kiểm thử & Xác minh (Verification)

1. **Kiểm thử đơn vị:** Chạy `pytest` đảm bảo 64/64 test hiện hành đều PASS.
2. **Kiểm tra import & facade:** Viết test kiểm tra khởi tạo `GoogleSheetsService()` và sự hiện diện đầy đủ của các phương thức cốt lõi.
3. **Kiểm tra Git Cleanliness:** `git status` không còn file rác untracked hay script thừa ở thư mục gốc.
