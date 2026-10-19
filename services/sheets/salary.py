"""Salary sheets mixin for salary calculation, reporting, and hourly rate management."""
from __future__ import annotations

import logging
import re
import threading
from datetime import date, datetime
from typing import Any, Optional

from gspread.utils import rowcol_to_a1

from config import Config
from utils.time_utils import local_now
from utils.validators import normalize_name

logger = logging.getLogger(__name__)


class SalarySheetsMixin:
    """Mixin quản lý tính toán lương, báo cáo bảng lương, mức lương theo giờ và ứng/thưởng."""

    @staticmethod
    def _column_letter(index: int) -> str:
        """Chuyển đổi chỉ số cột 1-based thành chữ cái cột (1 -> 'A', 27 -> 'AA')."""
        return re.sub(r'\d+', '', rowcol_to_a1(1, index))

    @staticmethod
    def _current_salary_month(now: datetime = None) -> tuple[int, int]:
        """Xác định (tháng, năm) của chu kỳ lương hiện tại (chu kỳ từ ngày 17 tháng này đến 16 tháng sau)."""
        now = now or local_now()
        if now.day < 17:
            return now.month, now.year
        if now.month == 12:
            return 1, now.year + 1
        return now.month + 1, now.year

    @staticmethod
    def _salary_period(month: int, year: int) -> tuple[date, date]:
        """Trả về (start_date, end_date) của chu kỳ tính lương tháng/năm."""
        start = date(year - 1, 12, 17) if month == 1 else date(year, month - 1, 17)
        return start, date(year, month, 16)

    @staticmethod
    def _number(raw, default=0.0) -> float:
        """Chuyển đổi chuỗi thành float an toàn."""
        try:
            return float(str(raw).strip().replace(',', '.'))
        except (TypeError, ValueError):
            return float(default)

    def _get_mapping_worksheet(self):
        return self.sh_salary.worksheet("Mapping")

    def _get_mapping_indices(self, headers):
        headers_norm = [normalize_name(h) for h in headers]
        nick_col = next((i for i, h in enumerate(headers_norm) if 'nickname' in h or h in {'nick', 'nicknamebot'}), 1)
        bal_col = next((i for i, h in enumerate(headers_norm) if 'sodu' in h or 'thuong' in h), 3)
        rate_col = next((i for i, h in enumerate(headers_norm) if ('luong' in h and 'ten' not in h) or 'rate' in h), 2)
        return nick_col, rate_col, bal_col

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
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
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
                invalidate = getattr(self, "_invalidate_cache", None)
                if invalidate:
                    invalidate("employees_detail", "salary_rates")
                return True
            except Exception as e:
                logger.error(f"Lỗi khi cập nhật mức lương cho {nickname}: {e}")
                return False

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
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
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
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
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
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
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
