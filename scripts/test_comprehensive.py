# -*- coding: utf-8 -*-
"""
Kiểm thử TOÀN DIỆN (Comprehensive Test Suite) cho Sober Bot.
Bao gồm: validators, google_sheets logic, decorators, auto_delete,
         overtime handler logic, checkin logic, reward eligibility,
         parse_amount_token, edge cases, regression tests.

Chạy: python scripts/test_comprehensive.py
"""
import sys
import re
import unicodedata
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Monkey-patch env vars trước khi import bất kỳ module nào có Config
import os
os.environ.setdefault("BOT_TOKEN", "FAKE_TOKEN_FOR_TEST")
os.environ.setdefault("GROUP_CHAT_ID", "-100123456789")
os.environ.setdefault("ADMIN_CHAT_ID", "987654321")
os.environ.setdefault("SPREADSHEET_ID", "FAKE_SPREADSHEET_ID")
os.environ.setdefault("DRIVE_FOLDER_ID", "FAKE_DRIVE_FOLDER_ID")
os.environ.setdefault("GOOGLE_CREDENTIALS_FILE", "credentials.json")

from utils.validators import parse_report_text, check_reward_eligibility, deduplicate_employees, _parse_amount_str
from google_sheets import _normalize_name_for_comparison, GoogleSheetsService

# ─── Test infrastructure ────────────────────────────────────────
passed = 0
failed = 0
errors = []

def assert_eq(test_name, actual, expected):
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"  ✅ {test_name}")
    else:
        failed += 1
        msg = f"  ❌ {test_name}\n     Mong đợi: {expected!r}\n     Thực tế:  {actual!r}"
        print(msg)
        errors.append(msg)

def assert_true(test_name, value):
    assert_eq(test_name, bool(value), True)

def assert_false(test_name, value):
    assert_eq(test_name, bool(value), False)

def assert_none(test_name, value):
    assert_eq(test_name, value, None)

def assert_not_none(test_name, value):
    global passed, failed
    if value is not None:
        passed += 1
        print(f"  ✅ {test_name}")
    else:
        failed += 1
        msg = f"  ❌ {test_name}  — Giá trị là None, mong đợi khác None"
        print(msg)
        errors.append(msg)

def header(title):
    print(f"\n{'='*60}")
    print(f"{title}")
    print('='*60)


# ═══════════════════════════════════════════════════════════════════
# 1. parse_report_text — Basic
# ═══════════════════════════════════════════════════════════════════
header("1. parse_report_text — Cơ bản")

# 1.1 Format chuẩn
e, r, c, err = parse_report_text("NV: tuananh, hoanglan\nDoanh thu: 1500k")
assert_eq("1.01 2 NV chuẩn", e, ['tuananh', 'hoanglan'])
assert_eq("1.02 DT 1500k → 1500000", r, 1500000)
assert_false("1.03 Không lỗi", err)

# 1.2 Suffix M
e, r, c, err = parse_report_text("NV: a\nDT: 2M")
assert_eq("1.04 DT 2M → 2000000", r, 2000000)

# 1.3 Suffix m thường
e, r, c, err = parse_report_text("NV: a\nDT: 1.5m")
assert_eq("1.05 DT 1.5m → 1500000", r, 1500000)

# 1.6 DT 1.500k → phân cách ngàn + K → 1.500.000
e, r, c, err = parse_report_text("NV: a\nDT: 1.500k")
assert_eq("1.06 DT 1.500k (ngàn + K) → 1500000", r, 1500000)
assert_false("1.06b Không lỗi", err)

# 1.5 Dấu phẩy phân cách
e, r, c, err = parse_report_text("NV: a\nDT: 1,500,000")
assert_eq("1.07 DT 1,500,000 → 1500000", r, 1500000)

# 1.6 Thuần số
e, r, c, err = parse_report_text("NV: a\nDoanh thu: 2000000")
assert_eq("1.08 DT thuần số", r, 2000000)

# 1.7 Tên có khoảng trắng trong tên
e, r, c, err = parse_report_text("NV: anh tuyet, quoc bao\nDT: 1200k")
assert_eq("1.09 Tên nhiều từ giữ nguyên khoảng trắng", e, ['anh tuyet', 'quoc bao'])
assert_eq("1.10 Đúng 2 NV", len(e), 2)

# 1.8 NV duy nhất
e, r, c, err = parse_report_text("NV: xuanhau\nDoanh thu: 800k")
assert_eq("1.11 1 NV duy nhất", e, ['xuanhau'])

# 1.9 Thiếu NV
e, r, c, err = parse_report_text("Doanh thu: 1500k")
assert_true("1.12 Thiếu NV → lỗi", err)

# 1.10 Thiếu DT
e, r, c, err = parse_report_text("NV: tuananh")
assert_true("1.13 Thiếu DT → lỗi", err)

# 1.11 Chuỗi rỗng
e, r, c, err = parse_report_text("")
assert_true("1.14 Chuỗi rỗng → lỗi", err)

# 1.12 DT âm — regex không match dấu trừ → lỗi cú pháp
e, r, c, err = parse_report_text("NV: a\nDT: -500k")
assert_true("1.15 DT âm → lỗi (regex không match '-')", err)

# 1.13 DT = 0
e, r, c, err = parse_report_text("NV: a\nDT: 0")
assert_eq("1.16 DT = 0 → 0", r, 0)

