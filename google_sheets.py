import gspread
import logging
import re
import time
import unicodedata
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)

def _normalize_name_for_comparison(s: str) -> str:
    """Chuẩn hóa Unicode và loại bỏ dấu Tiếng Việt để so sánh tên nhân viên.
    
    Ví dụ: 'Hoà' (NFC) và 'Hoà' (NFD) sẽ thành 'hoa' khi so sánh.
    Đặc biệt: 'Đ'/'đ' (U+0110/U+0111) không tách được qua NFD nên xử lý thủ công.
    """
    if not s:
        return ''
    s = str(s).strip()
    # BUG-2 FIX: Đ/đ không tách thành D + combining stroke qua NFD
    # → phải thay thế thủ công trước
    s = s.replace('Đ', 'D').replace('đ', 'd')
    # Chuẩn hóa Unicode NFD để tách dấu và ký tự
    s = unicodedata.normalize('NFD', s)
    # Loại bỏ các ký tự kết hợp (combining characters - dấu tiếng Việt)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    # Loại bỏ các ký tự không phải chữ cái/số, chuyển thành chữ thường
    s = re.sub(r'[^0-9a-zA-Z]', '', s).lower()
    return s

class GoogleSheetsService:
    def __init__(self, max_retries=3):
        """Khởi tạo Google Sheets Service với retry logic.
        
        Args:
            max_retries: Số lần thử lại tối đa khi kết nối thất bại
        """
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

                def _normalize(s: str) -> str:
                    if not s:
                        return ''
                    s = str(s).replace('Đ', 'D').replace('đ', 'd')
                    s = unicodedata.normalize('NFD', s)
                    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
                    s = re.sub(r'[^0-9a-zA-Z]', '', s).lower()
                    return s

                for idx, h in enumerate(self.balance_headers):
                    hn = _normalize(h)
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

    def save_report(self, date: str, employees, revenue: int, ca: str = None) -> bool:
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

            now = datetime.now()
            if not ca:
                if now.hour < 12:
                    ca = 'Sáng'
                elif now.hour < 18:
                    ca = 'Chiều'
                else:
                    ca = 'Tối'
            time_str = now.strftime("%H:%M %d/%m/%Y")
            status = 'Đã duyệt'

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
                end_col = chr(64 + num_cols)  # A=65, B=66, ...
                range_str = f'A{start_row_1b}:{end_col}{end_row_1b}'
                self.ws_history.update(range_str, values, value_input_option='USER_ENTERED')

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
            target = _normalize_name_for_comparison(nickname)
            
            # skip header row
            for i, v in enumerate(col_nicks[1:], start=2):
                if _normalize_name_for_comparison(str(v)) == target:
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
        """Lấy mức lương/giờ của tất cả nhân viên từ sheet Mapping (cột 3)."""
        try:
            records = self.ws_balance.get_all_values()
            rates = {}
            for row in records[1:]:  # Bỏ qua dòng tiêu đề
                if len(row) > 1 and row[1].strip():
                    nick = row[1].strip()
                    try:
                        rate = float(row[2].strip().replace(',', '.')) if len(row) > 2 and row[2].strip() else 16.0
                    except:
                        rate = 16.0
                    rates[nick] = rate
            return rates
        except Exception as e:
            logger.error(f"Lỗi khi lấy danh sách mức lương: {e}")
            return {}

    def update_salary_rate(self, nickname: str, new_rate: str) -> bool:
        """Cập nhật mức lương/giờ cho một nhân viên trên sheet Mapping."""
        try:
            col_nicks = self.ws_balance.col_values(2)  # Cột Nickname Bot
            target = nickname.strip().lower()
            
            for i, v in enumerate(col_nicks):
                if v.strip().lower() == target:
                    # Cập nhật cột C (Mức Lương/Giờ)
                    self.ws_balance.update_cell(i + 1, 3, new_rate)
                    return True
            return False
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
            return [_normalize_name_for_comparison(str(v)) for v in col_vals[1:] if str(v).strip()]
        except Exception as e:
            logger.error(f"Lỗi khi lấy danh sách nickname: {e}")
            return []

    def update_balance(self, nickname: str, amount_change: int) -> bool:
        """Cập nhật số dư. amount_change có thể là số dương (cộng) hoặc âm (trừ)."""
        try:
            nickname_clean = nickname.strip()
            nickname_normalized = _normalize_name_for_comparison(nickname_clean)

            # Read nickname column ONCE
            col_nicks = self.ws_balance.col_values(self.col_nickname_index)
            
            found_row = None
            for i, v in enumerate(col_nicks[1:], start=2):
                if _normalize_name_for_comparison(str(v)) == nickname_normalized:
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

    # ==================== GIỜ LÀM THÊM ====================

    def add_overtime(self, nickname: str, hours: float) -> bool:
        """Admin thêm giờ làm thêm cho nhân viên vào sheet GioLamThem.
        
        Cấu trúc: Ngày | Nickname | Tổng Số Giờ
        """
        try:
            today = datetime.now().strftime("%d/%m/%Y")
            
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

    # ==================== CHECK-IN / CHECK-OUT ====================

    def _get_shift_info(self, now: datetime) -> dict:
        """Xác định ca làm việc và giờ vào chuẩn dựa trên giờ hiện tại.
        
        Sử dụng khoảng cách gần nhất (phút) để phân biệt check-in sớm ca sau vs check-in trễ ca trước.
        """
        current_minutes = now.hour * 60 + now.minute
        
        shifts = [
            {'ca': 'Sáng', 'standard_start': 6 * 60 + 30},  # 6:30
            {'ca': 'Chiều', 'standard_start': 12 * 60},     # 12:00
            {'ca': 'Tối', 'standard_start': 18 * 60}        # 18:00
        ]
        
        closest_shift = min(shifts, key=lambda s: abs(current_minutes - s['standard_start']))
        return closest_shift

    def get_checked_in_employees(self) -> dict:
        """Lấy danh sách các nhân viên đã check-in hôm nay nhưng chưa check-out.
        
        Returns:
            dict: {nickname: checkin_time}
        """
        try:
            today = datetime.now().strftime("%d/%m/%Y")
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

    def checkin(self, nickname: str, shift_type: str = "") -> dict:
        """Ghi nhận check-in cho nhân viên vào sheet Checkin.
        
        Cấu trúc: Ngày | Nickname | Giờ Vào | Giờ Ra | Tổng Giờ | Ghi Chú
        
        Returns:
            dict với keys: success, time, note, late_minutes, ca, date_str
        """
        try:
            now = datetime.now()
            today = now.strftime("%d/%m/%Y")
            time_str = now.strftime("%H:%M:%S")
            
            # Kiểm tra đã check-in hôm nay chưa
            all_data = self.ws_checkin.get_all_values()
            for row in all_data[1:]:
                if len(row) >= 3:
                    row_date = row[0].strip()
                    row_nick = row[1].strip()
                    row_checkout = row[3].strip() if len(row) > 3 else ""
                    if (row_date == today and 
                        _normalize_name_for_comparison(row_nick) == _normalize_name_for_comparison(nickname) and
                        not row_checkout):
                        return {'success': False, 'error': 'already_checked_in',
                                'time': row[2].strip()}
            
            # Xác định ca và tính trễ
            shift = self._get_shift_info(now)
            standard_start = shift['standard_start']
            
            # Logic ca gãy: sau 19h30 mới tính trễ
            if shift_type == "Ca Gãy":
                standard_start = 19 * 60 + 30
                
            current_minutes = now.hour * 60 + now.minute
            late_minutes = max(0, current_minutes - standard_start)
            
            if late_minutes > 0:
                note = f"{shift_type} - Đi muộn {late_minutes}p" if shift_type else f"Đi muộn {late_minutes}p"
            else:
                note = f"{shift_type} - Đúng giờ" if shift_type else "Đúng giờ"
            
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
                
                end_col = chr(64 + num_cols)  # A=65, B=66, ...
                self.ws_checkin.update(f'A2:{end_col}2', [row[:num_cols]], value_input_option='USER_ENTERED')
                
            except Exception:
                # Fallback: insert_row nếu batch update fail
                logger.exception('Batch insert for checkin failed, falling back to insert_row')
                row = [today, nickname, time_str, "", "", note]
                # Pad thêm cột trống nếu cần
                while len(row) < num_cols:
                    row.append('')
                self.ws_checkin.insert_row(row[:num_cols], index=2, value_input_option='USER_ENTERED')
            
            logger.info(f"Check-in: {nickname} lúc {time_str} - {note}")
            return {
                'success': True,
                'time': time_str,
                'note': note,
                'late_minutes': late_minutes,
                'ca': shift['ca'],
                'date_str': today
            }
        except Exception as e:
            logger.error(f"Lỗi khi check-in cho {nickname}: {e}")
            return {'success': False, 'error': str(e)}

    def checkout(self, nickname: str) -> dict:
        """Ghi nhận check-out cho nhân viên.
        
        Tìm hàng check-in mới nhất (hôm nay, chưa có giờ ra) và cập nhật.
        
        Returns:
            dict với keys: success, time, total_hours, checkin_time
        """
        try:
            now = datetime.now()
            today = now.strftime("%d/%m/%Y")
            time_str = now.strftime("%H:%M:%S")
            
            # Tìm hàng check-in hôm nay chưa có giờ ra
            all_data = self.ws_checkin.get_all_values()
            target_row = None
            
            for i, row in enumerate(all_data[1:], start=2):  # Skip header
                if len(row) >= 3:
                    row_date = row[0].strip()
                    row_nick = row[1].strip()
                    row_checkout = row[3].strip() if len(row) > 3 else ""
                    row_note = row[5].strip() if len(row) > 5 else ""
                    
                    if (row_date == today and 
                        _normalize_name_for_comparison(row_nick) == _normalize_name_for_comparison(nickname) and
                        not row_checkout):
                        target_row = i
                        is_ca_gay = 'ca gãy' in row_note.lower()
            
            if not target_row:
                return {'success': False, 'error': 'not_checked_in'}
            
            # Cập nhật giờ ra (cột D)
            self.ws_checkin.update_cell(target_row, 4, time_str)
            
            # Tính tổng giờ
            checkin_time = all_data[target_row - 1][2]  # Cột C = Giờ Vào
            total_hours = 0.0
            try:
                checkin_dt = datetime.strptime(checkin_time.strip(), "%H:%M:%S")
                checkout_dt = datetime.strptime(time_str, "%H:%M:%S")
                diff = (checkout_dt - checkin_dt).total_seconds() / 3600
                # BUG-10 FIX: nếu diff âm → ca đêm qua nửa đêm, cộng thêm 24h
                if diff < 0:
                    diff += 24
                total_hours = round(diff, 1)
                self.ws_checkin.update_cell(target_row, 5, total_hours)  # Cột E = Tổng Giờ
            except Exception as calc_err:
                logger.warning(f"Không thể tính tổng giờ: {calc_err}")
            
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
                        _normalize_name_for_comparison(row_nick) == _normalize_name_for_comparison(nickname) and
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
                        _normalize_name_for_comparison(row_nick) == _normalize_name_for_comparison(nickname) and
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
            today = datetime.now().strftime("%d/%m/%Y")
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
                month_year = datetime.now().strftime("%m/%Y")
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
                                'pre_reported': 'báo trước' in note.lower()
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
            target = _normalize_name_for_comparison(nickname)
            for v in col_nicks[1:]:
                if _normalize_name_for_comparison(str(v)) == target:
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

    def remove_employee(self, nickname: str) -> bool:
        """Xóa nhân viên khỏi sheet SoDuThuong."""
        try:
            col_nicks = self.ws_balance.col_values(self.col_nickname_index)
            target = _normalize_name_for_comparison(nickname)
            for i, v in enumerate(col_nicks[1:], start=2):
                if _normalize_name_for_comparison(str(v)) == target:
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
                if nickname and _normalize_name_for_comparison(row_nick) != _normalize_name_for_comparison(nickname):
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
                key  = (date, ca)
                if key not in sessions:
                    sessions[key] = {
                        'date': date, 'ca': ca,
                        'employees': [], 'revenue': '',
                        'row_indices': [],
                        'time': row[3].strip() if len(row) > 3 else ''
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

    def update_report_revenue(self, row_indices: list, new_revenue: int) -> bool:
        """Cập nhật doanh thu (cột F) cho tất cả hàng trong một session."""
        try:
            for row_idx in row_indices:
                self.ws_history.update_cell(row_idx, 6, new_revenue)
            logger.info(f"Đã cập nhật DT={new_revenue} cho rows {row_indices}")
            return True
        except Exception as e:
            logger.error(f"Lỗi cập nhật doanh thu: {e}")
            return False

    def ensure_salary_worksheet(self):
        """Tạo sheet lương tháng mới nếu chưa có hoặc cập nhật format."""
        try:
            from datetime import datetime
            now = datetime.now()
            month_str = f"T{now.month}-{now.year}"
            try:
                ws = self.sh_salary.worksheet(f"{month_str}_New")
                return ws
            except Exception:
                try:
                    ws = self.sh_salary.worksheet(month_str)
                    return ws
                except Exception:
                    pass
            logger.info(f"Tạo sheet lương mới: {month_str}")
            return None
        except Exception as e:
            logger.error(f"Lỗi ensure_salary_worksheet: {e}")
            return None


    def get_salary_month_options(self) -> list:
        """Lấy danh sách các tháng có bảng lương."""
        try:
            options = []
            worksheets = self.sh_salary.worksheets()
            import datetime
            now = datetime.datetime.now()
            current_month = f"T{now.month}-{now.year}"
            
            for ws in worksheets:
                if ws.title.startswith('T'):
                    title = ws.title.replace('_New', '')
                    try:
                        m, y = title.replace('T', '').split('-')
                        options.append({'month': int(m), 'year': int(y), 'exists': True})
                    except Exception:
                        pass
            
            # Đảm bảo tháng hiện tại có trong list dù chưa có sheet
            has_current = any(o['month'] == now.month and o['year'] == now.year for o in options)
            if not has_current:
                options.append({'month': now.month, 'year': now.year, 'exists': False})
                
            return sorted(options, key=lambda x: (x['year'], x['month']), reverse=True)
        except Exception as e:
            import logging
            logging.error(f"Lỗi lấy ds tháng lương: {e}")
            return []

    def get_salary_report(self, month: int, year: int) -> str:
        """Tạo hoặc đọc bảng lương cho tháng được chỉ định và trả về chuỗi Markdown."""
        import logging
        try:
            # 1. Đảm bảo có sheet
            month_str = f"T{month}-{year}"
            try:
                ws = self.sh_salary.worksheet(month_str)
            except Exception:
                try:
                    ws = self.sh_salary.worksheet(f"{month_str}_New")
                except Exception:
                    # Tạo sheet mới
                    ws = self.sh_salary.add_worksheet(title=f"{month_str}_New", rows="100", cols="20")
                    headers = ["Ngày Tạo", "Tháng", "Tên Nhân Viên", "Nickname Bot", "Tổng Giờ Làm", "Mức Lương/Giờ", "Thưởng Tiền", "Ứng Lương", "Nhận Thực Tế"]
                    ws.append_row(headers)
                    # Gán format tiêu đề
                    ws.format("A1:I1", {"textFormat": {"bold": True}})
                    
            # 2. Đọc dữ liệu từ sheet Lương
            all_data = ws.get_all_values()
            
            # Lấy danh sách nhân viên từ Mapping (SoDuThuong)
            rates = self.get_all_salary_rates()
            
            # 3. Tính tổng giờ làm từ LichSuCheckin cho khoảng 17 tháng trước -> 16 tháng này
            import datetime
            if month == 1:
                start_date = datetime.date(year - 1, 12, 17)
            else:
                start_date = datetime.date(year, month - 1, 17)
            end_date = datetime.date(year, month, 16)
            
            checkin_data = self.ws_checkin.get_all_values()
            hours_dict = {}
            for row in checkin_data[1:]:
                if len(row) >= 5:
                    date_str = row[0].strip()
                    nick = row[1].strip()
                    try:
                        d, m, y = map(int, date_str.split('/'))
                        row_date = datetime.date(y, m, d)
                        if start_date <= row_date <= end_date:
                            hours = float(row[4].strip().replace(',', '.')) if row[4].strip() else 0.0
                            hours_dict[nick] = hours_dict.get(nick, 0.0) + hours
                    except Exception:
                        pass
                        
            # 4. Cập nhật hoặc tạo dòng cho mỗi nhân viên trong sheet Lương
            existing_rows = {row[3].strip(): i+1 for i, row in enumerate(all_data) if len(row) > 3 and i > 0}
            
            report_lines = []
            report_lines.append(f"💵 *BẢNG LƯƠNG T{month}/{year}* ({start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')})\n")
            
            for nick, rate in rates.items():
                hours = hours_dict.get(nick, 0.0)
                # Đọc ứng/thưởng cũ
                row_idx = existing_rows.get(nick)
                bonus, adv = 0, 0
                real_name = ""
                if row_idx and row_idx <= len(all_data):
                    r_data = all_data[row_idx - 1]
                    try:
                        real_name = str(r_data[2]).strip() if len(r_data) > 2 else ""
                    except: pass
                    try:
                        bonus = float(str(r_data[6]).replace(',', '').replace('.', '')) if len(r_data) > 6 and r_data[6].strip() else 0.0
                    except: pass
                    try:
                        adv = float(str(r_data[7]).replace(',', '').replace('.', '')) if len(r_data) > 7 and r_data[7].strip() else 0.0
                    except: pass
                
                # Tính tổng
                total_received = (hours * rate) + bonus - adv
                
                # Report line
                display_name = real_name if real_name else nick
                report_lines.append(f"👤 *{display_name}*")
                report_lines.append(f"  ⏳ {hours:g}h x {rate:g}k = {hours * rate:g}k")
                if bonus > 0:
                    report_lines.append(f"  🎁 Thưởng: +{bonus:g}k")
                if adv > 0:
                    report_lines.append(f"  💸 Ứng: -{adv:g}k")
                report_lines.append(f"  👉 *Thực nhận: {total_received:g}k*\n")
                
                # Cập nhật sheet (Tên thật cột C, Nickname cột D)
                now_str = datetime.datetime.now().strftime('%d/%m/%Y %H:%M')
                if row_idx:
                    # Update existing row
                    ws.update(f'D{row_idx}:I{row_idx}', [[nick, hours, rate, bonus, adv, total_received]])
                else:
                    # Chèn mới
                    ws.append_row([now_str, f"T{month}-{year}", "", nick, hours, rate, bonus, adv, total_received])
            
            if len(report_lines) == 1:
                return f"Không có dữ liệu cho tháng {month}/{year}."
                
            return "\n".join(report_lines)
            
        except Exception as e:
            logging.error(f"Lỗi get_salary_report: {e}")
            return f"❌ Lỗi: {e}"

    def update_salary_modifier(self, nickname: str, is_bonus: bool, amount: int, month: int, year: int) -> bool:
        """Cập nhật ứng/thưởng cho nhân viên trong tháng."""
        import logging
        try:
            month_str = f"T{month}-{year}"
            try:
                ws = self.sh_salary.worksheet(month_str)
            except Exception:
                ws = self.sh_salary.worksheet(f"{month_str}_New")
                
            all_data = ws.get_all_values()
            
            for i, row in enumerate(all_data):
                if len(row) > 3 and _normalize_name_for_comparison(row[3].strip()) == _normalize_name_for_comparison(nickname):
                    # Cột 7: Thưởng, Cột 8: Ứng (1-based index)
                    col = 7 if is_bonus else 8
                    current_val = 0
                    try:
                        if len(row) >= col and row[col-1].strip():
                            current_val = float(str(row[col-1]).replace(',', '').replace('.', ''))
                    except:
                        pass
                    
                    new_val = current_val + amount
                    ws.update_cell(i + 1, col, new_val)
                    
                    # Update Thực Nhận (cột I = cột 9)
                    try:
                        hours = float(row[4].replace(',','.')) if len(row) >= 5 and row[4] else 0.0
                        rate = float(row[5].replace(',','.')) if len(row) >= 6 and row[5] else 16.0
                        bonus = float(row[6].replace(',','.')) if len(row) >= 7 and row[6] else 0.0
                        adv = float(row[7].replace(',','.')) if len(row) >= 8 and row[7] else 0.0
                        
                        if is_bonus:
                            bonus = new_val
                        else:
                            adv = new_val
                            
                        ws.update_cell(i + 1, 9, (hours * rate) + bonus - adv)
                    except Exception as e:
                        logging.error(f"Lỗi update tổng thực nhận: {e}")
                        
                    return True
            return False
        except Exception as e:
            logging.error(f"Lỗi update_salary_modifier cho {nickname}: {e}")
            raise e
