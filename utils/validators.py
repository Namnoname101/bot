import re
from typing import Tuple, List


def _parse_amount_str(raw: str):
    """Parse một chuỗi số tiền linh hoạt, hỗ trợ các format:
    
    - Suffix M/m: 2M → 2,000,000 | 1.5M → 1,500,000 | 1.500M → 1,500,000
    - Suffix K/k: 1500k → 1,500,000 | 1.5k → 1,500 | 1.500k → 1,500,000
    - Thuần số:   2000000 | 1,500,000 | 1.500.000

    Quy tắc phân biệt dấu chấm/phẩy:
    - Nếu số phần thập phân sau dấu chấm là ĐÚNG 3 chữ số → dấu phân cách ngàn.
    - Ngược lại → dấu thập phân.

    Trả về int hoặc None nếu không parse được.
    """
    s = raw.strip().upper()
    if not s:
        return None

    try:
        if s.endswith('M'):
            num = s[:-1]
            num = _clean_number_str(num)
            return int(float(num) * 1_000_000)

        if s.endswith('K'):
            num = s[:-1]
            num = _clean_number_str(num)
            return int(float(num) * 1_000)

        # Không có suffix
        cleaned = _clean_number_str(s, allow_decimal=False)
        return int(cleaned)
    except Exception:
        return None


def _clean_number_str(s: str, allow_decimal: bool = True) -> str:
    """Chuẩn hoá chuỗi số: xử lý dấu chấm/phẩy là phân cách ngàn hay thập phân.
    
    Quy tắc:
    - Dấu phẩy: luôn là phân cách ngàn → loại bỏ.
    - Dấu chấm + 3 chữ số tiếp theo (VD: 1.500) → phân cách ngàn → loại bỏ.
    - Dấu chấm + 1-2 chữ số (VD: 1.5) → thập phân → giữ lại.
    """
    # Bước 1: Xóa dấu phẩy (luôn là phân cách ngàn)
    s = s.replace(',', '')

    if '.' not in s:
        return s

    # Bước 2: Kiểm tra tất cả dấu chấm
    # Xử lý trường hợp nhiều dấu chấm: 1.500.000 → tất cả là ngàn
    parts = s.split('.')
    if len(parts) > 2:
        # Nhiều dấu chấm → tất cả là phân cách ngàn
        return ''.join(parts)

    # Chỉ 1 dấu chấm: phân tích phần sau dấu chấm
    integer_part, decimal_part = parts
    if len(decimal_part) == 3:
        # Dạng 1.500 → phân cách ngàn
        return integer_part + decimal_part
    else:
        # Dạng 1.5 → thập phân — giữ lại nếu cho phép
        if allow_decimal:
            return integer_part + '.' + decimal_part
        else:
            return integer_part + decimal_part


def parse_report_text(text: str) -> Tuple[List[str], int, str, str]:
    """
    Phân tích nội dung tin nhắn báo cáo (caption ảnh).
    
    Hỗ trợ format linh hoạt:
        NV: tuananh, hoanglan
        Doanh thu: 1500000  (hoặc 1500k, 1.5M, 1.500k, 1,500,000...)
        Ca: sáng  (tùy chọn)
    
    Returns:
        (employees, revenue, ca, error_msg)
    """
    # Tìm dòng chứa tên nhân viên
    nv_match = re.search(r'(?:nv|nhân viên|nhan vien)[:\-]?[ \t]*([^\n]*)', text, re.IGNORECASE)
    # Tìm dòng chứa doanh thu
    dt_match = re.search(r'(?:doanh thu|dt|doanhthu)[:\-]?[ \t]*(\-?[\d\.\,kKmM]+)', text, re.IGNORECASE)
    
    if not nv_match or not dt_match:
        return [], 0, "", "Sai cú pháp! Hãy đảm bảo ghi chú ảnh có dòng 'NV: [tên]' và 'Doanh thu: [số tiền]'."
        
    raw_nvs = nv_match.group(1)
    # Tách tên chỉ bằng dấu phẩy để giữ nguyên khoảng trắng bên trong tên
    employees = [n.strip().lower() for n in raw_nvs.split(',') if n.strip()]
    
    # BUG-1 FIX: Parse số tiền với logic phân biệt dấu phẩy/chấm thông minh
    raw_dt = dt_match.group(1).strip()
    revenue = _parse_amount_str(raw_dt)
    
    if revenue is None:
        return [], 0, "", "Doanh thu không hợp lệ. Vui lòng chỉ nhập số (VD: 1500000, 1500k, 1.5M, 1.500k)."
    
    # Validation
    if revenue < 0:
        return [], 0, "", "❌ Doanh thu phải lớn hơn 0 VNĐ. Vui lòng kiểm tra lại."
    if revenue > 100_000_000:
        return [], 0, "", "❌ Doanh thu quá lớn (tối đa 100,000,000 VNĐ). Vui lòng kiểm tra lại."
        
    if not employees:
        return [], 0, "", "Không nhận diện được tên nhân viên nào."

    # BUG-3 FIX: Chỉ phát hiện Ca từ phần text NGOÀI dòng NV
    # để tránh false positive khi tên NV chứa từ 'sang', 'toi', v.v.
    text_for_ca = text[:nv_match.start()] + text[nv_match.end():]
    # Cũng loại bỏ phần doanh thu (dt line) để tránh match số trong dt
    if dt_match:
        dt_start = text_for_ca.find(dt_match.group(0))
        if dt_start != -1:
            text_for_ca = text_for_ca[:dt_start] + text_for_ca[dt_start + len(dt_match.group(0)):]

    ca = ""
    ca_match = re.search(r'(?:\bca\b[:\-\s]*)(sáng|sang|chiều|chieu|tối|toi)', text_for_ca, re.IGNORECASE)
    if ca_match:
        g = ca_match.group(1).lower()
        if 'sang' in g or 'sáng' in g:
            ca = 'Sáng'
        elif 'toi' in g or 'tối' in g:
            ca = 'Tối'
        else:
            ca = 'Chiều'
    else:
        low = text_for_ca.lower()
        if 'sáng' in low or 'sang' in low:
            ca = 'Sáng'
        elif 'tối' in low or 'toi' in low:
            ca = 'Tối'
        elif 'chiều' in low or 'chieu' in low:
            ca = 'Chiều'

    return employees, revenue, ca, ""


def check_reward_eligibility(num_employees: int, revenue: int) -> int:
    """
    Kiểm tra xem ca làm việc có đạt chỉ tiêu thưởng hay không.
    Trả về số ly thưởng mỗi nhân viên nhận được (0 nếu không đạt).
    """
    if num_employees == 2 and revenue >= 1_200_000:
        return 1
    elif num_employees >= 3 and revenue >= 1_500_000:
        return 1
    return 0


def deduplicate_employees(employees: List[str]) -> List[str]:
    """
    Loại bỏ nhân viên trùng lặp trong danh sách, giữ nguyên thứ tự.
    Ví dụ: ['anhuy', 'anhuy', 'xuanhau'] -> ['anhuy', 'xuanhau']
    """
    return list(dict.fromkeys(employees))