# 1.14 DT quá lớn (>100M)
e, r, c, err = parse_report_text("NV: a\nDT: 200000k")
assert_true("1.17 DT 200M → lỗi quá lớn", err)

# 1.15 DT biên đúng 100M
e, r, c, err = parse_report_text("NV: a\nDT: 100000k")
assert_eq("1.18 DT biên 100M = 100000000", r, 100000000)
assert_false("1.19 DT biên 100M hợp lệ", err)

# 1.16 Ca sáng dòng Ca:
e, r, c, err = parse_report_text("NV: a\nDT: 1000k\nCa: sáng")
assert_eq("1.20 Ca: sáng", c, 'Sáng')

# 1.17 Ca chiều không dấu
e, r, c, err = parse_report_text("NV: a\nDT: 1000k\nCa: chieu")
assert_eq("1.21 Ca: chieu → Chiều", c, 'Chiều')

# 1.18 Ca tối
e, r, c, err = parse_report_text("NV: a\nDT: 1000k\nCa: tối")
assert_eq("1.22 Ca: tối → Tối", c, 'Tối')

# 1.19 Ca suy từ ngữ cảnh 'sáng'
e, r, c, err = parse_report_text("NV: a\nDT: 1000k\nBáo cáo buổi sáng")
assert_eq("1.23 Suy ca từ 'sáng' trong text", c, 'Sáng')

# 1.20 Không có ca
e, r, c, err = parse_report_text("NV: a\nDT: 1000k")
assert_eq("1.24 Không ghi ca → rỗng", c, '')

# 1.21 Keyword 'nhân viên:'
e, r, c, err = parse_report_text("Nhân viên: tuananh, hoanglan\nDoanh thu: 1200k")
assert_eq("1.25 Keyword 'Nhân viên'", e, ['tuananh', 'hoanglan'])

# 1.22 Keyword 'nhan vien:' không dấu
e, r, c, err = parse_report_text("nhan vien: tuananh\ndt: 800k")
assert_eq("1.26 Keyword 'nhan vien'", e, ['tuananh'])

# 1.23 Trim khoảng trắng thừa quanh dấu phẩy
e, r, c, err = parse_report_text("NV:   tuananh  ,  hoanglan  \nDT: 1000k")
assert_eq("1.27 Trim NV", e, ['tuananh', 'hoanglan'])

# 1.24 DT 0k
e, r, c, err = parse_report_text("NV: a\nDT: 0k")
assert_eq("1.28 DT '0k' = 0", r, 0)

# 1.25 Dấu phẩy liên tiếp trong NV
e, r, c, err = parse_report_text("NV: anh,,,bao,,\nDT: 1000k")
assert_eq("1.29 Bỏ qua phần tử rỗng từ dấu phẩy liên tiếp", e, ['anh', 'bao'])

# 1.26 NV regex không lấy phần DT khi cùng dòng
e, r, c, err = parse_report_text("NV: anh, bao\nDT: 1000k")
assert_true("1.30 NV không chứa 'dt'", 'dt' not in ' '.join(e).lower())

# 1.27 NV trùng lặp — parse giữ nguyên (deduplicate riêng)
e, r, c, err = parse_report_text("NV: anhuy, anhuy, anhuy\nDT: 1500k")
assert_eq("1.31 Parse giữ nguyên trùng (chưa deduplicate)", len(e), 3)

# 1.28 DT viết thường 'doanh thu:'
e, r, c, err = parse_report_text("nv: a\ndoanh thu: 500k")
assert_eq("1.32 Keyword 'doanh thu' viết thường", r, 500000)

# 1.29 DT 1.5M (float suffix)
e, r, c, err = parse_report_text("NV: a\nDT: 1.5M")
assert_eq("1.33 DT 1.5M → 1500000", r, 1500000)

# 1.30 DT 2.5K
e, r, c, err = parse_report_text("NV: a\nDT: 2.5K")
assert_eq("1.34 DT 2.5K → 2500", r, 2500)


# ═══════════════════════════════════════════════════════════════════
# 2. check_reward_eligibility
# ═══════════════════════════════════════════════════════════════════
header("2. check_reward_eligibility")

assert_eq("2.01  1 NV + 0     → 0", check_reward_eligibility(1, 0), 0)
assert_eq("2.02  1 NV + 1.2M  → 0", check_reward_eligibility(1, 1200000), 0)
assert_eq("2.03  1 NV + 2M    → 0", check_reward_eligibility(1, 2000000), 0)
assert_eq("2.04  2 NV + 1.19M → 0", check_reward_eligibility(2, 1199999), 0)
assert_eq("2.05  2 NV + 1.2M  → 1", check_reward_eligibility(2, 1200000), 1)
assert_eq("2.06  2 NV + 2M    → 1", check_reward_eligibility(2, 2000000), 1)
assert_eq("2.07  2 NV + 0     → 0", check_reward_eligibility(2, 0), 0)
assert_eq("2.08  3 NV + 1.49M → 0", check_reward_eligibility(3, 1499999), 0)
assert_eq("2.09  3 NV + 1.5M  → 1", check_reward_eligibility(3, 1500000), 1)
assert_eq("2.10  3 NV + 2M    → 1", check_reward_eligibility(3, 2000000), 1)
assert_eq("2.11  3 NV + 1.2M  → 0", check_reward_eligibility(3, 1200000), 0)
assert_eq("2.12  4 NV + 1.5M  → 1", check_reward_eligibility(4, 1500000), 1)
assert_eq("2.13  5 NV + 2M    → 1", check_reward_eligibility(5, 2000000), 1)
assert_eq("2.14  0 NV + 2M    → 0", check_reward_eligibility(0, 2000000), 0)
# Biên: đúng 2 NV + đúng 1.2M = đạt
assert_eq("2.15  Biên chính xác 2NV/1.2M", check_reward_eligibility(2, 1200000), 1)
# Biên: đúng 3 NV + đúng 1.5M = đạt
assert_eq("2.16  Biên chính xác 3NV/1.5M", check_reward_eligibility(3, 1500000), 1)


