"""Script nhỏ để preview hoặc ghi thử hàng theo mẫu Bảng_1 vào Google Sheets.

Sử dụng:
    python scripts/test_append_bang1.py --date 21/05/2026 --employees "tuananh, hoanglan" --drive-link "https://..." [--commit]

Mặc định chỉ in ra hàng sẽ được ghi (an toàn). Thêm `--commit` để gọi thực sự `save_report`.

Lưu ý: để ghi thực sự cần cấu hình đúng `config.Config` với `GOOGLE_CREDENTIALS_FILE` và `SPREADSHEET_ID`.
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

# Ensure project root is on sys.path so we can import top-level modules
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google_sheets import GoogleSheetsService


def build_rows_preview(date: str, employees, ca: str = None):
    # Chuẩn hoá danh sách nhân viên
    if isinstance(employees, str):
        emps = [e.strip() for e in employees.split(',') if e.strip()]
        if not emps:
            emps = [e.strip() for e in employees.split() if e.strip()]
    elif isinstance(employees, (list, tuple)):
        emps = [str(e).strip() for e in employees if str(e).strip()]
    else:
        emps = [str(employees).strip()]

    now = datetime.now()
    if not ca:
        ca = 'Sáng' if now.hour < 12 else 'Chiều'
    time_str = now.strftime("%H:%M %d/%m/%Y")
    status = 'Đã duyệt'

    rows = []
    for nick in emps:
        rows.append([date, ca, nick, time_str, status])
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True)
    parser.add_argument('--employees', required=True)
    # No drive link column in the new sheet layout
    parser.add_argument('--commit', action='store_true', help='If set, actually write to Google Sheets')
    parser.add_argument('--ca', required=False, help='Optional Ca value (e.g. "Sáng" or "Chiều")')
    args = parser.parse_args()

    preview_rows = build_rows_preview(args.date, args.employees, ca=args.ca)
    print("Rows to append (preview):")
    for r in preview_rows:
        print(r)

    if args.commit:
        svc = GoogleSheetsService()
        ok = svc.save_report(args.date, args.employees, 0, ca=args.ca)
        print('Wrote to sheet:' , ok)
