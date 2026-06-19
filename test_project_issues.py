#!/usr/bin/env python3
"""
Test Script - Kiểm tra các vấn đề đã phát hiện trong QA Report

Chạy: python test_project_issues.py
"""
import sys
import re
import unicodedata
from typing import Tuple, List

# Import các module từ project
try:
    from utils.validators import parse_report_text, check_reward_eligibility, deduplicate_employees
    print("✅ Imported validators successfully")
except Exception as e:
    print(f"❌ Error importing validators: {e}")
    sys.exit(1)

# Color codes cho console output
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'

def print_test_header(title):
    """In tiêu đề test"""
    print(f"\n{BLUE}{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}{title}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")

def print_pass(msg):
    """In tin tức PASS"""
    print(f"{GREEN}✅ PASS{RESET}: {msg}")

def print_fail(msg):
    """In tin tức FAIL"""
    print(f"{RED}❌ FAIL{RESET}: {msg}")

def print_warning(msg):
    """In cảnh báo"""
    print(f"{YELLOW}⚠️  WARNING{RESET}: {msg}")

def print_info(msg):
    """In thông tin"""
    print(f"ℹ️  INFO: {msg}")

# ============================================================================
# TEST 1: Lỗi phân tách tên nhân viên bằng khoảng trắng
# ============================================================================
def test_employee_name_splitting():
    """Test lỗi phân tách tên nhân viên bằng khoảng trắng"""
    print_test_header("TEST 1: Kiểm tra Phân Tách Tên Nhân Viên")
    
    test_cases = [
        {
            "caption": "NV: anh tuyet, quoc bao\nDoanh thu: 1500000",
            "expected_employees": ["anh tuyet", "quoc bao"],
            "issue": "Nếu parse_report_text dùng split(r'[,]+|\\s+'), sẽ tách thành ['anh', 'tuyet', 'quoc', 'bao']"
        },
        {
            "caption": "NV: anhuy\nDoanh thu: 1200000",
            "expected_employees": ["anhuy"],
            "issue": "Tên có khoảng trắng dù không được cách"
        },
        {
            "caption": "NV: tuan anh, hoang lan, xuân hậu\nDoanh thu: 1600000",
            "expected_employees": ["tuan anh", "hoang lan", "xuân hậu"],
            "issue": "Tên đa từ với dấu tiếng Việt"
        }
    ]
    
    all_pass = True
    for i, test in enumerate(test_cases, 1):
        employees, revenue, ca, error = parse_report_text(test["caption"])
        
        # Chuẩn hóa để so sánh (loại bỏ dấu)
        def normalize(s):
            return unicodedata.normalize('NFD', s.lower()).encode('ascii', 'ignore').decode()
        
        expected_norm = [normalize(e) for e in test["expected_employees"]]
        actual_norm = [normalize(e) for e in employees]
        
        if expected_norm == actual_norm:
            print_pass(f"Test case {i}: {test['expected_employees']} ✓")
        else:
            print_fail(f"Test case {i}:")
            print(f"  Input: {test['caption']}")
            print(f"  Expected: {test['expected_employees']}")
            print(f"  Got:      {employees}")
            print(f"  Issue: {test['issue']}")
            all_pass = False
    
    return all_pass

# ============================================================================
# TEST 2: Kiểm tra xử lý doanh thu âm & quá lớn
# ============================================================================
def test_revenue_validation():
    """Test xử lý doanh thu âm hoặc quá lớn"""
    print_test_header("TEST 2: Kiểm tra Xử Lý Doanh Thu Đầu Vào")
    
    test_cases = [
        {
            "caption": "NV: anhuy\nDoanh thu: -1500000",
            "should_fail": True,
            "reason": "Doanh thu âm"
        },
        {
            "caption": "NV: anhuy\nDoanh thu: 999999999",
            "should_fail": True,
            "reason": "Doanh thu vượt quá 100,000,000 VNĐ"
        },
        {
            "caption": "NV: anhuy\nDoanh thu: 1500k",
            "should_pass": True,
            "expected_revenue": 1500000,
            "reason": "Doanh thu hợp lệ dạng K"
        },
        {
            "caption": "NV: anhuy\nDoanh thu: 1.500.000",
            "should_pass": True,
            "expected_revenue": 1500000,
            "reason": "Doanh thu với dấu chấm phân cách"
        }
    ]
    
    all_pass = True
    for i, test in enumerate(test_cases, 1):
        employees, revenue, ca, error = parse_report_text(test["caption"])
        
        if test.get("should_fail"):
            if error:
                print_pass(f"Test {i}: Đúng cách bắt lỗi - {test['reason']}")
                print(f"  Error message: {error[:50]}...")
            else:
                print_fail(f"Test {i}: Không bắt được lỗi - {test['reason']}")
                print(f"  Revenue: {revenue}")
                all_pass = False
        
        if test.get("should_pass"):
            if not error and revenue == test.get("expected_revenue"):
                print_pass(f"Test {i}: {test['reason']} = {revenue:,} VNĐ ✓")
            else:
                print_fail(f"Test {i}: {test['reason']}")
                print(f"  Expected: {test.get('expected_revenue'):,}")
                print(f"  Got: {revenue:,}")
                print(f"  Error: {error}")
                all_pass = False
    
    return all_pass