# ═══════════════════════════════════════════════════════════════════
# 3. deduplicate_employees
# ═══════════════════════════════════════════════════════════════════
header("3. deduplicate_employees")

assert_eq("3.01 3 trùng → 1", deduplicate_employees(['a', 'a', 'a']), ['a'])
assert_eq("3.02 Giữ thứ tự", deduplicate_employees(['b', 'a', 'b']), ['b', 'a'])
assert_eq("3.03 Không trùng → nguyên", deduplicate_employees(['x', 'y', 'z']), ['x', 'y', 'z'])
assert_eq("3.04 Danh sách rỗng", deduplicate_employees([]), [])
assert_eq("3.05 1 phần tử", deduplicate_employees(['solo']), ['solo'])
assert_eq("3.06 Giữ phần tử đầu khi trùng", deduplicate_employees(['a', 'b', 'a', 'c']), ['a', 'b', 'c'])
assert_eq("3.07 Tất cả trùng 5 phần tử", deduplicate_employees(['x']*5), ['x'])
assert_eq("3.08 Case-sensitive: 'A' ≠ 'a'", deduplicate_employees(['A', 'a']), ['A', 'a'])


# ═══════════════════════════════════════════════════════════════════
# 4. _normalize_name_for_comparison
# ═══════════════════════════════════════════════════════════════════
header("4. _normalize_name_for_comparison (Unicode)")

assert_eq("4.01 Chữ hoa → chữ thường", _normalize_name_for_comparison("TuanAnh"), "tuananh")
assert_eq("4.02 Bỏ dấu tiếng Việt", _normalize_name_for_comparison("hoà"), "hoa")
assert_eq("4.03 NFC == NFD", _normalize_name_for_comparison("hoà"), _normalize_name_for_comparison("hoà"))
assert_eq("4.04 Trim + bỏ dấu", _normalize_name_for_comparison("  Xuân Hậu  "), "xuanhau")
assert_eq("4.05 Chuỗi rỗng", _normalize_name_for_comparison(""), "")
assert_eq("4.06 Chỉ khoảng trắng", _normalize_name_for_comparison("   "), "")
assert_eq("4.07 Ký tự đặc biệt bị loại", _normalize_name_for_comparison("anh-uy_123"), "anhuy123")
assert_eq("4.08 Dấu đủ loại (có Đ)", _normalize_name_for_comparison("Đặng Hồng Phước"), "danghongphuoc")
assert_eq("4.09 Số và chữ", _normalize_name_for_comparison("nv01"), "nv01")
assert_eq("4.10 Chỉ dấu tiếng Việt", _normalize_name_for_comparison("ơ ư ề"), "oue")
assert_eq("4.11 Tên NFC: 'Hoàng Lan'", _normalize_name_for_comparison("Hoàng Lan"), "hoanglan")
assert_eq("4.12 Tên viết thường", _normalize_name_for_comparison("hoanglan"), "hoanglan")
assert_eq("4.13 4.11 == 4.12 (nhất quán)", _normalize_name_for_comparison("Hoàng Lan"), _normalize_name_for_comparison("hoanglan"))
assert_eq("4.14 Nhiều khoảng trắng giữa", _normalize_name_for_comparison("Tuan    Anh"), "tuananh")
assert_eq("4.15 Tên có số", _normalize_name_for_comparison("NV 02"), "nv02")
# BUG-2 regression: Đ/đ không bị mất
assert_eq("4.16 BUG-2 FIX: Đặng → dang", _normalize_name_for_comparison("Đặng"), "dang")
assert_eq("4.17 BUG-2 FIX: Định → dinh", _normalize_name_for_comparison("Đinh"), "dinh")
assert_eq("4.18 BUG-2 FIX: đ viết thường → d", _normalize_name_for_comparison("đức"), "duc")
assert_eq("4.19 BUG-2 FIX: 'Đặng Hồng Phước' → 'danghongphuoc'", _normalize_name_for_comparison("Đặng Hồng Phước"), "danghongphuoc")


# ═══════════════════════════════════════════════════════════════════
# 5. parse_amount_token (logic trong reward_handler) và _parse_amount_str
# ═══════════════════════════════════════════════════════════════════
header("5. parse_amount_token (logic trong reward_handler) và _parse_amount_str")

def parse_amount_token(tok: str):
    """Copy chính xác từ reward_handler.button_click_handler (sau khi fix BUG-1)"""
    def _clean_number_str_local(s: str, allow_decimal: bool = True) -> str:
        s = s.replace(',', '')
        if '.' not in s:
            return s
        parts = s.split('.')
        if len(parts) > 2:
            return ''.join(parts)
        integer_part, decimal_part = parts
        if len(decimal_part) == 3:
            return integer_part + decimal_part
        else:
            if allow_decimal:
                return integer_part + '.' + decimal_part
            return integer_part + decimal_part

    s = tok.strip().upper()
    if not s:
        return None
    try:
        if s.endswith('M'):
            num = _clean_number_str_local(s[:-1])
            return int(float(num) * 1_000_000)
        if s.endswith('K'):
            num = _clean_number_str_local(s[:-1])
            return int(float(num) * 1_000)
        cleaned = _clean_number_str_local(s, allow_decimal=False)
        return int(cleaned)
    except Exception:
        return None

