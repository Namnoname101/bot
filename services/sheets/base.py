import logging
import re
import threading
import time
from typing import Any, Optional

import gspread
from gspread.utils import rowcol_to_a1

from config import Config

logger = logging.getLogger(__name__)


class BaseSheetsService:
    """Lớp dịch vụ cơ sở quản lý kết nối Google Sheets, caching và custom worksheets."""

    @staticmethod
    def _column_letter(index: int) -> str:
        """Chuyển đổi chỉ số cột 1-based thành chữ cái cột (1 -> 'A', 27 -> 'AA')."""
        return re.sub(r'\d+', '', rowcol_to_a1(1, index))

    def __init__(self, max_retries: int = 3):
        """Khởi tạo Base Google Sheets Service với locks, cache và retry logic."""
        self._write_lock = threading.RLock()
        self._cache_lock = threading.Lock()
        self._cache = {}
        self.gc = None
        self.sh = None
        self.sh_salary = None
        self.sh_inventory = None
        self.ws_history = None
        self.ws_overtime = None
        self.ws_checkin = None

        if max_retries > 0:
            self._init_connections(max_retries=max_retries)

    def _init_connections(self, max_retries: int = 3):
        """Khởi tạo kết nối gspread và mở các bảng tính Google Sheets."""
        retry_count = 0
        last_error = None

        while retry_count < max_retries:
            try:
                self.gc = gspread.service_account_from_dict(Config.get_google_credentials_info())
                self.sh = self.gc.open_by_key(Config.SPREADSHEET_ID)
                self.sh_salary = self.gc.open_by_key(Config.SALARY_SPREADSHEET_ID)

                self.ws_history = self.sh.worksheet("LichSuThuong")
                self.ws_overtime = self.sh.worksheet("GioLamThem")
                self.ws_checkin = self.sh.worksheet("Checkin")

                self.sh_inventory = None
                if getattr(Config, "INVENTORY_SPREADSHEET_ID", None):
                    try:
                        self.sh_inventory = self.gc.open_by_key(Config.INVENTORY_SPREADSHEET_ID)
                        logger.info("✅ Kết nối Spreadsheet NVL thành công.")
                    except Exception as inv_err:
                        logger.warning(
                            "⚠️ Không kết nối được Spreadsheet NVL: %s. Tính năng kho sẽ bị tắt.",
                            str(inv_err)[:120],
                        )

                logger.info("✅ Kết nối Google Sheets thành công.")
                return

            except Exception as e:
                last_error = e
                retry_count += 1

                if retry_count < max_retries:
                    wait_time = 2 ** retry_count
                    logger.warning(
                        f"⚠️ Lỗi kết nối Google Sheets (lần {retry_count}/{max_retries}). "
                        f"Thử lại sau {wait_time}s...\nLỗi: {str(e)[:100]}"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"❌ Kết nối Google Sheets thất bại sau {max_retries} lần: {last_error}"
                    )
                    raise

    def _get_cache(self, key: str, ttl_seconds: float = 60.0) -> Optional[Any]:
        """Lấy giá trị từ bộ nhớ cache nếu chưa hết hạn TTL."""
        lock = getattr(self, "_cache_lock", None)
        if lock is None:
            self._cache_lock = threading.Lock()
            self._cache = {}
        with self._cache_lock:
            if key in self._cache:
                ts, val = self._cache[key]
                if time.time() - ts < ttl_seconds:
                    return val
                del self._cache[key]
        return None

    def _set_cache(self, key: str, value: Any):
        """Lưu giá trị vào cache kèm timestamp hiện tại."""
        lock = getattr(self, "_cache_lock", None)
        if lock is None:
            self._cache_lock = threading.Lock()
            self._cache = {}
        with self._cache_lock:
            self._cache[key] = (time.time(), value)

    def _invalidate_cache(self, *keys_or_prefixes: str):
        """Xoá cache theo danh sách key hoặc prefix (nếu rỗng thì xoá toàn bộ)."""
        lock = getattr(self, "_cache_lock", None)
        if lock is None:
            self._cache_lock = threading.Lock()
            self._cache = {}
            return
        with self._cache_lock:
            if not keys_or_prefixes:
                self._cache.clear()
                return
            for prefix in keys_or_prefixes:
                for k in list(self._cache.keys()):
                    if k == prefix or k.startswith(prefix):
                        self._cache.pop(k, None)

    def _get_or_create_custom_sheet(
        self, title: str, default_headers: list[str]
    ) -> Optional[gspread.Worksheet]:
        """Tìm worksheet, nếu chưa có thì tự động tạo mới với header chuẩn."""
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
        with self._write_lock:
            try:
                return self.sh.worksheet(title)
            except gspread.exceptions.WorksheetNotFound:
                try:
                    ws = self.sh.add_worksheet(
                        title=title, rows=200, cols=max(len(default_headers), 10)
                    )
                    if default_headers:
                        ws.append_row(default_headers, value_input_option='USER_ENTERED')
                    logger.info("✅ Đã tự động tạo worksheet mới: %s", title)
                    return ws
                except Exception as e:
                    logger.error("Không thể tạo worksheet %s: %s", title, e)
                    return None
            except Exception as e:
                logger.error("Lỗi khi tìm worksheet %s: %s", title, e)
                return None
