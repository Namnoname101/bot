import gspread
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta
from gspread.utils import rowcol_to_a1
from config import Config
from utils.validators import normalize_name
from utils.time_utils import local_now

logger = logging.getLogger(__name__)

# Tương thích với các script cũ; code mới dùng normalize_name trực tiếp.
_normalize_name_for_comparison = normalize_name


class GoogleSheetsService:
    @staticmethod
    def _column_letter(index: int) -> str:
        return re.sub(r'\d+', '', rowcol_to_a1(1, index))

    def __init__(self, max_retries=3):
        """Khởi tạo Google Sheets Service với retry logic.
        
        Args:
            max_retries: Số lần thử lại tối đa khi kết nối thất bại
        """
        self._write_lock = threading.RLock()
        retry_count = 0
        last_error = None
        
        while retry_count < max_retries:
            try:
                # Kết nối Google Sheets bằng Service Account
                self.gc = gspread.service_account_from_dict(Config.get_google_credentials_info())
                self.sh = self.gc.open_by_key(Config.SPREADSHEET_ID)
                self.sh_salary = self.gc.open_by_key(Config.SALARY_SPREADSHEET_ID)
                
                # Khởi tạo các trang tính (Worksheets)
                self.ws_history = self.sh.worksheet("LichSuThuong")
                self.ws_balance = self.sh.worksheet("SoDuThuong")
                self.ws_overtime = self.sh.worksheet("GioLamThem")
                self.ws_checkin = self.sh.worksheet("Checkin")
                logger.info("✅ Kết nối Google Sheets thành công.")
                
                # Detect header columns for balance sheet so we can read/write the "remaining" balance reliably
                try:
                    self.balance_headers = self.ws_balance.row_values(1) or []
                except Exception:
                    self.balance_headers = []

                # Default indices (1-based): assume Nickname in col 1 and balance in col 2
                self.col_nickname_index = 1
                self.col_dathuong_index = 2
                self.col_dadung_index = 3
                self.col_balance_index = 4


                for idx, h in enumerate(self.balance_headers):
                    hn = normalize_name(h)
                    if 'nick' in hn or 'ten' in hn:
                        self.col_nickname_index = idx + 1
                    elif 'dathuong' in hn:
                        self.col_dathuong_index = idx + 1
                    elif 'dadung' in hn:
                        self.col_dadung_index = idx + 1
                    elif 'conlai' in hn or 'sodu' in hn or 'solyconlai' in hn or 'remaining' in hn:
                        self.col_balance_index = idx + 1

                # Ensure indices are sensible
                if self.col_nickname_index < 1:
                    self.col_nickname_index = 1
                if self.col_balance_index < 1:
                    self.col_balance_index = 4
                
                # Kết nối thành công, thoát khỏi vòng lặp retry
                return
                
            except Exception as e:
                last_error = e
                retry_count += 1
                
                if retry_count < max_retries:
                    wait_time = 2 ** retry_count  # Exponential backoff: 2, 4, 8 seconds
                    logger.warning(
                        f"⚠️ Lỗi kết nối Google Sheets (lần {retry_count}/{max_retries}). "
                        f"Thử lại sau {wait_time}s...\nLỗi: {str(e)[:100]}"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"❌ Kết nối Google Sheets thất bại sau {max_retries} lần: {last_error}")
                    raise

    def save_report(
        self,
        date: str,
        employees,
        revenue: int,
        ca: str = None,
        report_key: str = None,
    ) -> bool | str:
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
                            'endIndex': start_index + insert_count
                        },
                        'inheritFromBefore': False
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

    def get_balance(self, nickname: str) -> int:
        """Lấy số dư của một nhân viên"""
        try:
            # Lấy toàn bộ cột nickname và balance bằng 2 API calls
            col_nicks = self.ws_balance.col_values(self.col_nickname_index)
            col_bals = self.ws_balance.col_values(self.col_balance_index)
            target = normalize_name(nickname)
            
            # skip header row
            for i, v in enumerate(col_nicks[1:], start=2):
                if normalize_name(str(v)) == target:
                    # Lấy giá trị từ cột balance ở dòng i này
                    if i - 1 < len(col_bals):
                        cell_val = col_bals[i - 1]
                    else:
                        cell_val = None
                    
                    if cell_val is None or str(cell_val).strip() == '':
                        return 0
                    try:
                        return int(str(cell_val).strip())
                    except ValueError:
                        # try to clean non-digit characters
                        cleaned = re.sub(r'[^0-9\-]', '', str(cell_val))
                        return int(cleaned) if cleaned else 0
            return 0
        except Exception as e:
            logger.error(f"Lỗi khi lấy số dư của {nickname}: {e}")
            return 0

    def get_all_salary_rates(self) -> dict:
        """Lấy mức lương/giờ từ Mapping, fallback SoDuThuong/default."""
        try:
            default_rate = Config.DEFAULT_HOURLY_RATE_K
            balance_rows = self.ws_balance.get_all_values()
            rates = {}
            for row in balance_rows[1:]:
                if len(row) < self.col_nickname_index:
                    continue
                nick = row[self.col_nickname_index - 1].strip()
                if not nick:
                    continue
                rate = default_rate
                if len(row) >= 5 and row[4].strip():
                    try:
                        rate = float(row[4].strip().replace(',', '.'))
                    except ValueError:
                        pass
                rates[nick] = rate

            try:
                ws_mapping = self.sh_salary.worksheet("Mapping")
            except Exception:
                return rates

            records = ws_mapping.get_all_values()
            if not records:
                return rates
            headers = [normalize_name(h) for h in records[0]]
            nick_col = next(
                (i for i, h in enumerate(headers) if 'nickname' in h or h in {'nick', 'nicknamebot'}),
                1 if len(headers) > 1 else 0,
            )
            rate_col = next(
                (i for i, h in enumerate(headers) if ('luong' in h and 'ten' not in h) or 'rate' in h),
                2,
            )
            for row in records[1:]:
                if len(row) <= nick_col or not row[nick_col].strip():
                    continue
                nick = row[nick_col].strip()
                rate = default_rate
                if len(row) > rate_col and row[rate_col].strip():
                    try:
                        rate = float(row[rate_col].strip().replace(',', '.'))
                    except ValueError:
                        pass
                existing = next((key for key in rates if normalize_name(key) == normalize_name(nick)), None)
                rates[existing or nick] = rate
            return rates
        except Exception as e:
            logger.error(f"Lỗi khi lấy danh sách mức lương từ Mapping: {e}")
            return {}

    def update_salary_rate(self, nickname: str, new_rate: str) -> bool:
        """Cập nhật nguồn chuẩn Mapping và mirror sang SoDuThuong để tương thích."""
        with self._write_lock:
            try:
                rate = float(str(new_rate).replace(',', '.'))
                if rate <= 0 or rate > 1000:
                    return False

                try:
                    ws_mapping = self.sh_salary.worksheet("Mapping")
                except Exception:
                    ws_mapping = self.sh_salary.add_worksheet(title="Mapping", rows=100, cols=3)
                    ws_mapping.update([["Tên Nhân Viên", "Nickname Bot", "Mức Lương/Giờ"]], range_name='A1:C1')

                rows = ws_mapping.get_all_values()
                if not rows:
                    ws_mapping.update([["Tên Nhân Viên", "Nickname Bot", "Mức Lương/Giờ"]], range_name='A1:C1')
                    rows = [["Tên Nhân Viên", "Nickname Bot", "Mức Lương/Giờ"]]
                if len(rows[0]) < 3 or not rows[0][2].strip():
                    ws_mapping.update_cell(1, 3, "Mức Lương/Giờ")

                target = normalize_name(nickname)
                mapping_row = next(
                    (i for i, row in enumerate(rows[1:], start=2)
                     if len(row) > 1 and normalize_name(row[1]) == target),
                    None,
                )
                if mapping_row:
                    ws_mapping.update_cell(mapping_row, 3, rate)
                else:
                    ws_mapping.append_row([nickname, nickname, rate], value_input_option='USER_ENTERED')

                balance_rows = self.ws_balance.get_all_values()
                for i, row in enumerate(balance_rows[1:], start=2):
                    if len(row) >= self.col_nickname_index and normalize_name(row[self.col_nickname_index - 1]) == target:
                        if len(balance_rows[0]) < 5 or not balance_rows[0][4].strip():
                            self.ws_balance.update_cell(1, 5, "Mức Lương/Giờ")
                        self.ws_balance.update_cell(i, 5, rate)
                        break
                return True
            except Exception as e:
                logger.error(f"Lỗi khi cập nhật mức lương cho {nickname}: {e}")
                return False


    def get_all_balances(self) -> dict:
        """Lấy số dư của tất cả nhân viên (dành cho quản lý)"""
        try:
            # Try to use header-aware mapping first
            headers = self.balance_headers
            if headers and len(headers) >= max(self.col_nickname_index, self.col_balance_index):
                nick_label = headers[self.col_nickname_index - 1]
                bal_label = headers[self.col_balance_index - 1]
                records = self.ws_balance.get_all_records()
                result = {}
                for row in records:
                    nick = str(row.get(nick_label, '')).strip()
                    if not nick:
                        continue
                    try:
                        bal = int(row.get(bal_label, 0) or 0)
                    except Exception:
                        bal = 0
                    result[nick] = bal
                return result

            # Fallback: read both columns at once (2 API calls thay vì N+1)
            col_nicks = self.ws_balance.col_values(self.col_nickname_index)[1:]
            col_bals = self.ws_balance.col_values(self.col_balance_index)[1:]
            result = {}
            for nick, bal in zip(col_nicks, col_bals):
                nick_str = str(nick).strip()
                if not nick_str:
                    continue
                try:
                    bal_val = int(str(bal).strip()) if bal and str(bal).strip() != '' else 0
                except Exception:
                    cleaned = re.sub(r'[^0-9\-]', '', str(bal or ''))
                    bal_val = int(cleaned) if cleaned else 0
                result[nick_str] = bal_val
            return result
        except Exception as e:
            logger.error(f"Lỗi khi lấy danh sách số dư: {e}")
            return {}

    def get_all_nicknames(self) -> list:
        """Lấy danh sách tất cả nickname hợp lệ từ Sheet SoDuThuong (chuẩn hóa Unicode)"""
        try:
            # Prefer reading column directly for speed
            col_vals = self.ws_balance.col_values(self.col_nickname_index)
            return [normalize_name(str(v)) for v in col_vals[1:] if str(v).strip()]
        except Exception as e:
            logger.error(f"Lỗi khi lấy danh sách nickname: {e}")
            return []

    def update_balance(self, nickname: str, amount_change: int) -> bool:
        with self._write_lock:
            return self._update_balance_unlocked(nickname, amount_change)

    def _update_balance_unlocked(self, nickname: str, amount_change: int) -> bool:
        """Cập nhật số dư. amount_change có thể là số dương (cộng) hoặc âm (trừ)."""
        try:
            nickname_clean = nickname.strip()
            nickname_normalized = normalize_name(nickname_clean)

            # Read nickname column ONCE
            col_nicks = self.ws_balance.col_values(self.col_nickname_index)
            
            found_row = None
            for i, v in enumerate(col_nicks[1:], start=2):
                if normalize_name(str(v)) == nickname_normalized:
                    found_row = i
                    break

            if found_row:
                # Cập nhật SoLyDaThuong (nếu cộng) hoặc SoLyDaDung (nếu trừ)
                target_col = self.col_dathuong_index if amount_change > 0 else self.col_dadung_index
                val_to_add = abs(amount_change)

                try:
                    col_data = self.ws_balance.col_values(target_col)
                    current_val = int(str(col_data[found_row - 1]).strip()) if found_row - 1 < len(col_data) and str(col_data[found_row - 1]).strip() != '' else 0
                except Exception:
                    current_val = 0

                new_val = current_val + val_to_add
                self.ws_balance.update_cell(found_row, target_col, new_val)
                logger.info(f"Cập nhật số dư {nickname}: {new_val}")
                return True

            # If not found, insert a new row at position 2
            if amount_change > 0:
                # Lấy số cột thực tế từ header
                try:
                    headers = self.ws_balance.row_values(1)
                    num_cols = len(headers)
                except Exception:
                    num_cols = max(len(self.balance_headers), self.col_balance_index)
                
                # Tạo row với đủ số cột
                row = [''] * num_cols
                row[self.col_nickname_index - 1] = nickname_clean
                row[self.col_dathuong_index - 1] = amount_change
                row[self.col_dadung_index - 1] = 0
                # Sử dụng formula động với INDIRECT và ROW() để tính toán cho hàng hiện tại
                if self.col_balance_index - 1 < num_cols:
                    row[self.col_balance_index - 1] = f"=INDIRECT(\"B\"&ROW())-INDIRECT(\"C\"&ROW())"
                
                self.ws_balance.insert_row(row, index=2, value_input_option='USER_ENTERED')
                logger.info(f"Đã thêm nhân viên mới {nickname} với số dư {amount_change}")
                return True

            logger.warning(f"Không tìm thấy nhân viên {nickname} để trừ thưởng.")
            return False
        except gspread.exceptions.CellNotFound:
            if amount_change > 0:
                # Lấy số cột thực tế từ header
                try:
                    headers = self.ws_balance.row_values(1)
                    num_cols = len(headers)
                except Exception:
                    num_cols = max(len(self.balance_headers), self.col_balance_index)
                
                row = [''] * num_cols
                row[self.col_nickname_index - 1] = nickname_clean
                row[self.col_dathuong_index - 1] = amount_change
                row[self.col_dadung_index - 1] = 0
                if self.col_balance_index - 1 < num_cols:
                    row[self.col_balance_index - 1] = f"=INDIRECT(\"B\"&ROW())-INDIRECT(\"C\"&ROW())"
                
                self.ws_balance.insert_row(row, index=2, value_input_option='USER_ENTERED')
                return True
            return False
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật số dư cho {nickname}: {e}")
            return False

    def batch_update_balances(self, nicknames: list, amount_change: int) -> bool:
        with self._write_lock:
            return self._batch_update_balances_unlocked(nicknames, amount_change)

    def _batch_update_balances_unlocked(self, nicknames: list, amount_change: int) -> bool:
        """Cập nhật số dư cho nhiều nhân viên cùng lúc để tối ưu API Google Sheets."""
        if not nicknames or amount_change == 0:
            return True
        try:
            col_nicks = self.ws_balance.col_values(self.col_nickname_index)
            col_nicks_normalized = [normalize_name(str(v)) for v in col_nicks]

            target_col = self.col_dathuong_index if amount_change > 0 else self.col_dadung_index
            target_col_letter = self._column_letter(target_col)

            try:
                col_data = self.ws_balance.col_values(target_col)
            except Exception:
                col_data = []

            updates = []
            inserts = []

            for nick in nicknames:
                nick_clean = nick.strip()
                nick_norm = normalize_name(nick_clean)

                try:
                    # skip header (index 0)
                    row_idx = col_nicks_normalized.index(nick_norm, 1) if len(col_nicks_normalized) > 1 else -1
                    if row_idx == -1:
                        raise ValueError

                    found_row = row_idx + 1

                    current_val = 0
                    if row_idx < len(col_data):
                        val_str = str(col_data[row_idx]).strip()
                        if val_str:
                            try:
                                current_val = int(val_str)
                            except ValueError:
                                pass

                    new_val = current_val + abs(amount_change)
                    updates.append({
                        'range': f"{target_col_letter}{found_row}",
                        'values': [[new_val]]
                    })
                except ValueError:
                    # Not found, prepare insert
                    if amount_change > 0:
                        inserts.append(nick_clean)

            if updates:
                self.ws_balance.batch_update(updates, value_input_option='USER_ENTERED')

            if inserts:
                for nick_clean in inserts:
                    # Fallback to insert_row cho NV mới
                    self._update_balance_unlocked(nick_clean, amount_change)

            logger.info(f"Đã batch update số dư cho {len(nicknames)} nhân viên.")
            return True
        except Exception as e:
            logger.error(f"Lỗi batch update balances: {e}")
            return False

    def consume_reward(self, nickname: str) -> dict:
        """Đọc và trừ một ly trong cùng critical section để tránh trừ quá số dư."""
        with self._write_lock:
            balance = self.get_balance(nickname)
            if balance <= 0:
                return {'success': False, 'error': 'insufficient_balance', 'balance': balance}
            success = self._update_balance_unlocked(nickname, -1)
            return {
                'success': success,
                'error': '' if success else 'update_failed',
                'balance': balance - 1 if success else balance,
            }

    # ==================== GIỜ LÀM THÊM ====================

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

    # ==================== CHECK-IN / CHECK-OUT ====================

    def _get_shift_info(self, now: datetime) -> dict:
        """Xác định ca theo khung giờ nghiệp vụ, tránh phân loại theo khoảng cách."""
        current_minutes = now.hour * 60 + now.minute
        if current_minutes < 12 * 60:
            return {'ca': 'Sáng', 'standard_start': 6 * 60 + 30}
        if current_minutes < 18 * 60:
            return {'ca': 'Chiều', 'standard_start': 12 * 60}
        return {'ca': 'Tối', 'standard_start': 18 * 60}

    def get_checked_in_employees(self) -> dict:
        """Lấy danh sách các nhân viên đã check-in hôm nay nhưng chưa check-out.
        
        Returns:
            dict: {nickname: checkin_time}
        """
        try:
            today = local_now().strftime("%d/%m/%Y")
            all_data = self.ws_checkin.get_all_values()
            checked_in = {}
            for row in all_data[1:]:
                if len(row) >= 3:
                    row_date = row[0].strip()
                    row_nick = row[1].strip()
                    row_checkout = row[3].strip() if len(row) > 3 else ""
                    if row_date == today and not row_checkout:
                        checked_in[row_nick] = row[2].strip()
            return checked_in
        except Exception as e:
            logger.error(f"Lỗi khi lấy danh sách check-in: {e}")
            return {}

    def get_open_checkin_sessions(
        self,
        ca: str = None,
        shift_type: str = None,
        date_str: str = None,
    ) -> list:
        """Lấy danh sách các phiên check-in chưa check-out.
        
        Args:
            ca: Lọc theo ca Sáng/Chiều/Tối.
            shift_type: Lọc theo loại ca (Ca Chính/Ca Gãy).
            date_str: Ngày dd/mm/YYYY; mặc định hôm nay.
            
        Returns:
            list: [{'nickname': str, 'checkin_time': str, 'shift_type': str, 'note': str}, ...]
        """
        try:
            all_data = self.ws_checkin.get_all_values()
            target_date = date_str or local_now().strftime("%d/%m/%Y")
            open_sessions = []
            for row in all_data[1:]:
                if len(row) >= 3:
                    row_date = row[0].strip()
                    row_nick = row[1].strip()
                    row_checkin = row[2].strip()
                    row_checkout = row[3].strip() if len(row) > 3 else ""
                    row_note = row[5].strip() if len(row) > 5 else ""
                    
                    if row_date == target_date and not row_checkout:
                        is_ca_gay = "ca gãy" in row_note.lower()
                        current_shift = "Ca Gãy" if is_ca_gay else "Ca Chính"
                        
                        if shift_type and current_shift != shift_type:
                            continue
                            
                        # Phục hồi 'ca' (Sáng/Chiều/Tối) từ giờ check-in để auto-checkout cuối ngày nhận diện được
                        try:
                            checkin_dt = datetime.strptime(row_checkin, "%H:%M:%S")
                            ca_label = self._get_shift_info(checkin_dt)['ca']
                        except Exception:
                            ca_label = ""
                            
                        if ca and ca_label != ca:
                            continue

                        open_sessions.append({
                            'date': row_date,
                            'nickname': row_nick,
                            'checkin_time': row_checkin,
                            'shift_type': current_shift,
                            'ca': ca_label,
                            'note': row_note
                        })
            return open_sessions
        except Exception as e:
            logger.error(f"Lỗi lấy phiên mở: {e}")
            return []

    def checkin(self, nickname: str, shift_type: str = "", ca: str = None) -> dict:
        """Ghi nhận check-in cho nhân viên vào sheet Checkin.
        
        Cấu trúc: Ngày | Nickname | Giờ Vào | Giờ Ra | Tổng Giờ | Ghi Chú
        
        Returns:
            dict với keys: success, time, note, late_minutes, ca, date_str
        """
        try:
            now = local_now()
            if shift_type not in {'Ca Chính', 'Ca Gãy'}:
                return {'success': False, 'error': 'invalid_shift_type'}
            today = now.strftime("%d/%m/%Y")
            actual_time_str = now.strftime("%H:%M:%S")
            
            # Kiểm tra đã check-in hôm nay chưa
            all_data = self.ws_checkin.get_all_values()
            for row in all_data[1:]:
                if len(row) >= 3:
                    row_date = row[0].strip()
                    row_nick = row[1].strip()
                    row_checkout = row[3].strip() if len(row) > 3 else ""
                    if (row_date == today and 
                        normalize_name(row_nick) == normalize_name(nickname) and
                        not row_checkout):
                        return {'success': False, 'error': 'already_checked_in',
                                'time': row[2].strip()}
            
            # Ca chính được người dùng chọn để check-in sớm không bị nhận nhầm
            # sang ca trước. Các lời gọi cũ không truyền ca vẫn được suy theo giờ.
            inferred_shift = self._get_shift_info(now)
            selected_ca = ca or inferred_shift['ca']
            shift_starts = {
                'Sáng': 6 * 60 + 30,
                'Chiều': 12 * 60,
                'Tối': 18 * 60,
            }
            shift_ends = {
                'Sáng': 12 * 60,
                'Chiều': 18 * 60,
                'Tối': 24 * 60,
            }
            if selected_ca not in shift_starts:
                return {'success': False, 'error': 'invalid_shift_ca'}

            standard_start = shift_starts[selected_ca]
            current_minutes = now.hour * 60 + now.minute

            # Ca gãy thuộc ca Tối và bắt đầu lúc 19:30.
            if shift_type == "Ca Gãy":
                selected_ca = 'Tối'
                standard_start = 19 * 60 + 30

            earliest_checkin = standard_start - 30
            if current_minutes < earliest_checkin:
                allowed_time = f"{earliest_checkin // 60:02d}:{earliest_checkin % 60:02d}"
                return {
                    'success': False,
                    'error': 'too_early',
                    'allowed_time': allowed_time,
                    'ca': selected_ca,
                }

            # Không cho chọn lại một ca đã kết thúc. Ca Tối được phép đến hết ngày.
            if shift_type == 'Ca Chính' and current_minutes >= shift_ends[selected_ca]:
                return {'success': False, 'error': 'shift_ended', 'ca': selected_ca}

            # Người đến sớm được ghi giờ chuẩn để không tự động phát sinh tiền công.
            early_minutes = max(0, standard_start - current_minutes)
            if early_minutes:
                time_str = f"{standard_start // 60:02d}:{standard_start % 60:02d}:00"
            else:
                time_str = actual_time_str

            # Cho phép trễ tối đa 5 phút (grace period)
            if current_minutes <= standard_start + 5:
                late_minutes = 0
            else:
                late_minutes = current_minutes - standard_start
            
            if late_minutes > 0:
                note = f"{shift_type} - Đi muộn {late_minutes}p" if shift_type else f"Đi muộn {late_minutes}p"
            else:
                note = f"{shift_type} - Đúng giờ" if shift_type else "Đúng giờ"
            note += f" - Ca {selected_ca}"
            if early_minutes:
                note += f" - Check-in sớm lúc {actual_time_str}"
            
            # Lấy số cột thực tế từ header
            try:
                headers = self.ws_checkin.row_values(1)
                num_cols = len(headers)
            except Exception:
                num_cols = 6  # Default: Ngày, Nickname, Giờ Vào, Giờ Ra, Tổng Giờ, Ghi Chú
            
            # Ghi hàng mới vào sheet với định dạng đúng
            try:
                # Sử dụng batch update để chèn hàng và copy format
                sheet_id = self.ws_checkin._properties['sheetId']
                requests = []
                
                # Chèn 1 hàng mới tại vị trí 2 (0-based index = row 2 trong 1-based)
                requests.append({
                    'insertDimension': {
                        'range': {
                            'sheetId': sheet_id,
                            'dimension': 'ROWS',
                            'startIndex': 1,
                            'endIndex': 2
                        },
                        'inheritFromBefore': False
                    }
                })
                
                # Copy format từ hàng 3 (nếu có data sẵn) hoặc header
                # FIX VẤN ĐỀ 3: tái dùng all_data thay vì gọi API lần thứ 2
                if len(all_data) > 2:
                    # Có hàng dữ liệu, copy format từ row 3
                    requests.append({
                        'copyPaste': {
                            'source': {
                                'sheetId': sheet_id,
                                'startRowIndex': 2,
                                'startColumnIndex': 0,
                                'endRowIndex': 3,
                                'endColumnIndex': num_cols
                            },
                            'destination': {
                                'sheetId': sheet_id,
                                'startRowIndex': 1,
                                'endRowIndex': 2,
                                'startColumnIndex': 0,
                                'endColumnIndex': num_cols
                            },
                            'pasteType': 'PASTE_FORMAT'
                        }
                    })
                
                self.sh.batch_update({'requests': requests})
                
                # Viết dữ liệu vào hàng mới - đủ số cột
                row = [today, nickname, time_str, "", "", note]
                # Pad thêm cột trống nếu cần
                while len(row) < num_cols:
                    row.append('')
                
                end_col = self._column_letter(num_cols)
                self.ws_checkin.update([row[:num_cols]], range_name=f'A2:{end_col}2', value_input_option='USER_ENTERED')
                
            except Exception:
                # Fallback: insert_row nếu batch update fail
                logger.exception('Batch insert for checkin failed, falling back to insert_row')
                row = [today, nickname, time_str, "", "", note]
                # Pad thêm cột trống nếu cần
                while len(row) < num_cols:
                    row.append('')
                self.ws_checkin.insert_row(row[:num_cols], index=2, value_input_option='USER_ENTERED')
            
            logger.info(
                "Check-in: %s bấm lúc %s, ghi nhận từ %s - %s",
                nickname,
                actual_time_str,
                time_str,
                note,
            )
            return {
                'success': True,
                'time': time_str,
                'actual_time': actual_time_str,
                'note': note,
                'late_minutes': late_minutes,
                'early_minutes': early_minutes,
                'ca': selected_ca,
                'date_str': today
            }
        except Exception as e:
            logger.error(f"Lỗi khi check-in cho {nickname}: {e}")
            return {'success': False, 'error': str(e)}

    def checkout(self, nickname: str, shift_type: str = None, force_time: str = None) -> dict:
        """Ghi nhận check-out cho nhân viên.
        
        Tìm hàng check-in mới nhất (hôm nay, chưa có giờ ra) và cập nhật.
        
        Returns:
            dict với keys: success, time, total_hours, checkin_time
        """
        try:
            now = local_now()
            today = now.strftime("%d/%m/%Y")
            time_str = force_time if force_time else now.strftime("%H:%M:%S")
            
            # Tìm hàng check-in hôm nay chưa có giờ ra
            all_data = self.ws_checkin.get_all_values()
            target_row = None
            
            is_ca_gay = False
            for i, row in enumerate(all_data[1:], start=2):  # Skip header
                if len(row) >= 3:
                    row_date = row[0].strip()
                    row_nick = row[1].strip()
                    row_checkout = row[3].strip() if len(row) > 3 else ""
                    row_note = row[5].strip() if len(row) > 5 else ""
                    
                    if (row_date == today and 
                        normalize_name(row_nick) == normalize_name(nickname) and
                        not row_checkout):
                        current_type = "Ca Gãy" if 'ca gãy' in row_note.lower() else "Ca Chính"
                        if shift_type and current_type != shift_type:
                            continue
                        target_row = i
                        is_ca_gay = current_type == "Ca Gãy"
                        break
            
            if not target_row:
                return {'success': False, 'error': 'not_checked_in'}
            
            # Tính tổng giờ trước khi ghi để không tạo giờ checkout ở tương lai
            # nếu người vừa check-in sớm lại bấm nhầm Check Out.
            checkin_time = all_data[target_row - 1][2]  # Cột C = Giờ Vào
            total_hours = 0.0
            calculated = False
            try:
                checkin_dt = datetime.strptime(checkin_time.strip(), "%H:%M:%S")
                checkout_dt = datetime.strptime(time_str, "%H:%M:%S")
                diff = (checkout_dt - checkin_dt).total_seconds() / 3600
                if diff < 0:
                    return {
                        'success': False,
                        'error': 'checkout_before_start',
                        'start_time': checkin_time.strip(),
                    }
                total_hours = round(diff, 1)
                calculated = True
            except Exception as calc_err:
                logger.warning(f"Không thể tính tổng giờ: {calc_err}")

            self.ws_checkin.update_cell(target_row, 4, time_str)  # Cột D = Giờ Ra
            if calculated:
                self.ws_checkin.update_cell(target_row, 5, total_hours)  # Cột E = Tổng Giờ
            
            logger.info(f"Check-out: {nickname} lúc {time_str} - Tổng: {total_hours}h")
            
            if is_ca_gay:
                try:
                    self.add_overtime(nickname, 2.0)
                    logger.info(f"Tự động thêm 2h làm thêm cho {nickname} (Ca Gãy)")
                except Exception as e:
                    logger.error(f"Lỗi thêm giờ làm thêm cho ca gãy: {e}")
                    
            return {
                'success': True,
                'time': time_str,
                'total_hours': str(total_hours).replace('.', ','),
                'checkin_time': checkin_time.strip(),
                'is_ca_gay': is_ca_gay
            }
        except Exception as e:
            logger.error(f"Lỗi khi check-out cho {nickname}: {e}")
            return {'success': False, 'error': str(e)}

    def mark_reported_late(self, nickname: str, date_str: str) -> bool:
        """Admin đánh dấu nhân viên đã báo trước khi đi trễ.
        
        Cập nhật Ghi Chú từ 'Đi muộn Xp' thành 'Đi muộn Xp (đã báo trước)'
        """
        try:
            all_data = self.ws_checkin.get_all_values()
            for i, row in enumerate(all_data[1:], start=2):
                if len(row) >= 6:
                    row_date = row[0].strip()
                    row_nick = row[1].strip()
                    row_note = row[5].strip()
                    
                    if (row_date == date_str and 
                        normalize_name(row_nick) == normalize_name(nickname) and
                        'muộn' in row_note.lower() and 
                        'báo trước' not in row_note.lower()):
                        new_note = f"{row_note} (đã báo trước)"
                        self.ws_checkin.update_cell(i, 6, new_note)
                        logger.info(f"Đã đánh dấu báo trước: {nickname} ngày {date_str}")
                        return True
            
            logger.warning(f"Không tìm thấy record trễ của {nickname} ngày {date_str}")
            return False
        except Exception as e:
            logger.error(f"Lỗi khi đánh dấu báo trước cho {nickname}: {e}")
            return False

    def mark_unreported_late(self, nickname: str, date_str: str) -> bool:
        """Admin đánh dấu nhân viên không báo trước khi đi trễ."""
        try:
            all_data = self.ws_checkin.get_all_values()
            for i, row in enumerate(all_data[1:], start=2):
                if len(row) >= 6:
                    row_date = row[0].strip()
                    row_nick = row[1].strip()
                    row_note = row[5].strip()
                    
                    if (row_date == date_str and 
                        normalize_name(row_nick) == normalize_name(nickname) and
                        'muộn' in row_note.lower() and 
                        'báo trước' not in row_note.lower()):
                        new_note = f"{row_note} (không báo trước)"
                        self.ws_checkin.update_cell(i, 6, new_note)
                        logger.info(f"Đã đánh dấu KHÔNG báo trước: {nickname} ngày {date_str}")
                        return True
            return False
        except Exception as e:
            logger.error(f"Lỗi khi đánh dấu không báo trước cho {nickname}: {e}")
            return False

    # ==================== QUẢN LÝ NHÂN VIÊN ====================

    def get_checkin_history_today(self) -> list:
        """Lấy toàn bộ lịch sử check-in hôm nay."""
        try:
            today = local_now().strftime("%d/%m/%Y")
            all_data = self.ws_checkin.get_all_values()
            records = []
            for row in all_data[1:]:
                if len(row) >= 3 and row[0].strip() == today:
                    records.append({
                        'date':          row[0].strip(),
                        'nickname':      row[1].strip(),
                        'checkin_time':  row[2].strip(),
                        'checkout_time': row[3].strip() if len(row) > 3 else '',
                        'total_hours':   row[4].strip() if len(row) > 4 else '',
                        'note':          row[5].strip() if len(row) > 5 else ''
                    })
            return records
        except Exception as e:
            logger.error(f"Lỗi lấy lịch sử check-in hôm nay: {e}")
            return []

    def get_late_statistics(self, month_year: str = None) -> list:
        """Lấy danh sách đi muộn trong tháng (format 'MM/YYYY')."""
        try:
            if not month_year:
                month_year = local_now().strftime("%m/%Y")
            all_data = self.ws_checkin.get_all_values()
            records = []
            for row in all_data[1:]:
                if len(row) < 6:
                    continue
                row_date = row[0].strip()
                parts = row_date.split('/')
                if len(parts) == 3:
                    row_my = f"{parts[1]}/{parts[2]}"
                    if row_my == month_year:
                        note = row[5].strip()
                        if 'muộn' in note.lower():
                            records.append({
                                'date':         row_date,
                                'nickname':     row[1].strip(),
                                'checkin_time': row[2].strip(),
                                'note':         note,
                                'pre_reported': '(đã báo trước)' in note.lower()
                            })
            return records
        except Exception as e:
            logger.error(f"Lỗi lấy thống kê đi muộn: {e}")
            return []

    def add_employee(self, nickname: str) -> dict:
        """Thêm nhân viên mới vào sheet SoDuThuong."""
        try:
            nickname = nickname.strip()
            if not nickname:
                return {'success': False, 'error': 'empty_name'}

            col_nicks = self.ws_balance.col_values(self.col_nickname_index)
            target = normalize_name(nickname)
            for v in col_nicks[1:]:
                if normalize_name(str(v)) == target:
                    return {'success': False, 'error': 'already_exists'}

            # Lấy số cột thực tế từ header
            try:
                headers = self.ws_balance.row_values(1)
                num_cols = len(headers)
            except Exception:
                num_cols = max(len(self.balance_headers), self.col_balance_index)
            
            # Tạo row với đủ số cột
            row = [''] * num_cols
            row[self.col_nickname_index - 1] = nickname
            row[self.col_dathuong_index - 1] = 0
            row[self.col_dadung_index - 1] = 0
            if self.col_balance_index - 1 < num_cols:
                row[self.col_balance_index - 1] = f"=INDIRECT(\"B\"&ROW())-INDIRECT(\"C\"&ROW())"
            
            self.ws_balance.insert_row(row, index=2, value_input_option='USER_ENTERED')
            logger.info(f"Đã thêm nhân viên: {nickname}")
            return {'success': True}
        except Exception as e:
            logger.error(f"Lỗi thêm nhân viên {nickname}: {e}")
            return {'success': False, 'error': str(e)}

    def rename_employee(self, old_nickname: str, new_nickname: str) -> dict:
        """Đổi nickname nhất quán trên các sheet nghiệp vụ và Mapping."""
        with self._write_lock:
            old_key = normalize_name(old_nickname)
            new_key = normalize_name(new_nickname)
            if not old_key or not new_key:
                return {'success': False, 'error': 'empty_name'}
            try:
                current = self.ws_balance.col_values(self.col_nickname_index)
                if any(normalize_name(v) == new_key for v in current[1:]):
                    return {'success': False, 'error': 'already_exists'}
                balance_row = next(
                    (i for i, value in enumerate(current[1:], start=2) if normalize_name(value) == old_key),
                    None,
                )
                if not balance_row:
                    return {'success': False, 'error': 'not_found'}

                targets = [
                    (self.ws_balance, self.col_nickname_index),
                    (self.ws_history, 3),
                    (self.ws_overtime, 2),
                    (self.ws_checkin, 2),
                ]
                for ws, col in targets:
                    values = ws.col_values(col)
                    updates = [
                        {'range': f'{self._column_letter(col)}{row_idx}', 'values': [[new_nickname]]}
                        for row_idx, value in enumerate(values[1:], start=2)
                        if normalize_name(value) == old_key
                    ]
                    if updates:
                        ws.batch_update(updates, value_input_option='USER_ENTERED')

                try:
                    ws_mapping = self.sh_salary.worksheet("Mapping")
                    rows = ws_mapping.get_all_values()
                    for i, row in enumerate(rows[1:], start=2):
                        if len(row) > 1 and normalize_name(row[1]) == old_key:
                            ws_mapping.update_cell(i, 2, new_nickname)
                except Exception:
                    logger.warning("Không cập nhật được nickname trong Mapping", exc_info=True)
                return {'success': True}
            except Exception as e:
                logger.error("Lỗi đổi tên %s -> %s: %s", old_nickname, new_nickname, e)
                return {'success': False, 'error': str(e)}

    def remove_employee(self, nickname: str) -> bool:
        """Xóa nhân viên khỏi sheet SoDuThuong."""
        try:
            col_nicks = self.ws_balance.col_values(self.col_nickname_index)
            target = normalize_name(nickname)
            for i, v in enumerate(col_nicks[1:], start=2):
                if normalize_name(str(v)) == target:
                    self.ws_balance.delete_rows(i)
                    logger.info(f"Đã xóa nhân viên: {nickname}")
                    return True
            logger.warning(f"Không tìm thấy nhân viên {nickname} để xóa")
            return False
        except Exception as e:
            logger.error(f"Lỗi xóa nhân viên {nickname}: {e}")
            return False

    def get_reward_history(self, nickname: str = None, limit: int = 20) -> list:
        """Lấy lịch sử báo cáo từ LichSuThuong, lọc theo nickname nếu có."""
        try:
            all_data = self.ws_history.get_all_values()
            records = []
            for row in all_data[1:]:
                if len(row) < 3:
                    continue
                row_nick = row[2].strip() if len(row) > 2 else ''
                if nickname and normalize_name(row_nick) != normalize_name(nickname):
                    continue
                records.append({
                    'date':     row[0].strip(),
                    'ca':       row[1].strip() if len(row) > 1 else '',
                    'nickname': row_nick,
                    'time':     row[3].strip() if len(row) > 3 else '',
                    'status':   row[4].strip() if len(row) > 4 else '',
                    'revenue':  row[5].strip() if len(row) > 5 else ''
                })
                if len(records) >= limit:
                    break
            return records
        except Exception as e:
            logger.error(f"Lỗi lấy lịch sử thưởng: {e}")
            return []

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

    @staticmethod
    def _current_salary_month(now: datetime = None) -> tuple[int, int]:
        now = now or local_now()
        if now.day < 17:
            return now.month, now.year
        if now.month == 12:
            return 1, now.year + 1
        return now.month + 1, now.year

    @staticmethod
    def _salary_period(month: int, year: int) -> tuple[date, date]:
        start = date(year - 1, 12, 17) if month == 1 else date(year, month - 1, 17)
        return start, date(year, month, 16)

    @staticmethod
    def _number(raw, default=0.0) -> float:
        try:
            return float(str(raw).strip().replace(',', '.'))
        except (TypeError, ValueError):
            return float(default)

    def _get_salary_worksheet(self, month: int, year: int, create: bool = True):
        base = f"Báo Cáo T{month}-{year}"
        for title in (base, f"{base}_New"):
            try:
                return self.sh_salary.worksheet(title)
            except Exception:
                pass
        if not create:
            return None
        ws = self.sh_salary.add_worksheet(title=base, rows=100, cols=9)
        ws.append_row([
            "Ngày Tạo", "Tháng", "Tên Nhân Viên", "Nickname Bot",
            "Tổng Giờ Làm", "Mức Lương/Giờ", "Thưởng Tiền",
            "Ứng Lương", "Nhận Thực Tế",
        ])
        try:
            ws.format("A1:I1", {"textFormat": {"bold": True}})
        except Exception:
            logger.warning("Không format được header bảng lương %s", base)
        return ws

    def ensure_salary_worksheet(self, month: int = None, year: int = None):
        """Tạo và làm mới bảng lương của kỳ hiện tại."""
        month, year = (month, year) if month and year else self._current_salary_month()
        self.get_salary_report(month, year)
        return self._get_salary_worksheet(month, year, create=False)

    def get_salary_month_options(self) -> list:
        """Nhận diện cả sheet legacy Tm-yyyy và sheet báo cáo chuẩn."""
        try:
            found = {}
            pattern = re.compile(r'^(?:Báo Cáo )?T(\d{1,2})-(\d{4})(?:_New)?$')
            for ws in self.sh_salary.worksheets():
                match = pattern.match(ws.title)
                if not match:
                    continue
                month, year = map(int, match.groups())
                if 1 <= month <= 12:
                    found[(month, year)] = True
            current = self._current_salary_month()
            found.setdefault(current, False)
            return [
                {'month': month, 'year': year, 'exists': exists}
                for (month, year), exists in sorted(
                    found.items(), key=lambda item: (item[0][1], item[0][0]), reverse=True
                )
            ]
        except Exception as e:
            logger.error("Lỗi lấy danh sách tháng lương: %s", e)
            return []

    def get_salary_report(self, month: int, year: int) -> str:
        """Tính kỳ 17→16, đồng bộ sheet báo cáo và trả về Markdown."""
        if not 1 <= int(month) <= 12:
            return "❌ Tháng lương không hợp lệ."
        with self._write_lock:
            try:
                ws = self._get_salary_worksheet(month, year, create=True)
                all_data = ws.get_all_values()
                rates = self.get_all_salary_rates()
                start_date, end_date = self._salary_period(month, year)

                hours_by_key = {}
                for row in self.ws_checkin.get_all_values()[1:]:
                    if len(row) < 5:
                        continue
                    try:
                        row_date = datetime.strptime(row[0].strip(), "%d/%m/%Y").date()
                    except ValueError:
                        continue
                    if start_date <= row_date <= end_date:
                        key = normalize_name(row[1])
                        hours_by_key[key] = hours_by_key.get(key, 0.0) + self._number(row[4])

                existing_rows = {
                    normalize_name(row[3]): index
                    for index, row in enumerate(all_data[1:], start=2)
                    if len(row) > 3 and normalize_name(row[3])
                }
                lines = [
                    f"💵 *BẢNG LƯƠNG T{month}/{year}* "
                    f"({start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')})\n"
                ]
                now_str = local_now().strftime('%d/%m/%Y %H:%M')
                for nick, rate in rates.items():
                    key = normalize_name(nick)
                    hours = round(hours_by_key.get(key, 0.0), 2)
                    row_idx = existing_rows.get(key)
                    bonus = advance = 0.0
                    real_name = ""
                    if row_idx and row_idx <= len(all_data):
                        old = all_data[row_idx - 1]
                        real_name = old[2].strip() if len(old) > 2 else ""
                        bonus = self._number(old[6]) if len(old) > 6 else 0.0
                        advance = self._number(old[7]) if len(old) > 7 else 0.0
                    total = round(hours * float(rate) + bonus - advance, 2)

                    display_name = (real_name or nick).replace('*', '').replace('_', ' ')
                    lines.extend([
                        f"👤 *{display_name}*",
                        f"  ⏳ {hours:g}h x {rate:g}k = {hours * rate:g}k",
                    ])
                    if bonus:
                        lines.append(f"  🎁 Thưởng: +{bonus:g}k")
                    if advance:
                        lines.append(f"  💸 Ứng: -{advance:g}k")
                    lines.append(f"  👉 *Thực nhận: {total:g}k*\n")

                    values = [nick, hours, rate, bonus, advance, total]
                    if row_idx:
                        ws.update([values], range_name=f'D{row_idx}:I{row_idx}', value_input_option='USER_ENTERED')
                    else:
                        ws.append_row(
                            [now_str, f"T{month}-{year}", "", *values],
                            value_input_option='USER_ENTERED',
                        )

                return "\n".join(lines) if rates else f"Không có nhân viên cho tháng {month}/{year}."
            except Exception:
                logger.exception("Lỗi tạo báo cáo lương T%s/%s", month, year)
                return "❌ Không thể tạo bảng lương. Vui lòng kiểm tra log hệ thống."

    def update_salary_modifier(self, nickname: str, is_bonus: bool, amount: int, month: int, year: int) -> bool:
        """Cộng ứng/thưởng vào đúng kỳ lương và cập nhật thực nhận."""
        if amount <= 0:
            return False
        with self._write_lock:
            try:
                self.get_salary_report(month, year)
                ws = self._get_salary_worksheet(month, year, create=False)
                rows = ws.get_all_values()
                for i, row in enumerate(rows[1:], start=2):
                    if len(row) <= 3 or normalize_name(row[3]) != normalize_name(nickname):
                        continue
                    target_col = 7 if is_bonus else 8
                    current = self._number(row[target_col - 1]) if len(row) >= target_col else 0.0
                    new_value = current + amount
                    hours = self._number(row[4]) if len(row) > 4 else 0.0
                    rate = self._number(row[5], Config.DEFAULT_HOURLY_RATE_K) if len(row) > 5 else Config.DEFAULT_HOURLY_RATE_K
                    bonus = new_value if is_bonus else (self._number(row[6]) if len(row) > 6 else 0.0)
                    advance = new_value if not is_bonus else (self._number(row[7]) if len(row) > 7 else 0.0)
                    ws.batch_update([
                        {'range': f'{self._column_letter(target_col)}{i}', 'values': [[new_value]]},
                        {'range': f'I{i}', 'values': [[round(hours * rate + bonus - advance, 2)]]},
                    ], value_input_option='USER_ENTERED')
                    return True
                return False
            except Exception:
                logger.exception("Lỗi cập nhật ứng/thưởng cho %s", nickname)
                return False
