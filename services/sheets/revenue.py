"""Revenue sheets mixin for shift revenue reporting and mapping sheet helpers."""
from __future__ import annotations

import logging
import re
import threading
from typing import Any, Optional, Union

from utils.time_utils import local_now
from utils.validators import normalize_name

logger = logging.getLogger(__name__)


class RevenueSheetsMixin:
    """Mixin quản lý báo cáo doanh thu ca, mapping sheet và cập nhật doanh thu."""

    def save_report(
        self,
        date: str,
        employees,
        revenue: int,
        ca: str = None,
        report_key: str = None,
    ) -> bool | str:
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
        with self._write_lock:
            return self._save_report_unlocked(date, employees, revenue, ca, report_key)

    def _save_report_unlocked(
        self,
        date: str,
        employees,
        revenue: int,
        ca: str = None,
        report_key: str = None,
    ) -> bool | str:
        """Lưu lịch sử duyệt báo cáo theo mẫu Bảng_1.

        Mẫu cột (theo thứ tự): Ngày, Ca, Nickname, ThoiGianBaoCao, TrangThai, DoanhThu

        - `employees` có thể là chuỗi phân tách bằng dấu phẩy hoặc danh sách.
        - Ghi một hàng cho mỗi nickname.
        - `Ca` được suy ra từ giờ hiện tại: trước 12h -> 'Sáng', còn lại -> 'Chiều'.
        - `ThoiGianBaoCao` là thời gian hiện tại khi ghi (format HH:MM dd/mm/YYYY).
        - `TrangThai` mặc định là 'Đã duyệt'.
        """
        try:
            # Chuẩn hoá danh sách nhân viên
            if isinstance(employees, str):
                # tách theo dấu phẩy chính là kịch bản phổ biến
                emps = [e.strip() for e in employees.split(',') if e.strip()]
                # nếu vẫn rỗng, thử tách theo whitespace
                if not emps:
                    emps = [e.strip() for e in employees.split() if e.strip()]
            elif isinstance(employees, (list, tuple)):
                emps = [str(e).strip() for e in employees if str(e).strip()]
            else:
                emps = [str(employees).strip()]

            if not emps:
                logger.warning("Không có nhân viên hợp lệ để lưu báo cáo.")
                return False

            if report_key:
                marker = f"[ref:{report_key}]"
                if any(marker in value for value in self.ws_history.col_values(5)[1:]):
                    logger.info("Bỏ qua báo cáo trùng %s", report_key)
                    return 'duplicate'

            now = local_now()
            if not ca:
                if now.hour < 12:
                    ca = 'Sáng'
                elif now.hour < 18:
                    ca = 'Chiều'
                else:
                    ca = 'Tối'
            time_str = now.strftime("%H:%M %d/%m/%Y")
            status = 'Đã duyệt' + (f" [ref:{report_key}]" if report_key else '')

            # Lấy số cột thực tế từ header
            try:
                headers = self.ws_history.row_values(1)
                num_cols = len(headers)
            except Exception:
                num_cols = 6  # Default: Ngày, Ca, Nickname, ThoiGianBaoCao, TrangThai, DoanhThu

            # Thêm hàng mới vào vị trí ngay sau header, kế thừa định dạng từ hàng dữ liệu đầu tiên
            try:
                sheet_id = self.ws_history._properties['sheetId']
                # Số dòng đang có dữ liệu (bao gồm header)
                existing = self.ws_history.get_all_values()
                used_rows = len(existing)

                insert_count = len(emps)
                # Chèn ngay sau header (start_index = 1 trong 0-based, tức row 2 trong 1-based)
                start_index = 1 if used_rows >= 1 else 0

                requests = []

                # 1. Chèn hàng trống mới
                requests.append({
                    'insertDimension': {
                        'range': {
                            'sheetId': sheet_id,
                            'dimension': 'ROWS',
                            'startIndex': start_index,
                            'endIndex': start_index + insert_count,
                        },
                        'inheritFromBefore': False,
                    }
                })

                self.sh.batch_update({'requests': requests})

                # Viết giá trị vào các hàng vừa chèn - đủ số cột
                start_row_1b = start_index + 1
                end_row_1b = start_row_1b + insert_count - 1
                values = []
                for nick in emps:
                    # Tạo row với đủ số cột
                    row = [date, ca, nick, time_str, status, revenue]
                    # Pad thêm cột trống nếu cần
                    while len(row) < num_cols:
                        row.append('')
                    values.append(row[:num_cols])

                # Xác định range theo số cột thực tế
                end_col = self._column_letter(num_cols)
                range_str = f'A{start_row_1b}:{end_col}{end_row_1b}'
                self.ws_history.update(values, range_name=range_str, value_input_option='USER_ENTERED')

                logger.info(f"Đã lưu báo cáo cho {len(emps)} nhân viên")
                return True
            except Exception:
                # Nếu batch_update không khả dụng, fallback về insert_row từng hàng
                logger.exception('Batch insert failed, falling back to insert_row')
                for nick in reversed(emps):
                    row = [date, ca, nick, time_str, status, revenue]
                    # Pad thêm cột trống nếu cần
                    while len(row) < num_cols:
                        row.append('')
                    self.ws_history.insert_row(row[:num_cols], index=2, value_input_option='USER_ENTERED')

                return True
        except Exception as e:
            logger.error(f"Lỗi khi lưu báo cáo: {e}")
            return False

    def _get_mapping_worksheet(self):
        return self.sh_salary.worksheet("Mapping")

    def _get_mapping_indices(self, headers):
        headers_norm = [normalize_name(h) for h in headers]
        nick_col = next((i for i, h in enumerate(headers_norm) if 'nickname' in h or h in {'nick', 'nicknamebot'}), 1)
        bal_col = next((i for i, h in enumerate(headers_norm) if 'sodu' in h or 'thuong' in h), 3)
        rate_col = next((i for i, h in enumerate(headers_norm) if ('luong' in h and 'ten' not in h) or 'rate' in h), 2)
        return nick_col, rate_col, bal_col

    def get_recent_revenue_reports(self, limit: int = 8) -> list:
        """Lấy các ca báo cáo gần nhất, gom nhóm theo (ngày, ca).

        Mỗi session: {date, ca, employees, revenue, row_indices, time}
        """
        try:
            all_data = self.ws_history.get_all_values()
            sessions: dict = {}   # key = (date, ca)
            for i, row in enumerate(all_data[1:], start=2):
                if len(row) < 3:
                    continue
                date = row[0].strip()
                ca   = row[1].strip()
                nick = row[2].strip()
                rev  = row[5].strip() if len(row) > 5 else ''
                report_time = row[3].strip() if len(row) > 3 else ''
                status = row[4].strip() if len(row) > 4 else ''
                ref_match = re.search(r'\[ref:([^\]]+)\]', status)
                report_ref = ref_match.group(1) if ref_match else ''
                key  = (date, ca, report_ref or report_time)
                if key not in sessions:
                    sessions[key] = {
                        'date': date, 'ca': ca,
                        'employees': [], 'revenue': '',
                        'row_indices': [],
                        'time': report_time,
                        'report_ref': report_ref,
                    }
                    if len(sessions) > limit * 3:  # stop collecting more keys early
                        break
                sessions[key]['employees'].append(nick)
                sessions[key]['row_indices'].append(i)
                # Giữ doanh thu mới nhất (hàng đầu tiên gặp = mới nhất vì insert ở top)
                if rev and not sessions[key]['revenue']:
                    sessions[key]['revenue'] = rev

            return list(sessions.values())[:limit]
        except Exception as e:
            logger.error(f"Lỗi lấy báo cáo gần nhất: {e}")
            return []

    def update_report_revenue(self, session, new_revenue: int) -> bool:
        """Cập nhật doanh thu sau khi tìm lại row hiện tại, tránh row index bị dịch."""
        try:
            if isinstance(session, dict):
                all_data = self.ws_history.get_all_values()
                employees = {normalize_name(n) for n in session.get('employees', [])}
                row_indices = []
                for i, row in enumerate(all_data[1:], start=2):
                    if len(row) < 3:
                        continue
                    if row[0].strip() != session.get('date') or row[1].strip() != session.get('ca'):
                        continue
                    if session.get('report_ref'):
                        status = row[4].strip() if len(row) > 4 else ''
                        if f"[ref:{session['report_ref']}]" not in status:
                            continue
                    if session.get('time') and (len(row) <= 3 or row[3].strip() != session.get('time')):
                        continue
                    if employees and normalize_name(row[2]) not in employees:
                        continue
                    row_indices.append(i)
            else:
                row_indices = list(session or [])
            if not row_indices:
                return False
            for row_idx in row_indices:
                self.ws_history.update_cell(row_idx, 6, new_revenue)
            logger.info(f"Đã cập nhật DT={new_revenue} cho rows {row_indices}")
            return True
        except Exception as e:
            logger.error(f"Lỗi cập nhật doanh thu: {e}")
            return False