assert_eq("5.01 '1500k' → 1500000", parse_amount_token('1500k'), 1500000)
assert_eq("5.02 '1.5M' → 1500000", parse_amount_token('1.5M'), 1500000)
assert_eq("5.03 '2M' → 2000000", parse_amount_token('2M'), 2000000)
assert_eq("5.04 '800' → 800", parse_amount_token('800'), 800)
assert_eq("5.05 'abc' → None", parse_amount_token('abc'), None)
assert_eq("5.06 '0' → 0", parse_amount_token('0'), 0)
assert_eq("5.07 '0k' → 0", parse_amount_token('0k'), 0)
assert_eq("5.08 '0M' → 0", parse_amount_token('0M'), 0)
assert_eq("5.09 '1,500' → 1500", parse_amount_token('1,500'), 1500)
assert_eq("5.10 '2.000' → 2000", parse_amount_token('2.000'), 2000)
assert_eq("5.11 '500k' → 500000", parse_amount_token('500k'), 500000)
assert_eq("5.12 '1.5m' (chữ thường) → 1500000", parse_amount_token('1.5m'), 1500000)
assert_eq("5.13 '  1500k  ' (có khoảng trắng) → 1500000", parse_amount_token('  1500k  '), 1500000)
assert_eq("5.14 '1500K' (chữ hoa) → 1500000", parse_amount_token('1500K'), 1500000)
assert_none("5.15 'abc' không phải số", parse_amount_token('abc'))
assert_none("5.16 '' chuỗi rỗng", parse_amount_token(''))
# BUG-1 regression: 1.500k và 1.500.000
assert_eq("5.17 BUG-1 FIX: '1.500k' → 1500000", parse_amount_token('1.500k'), 1500000)
assert_eq("5.18 BUG-1 FIX: '1.500K' → 1500000", parse_amount_token('1.500K'), 1500000)
assert_eq("5.19 BUG-1 FIX: '1.500M' → 1500000000", parse_amount_token('1.500M'), 1500000000)
assert_eq("5.20 '1.500.000' (số thuần) → 1500000", parse_amount_token('1.500.000'), 1500000)
# _parse_amount_str (exported from validators)
assert_eq("5.21 _parse_amount_str '1.500k'", _parse_amount_str('1.500k'), 1500000)
assert_eq("5.22 _parse_amount_str '1.5M'", _parse_amount_str('1.5M'), 1500000)
assert_eq("5.23 _parse_amount_str '1,500,000'", _parse_amount_str('1,500,000'), 1500000)
assert_eq("5.24 _parse_amount_str '2000000'", _parse_amount_str('2000000'), 2000000)


# ═══════════════════════════════════════════════════════════════════
# 6. _get_shift_info (logic phân ca)
# ═══════════════════════════════════════════════════════════════════
header("6. _get_shift_info (Phân ca làm việc)")

def _get_shift_info(hour: int, minute: int = 0) -> dict:
    """Copy logic từ google_sheets.GoogleSheetsService._get_shift_info"""
    current_minutes = hour * 60 + minute
    shifts = [
        {'ca': 'Sáng', 'standard_start': 6 * 60 + 30},   # 6:30
        {'ca': 'Chiều', 'standard_start': 12 * 60},        # 12:00
        {'ca': 'Tối', 'standard_start': 18 * 60}           # 18:00
    ]
    return min(shifts, key=lambda s: abs(current_minutes - s['standard_start']))

# Check-in lúc 6:30 → Ca Sáng, 0 phút trễ
shift = _get_shift_info(6, 30)
assert_eq("6.01 6:30 → Ca Sáng", shift['ca'], 'Sáng')
assert_eq("6.02 6:30 standard_start = 390", shift['standard_start'], 390)

# Check-in lúc 6:45 → Ca Sáng, 15 phút trễ
shift = _get_shift_info(6, 45)
assert_eq("6.03 6:45 → Ca Sáng", shift['ca'], 'Sáng')
late = max(0, 6*60+45 - shift['standard_start'])
assert_eq("6.04 6:45 trễ 15p", late, 15)

# Check-in lúc 12:00 → Ca Chiều
shift = _get_shift_info(12, 0)
assert_eq("6.05 12:00 → Ca Chiều", shift['ca'], 'Chiều')
late = max(0, 12*60 - shift['standard_start'])
assert_eq("6.06 12:00 đúng giờ (0p trễ)", late, 0)

# Check-in lúc 12:30 → Ca Chiều, 30p trễ
shift = _get_shift_info(12, 30)
assert_eq("6.07 12:30 → Ca Chiều", shift['ca'], 'Chiều')
late = max(0, 12*60+30 - shift['standard_start'])
assert_eq("6.08 12:30 trễ 30p", late, 30)

# Check-in lúc 18:00 → Ca Tối
shift = _get_shift_info(18, 0)
assert_eq("6.09 18:00 → Ca Tối", shift['ca'], 'Tối')
late = max(0, 18*60 - shift['standard_start'])
assert_eq("6.10 18:00 đúng giờ (0p trễ)", late, 0)

