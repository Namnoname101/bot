# Architecture & Codebase Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chuẩn hóa môi trường test, dọn dẹp thư mục gốc, và phân rã file monolithic `google_sheets.py` (2.600 dòng) thành kiến trúc Modular Domain Mixins với lớp Facade đảm bảo 100% tương thích ngược.

**Architecture:** Sử dụng mô hình Domain Mixins kết hợp Facade pattern. Toàn bộ logic trong `google_sheets.py` được chia tách thành các mixin độc lập theo từng domain trong package `services/sheets/` (`base.py`, `attendance.py`, `revenue.py`, `reward.py`, `salary.py`, `inventory.py`, `sync.py`, `admin.py`). Lớp `GoogleSheetsService` trong `google_sheets.py` kế thừa các mixin này, giữ nguyên chữ ký hàm, thuộc tính và phương thức tĩnh. Thư mục gốc được tinh giản bằng cách gom script cũ vào `scripts/legacy/` và loại bỏ file rác khỏi Git tracking.

**Tech Stack:** Python 3.13, pytest, gspread, google-api-python-client, python-telegram-bot

**Spec:** [docs/superpowers/specs/2026-10-19-architecture-and-codebase-cleanup-design.md](file:///e:/Du%20An/Python/Sober/Bot/docs/superpowers/specs/2026-10-19-architecture-and-codebase-cleanup-design.md)

## Global Constraints

- Không sửa đổi logic nghiệp vụ tính toán (doanh thu, lương, ca, thưởng, trừ tồn kho).
- Giữ nguyên chữ ký hàm và kiểu trả về của toàn bộ phương thức công khai trong `GoogleSheetsService`.
- Giữ nguyên các phương thức tĩnh/classmethod cũ: `_column_letter`, `_current_salary_month`, `_salary_period`.
- Giữ nguyên biến/hàm được export: `_normalize_name_for_comparison`.
- Toàn bộ 64 test hiện tại trong `tests/` phải luôn PASS ở mọi giai đoạn.

## Review Focus

1. **Khả năng import sau khi di chuyển file**: Các import dạng `from google_sheets import GoogleSheetsService` hoặc `from google_sheets import _normalize_name_for_comparison` không được phép lỗi.
2. **Kế thừa thuộc tính & Lock**: Các mixin cần dùng chung `self.client`, `self.gc`, `self.spreadsheet`, `self._cache`, `self._cache_lock` từ `BaseSheetsService` mà không gây xung đột `__init__`.
3. **Các static helper method**: `GoogleSheetsService._column_letter(27)` và các hàm tính toán chu kỳ lương phải được gọi trực tiếp từ class mà không cần khởi tạo instance.
4. **Không làm mất file dữ liệu người dùng**: Dùng `git rm --cached` để untrack các file output/backup, không dùng lệnh xóa vĩnh viễn tệp trên đĩa khi người dùng cần đối soát.
5. **Độ cô lập của Pytest**: Lệnh `pytest` ở thư mục gốc không được quét nhầm các file kiểm thử thử nghiệm trong `scripts/`.

---

### Task 1: Cấu hình `pytest.ini` & Xác nhận Test Suite

**Files:**
- Create: `pytest.ini`
- Test: `tests/`

**Interfaces:**
- Consumes: Cấu hình pytest
- Produces: Môi trường chạy test chuẩn hóa tại root

- [ ] **Step 1: Viết file cấu hình `pytest.ini` tại thư mục gốc**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

- [ ] **Step 2: Chạy lệnh `pytest` từ thư mục gốc**

Run: `pytest`  
Expected: PASS toàn bộ 64 tests (không bị lỗi SystemExit từ `scripts/test_all_logic.py`).

- [ ] **Step 3: Commit**

```bash
git add pytest.ini
git commit -m "chore: add pytest.ini to constrain test collection to tests directory"
```

---

### Task 2: Dọn dẹp Root - Di chuyển Script Chạy 1 Lần vào `scripts/legacy/`

**Files:**
- Create directory: `scripts/legacy/`
- Move from root:
  - `append_handlers.py`, `append_handlers2.py`, `append_method.py`, `apply_fixes.py`
  - `fix_dai.py`, `fix_names.py`, `restore_names.py`, `rename_sheets.py`
  - `setup_formulas.py`, `update_formulas.py`, `update_salary_formulas.py`
  - `research_sheet.py`, `generate_template.py`
  - `test_advanced_audit.py`, `test_export.py`, `test_project_issues.py`, `test_salary_read.py`

**Interfaces:**
- Consumes: N/A
- Produces: Thư mục `scripts/legacy/` chứa các script bảo trì cũ

- [ ] **Step 1: Tạo thư mục `scripts/legacy/` và di chuyển 17 file script**

Di chuyển toàn bộ các script bảo trì chạy 1 lần từ thư mục gốc vào `scripts/legacy/` bằng `git mv`.

- [ ] **Step 2: Chạy kiểm thử để đảm bảo không file production nào bị ảnh hưởng**

Run: `pytest`  
Expected: PASS toàn bộ 64 tests.

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor: move one-off maintenance and audit scripts to scripts/legacy"
```

---

### Task 3: Dọn dẹp Root - Untrack File Rác và Cập nhật `.gitignore`

**Files:**
- Modify: `.gitignore`
- Untrack in git:
  - `sober-bot-source.zip`
  - `mapping_output.txt`, `mapping_output3.txt`, `output.txt`, `output_inline.txt`, `output_mapping.txt`, `output_sodu.txt`, `rates_output.txt`, `rates_output2.txt`, `test_output.txt`, `test_output2.txt`, `migration_info.txt`

**Interfaces:**
- Consumes: N/A
- Produces: `.gitignore` đầy đủ pattern bảo vệ repo

- [ ] **Step 1: Cập nhật `.gitignore`**

Thêm các rule cho file nén, output dump, txt research:
```gitignore
*.zip
*_output*.txt
output*.txt
mapping_output*.txt
rates_output*.txt
test_output*.txt
migration_info.txt
sheet_research*.txt
temp_logs*.txt
*.coverage
```

- [ ] **Step 2: Untrack các file rác bằng `git rm --cached`**

Run: `git rm --cached sober-bot-source.zip mapping_output*.txt output*.txt rates_output*.txt test_output*.txt migration_info.txt`  
Expected: Files được bỏ theo dõi trong Git nhưng vẫn giữ nguyên trên đĩa nếu người dùng cần.

- [ ] **Step 3: Kiểm tra `git status` và chạy test**

Run: `git status; pytest`  
Expected: Git status sạch, không có file rác untracked; 64 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: untrack legacy output dumps and archive files, update .gitignore"
```

---

### Task 4: Thiết lập Package `services/sheets/` và `base.py`

**Files:**
- Create: `services/__init__.py`
- Create: `services/sheets/__init__.py`
- Create: `services/sheets/base.py`
- Create: `tests/test_sheets_base.py`

**Interfaces:**
- Consumes: `config.Config`, `gspread`, `oauth2client`
- Produces: `BaseSheetsService` cung cấp:
  - `__init__(self, max_retries=3)`
  - `_init_connections(self, max_retries)`
  - `_get_cache(self, key, ttl_seconds)`
  - `_set_cache(self, key, value)`
  - `_invalidate_cache(self, *keys_or_prefixes)`
  - `_get_or_create_custom_sheet(self, title, default_headers)`

- [ ] **Step 1: Viết test cho `BaseSheetsService` trong `tests/test_sheets_base.py`**

Test logic cache, invalidation và khởi tạo cơ bản:
```python
import unittest
from services.sheets.base import BaseSheetsService

class TestBaseSheetsService(unittest.TestCase):
    def test_cache_set_get_invalidate(self):
        svc = BaseSheetsService.__new__(BaseSheetsService)
        svc._cache = {}
        svc._cache_lock = None
        svc._set_cache("key1", "val1")
        self.assertEqual(svc._get_cache("key1"), "val1")
        svc._invalidate_cache("key1")
        self.assertIsNone(svc._get_cache("key1"))
```

- [ ] **Step 2: Chạy test để xác nhận FAIL vì module chưa tồn tại**

Run: `pytest tests/test_sheets_base.py -v`  
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Triển khai `services/sheets/base.py`**

Trích xuất phần khởi tạo kết nối Google API, gspread client, drive client, cache mechanism (`_get_cache`, `_set_cache`, `_invalidate_cache`), thread locks và helper tạo custom sheet từ `google_sheets.py`.

- [ ] **Step 4: Chạy lại test `test_sheets_base.py`**

Run: `pytest tests/test_sheets_base.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/ tests/test_sheets_base.py
git commit -m "feat(sheets): introduce BaseSheetsService with connection and caching"
```

---

### Task 5: Trích xuất các Domain Mixin: Attendance, Revenue & Admin

**Files:**
- Create: `services/sheets/attendance.py` (`AttendanceSheetsMixin`)
- Create: `services/sheets/revenue.py` (`RevenueSheetsMixin`)
- Create: `services/sheets/admin.py` (`AdminSheetsMixin`)

**Interfaces:**
- Consumes: `BaseSheetsService`
- Produces:
  - `AttendanceSheetsMixin`: `_get_shift_info`, `get_checked_in_employees`, `get_open_checkin_sessions`, `checkin`, `checkout`, `mark_reported_late`, `mark_unreported_late`, `get_checkin_history_today`, `get_late_statistics`.
  - `RevenueSheetsMixin`: `save_report`, `_save_report_unlocked`, `_get_mapping_worksheet`, `_get_mapping_indices`, `get_recent_revenue_reports`, `update_report_revenue`.
  - `AdminSheetsMixin`: `_get_admin_worksheet`, `get_admin_list`, `add_admin`, `add_overtime`, `get_overtime_summary`.

- [ ] **Step 1: Viết module `services/sheets/attendance.py`**
Di chuyển logic chấm công và xử lý phiên trực từ `google_sheets.py`.

- [ ] **Step 2: Viết module `services/sheets/revenue.py`**
Di chuyển logic báo cáo doanh thu ca và mapping sheet từ `google_sheets.py`.

- [ ] **Step 3: Viết module `services/sheets/admin.py`**
Di chuyển logic admin permissions và overtime từ `google_sheets.py`.

- [ ] **Step 4: Commit**

```bash
git add services/sheets/attendance.py services/sheets/revenue.py services/sheets/admin.py
git commit -m "feat(sheets): extract attendance, revenue, and admin domain mixins"
```

---

### Task 6: Trích xuất các Domain Mixin: Reward, Salary, Inventory & Sync

**Files:**
- Create: `services/sheets/reward.py` (`RewardSheetsMixin`)
- Create: `services/sheets/salary.py` (`SalarySheetsMixin`)
- Create: `services/sheets/inventory.py` (`InventorySheetsMixin`)
- Create: `services/sheets/sync.py` (`SyncSheetsMixin`)

**Interfaces:**
- Consumes: `BaseSheetsService`
- Produces:
  - `RewardSheetsMixin`: `get_balance`, `get_all_balances`, `get_all_nicknames`, `get_employees_detail`, `update_balance`, `_update_balance_unlocked`, `batch_update_balances`, `_batch_update_balances_unlocked`, `consume_reward`, `add_employee`, `rename_employee`, `remove_employee`, `get_reward_history`, `get_employee_personal_summary`.
  - `SalarySheetsMixin`: `_column_letter`, `_current_salary_month`, `_salary_period`, `_number`, `_get_salary_worksheet`, `ensure_salary_worksheet`, `get_salary_month_options`, `get_salary_report`, `get_salary_data`, `get_all_salary_rates`, `update_salary_rate`, `update_salary_modifier`.
  - `InventorySheetsMixin`: `_clean_item_name`, `_parse_float`, `_get_current_monthly_ws`, `_get_inventory_ws`, `_get_metadata_map`, `get_all_materials`, `get_material_groups`, `_locate_item_on_monthly_ws`, `add_material`, `update_material`, `remove_material`, `import_stock`, `batch_import_stock`, `export_stock`, `batch_export_stock`, `get_inventory_history`, `get_low_stock_items`.
  - `SyncSheetsMixin`: `append_sheet_leave_request`, `update_sheet_leave_request_status`, `load_sheet_leave_requests`, `append_sheet_petty_expense`, `load_sheet_petty_expenses`, `sync_sheet_recipes`, `load_sheet_recipes`, `save_sheet_shift_schedule`, `load_sheet_shift_schedules`, `save_sheet_account`, `load_sheet_accounts`, `sync_sheet_employee_roles`, `load_sheet_employee_roles`.

- [ ] **Step 1: Viết module `services/sheets/reward.py`**
- [ ] **Step 2: Viết module `services/sheets/salary.py`**
- [ ] **Step 3: Viết module `services/sheets/inventory.py`**
- [ ] **Step 4: Viết module `services/sheets/sync.py`**
- [ ] **Step 5: Commit**

```bash
git add services/sheets/reward.py services/sheets/salary.py services/sheets/inventory.py services/sheets/sync.py
git commit -m "feat(sheets): extract reward, salary, inventory, and sync domain mixins"
```

---

### Task 7: Cập nhật `google_sheets.py` thành Facade & Xác minh Tương thích Ngược 100%

**Files:**
- Modify: `google_sheets.py`
- Test: `tests/test_sheets_logic.py`, `tests/`

**Interfaces:**
- Consumes: Tất cả mixins từ `services/sheets/`
- Produces: `GoogleSheetsService` (Facade Class) & `_normalize_name_for_comparison`

- [ ] **Step 1: Cập nhật `google_sheets.py` kế thừa toàn bộ domain mixins**

`google_sheets.py` trở thành file gọn gàng (~60 dòng):
```python
from services.sheets.base import BaseSheetsService
from services.sheets.attendance import AttendanceSheetsMixin
from services.sheets.revenue import RevenueSheetsMixin
from services.sheets.admin import AdminSheetsMixin
from services.sheets.reward import RewardSheetsMixin
from services.sheets.salary import SalarySheetsMixin
from services.sheets.inventory import InventorySheetsMixin
from services.sheets.sync import SyncSheetsMixin
from utils.validators import normalize_name as _normalize_name_for_comparison

class GoogleSheetsService(
    BaseSheetsService,
    AttendanceSheetsMixin,
    RevenueSheetsMixin,
    AdminSheetsMixin,
    RewardSheetsMixin,
    SalarySheetsMixin,
    InventorySheetsMixin,
    SyncSheetsMixin,
):
    """Facade class tương thích ngược hoàn toàn với hệ thống cũ."""
    pass
```

- [ ] **Step 2: Chạy toàn bộ test suite `pytest`**

Run: `pytest`  
Expected: PASS toàn bộ 64 tests hiện tại + test mới (không có bất kỳ regression nào).

- [ ] **Step 3: Kiểm tra smoke test khởi tạo và gọi static helper**

Run: `python -c "from google_sheets import GoogleSheetsService, _normalize_name_for_comparison; print('Letter 27:', GoogleSheetsService._column_letter(27)); print('Norm:', _normalize_name_for_comparison('Hòa'))"`  
Expected: In ra `Letter 27: AA` và `Norm: hoa`.

- [ ] **Step 4: Commit**

```bash
git add google_sheets.py
git commit -m "refactor(sheets): convert google_sheets.py to modular facade architecture"
```
