# Employee Penalty System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây dựng hệ thống lập biên bản phạt kỷ luật cố định 10.000đ/lần trên Bot Telegram và WebApp, tự động trừ vào bảng lương tháng, hiển thị minh bạch cho nhân viên và có bảng xếp hạng phạt.

**Architecture:** Mở rộng `WebAppStore` với mục `penalties`, đồng bộ tự động lên Google Sheets tab `Lịch Sử Phạt`. Tích hợp quy tắc trừ lương trong `SalarySheetsMixin` và `RewardSheetsMixin`. Bổ sung flow chọn nhân viên + nhập lý do trên Bot Telegram thông báo vào nhóm quán, kèm các API endpoints và giao diện WebApp (xem phạt cá nhân và bảng xếp hạng).

**Tech Stack:** Python 3.11/3.13, python-telegram-bot, aiohttp, gspread, Vanilla JS/CSS/HTML5, pytest, unittest.

**Spec:** [docs/superpowers/specs/2026-10-20-employee-penalty-system-design.md](file:///e:/Du%20An/Python/Sober/Bot/docs/superpowers/specs/2026-10-20-employee-penalty-system-design.md)

## Global Constraints

- Mức phạt là cố định **10.000đ/lần** (10k), không cho phép nhập số tiền khác.
- Kỳ lương tính phạt đồng bộ chuẩn kỳ quán: từ ngày 17 tháng trước đến ngày 16 tháng này (`_salary_period` / `_salary_window`).
- Mọi thao tác phạt phải gửi thông báo công khai vào `Config.GROUP_CHAT_ID`.
- Dữ liệu phạt phải được lưu trữ bền vững trong `store.json` và đồng bộ vào tab `Lịch Sử Phạt` trên Google Sheets.
- Không phá vỡ backward compatibility với 78 bài test hiện có.

## Review Focus

1. **Chuỗi nickname có ký tự đặc biệt hoặc chữ hoa/thường:** Tìm kiếm và đếm số lần phạt phải dùng `normalize_name(nick)` để tránh sót phạt.
2. **Kỳ lương chuyển năm (Tháng 12 → Tháng 1):** Bộ lọc ngày phạt trong kỳ lương phải khớp chính xác ngày 17 đến 16 qua ranh giới năm mới.
3. **Lý do phạt để trống hoặc chứa toàn khoảng trắng:** Hệ thống phải validate và từ chối, yêu cầu nhập lý do rõ ràng.
4. **Nhân viên không có trong danh sách quán:** Không cho phép lập biên bản phạt đối với tên không tồn tại.
5. **Gửi tin nhắn nhóm thất bại:** Nếu gửi thông báo nhóm gặp lỗi mạng, biên bản phạt vẫn phải được ghi nhận vào hệ thống thành công (không crash bot).

---

### Task 1: Store & Sheets Sync Foundation (`penalties`)

**Files:**
- Create: `tests/test_penalties.py`
- Modify: `webapp/store.py`
- Modify: `services/sheets/sync.py`

**Interfaces:**
- Produces:
  - `store.add_penalty(nickname: str, reason: str, admin_name: str, created_at: str | None = None) -> dict`
  - `store.get_penalties(nickname: str | None = None, start_date: date | None = None, end_date: date | None = None) -> list[dict]`
  - `store.get_penalties_leaderboard(start_date: date | None = None, end_date: date | None = None) -> list[dict]`
  - `sheets.save_sheet_penalty(penalty_record: dict) -> bool`
  - `sheets.load_sheet_penalties() -> list[dict]`

- [ ] **Step 1: Write failing tests in `tests/test_penalties.py`**

```python
import unittest
from datetime import date
from webapp.store import WebAppStore

class PenaltyStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = WebAppStore(store_file=":memory:")

    def test_add_penalty_fixed_amount_and_validation(self):
        rec = self.store.add_penalty(nickname="Tuấn", reason="Quên tắt máy pha", admin_name="Admin")
        self.assertEqual(rec["amount"], 10000)
        self.assertEqual(rec["nickname"], "Tuấn")
        self.assertEqual(rec["reason"], "Quên tắt máy pha")
        self.assertEqual(rec["admin_name"], "Admin")

        with self.assertRaises(ValueError):
            self.store.add_penalty(nickname="", reason="Hợp lệ", admin_name="Admin")
        with self.assertRaises(ValueError):
            self.store.add_penalty(nickname="Tuấn", reason="   ", admin_name="Admin")

    def test_get_penalties_and_leaderboard(self):
        self.store.add_penalty(nickname="Tuấn", reason="Lỗi 1", admin_name="Admin", created_at="10:00 20/10/2026")
        self.store.add_penalty(nickname="Tuấn", reason="Lỗi 2", admin_name="Admin", created_at="11:00 20/10/2026")
        self.store.add_penalty(nickname="An", reason="Lỗi 3", admin_name="Admin", created_at="12:00 20/10/2026")

        tuan_fines = self.store.get_penalties(nickname="Tuấn")
        self.assertEqual(len(tuan_fines), 2)

        board = self.store.get_penalties_leaderboard()
        self.assertEqual(board[0]["nickname"], "Tuấn")
        self.assertEqual(board[0]["count"], 2)
        self.assertEqual(board[0]["total_amount"], 20000)
        self.assertEqual(board[1]["nickname"], "An")
        self.assertEqual(board[1]["count"], 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_penalties.py -v`
Expected: FAIL with "AttributeError: 'WebAppStore' object has no attribute 'add_penalty'"

- [ ] **Step 3: Implement `add_penalty`, `get_penalties`, `get_penalties_leaderboard` in `webapp/store.py` and sync in `services/sheets/sync.py`**

Implement store methods and sheet sync tab `Lịch Sử Phạt`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_penalties.py -v`
Expected: PASS (all tests pass)

- [ ] **Step 5: Commit**

```bash
git add tests/test_penalties.py webapp/store.py services/sheets/sync.py
git commit -m "feat(penalty): add penalty store and sheets sync with 10k fixed amount"
```

---

### Task 2: Payroll Deduction Integration (`services/sheets/salary.py` & `reward.py`)

**Files:**
- Modify: `services/sheets/salary.py`
- Modify: `services/sheets/reward.py`
- Test: `tests/test_penalties.py`

**Interfaces:**
- Consumes: `store.get_penalties(...)`
- Produces:
  - `salary_data['items'][i]['penalty_amount']`
  - `salary_data['items'][i]['penalty_count']`
  - `salary_data['items'][i]['total']` (reflects -penalty_amount)
  - `personal_summary['penalty_amount_k']`
  - `personal_summary['penalty_count']`

- [ ] **Step 1: Write failing test in `tests/test_penalties.py` verifying salary calculation includes penalty deduction**

```python
    def test_salary_deduction_includes_penalties(self):
        # 10h x 20k = 200k base. 2 penalties = -20k. Total = 180k.
        ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_penalties.py -k test_salary_deduction_includes_penalties -v`
Expected: FAIL

- [ ] **Step 3: Update `get_salary_data` and `get_personal_summary` to incorporate penalties**

Deduct `penalty_count * 10k` from net salary for the corresponding period.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_penalties.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/sheets/salary.py services/sheets/reward.py tests/test_penalties.py
git commit -m "feat(salary): integrate automatic penalty deductions into payroll calculations"
```

---

### Task 3: Telegram Bot Penalty Flow & Commands

**Files:**
- Modify: `handlers/management_handler.py`
- Modify: `handlers/reward_handler.py`
- Modify: `main.py`
- Test: `tests/test_penalties.py`

**Interfaces:**
- Produces:
  - `handle_fine_list_button(update, context)`
  - `handle_fine_select_emp(query, context, nickname)`
  - `handle_fine_reason_input(update, context)`
  - `bangphat_command(update, context)`
  - `xemphat_command(update, context)`
  - `phat_command(update, context)`

- [ ] **Step 1: Write test for bot handlers in `tests/test_penalties.py`**

Test helper functions and state management for penalty inputs.

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_penalties.py -k test_bot -v`
Expected: FAIL

- [ ] **Step 3: Implement bot handlers and commands**

Add `[ ⚠️ Phạt Nhân Viên (10k) ]` button, `/phat`, `/bangphat`, `/xemphat`, and public notification dispatch to `GROUP_CHAT_ID`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_penalties.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add handlers/management_handler.py handlers/reward_handler.py main.py tests/test_penalties.py
git commit -m "feat(bot): add penalty button, /phat, /bangphat, /xemphat commands with group notifications"
```

---

### Task 4: WebApp API Endpoints

**Files:**
- Modify: `webapp/server.py`
- Test: `tests/test_webapp.py`

**Interfaces:**
- Produces:
  - `GET /api/penalties`
  - `POST /api/admin/penalties/add`
  - Updates to `GET /api/bootstrap` (adds `personal_penalties` and `penalties_leaderboard`)

- [ ] **Step 1: Write integration test in `tests/test_webapp.py`**

Test `GET /api/penalties` and `POST /api/admin/penalties/add` endpoints.

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_webapp.py -k test_penalties_api -v`
Expected: FAIL (404 Not Found)

- [ ] **Step 3: Implement endpoints in `webapp/server.py`**

Add routes and handler functions with admin validation.

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_webapp.py -k test_penalties_api -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add webapp/server.py tests/test_webapp.py
git commit -m "feat(api): add penalties get and admin add endpoints"
```

---

### Task 5: WebApp Frontend Integration

**Files:**
- Modify: `webapp/static/index.html`
- Modify: `webapp/static/styles.css`
- Modify: `webapp/static/app.js`

**Interfaces:**
- Produces:
  - Employee view: `⚠️ Phạt kỷ luật (-10k/lần)` breakdown row with click-to-view history modal.
  - Admin view: Leaderboard card in Overview and Penalty deduction display in Payroll tab.
  - Admin action: Quick fine modal in WebApp.

- [ ] **Step 1: Update `webapp/static/index.html`**

Add penalty breakdown row in employee payroll card, penalty leaderboard widget in Admin Overview, and penalty history modal.

- [ ] **Step 2: Update `webapp/static/styles.css`**

Add styles for `.penalty-badge`, `.leaderboard-rank`, `.penalty-history-card`.

- [ ] **Step 3: Update `webapp/static/app.js`**

Implement `renderEmployeePenalties()`, `renderAdminPenaltiesLeaderboard()`, `openQuickFineModal()`, `submitQuickFine()`.

- [ ] **Step 4: Run full test suite to verify no regressions**

Run: `pytest`
Expected: PASS (all tests pass, 100%)

- [ ] **Step 5: Commit**

```bash
git add webapp/static/index.html webapp/static/styles.css webapp/static/app.js
git commit -m "feat(ui): add penalty breakdown, history modal, and leaderboard to webapp"
```