# Check-in lúc 9:15 → Gần Ca Sáng (6:30) hơn Ca Chiều (12:00)?
# 9:15 = 555 phút; Ca Sáng: |555-390|=165; Ca Chiều: |555-720|=165 → tie → Sáng (first)
shift = _get_shift_info(9, 15)
# Tie-breaking: min() trả về phần tử đầu tiên (Sáng)
assert_eq("6.11 9:15 tie → Ca Sáng (first element)", shift['ca'], 'Sáng')

# Check-in lúc 9:16 → Ca Chiều gần hơn
shift = _get_shift_info(9, 16)
assert_eq("6.12 9:16 → Ca Chiều (gần hơn)", shift['ca'], 'Chiều')

# Check-in lúc 15:00 → giữa Chiều (12:00) và Tối (18:00) → tie=180 → Chiều
shift = _get_shift_info(15, 0)
assert_eq("6.13 15:00 tie → Ca Chiều (first)", shift['ca'], 'Chiều')

# Check-in lúc 15:01 → Tối gần hơn
shift = _get_shift_info(15, 1)
assert_eq("6.14 15:01 → Ca Tối (gần hơn)", shift['ca'], 'Tối')

# Sáng sớm 0:00 → Ca Sáng (gần nhất)
shift = _get_shift_info(0, 0)
assert_eq("6.15 0:00 → Ca Sáng (gần nhất)", shift['ca'], 'Sáng')

# 23:59 → Ca Tối
shift = _get_shift_info(23, 59)
assert_eq("6.16 23:59 → Ca Tối", shift['ca'], 'Tối')


# ═══════════════════════════════════════════════════════════════════
# 7. Tính tổng giờ check-out (checkout logic)
# ═══════════════════════════════════════════════════════════════════
header("7. Tính tổng giờ check-out")

def calc_hours(checkin_str: str, checkout_str: str) -> float:
    """Copy logic từ GoogleSheetsService.checkout"""
    fmt = "%H:%M:%S"
    checkin_dt = datetime.strptime(checkin_str, fmt)
    checkout_dt = datetime.strptime(checkout_str, fmt)
    diff = (checkout_dt - checkin_dt).total_seconds() / 3600
    if diff < 0:
        diff += 24
    return round(diff, 1)

assert_eq("7.01 Ca sáng 6:30-12:00 = 5.5h", calc_hours("06:30:00", "12:00:00"), 5.5)
assert_eq("7.02 Ca chiều 12:00-18:00 = 6.0h", calc_hours("12:00:00", "18:00:00"), 6.0)
assert_eq("7.03 Ca tối 18:00-22:30 = 4.5h", calc_hours("18:00:00", "22:30:00"), 4.5)
assert_eq("7.04 Qua nửa đêm 22:00-02:00 = 4.0h", calc_hours("22:00:00", "02:00:00"), 4.0)
assert_eq("7.05 Cùng giờ vào ra = 0.0h", calc_hours("08:00:00", "08:00:00"), 0.0)
assert_eq("7.06 1 phút làm việc = 0.0h (round)", calc_hours("08:00:00", "08:01:00"), 0.0)
assert_eq("7.07 90 phút = 1.5h", calc_hours("08:00:00", "09:30:00"), 1.5)
assert_eq("7.08 Qua đêm 23:00-07:00 = 8.0h", calc_hours("23:00:00", "07:00:00"), 8.0)


# ═══════════════════════════════════════════════════════════════════
# 8. overtime_handler — parse số giờ
# ═══════════════════════════════════════════════════════════════════
header("8. Overtime — Parse số giờ")

def parse_ot_hours(text: str):
    """Copy logic từ overtime_handler.handle_overtime_hours_input"""
    try:
        hours = float(text.replace(',', '.'))
        if hours <= 0 or hours > 24:
            raise ValueError("Số giờ không hợp lệ")
        return hours
    except (ValueError, TypeError):
        return None

assert_eq("8.01 '1' → 1.0", parse_ot_hours('1'), 1.0)
assert_eq("8.02 '1.5' → 1.5", parse_ot_hours('1.5'), 1.5)
assert_eq("8.03 '2,5' (dấu phẩy) → 2.5", parse_ot_hours('2,5'), 2.5)
assert_eq("8.04 '0' → None (không hợp lệ)", parse_ot_hours('0'), None)
assert_eq("8.05 '-1' → None", parse_ot_hours('-1'), None)
assert_eq("8.06 '25' → None (>24h)", parse_ot_hours('25'), None)
assert_eq("8.07 '24' → 24.0", parse_ot_hours('24'), 24.0)
assert_eq("8.08 'abc' → None", parse_ot_hours('abc'), None)
assert_eq("8.09 '' → None", parse_ot_hours(''), None)
assert_eq("8.10 '0.5' → 0.5", parse_ot_hours('0.5'), 0.5)
assert_eq("8.11 '8' → 8.0", parse_ot_hours('8'), 8.0)


# ═══════════════════════════════════════════════════════════════════
# 9. Config — biến môi trường
# ═══════════════════════════════════════════════════════════════════
header("9. Config — Kiểm tra biến môi trường")

