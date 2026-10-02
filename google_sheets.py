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
                self.ws_overtime = self.sh.worksheet("GioLamThem")
                self.ws_checkin = self.sh.worksheet("Checkin")
                # Kết nối Spreadsheet Nguyên Vật Liệu (tùy chọn, không block khởi động)
                self.sh_inventory = None
                if Config.INVENTORY_SPREADSHEET_ID:
                    try:
                        self.sh_inventory = self.gc.open_by_key(Config.INVENTORY_SPREADSHEET_ID)
                        logger.info("✅ Kết nối Spreadsheet NVL thành công.")
                    except Exception as inv_err:
                        logger.warning("⚠️ Không kết nối được Spreadsheet NVL: %s. Tính năng kho sẽ bị tắt.", str(inv_err)[:120])
                logger.info("✅ Kết nối Google Sheets thành công.")
                
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

    def _get_mapping_worksheet(self):
        return self.sh_salary.worksheet("Mapping")

    def _get_mapping_indices(self, headers):
        headers_norm = [normalize_name(h) for h in headers]
        nick_col = next((i for i, h in enumerate(headers_norm) if 'nickname' in h or h in {'nick', 'nicknamebot'}), 1)
        bal_col = next((i for i, h in enumerate(headers_norm) if 'sodu' in h or 'thuong' in h), 3)
        rate_col = next((i for i, h in enumerate(headers_norm) if ('luong' in h and 'ten' not in h) or 'rate' in h), 2)
        return nick_col, rate_col, bal_col

    def get_balance(self, nickname: str) -> int:
        """Lấy số dư từ sheet Mapping"""
        try:
            ws_map = self._get_mapping_worksheet()
            records = ws_map.get_all_values()
            if not records: return 0
            nick_col, _, bal_col = self._get_mapping_indices(records[0])
            
            target = normalize_name(nickname)
            for row in records[1:]:
                if len(row) > nick_col and normalize_name(row[nick_col]) == target:
                    if len(row) > bal_col:
                        try:
                            return int(row[bal_col].strip().replace(',', ''))
                        except:
                            return 0
            return 0
        except Exception as e:
            logger.error(f"Error get_balance: {e}")
            return 0

    def get_all_salary_rates(self) -> dict:
        """Lấy mức lương/giờ từ Mapping (và fallback sang ws_balance nếu có)."""
        rates = {}
        default_rate = Config.DEFAULT_HOURLY_RATE_K
        try:
            ws_map = self._get_mapping_worksheet()
            records = ws_map.get_all_values()
            if records:
                nick_col, rate_col, _ = self._get_mapping_indices(records[0])
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
                    rates[nick] = rate
        except Exception as e:
            logger.error(f"Error get_all_salary_rates (Mapping): {e}")

        ws_balance = getattr(self, 'ws_balance', None)
        if ws_balance is not None:
            try:
                col_idx = getattr(self, 'col_nickname_index', 1) - 1
                existing_norm = {normalize_name(k) for k in rates}
                for row in ws_balance.get_all_values()[1:]:
                    if len(row) <= col_idx or not row[col_idx].strip():
                        continue
                    nick = row[col_idx].strip()
                    if normalize_name(nick) in existing_norm:
                        continue
                    rate = default_rate
                    if len(row) > 4 and row[4].strip():
                        try:
                            rate = float(row[4].strip().replace(',', '.'))
                        except ValueError:
                            pass
                    rates[nick] = rate
                    existing_norm.add(normalize_name(nick))
            except Exception as e:
                logger.error(f"Error get_all_salary_rates (ws_balance): {e}")

        return rates

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

                ws_balance = getattr(self, 'ws_balance', None)
                if ws_balance is not None:
                    col_idx = getattr(self, 'col_nickname_index', 1)
                    balance_rows = ws_balance.get_all_values()
                    for i, row in enumerate(balance_rows[1:], start=2):
                        if len(row) >= col_idx and normalize_name(row[col_idx - 1]) == target:
                            if len(balance_rows[0]) < 5 or not balance_rows[0][4].strip():
                                ws_balance.update_cell(1, 5, "Mức Lương/Giờ")
                            ws_balance.update_cell(i, 5, rate)
                            break
                return True
            except Exception as e:
                logger.error(f"Lỗi khi cập nhật mức lương cho {nickname}: {e}")
                return False


    def get_all_balances(self) -> dict:
        """Lấy tất cả số dư từ Mapping"""
        balances = {}
        try:
            ws_map = self._get_mapping_worksheet()
            records = ws_map.get_all_values()
            if not records: return balances
            nick_col, rate_col, bal_col = self._get_mapping_indices(records[0])
            
            for row in records[1:]:
                if len(row) > nick_col and row[nick_col].strip():
                    nick = normalize_name(row[nick_col])
                    val = 0
                    if len(row) > bal_col:
                        try:
                            val = int(row[bal_col].strip().replace(',', ''))
                        except:
                            pass
                    balances[nick] = val
            return balances
        except Exception:
            return balances

    def get_all_nicknames(self) -> list:
        """Lấy danh sách nickname hợp lệ từ Sheet Mapping"""
        try:
            ws = self._get_mapping_worksheet()
            records = ws.get_all_values()
            if not records: return []
            nick_col, _, _ = self._get_mapping_indices(records[0])
            
            nicks = []
            for row in records[1:]:
                if len(row) > nick_col and row[nick_col].strip():
                    nicks.append(normalize_name(row[nick_col]))
            return nicks
        except Exception:
            return []

    def get_employees_detail(self) -> list:
        """Lấy danh sách nhân viên đầy đủ (tên thật, nickname, mức lương/giờ, số dư ly thưởng)."""
        default_rate = Config.DEFAULT_HOURLY_RATE_K
        employees = []
        try:
            ws = self._get_mapping_worksheet()
            records = ws.get_all_values()
            if not records:
                return []
            nick_col, rate_col, bal_col = self._get_mapping_indices(records[0])
            for row in records[1:]:
                if len(row) <= nick_col or not row[nick_col].strip():
                    continue
                display_nick = row[nick_col].strip()
                full_name = row[0].strip() if len(row) > 0 and nick_col != 0 else display_nick
                rate = default_rate
                if len(row) > rate_col and row[rate_col].strip():
                    try:
                        rate = float(row[rate_col].strip().replace(',', '.'))
                    except ValueError:
                        pass
                bal = 0
                if len(row) > bal_col and row[bal_col].strip():
                    try:
                        bal = int(float(row[bal_col].strip().replace(',', '')))
                    except ValueError:
                        pass
                employees.append({
                    'nickname': display_nick,
                    'key': normalize_name(display_nick),
                    'full_name': full_name or display_nick,
                    'rate': rate,
                    'balance': bal,
                })
            return employees
        except Exception as e:
            logger.error(f"Error get_employees_detail: {e}")
            return []

    def update_balance(self, nickname: str, amount_change: int) -> bool:
        with self._write_lock:
            return self._update_balance_unlocked(nickname, amount_change)

    def _update_balance_unlocked(self, nickname: str, amount_change: int) -> bool:
        """Cập nhật số dư trong Mapping."""
        try:
            ws_map = self._get_mapping_worksheet()
            records = ws_map.get_all_values()
            if not records: return False
            nick_col, rate_col, bal_col = self._get_mapping_indices(records[0])
            
            target = normalize_name(nickname)
            for i, row in enumerate(records[1:], start=2):
                if len(row) > nick_col and normalize_name(row[nick_col]) == target:
                    current_val = 0
                    if len(row) > bal_col:
                        try:
                            current_val = int(row[bal_col].strip().replace(',', ''))
                        except:
                            pass
                    new_val = current_val + amount_change
                    ws_map.update_cell(i, bal_col + 1, new_val)
                    return True
            
            # Nếu chưa có, thêm mới
            new_row = [''] * (max(nick_col, bal_col) + 1)
            new_row[nick_col] = nickname
            new_row[bal_col] = amount_change
            ws_map.append_row(new_row, value_input_option='USER_ENTERED')
            return True
        except Exception as e:
            logger.error(f"Error update_balance: {e}")
            return False

    def batch_update_balances(self, nicknames: list, amount_change: int) -> bool:
        with self._write_lock:
            return self._batch_update_balances_unlocked(nicknames, amount_change)

    def _batch_update_balances_unlocked(self, nicknames: list, amount_change: int) -> bool:
        if not nicknames or amount_change == 0:
            return True
        try:
            ws_map = self._get_mapping_worksheet()
            records = ws_map.get_all_values()
            if not records: return False
            nick_col, rate_col, bal_col = self._get_mapping_indices(records[0])
            
            updates = []
            targets = {normalize_name(n): n for n in nicknames}
            found_targets = set()
            
            for i, row in enumerate(records[1:], start=2):
                if len(row) > nick_col:
                    nick_norm = normalize_name(row[nick_col])
                    if nick_norm in targets:
                        found_targets.add(nick_norm)
                        current_val = 0
                        if len(row) > bal_col:
                            try:
                                current_val = int(row[bal_col].strip().replace(',', ''))
                            except:
                                pass
                        updates.append({
                            'range': f"{self._column_letter(bal_col + 1)}{i}",
                            'values': [[current_val + amount_change]]
                        })
            
            if updates:
                ws_map.batch_update(updates, value_input_option='USER_ENTERED')
            
            # Insert missing ones
            for nick_norm, original_nick in targets.items():
                if nick_norm not in found_targets:
                    self._update_balance_unlocked(original_nick, amount_change)
            
            return True
        except Exception as e:
            logger.error(f"Error batch_update_balances: {e}")
            return False

    def consume_reward(self, nickname: str) -> dict:
        """Giảm 1 ly."""
        with self._write_lock:
            try:
                current_balance = self.get_balance(nickname)
                if current_balance <= 0:
                    return {'success': False, 'error': 'insufficient_balance'}
                success = self._update_balance_unlocked(nickname, -1)
                if success:
                    return {'success': True, 'balance': current_balance - 1}
                return {'success': False, 'error': 'update_failed'}
            except Exception as e:
                logger.error(f"Lỗi consume_reward {nickname}: {e}")
                return {'success': False, 'error': str(e)}

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
        """Thêm nhân viên mới vào sheet Mapping."""
        with self._write_lock:
            try:
                target = normalize_name(nickname)
                if not target:
                    return {'success': False, 'error': 'empty_name'}
                ws = self._get_mapping_worksheet()
                records = ws.get_all_values()
                if records:
                    nick_col, _, _ = self._get_mapping_indices(records[0])
                    for row in records[1:]:
                        if len(row) > nick_col and normalize_name(row[nick_col]) == target:
                            return {'success': False, 'error': 'already_exists'}
                ws.append_row([nickname, nickname, Config.DEFAULT_HOURLY_RATE_K, 0], value_input_option='USER_ENTERED')
                return {'success': True}
            except Exception as e:
                return {'success': False, 'error': str(e)}

    def rename_employee(self, old_nickname: str, new_nickname: str) -> dict:
        """Đổi nickname nhất quán trên các sheet nghiệp vụ và Mapping."""
        with self._write_lock:
            old_key = normalize_name(old_nickname)
            new_key = normalize_name(new_nickname)
            if not old_key or not new_key:
                return {'success': False, 'error': 'empty_name'}
            try:
                found = False
                ws_balance = getattr(self, 'ws_balance', None)
                if ws_balance is not None:
                    col_idx = getattr(self, 'col_nickname_index', 1)
                    current = ws_balance.col_values(col_idx)
                    if any(normalize_name(v) == new_key for v in current[1:]):
                        return {'success': False, 'error': 'already_exists'}
                    balance_row = next(
                        (i for i, value in enumerate(current[1:], start=2) if normalize_name(value) == old_key),
                        None,
                    )
                    if balance_row:
                        found = True

                ws_mapping = None
                try:
                    ws_mapping = self._get_mapping_worksheet()
                    rows = ws_mapping.get_all_values()
                    if rows:
                        nick_col, _, _ = self._get_mapping_indices(rows[0])
                        if any(len(r) > nick_col and normalize_name(r[nick_col]) == new_key for r in rows[1:]):
                            return {'success': False, 'error': 'already_exists'}
                        for i, row in enumerate(rows[1:], start=2):
                            if len(row) > nick_col and normalize_name(row[nick_col]) == old_key:
                                found = True
                                ws_mapping.update_cell(i, nick_col + 1, new_nickname)
                except Exception:
                    logger.warning("Không kiểm tra/cập nhật được nickname trong Mapping", exc_info=True)

                if not found:
                    return {'success': False, 'error': 'not_found'}

                targets = []
                if ws_balance is not None:
                    targets.append((ws_balance, getattr(self, 'col_nickname_index', 1)))
                for ws_attr, col in (('ws_history', 3), ('ws_overtime', 2), ('ws_checkin', 2)):
                    ws_obj = getattr(self, ws_attr, None)
                    if ws_obj is not None:
                        targets.append((ws_obj, col))

                for ws, col in targets:
                    values = ws.col_values(col)
                    updates = [
                        {'range': f'{self._column_letter(col)}{row_idx}', 'values': [[new_nickname]]}
                        for row_idx, value in enumerate(values[1:], start=2)
                        if normalize_name(value) == old_key
                    ]
                    if updates:
                        ws.batch_update(updates, value_input_option='USER_ENTERED')

                return {'success': True}
            except Exception as e:
                logger.error("Lỗi đổi tên %s -> %s: %s", old_nickname, new_nickname, e)
                return {'success': False, 'error': str(e)}

    def remove_employee(self, nickname: str) -> bool:
        """Xóa nhân viên khỏi sheet Mapping."""
        with self._write_lock:
            try:
                ws = self._get_mapping_worksheet()
                records = ws.get_all_values()
                if not records: return False
                nick_col, _, _ = self._get_mapping_indices(records[0])
                target = normalize_name(nickname)
                for i, row in enumerate(records[1:], start=2):
                    if len(row) > nick_col and normalize_name(row[nick_col]) == target:
                        ws.delete_rows(i)
                        return True
                return False
            except Exception:
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

    def get_salary_data(self, month: int, year: int) -> dict:
        """Trả về dữ liệu bảng lương dạng dict có cấu trúc cho Mini App đồng thời đồng bộ sheet."""
        if not 1 <= int(month) <= 12:
            return {'success': False, 'error': 'Tháng lương không hợp lệ.'}
        with self._write_lock:
            try:
                report_md = self.get_salary_report(month, year)
                ws = self._get_salary_worksheet(month, year, create=False)
                start_date, end_date = self._salary_period(month, year)
                items = []
                if ws:
                    for row in ws.get_all_values()[1:]:
                        if len(row) <= 3 or not row[3].strip():
                            continue
                        real_name = row[2].strip() if len(row) > 2 else ''
                        nick = row[3].strip()
                        hours = round(self._number(row[4]) if len(row) > 4 else 0.0, 2)
                        rate = round(self._number(row[5], Config.DEFAULT_HOURLY_RATE_K) if len(row) > 5 else Config.DEFAULT_HOURLY_RATE_K, 2)
                        bonus = round(self._number(row[6]) if len(row) > 6 else 0.0, 2)
                        advance = round(self._number(row[7]) if len(row) > 7 else 0.0, 2)
                        total = round(self._number(row[8], hours * rate + bonus - advance) if len(row) > 8 else (hours * rate + bonus - advance), 2)
                        items.append({
                            'nickname': nick,
                            'display_name': real_name or nick,
                            'hours': hours,
                            'rate': rate,
                            'base_pay': round(hours * rate, 2),
                            'bonus': bonus,
                            'advance': advance,
                            'total': total,
                        })
                return {
                    'success': True,
                    'month': int(month),
                    'year': int(year),
                    'period_start': start_date.strftime('%d/%m/%Y'),
                    'period_end': end_date.strftime('%d/%m/%Y'),
                    'items': items,
                    'total_hours': round(sum(x['hours'] for x in items), 2),
                    'total_payout': round(sum(x['total'] for x in items), 2),
                    'markdown': report_md,
                }
            except Exception as e:
                logger.exception("Lỗi lấy dữ liệu lương T%s/%s", month, year)
                return {'success': False, 'error': str(e)}

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

    # ==================== QUẢN LÝ NGUYÊN VẬT LIỆU ====================

    @staticmethod
    def _clean_item_name(raw_name: str) -> str:
        """Bỏ số thứ tự đầu tên (VD: '1.Sữa đặc ' -> 'Sữa đặc', '29.1. Mứt' -> 'Mứt')."""
        if not raw_name:
            return ""
        return re.sub(r'^\d+([.,]\d+)*\.\s*', '', str(raw_name).strip()).strip()

    @staticmethod
    def _parse_float(val, default: float = 0.0) -> float:
        if val is None:
            return default
        s = str(val).strip()
        if not s:
            return default
        try:
            return float(s.replace(',', '.'))
        except ValueError:
            return default

    def _get_current_monthly_ws(self, create_if_new_month: bool = True):
        """Lấy worksheet của tháng hiện tại (VD: 'Tháng 92026').
        Nếu bước sang tháng mới mà chưa có sheet, tự động nhân bản từ sheet tháng trước
        và kết chuyển Số lượng cuối tháng -> Số lượng đầu tháng.
        """
        if not self.sh_inventory:
            raise RuntimeError("Chưa cấu hình INVENTORY_SPREADSHEET_ID")

        now = local_now()
        month, year = now.month, now.year
        month_tag = f"{month}{year}"        # VD: '102026'
        alt_tag = f"tháng {month}/{year}"   # VD: 'tháng 10/2026'
        short_tag = f"t{month}/{year}"      # VD: 't10/2026'
        short_tag2 = f"t{month}{year}"      # VD: 't102026'
        tags = [short_tag, alt_tag, month_tag, short_tag2, f"tháng {month} {year}", f"t{month} {year}"]

        worksheets = [
            ws for ws in self.sh_inventory.worksheets()
            if ws.title not in ("DanhMuc", "LichSu")
        ]
        if not worksheets:
            raise RuntimeError("File kho chưa có sheet tháng nào")

        # 1. Tìm sheet khớp chính xác tháng + năm hiện tại (VD: 'T10/2026', 'Tháng 102026')
        for ws in reversed(worksheets):
            t_low = ws.title.lower()
            if any(tag in t_low for tag in tags):
                return ws

        # 2. Nếu chưa có sheet của tháng+năm hiện tại -> Tự động nhân bản từ sheet tháng gần nhất
        prev_ws = worksheets[-1]
        if not create_if_new_month:
            return prev_ws

        new_title = f"Tháng {month}{year}"
        try:
            new_ws = self.sh_inventory.duplicate_sheet(
                prev_ws.id,
                insert_sheet_index=len(self.sh_inventory.worksheets()),
                new_sheet_name=new_title,
            )
            rows = new_ws.get_all_values()
            rollover_updates = []

            for r_idx, r in enumerate(rows, start=1):
                # Kết chuyển phần NVL (Cột B: tên, C: đầu tháng, D: nhập thêm, E: cuối tháng)
                name_nvl = r[1].strip() if len(r) > 1 else ''
                if name_nvl and not name_nvl.lower().startswith('tên') and not name_nvl.lower().startswith('thành tiền'):
                    end_stock = r[4].strip() if len(r) > 4 and r[4].strip() else 0
                    end_val = self._parse_float(end_stock, 0.0)
                    rollover_updates.append({
                        'range': f'C{r_idx}:E{r_idx}',
                        'values': [[end_val, "", end_val]],
                    })

                # Kết chuyển phần CCDC (Cột K: tên, L: đầu tháng, M: nhập thêm, N: cuối tháng)
                if len(r) > 10:
                    name_ccdc = r[10].strip()
                    if name_ccdc and not name_ccdc.lower().startswith('tên') and not name_ccdc.lower().startswith('công cụ'):
                        end_stock_c = r[13].strip() if len(r) > 13 and r[13].strip() else 0
                        end_val_c = self._parse_float(end_stock_c, 0.0)
                        rollover_updates.append({
                            'range': f'L{r_idx}:N{r_idx}',
                            'values': [[end_val_c, "", end_val_c]],
                        })

            if rollover_updates:
                new_ws.batch_update(rollover_updates, value_input_option='USER_ENTERED')

            logger.info("✅ Đã tự động nhân bản & kết chuyển tồn kho sang sheet mới: %s", new_title)
            return new_ws
        except Exception as e:
            logger.warning("Không thể tự tạo sheet tháng mới (%s), dùng sheet gần nhất '%s': %s", new_title, prev_ws.title, e)
            return prev_ws

    def _get_inventory_ws(self, sheet_name: str, create: bool = True):
        """Lấy worksheet phụ trợ (LichSu / DanhMuc)."""
        if not self.sh_inventory:
            raise RuntimeError("Chưa cấu hình INVENTORY_SPREADSHEET_ID")
        try:
            return self.sh_inventory.worksheet(sheet_name)
        except Exception:
            if not create:
                return None
            if sheet_name == "DanhMuc":
                ws = self.sh_inventory.add_worksheet(title="DanhMuc", rows=300, cols=6)
                ws.update([["Nhóm", "Tên NVL", "Đơn Vị", "Tồn Kho", "Mức Tối Thiểu", "Giá Nhập"]], range_name='A1:F1')
                return ws
            elif sheet_name == "LichSu":
                ws = self.sh_inventory.add_worksheet(title="LichSu", rows=1000, cols=6)
                ws.update([["Ngày", "Loại", "Tên NVL", "Số Lượng", "Người Thực Hiện", "Ghi Chú"]], range_name='A1:F1')
                return ws
            raise

    def _get_metadata_map(self) -> dict:
        """Lấy cấu hình Đơn vị & Mức tối thiểu từ tab DanhMuc (nếu có)."""
        meta = {}
        try:
            ws_dm = self._get_inventory_ws("DanhMuc", create=False)
            if ws_dm:
                for r in ws_dm.get_all_values()[1:]:
                    if len(r) > 1 and r[1].strip():
                        key = normalize_name(r[1].strip())
                        meta[key] = {
                            'unit': r[2].strip() if len(r) > 2 else '',
                            'min_stock': self._parse_float(r[4] if len(r) > 4 else 0),
                        }
        except Exception:
            pass
        return meta

    def get_all_materials(self, group: str = None) -> list:
        """Đọc trực tiếp danh sách NVL & CCDC từ sheet tháng hiện tại."""
        try:
            ws = self._get_current_monthly_ws(create_if_new_month=True)
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return []

            meta_map = self._get_metadata_map()
            materials = []
            current_group = "Khác"

            # 1. Quét phần Nguyên Vật Liệu (cột A-H)
            for r in rows:
                g = r[0].strip() if len(r) > 0 else ''
                if g and not g.lower().startswith('tên'):
                    current_group = re.sub(r'^\d+\.\s*', '', g).strip()
                raw_name = r[1].strip() if len(r) > 1 else ''
                if raw_name and not raw_name.lower().startswith('tên') and not raw_name.lower().startswith('thành tiền'):
                    cname = self._clean_item_name(raw_name)
                    if not cname:
                        continue
                    if group and current_group.lower() != group.lower():
                        continue
                    start_s = self._parse_float(r[2] if len(r) > 2 else 0)
                    import_s = self._parse_float(r[3] if len(r) > 3 else 0)
                    end_str = r[4].strip() if len(r) > 4 else ''
                    stock = self._parse_float(end_str) if end_str else round(start_s + import_s, 3)
                    price = self._parse_float(r[6] if len(r) > 6 else 0)
                    m_info = meta_map.get(normalize_name(cname), {})
                    materials.append({
                        'group': current_group,
                        'name': cname,
                        'unit': m_info.get('unit', ''),
                        'stock': stock,
                        'min_stock': m_info.get('min_stock', 0.0),
                        'price': price,
                    })

            # 2. Quét phần Công Cụ Dụng Cụ (cột K-Q)
            ccdc_group = "Công cụ dụng cụ"
            if not group or ccdc_group.lower() == group.lower():
                for r in rows:
                    if len(r) > 10:
                        raw_name = r[10].strip()
                        if raw_name and not raw_name.lower().startswith('tên') and not raw_name.lower().startswith('công cụ'):
                            cname = self._clean_item_name(raw_name)
                            if not cname:
                                continue
                            start_s = self._parse_float(r[11] if len(r) > 11 else 0)
                            import_s = self._parse_float(r[12] if len(r) > 12 else 0)
                            end_str = r[13].strip() if len(r) > 13 else ''
                            stock = self._parse_float(end_str) if end_str else round(start_s + import_s, 3)
                            price = self._parse_float(r[15] if len(r) > 15 else 0)
                            m_info = meta_map.get(normalize_name(cname), {})
                            materials.append({
                                'group': ccdc_group,
                                'name': cname,
                                'unit': m_info.get('unit', ''),
                                'stock': stock,
                                'min_stock': m_info.get('min_stock', 0.0),
                                'price': price,
                            })

            return materials
        except Exception as e:
            logger.error("Lỗi lấy danh mục NVL từ sheet tháng: %s", e)
            return []

    def get_material_groups(self) -> list:
        """Lấy danh sách các nhóm NVL duy nhất."""
        materials = self.get_all_materials()
        groups = []
        for m in materials:
            grp = m.get('group', 'Khác')
            if grp and grp not in groups:
                groups.append(grp)
        return groups

    def _locate_item_on_monthly_ws(self, rows: list, target_norm: str):
        """Tìm vị trí dòng và nhánh (NVL hay CCDC) của mặt hàng trên sheet tháng.
        Trả về dict: {'row_idx': int, 'is_ccdc': bool, 'clean_name': str, 'start_qty': float, 'import_qty': float, 'end_qty': float, 'price': float}
        """
        for r_idx, r in enumerate(rows, start=1):
            # Kiểm tra cột B (NVL)
            if len(r) > 1 and r[1].strip():
                cname = self._clean_item_name(r[1])
                if cname and normalize_name(cname) == target_norm:
                    sq = self._parse_float(r[2] if len(r) > 2 else 0)
                    iq = self._parse_float(r[3] if len(r) > 3 else 0)
                    eq_str = r[4].strip() if len(r) > 4 else ''
                    eq = self._parse_float(eq_str) if eq_str else round(sq + iq, 3)
                    return {
                        'row_idx': r_idx,
                        'is_ccdc': False,
                        'clean_name': cname,
                        'start_qty': sq,
                        'import_qty': iq,
                        'end_qty': eq,
                        'price': self._parse_float(r[6] if len(r) > 6 else 0),
                    }
            # Kiểm tra cột K (CCDC)
            if len(r) > 10 and r[10].strip():
                cname = self._clean_item_name(r[10])
                if cname and normalize_name(cname) == target_norm:
                    sq = self._parse_float(r[11] if len(r) > 11 else 0)
                    iq = self._parse_float(r[12] if len(r) > 12 else 0)
                    eq_str = r[13].strip() if len(r) > 13 else ''
                    eq = self._parse_float(eq_str) if eq_str else round(sq + iq, 3)
                    return {
                        'row_idx': r_idx,
                        'is_ccdc': True,
                        'clean_name': cname,
                        'start_qty': sq,
                        'import_qty': iq,
                        'end_qty': eq,
                        'price': self._parse_float(r[15] if len(r) > 15 else 0),
                    }
        return None

    def add_material(self, name: str, unit: str, min_stock: float = 0, price: float = 0, group: str = "Khác") -> dict:
        """Thêm NVL mới trực tiếp vào sheet tháng hiện tại và lưu cấu hình."""
        with self._write_lock:
            try:
                ws = self._get_current_monthly_ws(create_if_new_month=True)
                rows = ws.get_all_values()
                target = normalize_name(name)
                if self._locate_item_on_monthly_ws(rows, target):
                    return {'success': False, 'error': 'already_exists'}

                # Tìm dòng trống tiếp theo của nhánh NVL (trước dòng tổng cuối cùng nếu có)
                insert_row_idx = len(rows)
                if insert_row_idx < 2:
                    insert_row_idx = 2
                # Nếu dòng cuối chỉ chứa tổng thành tiền (cột B trống, cột H có giá trị), chèn ngay trên dòng đó
                if rows and not (len(rows[-1]) > 1 and rows[-1][1].strip()):
                    target_r = len(rows)
                else:
                    target_r = len(rows) + 1

                if "công cụ" in group.lower() or "ccdc" in group.lower():
                    # Ghi vào nhánh CCDC (cột K -> Q)
                    ccdc_last = 2
                    for i, r in enumerate(rows, start=1):
                        if len(r) > 10 and r[10].strip():
                            ccdc_last = i + 1
                    ws.update(
                        [[name, 0, "", 0, f"=sum(L{ccdc_last}+M{ccdc_last}-N{ccdc_last})", price, f"=sum(O{ccdc_last}*P{ccdc_last})"]],
                        range_name=f'K{ccdc_last}:Q{ccdc_last}',
                        value_input_option='USER_ENTERED',
                    )
                else:
                    ws.update(
                        [[group, name, 0, "", 0, f"=sum(C{target_r}+D{target_r}-E{target_r})", price, f"=sum(G{target_r}*F{target_r})"]],
                        range_name=f'A{target_r}:H{target_r}',
                        value_input_option='USER_ENTERED',
                    )

                # Lưu unit & min_stock vào DanhMuc nếu có
                try:
                    ws_dm = self._get_inventory_ws("DanhMuc", create=True)
                    ws_dm.append_row([group, name, unit, 0, min_stock, price], value_input_option='USER_ENTERED')
                except Exception:
                    pass

                return {'success': True}
            except Exception as e:
                logger.error("Lỗi thêm NVL %s: %s", name, e)
                return {'success': False, 'error': str(e)}

    def update_material(self, name: str, **fields) -> bool:
        """Cập nhật thông tin NVL (giá trên sheet tháng + unit/min_stock trên DanhMuc)."""
        with self._write_lock:
            try:
                ws = self._get_current_monthly_ws(create_if_new_month=True)
                rows = ws.get_all_values()
                target = normalize_name(name)
                loc = self._locate_item_on_monthly_ws(rows, target)
                if not loc:
                    return False

                if 'price' in fields and fields['price'] is not None:
                    price_col = 'P' if loc['is_ccdc'] else 'G'
                    ws.update([[fields['price']]], range_name=f"{price_col}{loc['row_idx']}", value_input_option='USER_ENTERED')

                # Cập nhật unit & min_stock trên DanhMuc
                try:
                    ws_dm = self._get_inventory_ws("DanhMuc", create=True)
                    dm_rows = ws_dm.get_all_values()
                    found_dm = False
                    for i, r in enumerate(dm_rows[1:], start=2):
                        if len(r) > 1 and normalize_name(r[1]) == target:
                            updates = []
                            if 'unit' in fields:
                                updates.append({'range': f'C{i}', 'values': [[fields['unit']]]})
                            if 'min_stock' in fields:
                                updates.append({'range': f'E{i}', 'values': [[fields['min_stock']]]})
                            if 'price' in fields:
                                updates.append({'range': f'F{i}', 'values': [[fields['price']]]})
                            if updates:
                                ws_dm.batch_update(updates, value_input_option='USER_ENTERED')
                            found_dm = True
                            break
                    if not found_dm:
                        ws_dm.append_row([
                            fields.get('group', 'Khác'),
                            loc['clean_name'],
                            fields.get('unit', ''),
                            loc['end_qty'],
                            fields.get('min_stock', 0),
                            fields.get('price', loc['price']),
                        ], value_input_option='USER_ENTERED')
                except Exception:
                    pass

                return True
            except Exception as e:
                logger.error("Lỗi cập nhật NVL %s: %s", name, e)
                return False

    def remove_material(self, name: str) -> bool:
        """Xóa NVL khỏi sheet tháng hiện tại."""
        with self._write_lock:
            try:
                ws = self._get_current_monthly_ws(create_if_new_month=True)
                rows = ws.get_all_values()
                target = normalize_name(name)
                loc = self._locate_item_on_monthly_ws(rows, target)
                if not loc:
                    return False
                r_idx = loc['row_idx']
                if loc['is_ccdc']:
                    ws.batch_clear([f'K{r_idx}:Q{r_idx}'])
                else:
                    ws.batch_clear([f'B{r_idx}:H{r_idx}'])
                return True
            except Exception as e:
                logger.error("Lỗi xóa NVL %s: %s", name, e)
                return False

    def import_stock(self, name: str, qty: float, user: str, note: str = "") -> bool:
        """Nhập kho trực tiếp vào sheet tháng hiện tại (uỷ quyền qua batch_import_stock)."""
        res = self.batch_import_stock([{'name': name, 'qty': qty}], user, note)
        return bool(res.get('success') and res.get('imported'))

    def batch_import_stock(self, items: list, user: str, note: str = "") -> dict:
        """Nhập kho nhiều món cùng lúc trực tiếp vào sheet tháng hiện tại:
        - Cộng vào cột 'Số lượng nhập thêm hàng' (cột D cho NVL / cột M cho CCDC)
        - Cộng vào cột 'Số lượng cuối tháng' (cột E cho NVL / cột N cho CCDC)
        - Ghi lịch sử vào tab LichSu
        """
        with self._write_lock:
            try:
                ws = self._get_current_monthly_ws(create_if_new_month=True)
                rows = ws.get_all_values()
                meta_map = self._get_metadata_map()

                updates = []
                imported = []
                errors = []
                today = local_now().strftime("%d/%m/%Y %H:%M")
                log_rows = []

                for item in items:
                    name = item['name']
                    qty = float(item['qty'])
                    target = normalize_name(name)
                    loc = self._locate_item_on_monthly_ws(rows, target)
                    if not loc:
                        errors.append(f"Không tìm thấy '{name}'")
                        continue

                    r_idx = loc['row_idx']
                    new_import = round(loc['import_qty'] + qty, 3)
                    new_end = round(loc['end_qty'] + qty, 3)
                    clean_name = loc['clean_name']
                    unit = meta_map.get(target, {}).get('unit', '')

                    if loc['is_ccdc']:
                        updates.append({'range': f'M{r_idx}:N{r_idx}', 'values': [[new_import, new_end]]})
                        while len(rows[r_idx - 1]) <= 13:
                            rows[r_idx - 1].append('')
                        rows[r_idx - 1][12] = str(new_import)
                        rows[r_idx - 1][13] = str(new_end)
                    else:
                        updates.append({'range': f'D{r_idx}:E{r_idx}', 'values': [[new_import, new_end]]})
                        while len(rows[r_idx - 1]) <= 4:
                            rows[r_idx - 1].append('')
                        rows[r_idx - 1][3] = str(new_import)
                        rows[r_idx - 1][4] = str(new_end)

                    log_rows.append([today, "Nhập", clean_name, qty, user, note])
                    imported.append({
                        'name': clean_name,
                        'qty': qty,
                        'new_stock': new_end,
                        'unit': unit,
                    })

                if updates:
                    ws.batch_update(updates, value_input_option='USER_ENTERED')
                    try:
                        ws_log = self._get_inventory_ws("LichSu")
                        for lr in reversed(log_rows):
                            ws_log.insert_row(lr, index=2, value_input_option='USER_ENTERED')
                    except Exception as log_err:
                        logger.warning("Không ghi được LichSu nhập kho: %s", log_err)

                return {
                    'success': len(imported) > 0,
                    'imported': imported,
                    'errors': errors,
                }
            except Exception as e:
                logger.error("Lỗi batch_import_stock: %s", e)
                return {'success': False, 'error': 'Lỗi kết nối kho', 'imported': [], 'errors': ['Lỗi kết nối kho']}

    def export_stock(self, name: str, qty: float, user: str, note: str = "") -> dict:
        """Xuất kho trực tiếp trên sheet tháng hiện tại (uỷ quyền qua batch_export_stock)."""
        res = self.batch_export_stock([{'name': name, 'qty': qty}], user, note)
        if not res.get('success') or not res.get('exported'):
            err = res.get('errors', ['Không thể xuất kho'])[0] if res.get('errors') else res.get('error', 'Không thể xuất kho')
            return {'success': False, 'error': err}
        exp = res['exported'][0]
        alerts = res.get('low_stock_alerts', [])
        return {
            'success': True,
            'new_stock': exp['new_stock'],
            'unit': exp.get('unit', ''),
            'low_stock': len(alerts) > 0,
            'min_stock': alerts[0].get('min_stock', 0) if alerts else 0,
        }

    def batch_export_stock(self, items: list, user: str, note: str = "") -> dict:
        """Xuất kho nhiều món cùng lúc trực tiếp trên sheet tháng hiện tại:
        - Trừ vào cột 'Số lượng cuối tháng' (cột E cho NVL / cột N cho CCDC).
          Nhờ công thức =SUM(C+D-E) có sẵn trên sheet, cột 'Số lượng đã sử dụng'
          và 'Thành tiền' sẽ tự động nhảy số!
        - Nếu tồn kho = 0 (nhân viên lấy vượt số đầu+nhập trên sheet), tự động
          tăng cột Đầu/Nhập hoặc cho phép cập nhật để không bao giờ chặn nhân viên.
        - Ghi lịch sử vào tab LichSu.
        """
        with self._write_lock:
            try:
                ws = self._get_current_monthly_ws(create_if_new_month=True)
                rows = ws.get_all_values()
                meta_map = self._get_metadata_map()

                updates = []
                exported = []
                low_stock_alerts = []
                errors = []
                today = local_now().strftime("%d/%m/%Y %H:%M")
                log_rows = []

                for item in items:
                    name = item['name']
                    qty = float(item['qty'])
                    target = normalize_name(name)
                    loc = self._locate_item_on_monthly_ws(rows, target)
                    if not loc:
                        errors.append(f"Không tìm thấy '{name}'")
                        continue

                    r_idx = loc['row_idx']
                    current_end = loc['end_qty']
                    new_stock = round(max(0.0, current_end - qty), 3)

                    m_info = meta_map.get(target, {})
                    unit = m_info.get('unit', '')
                    min_stock = m_info.get('min_stock', 0.0)
                    clean_name = loc['clean_name']

                    end_col = 'N' if loc['is_ccdc'] else 'E'
                    updates.append({'range': f'{end_col}{r_idx}', 'values': [[new_stock]]})

                    # Cập nhật lại vào mảng rows trong bộ nhớ nếu trùng món
                    col_idx = 13 if loc['is_ccdc'] else 4
                    while len(rows[r_idx - 1]) <= col_idx:
                        rows[r_idx - 1].append('')
                    rows[r_idx - 1][col_idx] = str(new_stock)

                    log_rows.append([today, "Xuất", clean_name, qty, user, note])
                    exported.append({
                        'name': clean_name,
                        'qty': qty,
                        'new_stock': new_stock,
                        'unit': unit,
                    })
                    if new_stock <= 0 or (min_stock > 0 and new_stock <= min_stock):
                        low_stock_alerts.append({
                            'name': clean_name,
                            'new_stock': new_stock,
                            'min_stock': min_stock,
                            'unit': unit,
                        })

                if updates:
                    try:
                        ws.batch_update(updates, value_input_option='USER_ENTERED')
                        ws_log = self._get_inventory_ws("LichSu")
                        for lr in reversed(log_rows):
                            ws_log.insert_row(lr, index=2, value_input_option='USER_ENTERED')
                    except Exception as write_err:
                        logger.warning("Không ghi được lên Sheet NVL (chưa cấp quyền Editor): %s", write_err)

                return {
                    'success': len(exported) > 0,
                    'exported': exported,
                    'low_stock_alerts': low_stock_alerts,
                    'errors': errors,
                }
            except Exception as e:
                logger.error("Lỗi batch_export_stock: %s", e)
                return {'success': False, 'error': 'Lỗi kết nối kho', 'exported': [], 'errors': ['Lỗi kết nối kho']}

    def get_inventory_history(self, limit: int = 20) -> list:
        """Lấy lịch sử nhập/xuất kho gần nhất."""
        try:
            ws = self._get_inventory_ws("LichSu", create=False)
            if not ws:
                return []
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return []
            result = []
            for row in rows[1:limit + 1]:
                if not row[0].strip():
                    continue
                result.append({
                    'date': row[0].strip(),
                    'type': row[1].strip() if len(row) > 1 else '',
                    'name': row[2].strip() if len(row) > 2 else '',
                    'qty': self._parse_float(row[3] if len(row) > 3 else 0),
                    'user': row[4].strip() if len(row) > 4 else '',
                    'note': row[5].strip() if len(row) > 5 else '',
                })
            return result
        except Exception as e:
            logger.error("Lỗi lấy lịch sử kho: %s", e)
            return []

    def get_low_stock_items(self) -> list:
        """Lấy danh sách NVL dưới mức tồn kho tối thiểu."""
        materials = self.get_all_materials()
        return [m for m in materials if m['min_stock'] > 0 and m['stock'] <= m['min_stock']]

    def get_employee_personal_summary(self, nickname: str) -> dict:
        """Lấy thống kê cá nhân của 1 nhân viên trong kỳ lương hiện tại (giờ công, OT, lương tạm tính, đi muộn, lịch sử chấm công)."""
        target = normalize_name(nickname)
        if not target:
            return {'success': False, 'error': 'Thiếu tên nhân viên'}
        try:
            month, year = self._current_salary_month()
            start_date, end_date = self._salary_period(month, year)

            emp_details = self.get_employees_detail()
            emp_info = next((e for e in emp_details if normalize_name(e.get('nickname', '')) == target), None)
            rate = float(emp_info.get('rate', Config.DEFAULT_HOURLY_RATE_K)) if emp_info else float(Config.DEFAULT_HOURLY_RATE_K)
            balance = int(emp_info.get('balance', 0)) if emp_info else 0
            display_nick = emp_info.get('nickname', nickname) if emp_info else nickname

            regular_hours = 0.0
            late_count = 0
            recent_checkins = []

            if getattr(self, 'ws_checkin', None) is not None:
                all_rows = self.ws_checkin.get_all_values()[1:]
                for row in all_rows:
                    if len(row) < 2 or normalize_name(row[1]) != target:
                        continue
                    r_date_str = row[0].strip()
                    ci_time = row[2].strip() if len(row) > 2 else ''
                    co_time = row[3].strip() if len(row) > 3 else ''
                    hrs_str = row[4].strip() if len(row) > 4 else ''
                    note = row[5].strip() if len(row) > 5 else ''

                    if len(recent_checkins) < 12:
                        recent_checkins.append({
                            'date': r_date_str,
                            'checkin_time': ci_time,
                            'checkout_time': co_time or 'Đang làm',
                            'total_hours': hrs_str or '—',
                            'note': note,
                        })

                    try:
                        d_obj = datetime.strptime(r_date_str, "%d/%m/%Y").date()
                    except ValueError:
                        continue
                    if start_date <= d_obj <= end_date:
                        if hrs_str:
                            regular_hours += self._number(hrs_str, 0.0)
                        if 'muộn' in note.lower():
                            late_count += 1

            ot_map = self.get_overtime_summary(start_date, end_date) or {}
            ot_hours = 0.0
            for k, v in ot_map.items():
                if normalize_name(k) == target:
                    ot_hours += float(v or 0.0)

            total_hours = round(regular_hours + ot_hours, 2)
            estimated_pay_k = round(total_hours * rate, 1)

            return {
                'success': True,
                'nickname': display_nick,
                'month': month,
                'year': year,
                'period': f"{start_date.strftime('%d/%m/%Y')} → {end_date.strftime('%d/%m/%Y')}",
                'regular_hours': round(regular_hours, 2),
                'overtime_hours': round(ot_hours, 2),
                'total_hours': total_hours,
                'rate': rate,
                'estimated_pay_k': estimated_pay_k,
                'balance': balance,
                'late_count': late_count,
                'recent_checkins': recent_checkins,
            }
        except Exception as e:
            logger.error("Lỗi lấy thống kê cá nhân %s: %s", nickname, e)
            return {'success': False, 'error': str(e)}

