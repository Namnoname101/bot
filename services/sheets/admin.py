"""Admin sheets mixin for admin permissions, overtime, and administrative tracking."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Optional, Set

from utils.time_utils import local_now
from utils.validators import normalize_name

logger = logging.getLogger(__name__)


class AdminSheetsMixin:
    """Mixin quản lý phân quyền Admin trên Sheets và tổng hợp giờ làm thêm."""

    def add_overtime(self, nickname: str, hours: float) -> bool:
        """Admin thêm giờ làm thêm cho nhân viên vào sheet GioLamThem.

        Cấu trúc: Ngày | Nickname | Tổng Số Giờ
        """
        try:
            today = local_now().strftime("%d/%m/%Y")

            # Lấy số cột thực tế từ header
            try:
                headers = self.ws_overtime.row_values(1)
                num_cols = len(headers)
            except Exception:
                num_cols = 3  # Default: Ngày, Nickname, Tổng Số Giờ

            # Tạo row với đủ số cột
            row = [today, nickname, hours]
            # Pad thêm cột trống nếu cần
            while len(row) < num_cols:
                row.append('')

            self.ws_overtime.insert_row(row[:num_cols], index=2, value_input_option='USER_ENTERED')
            logger.info(f"Đã thêm {hours}h làm thêm cho {nickname}")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi thêm giờ làm thêm cho {nickname}: {e}")
            return False

    def get_overtime_summary(self, start_date: datetime, end_date: datetime) -> dict:
        """Tổng hợp giờ làm thêm trong khoảng ngày, nhận diện cột theo header."""
        try:
            rows = self.ws_overtime.get_all_values()
            if not rows:
                return {}
            headers = [normalize_name(h) for h in rows[0]]
            date_col = next((i for i, h in enumerate(headers) if h in {'ngay', 'date'}), 0)
            nick_col = next((i for i, h in enumerate(headers) if 'nick' in h or h in {'ten', 'nhanvien'}), 1)
            hours_col = next((i for i, h in enumerate(headers) if 'gio' in h or 'hours' in h), 2)
            result = {}
            for row in rows[1:]:
                if len(row) <= max(date_col, nick_col, hours_col):
                    continue
                try:
                    row_date = datetime.strptime(row[date_col].strip(), "%d/%m/%Y")
                    if not start_date.date() <= row_date.date() <= end_date.date():
                        continue
                    nick = row[nick_col].strip()
                    hours = float(row[hours_col].strip().replace(',', '.'))
                except (TypeError, ValueError):
                    continue
                if nick:
                    result[nick] = result.get(nick, 0.0) + hours
            return result
        except Exception as e:
            logger.error("Lỗi tổng hợp giờ làm thêm: %s", e)
            return {}

    def _get_admin_worksheet(self, create: bool = False):
        try:
            return self.sh.worksheet("AdminList")
        except Exception:
            if not create:
                return None
            ws = self.sh.add_worksheet(title="AdminList", rows=100, cols=3)
            ws.update([["TelegramID", "GrantedBy", "GrantedAt"]], range_name='A1:C1')
            return ws

    def get_admin_list(self) -> set:
        """Đọc danh sách admin phụ; dữ liệu lỗi được bỏ qua an toàn."""
        try:
            ws = self._get_admin_worksheet(create=False)
            if not ws:
                return set()
            result = set()
            for value in ws.col_values(1)[1:]:
                try:
                    result.add(int(str(value).strip()))
                except (TypeError, ValueError):
                    continue
            return result
        except Exception as e:
            logger.error("Lỗi đọc AdminList: %s", e)
            return set()

    def add_admin(self, telegram_id: int, granted_by: str) -> bool:
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
        with self._write_lock:
            try:
                telegram_id = int(telegram_id)
                if telegram_id <= 0:
                    return False
                ws = self._get_admin_worksheet(create=True)
                existing = self.get_admin_list()
                if telegram_id in existing:
                    return True
                ws.append_row(
                    [telegram_id, str(granted_by), local_now().strftime("%d/%m/%Y %H:%M:%S")],
                    value_input_option='USER_ENTERED',
                )
                return True
            except Exception as e:
                logger.error("Lỗi thêm admin %s: %s", telegram_id, e)
                return False