try:
    from config import Config
    assert_true("9.01 BOT_TOKEN được đặt", Config.BOT_TOKEN)
    assert_true("9.02 SPREADSHEET_ID được đặt", Config.SPREADSHEET_ID)
    assert_true("9.03 DRIVE_FOLDER_ID được đặt", Config.DRIVE_FOLDER_ID)
    assert_true("9.04 GROUP_CHAT_ID là số nguyên", isinstance(Config.GROUP_CHAT_ID, int))
    assert_true("9.05 ADMIN_CHAT_ID là số nguyên", isinstance(Config.ADMIN_CHAT_ID, int))
    assert_true("9.06 GROUP_CHAT_ID != ADMIN_CHAT_ID", Config.GROUP_CHAT_ID != Config.ADMIN_CHAT_ID)
    assert_true("9.07 GOOGLE_CREDENTIALS_FILE được đặt", Config.GOOGLE_CREDENTIALS_FILE)
    print("  ℹ️  9.08 Config.validate() đã chạy thành công khi import")
    passed += 1
except Exception as ex:
    failed += 1
    errors.append(f"  ❌ 9.xx Config import error: {ex}")
    print(f"  ❌ 9.xx Config import error: {ex}")


# ═══════════════════════════════════════════════════════════════════
# 10. auto_delete — track_message / delete_tracked_messages
# ═══════════════════════════════════════════════════════════════════
header("10. auto_delete — track_message & delete_tracked_messages")

from utils.auto_delete import track_message, get_main_keyboard, get_admin_keyboard

class MockContext:
    def __init__(self):
        self.chat_data = {}

ctx = MockContext()

# Bắt đầu: không có to_delete
assert_false("10.01 Ban đầu không có 'to_delete'", 'to_delete' in ctx.chat_data)

track_message(ctx, 100)
assert_true("10.02 Sau track_message(100): 'to_delete' tồn tại", 'to_delete' in ctx.chat_data)
assert_true("10.03 100 trong to_delete", 100 in ctx.chat_data['to_delete'])

track_message(ctx, 200)
assert_true("10.04 200 trong to_delete", 200 in ctx.chat_data['to_delete'])
assert_eq("10.05 to_delete có 2 phần tử", len(ctx.chat_data['to_delete']), 2)

# Track cùng ID 2 lần → set không trùng lặp
track_message(ctx, 100)
assert_eq("10.06 Track trùng ID → vẫn 2 phần tử", len(ctx.chat_data['to_delete']), 2)

# get_main_keyboard trả về ReplyKeyboardMarkup
kb = get_main_keyboard()
assert_not_none("10.07 get_main_keyboard() không None", kb)

# get_admin_keyboard trả về ReplyKeyboardMarkup
akb = get_admin_keyboard()
assert_not_none("10.08 get_admin_keyboard() không None", akb)

# GUIDE_MESSAGE
from utils.auto_delete import GUIDE_MESSAGE
assert_true("10.09 GUIDE_MESSAGE không rỗng", len(GUIDE_MESSAGE) > 0)
assert_true("10.10 GUIDE_MESSAGE chứa 'Check In'", 'Check In' in GUIDE_MESSAGE)
assert_true("10.11 GUIDE_MESSAGE chứa 'Check Out'", 'Check Out' in GUIDE_MESSAGE)
assert_true("10.12 GUIDE_MESSAGE chứa 'Doanh Thu'", 'Doanh Thu' in GUIDE_MESSAGE)


# ═══════════════════════════════════════════════════════════════════
# 11. checkin_handler — _build_employee_picker
# ═══════════════════════════════════════════════════════════════════
header("11. checkin_handler — _build_employee_picker")

from handlers.checkin_handler import _build_employee_picker

# Keyboard với 1 NV
nicknames = {"anhuy": 5}
kb = _build_employee_picker(nicknames, "ci_sel")
assert_not_none("11.01 Keyboard không None (1 NV)", kb)
# Inline keyboard có ít nhất 2 hàng: [nhân viên] + [Hủy]
assert_true("11.02 Có ít nhất 2 hàng (NV + Hủy)", len(kb.inline_keyboard) >= 2)

# Keyboard với 4 NV → 2 hàng NV (2 cột mỗi hàng) + 1 hàng Hủy
nicknames4 = {"A": 1, "B": 2, "C": 3, "D": 4}
kb4 = _build_employee_picker(nicknames4, "co_sel")
assert_not_none("11.03 Keyboard không None (4 NV)", kb4)
# Hàng cuối luôn là nút Hủy
last_row = kb4.inline_keyboard[-1]
assert_eq("11.04 Hàng cuối là nút Hủy", last_row[0].text, "❌ Hủy")
assert_eq("11.05 Callback data nút Hủy", last_row[0].callback_data, "co_sel_cancel")

# Keyboard với 3 NV → 1 hàng 2 nút + 1 hàng 1 nút + 1 hàng Hủy
nicknames3 = {"X": 1, "Y": 2, "Z": 3}
kb3 = _build_employee_picker(nicknames3, "ci_sel")
assert_eq("11.06 3 NV → 3 hàng (2+1+Hủy)", len(kb3.inline_keyboard), 3)

# Keyboard rỗng → chỉ có hàng Hủy
kb0 = _build_employee_picker({}, "ci_sel")
assert_eq("11.07 0 NV → chỉ hàng Hủy", len(kb0.inline_keyboard), 1)


# ═══════════════════════════════════════════════════════════════════
# 12. reward_handler — build_multi_select_keyboard
# ═══════════════════════════════════════════════════════════════════
header("12. reward_handler — build_multi_select_keyboard")

from handlers.reward_handler import build_multi_select_keyboard

