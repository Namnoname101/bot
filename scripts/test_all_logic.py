# -*- coding: utf-8 -*-
"""Kiểm thử toàn diện các hàm logic cốt lõi của Sober Bot.

Chạy: python scripts/test_all_logic.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Không cần .env / Google Sheets để test logic thuần ──
# Monkey-patch Config trước khi import bất kỳ module nào
import os
os.environ.setdefault("BOT_TOKEN", "FAKE")
os.environ.setdefault("GROUP_CHAT_ID", "123")
os.environ.setdefault("ADMIN_CHAT_ID", "456")
os.environ.setdefault("SPREADSHEET_ID", "FAKE")
os.environ.setdefault("DRIVE_FOLDER_ID", "FAKE")

from utils.validators import parse_report_text, check_reward_eligibility, deduplicate_employees
from google_sheets import _normalize_name_for_comparison

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


# ═══════════════════════════════════════════════════════════════
# 1. TEST parse_report_text
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("1. KIỂM THỬ parse_report_text")
print("="*60)

# 1.1 Kịch bản chuẩn
emps, rev, ca, err = parse_report_text("NV: tuananh, hoanglan\nDoanh thu: 1500k")
assert_eq("1.1a Phân tích 2 NV chuẩn", emps, ['tuananh', 'hoanglan'])
assert_eq("1.1b Doanh thu 1500k = 1500000", rev, 1500000)
assert_false("1.1c Không có lỗi", err)

# 1.2 Doanh thu có dấu chấm
emps, rev, ca, err = parse_report_text("NV: a\nDT: 1.500k")
assert_eq("1.2 DT 1.500k = 1500000", rev, 1500000)

# 1.3 Doanh thu có dấu phẩy 
emps, rev, ca, err = parse_report_text("NV: a\nDT: 1,500,000")
assert_eq("1.3 DT 1,500,000 = 1500000", rev, 1500000)

# 1.4 Doanh thu thuần số
emps, rev, ca, err = parse_report_text("NV: a\nDoanh thu: 2000000")
assert_eq("1.4 DT 2000000 thuần", rev, 2000000)

# 1.5 Tên có khoảng trắng (FIX quan trọng)
emps, rev, ca, err = parse_report_text("NV: anh tuyet, quoc bao\nDT: 1200k")
assert_eq("1.5a Tên có khoảng trắng giữ nguyên", emps, ['anh tuyet', 'quoc bao'])
assert_eq("1.5b Đếm đúng 2 NV", len(emps), 2)

# 1.6 Tên một NV duy nhất
emps, rev, ca, err = parse_report_text("NV: xuanhau\nDoanh thu: 800k")
assert_eq("1.6 Một NV duy nhất", emps, ['xuanhau'])

# 1.7 NV trùng lặp (parse không tự deduplicate — kiểm tra hàm riêng)
emps, rev, ca, err = parse_report_text("NV: anhuy, anhuy, anhuy\nDT: 1500k")
assert_eq("1.7 Parse giữ nguyên trùng lặp", len(emps), 3)

# 1.8 Thiếu dòng NV
emps, rev, ca, err = parse_report_text("Doanh thu: 1500k")
assert_true("1.8 Thiếu NV → có lỗi", err)

# 1.9 Thiếu dòng Doanh thu
emps, rev, ca, err = parse_report_text("NV: tuananh")
assert_true("1.9 Thiếu DT → có lỗi", err)

# 1.10 Caption rỗng
emps, rev, ca, err = parse_report_text("")
assert_true("1.10 Chuỗi rỗng → có lỗi", err)

# 1.11 Doanh thu âm (regex [\\d\\.\\,kK]+ không match dấu trừ nên sẽ thành lỗi cú pháp)
emps, rev, ca, err = parse_report_text("NV: a\nDT: -500k")
assert_true("1.11 DT âm → lỗi cú pháp (regex không match)", err)

# 1.12 Doanh thu quá lớn
emps, rev, ca, err = parse_report_text("NV: a\nDT: 200000k")
assert_true("1.12 DT quá lớn (200M) → lỗi", err)

# 1.13 Doanh thu biên 100M chính xác
emps, rev, ca, err = parse_report_text("NV: a\nDT: 100000k")
assert_eq("1.13 DT biên 100M = 100000000", rev, 100000000)
assert_false("1.13b Biên 100M hợp lệ", err)

# 1.14 Nhận diện Ca Sáng
emps, rev, ca, err = parse_report_text("NV: a\nDT: 1000k\nCa: sáng")
assert_eq("1.14 Ca sáng", ca, 'Sáng')

# 1.15 Nhận diện Ca Chiều
emps, rev, ca, err = parse_report_text("NV: a\nDT: 1000k\nCa: chieu")
assert_eq("1.15 Ca chiều (không dấu)", ca, 'Chiều')

# 1.16 Nhận diện Ca từ ngữ cảnh (không có dòng Ca: riêng)
emps, rev, ca, err = parse_report_text("NV: a\nDT: 1000k\nBáo cáo buổi sáng")
assert_eq("1.16 Suy ca từ ngữ cảnh 'sáng'", ca, 'Sáng')

# 1.17 Không rõ Ca
emps, rev, ca, err = parse_report_text("NV: a\nDT: 1000k")
assert_eq("1.17 Không ghi ca → rỗng", ca, '')

# 1.18 Keyword 'nhân viên:' thay vì 'nv:'
emps, rev, ca, err = parse_report_text("Nhân viên: tuananh, hoanglan\nDoanh thu: 1200k")
assert_eq("1.18 Keyword 'Nhân viên'", emps, ['tuananh', 'hoanglan'])

# 1.19 Keyword 'nhan vien:' (không dấu)
emps, rev, ca, err = parse_report_text("nhan vien: tuananh\ndt: 800k")
assert_eq("1.19 Keyword 'nhan vien' (không dấu)", emps, ['tuananh'])

# 1.20 NV có khoảng trắng thừa xung quanh dấu phẩy
emps, rev, ca, err = parse_report_text("NV:   tuananh  ,  hoanglan  \nDT: 1000k")
assert_eq("1.20 Trim khoảng trắng thừa", emps, ['tuananh', 'hoanglan'])

# 1.21 Regex NV match greedy — kiểm tra NV lấy tới cuối dòng, 
#       KHÔNG lấy luôn dòng DT nếu cùng dòng
emps, rev, ca, err = parse_report_text("NV: anh, bao\nDT: 1000k")
# 'anh, bao' should NOT include '\nDT: 1000k'
assert_eq("1.21a Regex NV chỉ lấy đúng tên", 'dt' not in ' '.join(emps).lower(), True)

# 1.22 DT: 0 (doanh thu = 0 hợp lệ)
emps, rev, ca, err = parse_report_text("NV: a\nDT: 0")
assert_eq("1.22 DT = 0 hợp lệ", rev, 0)
assert_false("1.22b Không lỗi", err)


# ═══════════════════════════════════════════════════════════════
# 2. TEST check_reward_eligibility 
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("2. KIỂM THỬ check_reward_eligibility")
print("="*60)

assert_eq("2.1  1 NV + 1.2M → 0", check_reward_eligibility(1, 1200000), 0)
assert_eq("2.2  1 NV + 2M   → 0", check_reward_eligibility(1, 2000000), 0)
assert_eq("2.3  2 NV + 1.2M → 1", check_reward_eligibility(2, 1200000), 1)
assert_eq("2.4  2 NV + 1.19M → 0", check_reward_eligibility(2, 1199999), 0)
assert_eq("2.5  2 NV + 0    → 0", check_reward_eligibility(2, 0), 0)
assert_eq("2.6  3 NV + 1.5M → 1", check_reward_eligibility(3, 1500000), 1)
assert_eq("2.7  3 NV + 1.49M → 0", check_reward_eligibility(3, 1499999), 0)
assert_eq("2.8  3 NV + 1.2M → 0", check_reward_eligibility(3, 1200000), 0)
assert_eq("2.9  5 NV + 2M   → 1", check_reward_eligibility(5, 2000000), 1)
assert_eq("2.10 0 NV + 2M   → 0", check_reward_eligibility(0, 2000000), 0)


# ═══════════════════════════════════════════════════════════════
# 3. TEST deduplicate_employees
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("3. KIỂM THỬ deduplicate_employees")
print("="*60)

assert_eq("3.1 Trùng 3 → 1", deduplicate_employees(['a', 'a', 'a']), ['a'])
assert_eq("3.2 Giữ thứ tự", deduplicate_employees(['b', 'a', 'b']), ['b', 'a'])
assert_eq("3.3 Không trùng → nguyên", deduplicate_employees(['x', 'y', 'z']), ['x', 'y', 'z'])
assert_eq("3.4 Danh sách rỗng", deduplicate_employees([]), [])
assert_eq("3.5 Một phần tử", deduplicate_employees(['solo']), ['solo'])


# ═══════════════════════════════════════════════════════════════
# 4. TEST _normalize_name_for_comparison (Unicode)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("4. KIỂM THỬ _normalize_name_for_comparison (Unicode)")
print("="*60)

assert_eq("4.1 Chữ thường", _normalize_name_for_comparison("TuanAnh"), "tuananh")
assert_eq("4.2 Bỏ dấu tiếng Việt", _normalize_name_for_comparison("hoà"), "hoa")
assert_eq("4.3 NFC vs NFD giống nhau",
          _normalize_name_for_comparison("hoà"),  # NFC
          _normalize_name_for_comparison("hoà"))   # may be NFD from some input
assert_eq("4.4 Bỏ khoảng trắng + dấu", _normalize_name_for_comparison("  Xuân Hậu  "), "xuanhau")
assert_eq("4.5 Chuỗi rỗng", _normalize_name_for_comparison(""), "")
assert_eq("4.6 Chỉ có dấu cách", _normalize_name_for_comparison("   "), "")
assert_eq("4.7 Ký tự đặc biệt bị loại", _normalize_name_for_comparison("anh-uy_123"), "anhuy123")
assert_eq("4.8 Dấu đủ loại", _normalize_name_for_comparison("Đặng Hồng Phước"), "danghongphuoc")


# ═══════════════════════════════════════════════════════════════
# 5. TEST tích hợp: parse + deduplicate + normalize  
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("5. KIỂM THỬ TÍCH HỢP (Integration)")
print("="*60)

# 5.1 Luồng đầy đủ: parse → deduplicate → validate
emps, rev, ca, err = parse_report_text("NV: anhuy, anhuy, xuanhau\nDT: 1500k")
emps = deduplicate_employees(emps)
assert_eq("5.1a Sau deduplicate: 2 NV", len(emps), 2)
assert_eq("5.1b Danh sách đúng", emps, ['anhuy', 'xuanhau'])
assert_eq("5.1c Thưởng đúng (2 NV + 1.5M)", check_reward_eligibility(len(emps), rev), 1)

# 5.2 Tên trùng sau khi normalize
n1 = _normalize_name_for_comparison("Hoà")
n2 = _normalize_name_for_comparison("hoa")
assert_eq("5.2 'Hoà' vs 'hoa' chuẩn hóa giống nhau", n1, n2)

# 5.3 So sánh tên nhân viên với dữ liệu sheets (giả lập)
sheet_nicknames_raw = ["TuấnAnh", "Hoàng Lan", "Xuân Hậu"]
sheet_nicknames_normalized = [_normalize_name_for_comparison(n) for n in sheet_nicknames_raw]
user_input = "tuananh"
assert_eq("5.3 User 'tuananh' khớp Sheet 'TuấnAnh'",
          _normalize_name_for_comparison(user_input) in sheet_nicknames_normalized, True)

user_input2 = "hoanglan"
assert_eq("5.4 User 'hoanglan' khớp Sheet 'Hoàng Lan'",
          _normalize_name_for_comparison(user_input2) in sheet_nicknames_normalized, True)

# 5.5 Luồng quick_report: parse_amount_token
def parse_amount_token(tok: str):
    s = tok.upper().replace('.', '').replace(',', '')
    if 'K' in s:
        s = s.replace('K', '000')
    try:
        return int(s)
    except Exception:
        return None

assert_eq("5.5a parse '1500k'", parse_amount_token('1500k'), 1500000)
assert_eq("5.5b parse '1.5M' (chỉ bỏ dấu chấm)", parse_amount_token('1.5M'), None)  # 15M is not a number without M support
assert_eq("5.5c parse '800'", parse_amount_token('800'), 800)
assert_eq("5.5d parse 'abc'", parse_amount_token('abc'), None)
assert_eq("5.5e parse '0'", parse_amount_token('0'), 0)

# ═══════════════════════════════════════════════════════════════
# 6. TEST EDGE CASES ĐẶC BIỆT
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("6. KIỂM THỬ EDGE CASES ĐẶC BIỆT")
print("="*60)

# 6.1 NV regex greedy problem: NV line chứa cả "doanh thu" 
# (nếu user viết trên 1 dòng)
text_oneline = "NV: tuan doanh thu: 1200k"
emps, rev, ca, err = parse_report_text(text_oneline)
# Regex NV: (.+) sẽ lấy "tuan doanh thu: 1200k" 
# Regex DT: sẽ match "1200k"
# Vấn đề: tên NV sẽ chứa "tuan doanh thu: 1200k"
if not err:
    has_junk = any('doanh' in e or 'thu' in e or '1200k' in e for e in emps)
    if has_junk:
        failed += 1
        msg = "  ❌ 6.1 BUG: NV regex lấy luôn phần doanh thu khi viết cùng dòng"
        print(msg)
        errors.append(msg)
    else:
        passed += 1
        print("  ✅ 6.1 NV regex tách đúng khi viết cùng dòng")
else:
    passed += 1
    print(f"  ✅ 6.1 Báo lỗi khi format 1 dòng (chấp nhận được): {err}")

# 6.2 Callback data split: approve_rpt_123 → action='approve', id='rpt_123'
data = "approve_rpt_123"
action, report_id = data.split('_', 1)
assert_eq("6.2 Callback split approve", (action, report_id), ('approve', 'rpt_123'))

data2 = "reject_rpt_cmd_456"
action2, report_id2 = data2.split('_', 1)
assert_eq("6.3 Callback split reject", (action2, report_id2), ('reject', 'rpt_cmd_456'))

# 6.4 chr(64 + col_index) cho các cột > Z (col 27+)
col_index = 26  # Z
assert_eq("6.4a chr(64+26) = Z", chr(64 + col_index), 'Z')
col_index_bad = 27  # [  ← không phải ký tự hợp lệ cho cột Sheets!
result_char = chr(64 + col_index_bad)
is_valid_col = result_char.isalpha()
if not is_valid_col:
    failed += 1
    msg = f"  ❌ 6.4b BUG: chr(64+27) = '{result_char}' — không hợp lệ cho cột Sheets khi có >26 cột"
    print(msg)
    errors.append(msg)
else:
    passed += 1
    print(f"  ✅ 6.4b chr(64+27) hợp lệ")

# 6.5 Ca detection false positive: tên NV chứa "sang"
emps, rev, ca, err = parse_report_text("NV: sang\nDT: 1000k")
# "sang" xuất hiện trong tên NV, nhưng hệ thống phát hiện ca = Sáng (false positive)
if ca == 'Sáng':
    failed += 1
    msg = "  ❌ 6.5 BUG: Tên NV 'sang' bị nhận nhầm thành Ca Sáng"
    print(msg)
    errors.append(msg)
else:
    passed += 1
    print("  ✅ 6.5 Tên 'sang' không bị nhầm thành Ca")

# 6.6 Race condition: use_reward đọc balance rồi mới trừ
# (Không thể test trực tiếp nhưng ghi nhận là thiết kế concern)
print("  ℹ️  6.6 Race condition use_reward: get_balance → update_balance không atomic (ghi nhận)")

# 6.7 DT: 0k → 0000 = 0
emps, rev, ca, err = parse_report_text("NV: a\nDT: 0k")
assert_eq("6.7 DT '0k' = 0", rev, 0)

# 6.8 Nhiều dấu phẩy liên tiếp trong danh sách NV
emps, rev, ca, err = parse_report_text("NV: anh,,,bao,,\nDT: 1000k")
assert_eq("6.8 Bỏ qua phần tử rỗng từ dấu phẩy liên tiếp", emps, ['anh', 'bao'])


# ═══════════════════════════════════════════════════════════════
# KẾT QUẢ
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*60)
total = passed + failed
print(f"KẾT QUẢ: {passed}/{total} PASSED, {failed}/{total} FAILED")
print("="*60)

if errors:
    print("\n🔴 CÁC LỖI CẦN SỬA:")
    for e in errors:
        print(e)

sys.exit(1 if failed else 0)
