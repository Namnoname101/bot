"""Attendance sheets mixin for check-in, check-out, and shift tracking."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from utils.time_utils import local_now
from utils.validators import normalize_name

logger = logging.getLogger(__name__)


class AttendanceSheetsMixin:
    """Mixin quản lý chấm công, ca làm việc, check-in, check-out và thống kê đi muộn."""

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
                            'note': row_note,
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
                        return {
                            'success': False,
                            'error': 'already_checked_in',
                            'time': row[2].strip(),
                        }

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
                            'endIndex': 2,
                        },
                        'inheritFromBefore': False,
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
                                'endColumnIndex': num_cols,
                            },
                            'destination': {
                                'sheetId': sheet_id,
                                'startRowIndex': 1,
                                'endRowIndex': 2,
                                'startColumnIndex': 0,
                                'endColumnIndex': num_cols,
                            },
                            'pasteType': 'PASTE_FORMAT',
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
                'date_str': today,
            }
        except Exception as e:
            logger.error(f"Lỗi khi check-in cho {nickname}: {e}")
            return {'success': False, 'error': str(e)}

    def checkout(self, nickname: str, shift_type: str = None, force_time: str = None) -> dict:
        """Ghi nhận check-out cho nhân viên.

        Tìm hàng check-in mới nhất (hôm nay HOẶC hôm qua, chưa có giờ ra) và cập nhật.
        Hỗ trợ ca đêm: checkout qua ngày mới (ví dụ check-in 18:00, checkout 00:30 hôm sau).

        Returns:
            dict với keys: success, time, total_hours, checkin_time
        """
        try:
            now = local_now()
            today = now.strftime("%d/%m/%Y")
            yesterday = (now - timedelta(days=1)).strftime("%d/%m/%Y")
            time_str = force_time if force_time else now.strftime("%H:%M:%S")

            # Tìm hàng check-in hôm nay HOẶC hôm qua chưa có giờ ra
            all_data = self.ws_checkin.get_all_values()
            target_row = None
            checkin_date = None

            is_ca_gay = False
            for i, row in enumerate(all_data[1:], start=2):  # Skip header
                if len(row) >= 3:
                    row_date = row[0].strip()
                    row_nick = row[1].strip()
                    row_checkout = row[3].strip() if len(row) > 3 else ""
                    row_note = row[5].strip() if len(row) > 5 else ""

                    if (row_date in (today, yesterday) and 
                        normalize_name(row_nick) == normalize_name(nickname) and
                        not row_checkout):
                        current_type = "Ca Gãy" if 'ca gãy' in row_note.lower() else "Ca Chính"
                        if shift_type and current_type != shift_type:
                            continue
                        target_row = i
                        checkin_date = row_date
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
                # Xử lý ca đêm: nếu checkout qua ngày mới, diff âm → cộng 24h
                if diff < 0 and checkin_date == yesterday:
                    diff += 24.0
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
                'is_ca_gay': is_ca_gay,
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
                        'note':          row[5].strip() if len(row) > 5 else '',
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
                                'pre_reported': '(đã báo trước)' in note.lower(),
                            })
            return records
        except Exception as e:
            logger.error(f"Lỗi lấy thống kê đi muộn: {e}")
            return []