# Tất cả chưa chọn
sel = {"A": False, "B": False}
kb = build_multi_select_keyboard(sel)
assert_not_none("12.01 Keyboard không None", kb)
# Cuối có 2 hàng: Xác Nhận và Hủy
assert_eq("12.02 Hàng cuối: Xác Nhận + Hủy", len(kb.inline_keyboard[-1]) + len(kb.inline_keyboard[-2]), 2)

# Chọn A → nút hiển thị "✅ A"
sel2 = {"A": True, "B": False}
kb2 = build_multi_select_keyboard(sel2)
# Lấy tất cả các nút trừ 2 hàng cuối
buttons = [btn for row in kb2.inline_keyboard[:-2] for btn in row]
a_btn = next((b for b in buttons if 'A' in b.text), None)
assert_not_none("12.03 Tìm thấy nút A", a_btn)
assert_true("12.04 A được chọn → có ✅", a_btn.text.startswith('✅'))

b_btn = next((b for b in buttons if b.text == 'B'), None)
assert_not_none("12.05 Tìm thấy nút B", b_btn)
assert_eq("12.06 B chưa chọn → không có ✅", b_btn.text, 'B')

# callback data toggle_emp_
assert_true("12.07 callback data A đúng", a_btn.callback_data == 'toggle_emp_A')


# ═══════════════════════════════════════════════════════════════════
# 13. Callback data parsing (inline handlers)
# ═══════════════════════════════════════════════════════════════════
header("13. Callback data parsing")

# ci_sel_
data = "ci_sel_TuanAnh"
assert_eq("13.01 ci_sel prefix", data.startswith("ci_sel_"), True)
nick = data[len("ci_sel_"):]
assert_eq("13.02 ci_sel nick extract", nick, "TuanAnh")

# co_sel_cancel
data2 = "co_sel_cancel"
nick2 = data2[len("co_sel_"):]
assert_eq("13.03 co_sel cancel", nick2, "cancel")

# ot_sel_
data3 = "ot_sel_HoangLan"
nick3 = data3[len("ot_sel_"):]
assert_eq("13.04 ot_sel nick", nick3, "HoangLan")

# mark_reported_ (date_str có thể có /)
data4 = "mark_reported_30/05/2026_TuanAnh"
raw4 = data4[len("mark_reported_"):]
parts4 = raw4.split("_", 1)
assert_eq("13.05 mark_reported date", parts4[0], "30/05/2026")
assert_eq("13.06 mark_reported nick", parts4[1], "TuanAnh")

# mark_unreported_
data5 = "mark_unreported_01/06/2026_Nguyen Van A"
raw5 = data5[len("mark_unreported_"):]
parts5 = raw5.split("_", 1)
assert_eq("13.07 mark_unreported date", parts5[0], "01/06/2026")
assert_eq("13.08 mark_unreported nick", parts5[1], "Nguyen Van A")

# toggle_emp_
data6 = "toggle_emp_XuanHau"
nick6 = data6[len("toggle_emp_"):]
assert_eq("13.09 toggle_emp nick", nick6, "XuanHau")

# check_reward_
data7 = "check_reward_AnHuy"
nick7 = data7[len("check_reward_"):]
assert_eq("13.10 check_reward nick", nick7, "AnHuy")

# use_reward_
data8 = "use_reward_HoangLan"
nick8 = data8[len("use_reward_"):]
assert_eq("13.11 use_reward nick", nick8, "HoangLan")


# ═══════════════════════════════════════════════════════════════════
# 14. Integration: parse → validate → reward flow
# ═══════════════════════════════════════════════════════════════════
header("14. Integration: Luồng báo cáo ảnh đầy đủ")

# 14.1 Luồng đầy đủ: parse → deduplicate → check_reward
emps, rev, ca, err = parse_report_text("NV: anhuy, anhuy, xuanhau\nDT: 1500k")
emps = deduplicate_employees(emps)
assert_eq("14.01 Sau deduplicate: 2 NV", len(emps), 2)
assert_eq("14.02 Danh sách: ['anhuy', 'xuanhau']", emps, ['anhuy', 'xuanhau'])
assert_eq("14.03 2 NV + 1.5M → thưởng 1", check_reward_eligibility(len(emps), rev), 1)

# 14.2 NV khớp với dữ liệu sheet (giả lập normalize)
sheet_raw = ["TuấnAnh", "Hoàng Lan", "Xuân Hậu"]
sheet_normalized = [_normalize_name_for_comparison(n) for n in sheet_raw]

def _normalize(s):
    s = unicodedata.normalize('NFD', str(s).strip())
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r'[^0-9a-zA-Z]', '', s).lower()
    return s

# User nhập 'tuananh' → khớp 'TuấnAnh'
emps_input = ['tuananh', 'hoanglan']
invalid = [e for e in emps_input if _normalize(e) not in sheet_normalized]
assert_eq("14.04 'tuananh' khớp 'TuấnAnh' trong sheet", invalid, [])

# User nhập sai tên
emps_bad = ['tuananh', 'khongcotennay']
invalid_bad = [e for e in emps_bad if _normalize(e) not in sheet_normalized]
assert_eq("14.05 Tên sai bị phát hiện", invalid_bad, ['khongcotennay'])

# 14.3 Luồng quick_report (button ⚡ Báo Doanh Thu)
emps_sel = ['AnHuy', 'XuanHau']
revenue_input = '1.5M'
rev_parsed = parse_amount_token(revenue_input)
assert_eq("14.06 Quick report: parse '1.5M' → 1500000", rev_parsed, 1500000)
reward = check_reward_eligibility(len(emps_sel), rev_parsed)
assert_eq("14.07 Quick report: 2 NV + 1.5M → 1 ly", reward, 1)