# ============================================================================
# TEST 3: Kiểm tra loại bỏ nhân viên trùng lặp
# ============================================================================
def test_deduplicate_employees():
    """Test hàm loại bỏ nhân viên trùng lặp"""
    print_test_header("TEST 3: Kiểm tra Loại Bỏ Nhân Viên Trùng Lặp")
    
    test_cases = [
        {
            "input": ["anhuy", "anhuy", "anhuy"],
            "expected": ["anhuy"],
            "reason": "3 lần cùng tên phải trở thành 1"
        },
        {
            "input": ["anhuy", "hoanglan", "anhuy"],
            "expected": ["anhuy", "hoanglan"],
            "reason": "Giữ nguyên thứ tự, loại bỏ trùng"
        },
        {
            "input": ["a", "b", "c"],
            "expected": ["a", "b", "c"],
            "reason": "Không có trùng lặp"
        }
    ]
    
    all_pass = True
    for i, test in enumerate(test_cases, 1):
        result = deduplicate_employees(test["input"])
        if result == test["expected"]:
            print_pass(f"Test {i}: {test['reason']} ✓")
        else:
            print_fail(f"Test {i}: {test['reason']}")
            print(f"  Input:    {test['input']}")
            print(f"  Expected: {test['expected']}")
            print(f"  Got:      {result}")
            all_pass = False
    
    return all_pass

# ============================================================================
# TEST 4: Kiểm tra chỉ tiêu thưởng
# ============================================================================
def test_reward_eligibility():
    """Test kiểm tra điều kiện đạt chỉ tiêu thưởng"""
    print_test_header("TEST 4: Kiểm tra Điều Kiện Đạt Chỉ Tiêu Thưởng")
    
    test_cases = [
        {
            "num_employees": 2,
            "revenue": 1200000,
            "expected_reward": 1,
            "reason": "2 người, DT 1.2M -> 1 ly"
        },
        {
            "num_employees": 2,
            "revenue": 1100000,
            "expected_reward": 0,
            "reason": "2 người, DT 1.1M -> 0 ly (không đạt)"
        },
        {
            "num_employees": 3,
            "revenue": 1500000,
            "expected_reward": 1,
            "reason": "3 người, DT 1.5M -> 1 ly"
        },
        {
            "num_employees": 3,
            "revenue": 1400000,
            "expected_reward": 0,
            "reason": "3 người, DT 1.4M -> 0 ly (không đạt)"
        },
        {
            "num_employees": 1,
            "revenue": 10000000,
            "expected_reward": 0,
            "reason": "1 người -> không đủ điều kiện (cần >=2)"
        }
    ]
    
    all_pass = True
    for i, test in enumerate(test_cases, 1):
        reward = check_reward_eligibility(test["num_employees"], test["revenue"])
        if reward == test["expected_reward"]:
            print_pass(f"Test {i}: {test['reason']} ✓")
        else:
            print_fail(f"Test {i}: {test['reason']}")
            print(f"  Expected reward: {test['expected_reward']} ly")
            print(f"  Got:             {reward} ly")
            all_pass = False
    
    return all_pass

# ============================================================================
# TEST 5: Kiểm tra chuẩn hóa Unicode tiếng Việt
# ============================================================================
def test_unicode_normalization():
    """Test chuẩn hóa Unicode tiếng Việt"""
    print_test_header("TEST 5: Kiểm tra Chuẩn Hóa Unicode Tiếng Việt")
    
    # Các cách biểu diễn khác nhau của cùng một tên
    test_cases = [
        {
            "name1": "hoà",     # NFC (dựng sẵn)
            "name2": "hoà",     # NFD (tổ hợp)
            "should_match": True,
            "reason": "Cùng tên nhưng Unicode form khác"
        },
        {
            "name1": "Hòa",
            "name2": "hòa",
            "should_match": False,  # Khác nhau ở case sensitivity
            "reason": "Khác nhau về case (cần chuẩn hóa lowercase)"
        }
    ]
    
    def normalize_unicode(s):
        """Chuẩn hóa NFD và loại bỏ dấu"""
        s = unicodedata.normalize('NFD', str(s).lower().strip())
        s = ''.join(ch for ch in s if not unicodedata.combining(ch))
        return s
    
    all_pass = True
    for i, test in enumerate(test_cases, 1):
        norm1 = normalize_unicode(test["name1"])
        norm2 = normalize_unicode(test["name2"])
        matches = (norm1 == norm2)
        
        if matches == test["should_match"]:
            result = "khớp ✓" if matches else "không khớp ✓"
            print_pass(f"Test {i}: {test['reason']} - {result}")
        else:
            print_fail(f"Test {i}: {test['reason']}")
            print(f"  Name1 (normalized): '{norm1}'")
            print(f"  Name2 (normalized): '{norm2}'")
            all_pass = False
    
    return all_pass

# ============================================================================
# MAIN
# ============================================================================
def main():
    """Chạy tất cả tests"""
    print(f"{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}COMPREHENSIVE TEST SUITE - SOBER BOT{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}")
    
    results = {
        "TEST 1: Phân tách tên": test_employee_name_splitting(),
        "TEST 2: Xử lý doanh thu": test_revenue_validation(),
        "TEST 3: Loại bỏ trùng": test_deduplicate_employees(),
        "TEST 4: Chỉ tiêu thưởng": test_reward_eligibility(),
        "TEST 5: Unicode": test_unicode_normalization(),
    }
    
    # Tóm tắt kết quả
    print(f"\n{BLUE}{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}TÓM TẮT KẾT QUẢ{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = f"{GREEN}✅ PASS{RESET}" if result else f"{RED}❌ FAIL{RESET}"
        print(f"{status} {test_name}")
    
    print(f"\n{BOLD}Tổng cộng: {passed}/{total} test passed{RESET}\n")
    
    if passed == total:
        print(f"{GREEN}{BOLD}🎉 Tất cả tests đều thành công!{RESET}\n")
        return 0
    else:
        print(f"{RED}{BOLD}❌ Có {total - passed} test không thành công!{RESET}\n")
        return 1

if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