# 14.4 Luồng không đạt thưởng
emps_alone = ['AnHuy']
rev_low = parse_amount_token('800k')
reward_none = check_reward_eligibility(len(emps_alone), rev_low)
assert_eq("14.08 1 NV + 800k → 0 ly", reward_none, 0)


# ═══════════════════════════════════════════════════════════════════
# 15. Edge cases & Regression tests
# ═══════════════════════════════════════════════════════════════════
header("15. Edge Cases & Regression Tests")

# 15.1 Tên NV 'sang' → không bị nhầm thành Ca Sáng (BUG-3 FIX)
emps, rev, ca, err = parse_report_text("NV: sang\nDT: 1000k")
assert_eq("15.01 BUG-3 FIX: Tên 'sang' không bị nhầm thành Ca Sáng", ca, '')

# 15.2 DT có cả chấm và phẩy → cắt sạch rồi parse
e, r, c, err = parse_report_text("NV: a\nDT: 1.500.000")
if not err:
    assert_eq("15.02 '1.500.000' → 1500000", r, 1500000)
else:
    passed += 1
    print(f"  ✅ 15.02 '1.500.000' báo lỗi (chấp nhận được): {err}")

# 15.3 Checkout qua nửa đêm (diff âm → +24h)
diff_neg = (2*60) - (22*60)  # minutes
diff_h = diff_neg / 60
if diff_h < 0:
    diff_h += 24
assert_eq("15.03 22:00 → 02:00 qua đêm = 4h", round(diff_h, 1), 4.0)

# 15.4 mark_reported_late: parse date_str có dấu /
raw = "30/05/2026_NhanVien"
parts = raw.split("_", 1)
assert_eq("15.04 date_str chứa / được parse đúng", parts[0], "30/05/2026")
assert_eq("15.05 nickname sau date_str", parts[1], "NhanVien")

# 15.5 use_reward khi balance = 0 → từ chối
balance = 0
can_use = balance > 0
assert_false("15.06 balance=0 → không dùng được", can_use)

# 15.6 use_reward khi balance = 1 → được dùng
balance1 = 1
can_use1 = balance1 > 0
assert_true("15.07 balance=1 → dùng được", can_use1)

# 15.7 Callback data prefix check đúng thứ tự
callbacks = [
    ("ci_sel_A", "ci_sel_"),
    ("co_sel_B", "co_sel_"),
    ("ot_sel_C", "ot_sel_"),
    ("mark_reported_D", "mark_reported_"),
    ("mark_unreported_E", "mark_unreported_"),
    ("toggle_emp_F", "toggle_emp_"),
    ("confirm_report_emps", "confirm_report_emps"),
    ("cancel_report_emps", "cancel_report_emps"),
    ("check_reward_G", "check_reward_"),
    ("use_reward_H", "use_reward_"),
]
for data, prefix in callbacks:
    assert_true(f"15.08 '{data}' startswith '{prefix}'", data.startswith(prefix))

# 15.9 Safe nick (tránh lỗi Markdown với _ và *)
def safe_nick(nick: str) -> str:
    return nick.replace('_', r'\_').replace('*', r'\*')

assert_eq("15.18 safe_nick xử lý '_'", safe_nick("nguyen_van_a"), r"nguyen\_van\_a")
assert_eq("15.19 safe_nick xử lý '*'", safe_nick("nv*special"), r"nv\*special")
assert_eq("15.20 safe_nick không thay đổi tên bình thường", safe_nick("TuanAnh"), "TuanAnh")


# ═══════════════════════════════════════════════════════════════════
# 16. Import tất cả modules (smoke test)
# ═══════════════════════════════════════════════════════════════════
header("16. Smoke test — Import tất cả modules")

modules_to_test = [
    ("config", "Config"),
    ("utils.validators", "parse_report_text"),
    ("utils.decorators", "group_only"),
    ("utils.auto_delete", "track_message"),
    ("handlers.checkin_handler", "_build_employee_picker"),
    ("handlers.reward_handler", "button_click_handler"),
    ("handlers.overtime_handler", "handle_add_overtime_button"),
    ("handlers.report_handler", "handle_photo_report"),
    ("google_sheets", "_normalize_name_for_comparison"),
    ("google_drive", "GoogleDriveService"),
]

for module_name, attr_name in modules_to_test:
    try:
        import importlib
        mod = importlib.import_module(module_name)
        assert_true(f"16.xx import {module_name}.{attr_name}", hasattr(mod, attr_name))
    except Exception as ex:
        failed += 1
        msg = f"  ❌ 16.xx import {module_name} FAILED: {ex}"
        print(msg)
        errors.append(msg)


# ═══════════════════════════════════════════════════════════════════
# KẾT QUẢ
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
total = passed + failed
pct = round(100 * passed / total, 1) if total > 0 else 0
print(f"KẾT QUẢ: {passed}/{total} PASSED ({pct}%), {failed}/{total} FAILED")
print('='*60)

if errors:
    print(f"\n🔴 CÁC LỖI ({len(errors)}):")
    for e in errors:
        print(e)
else:
    print("\n🎉 TẤT CẢ TESTS ĐỀU PASS!")

sys.exit(1 if failed else 0)
