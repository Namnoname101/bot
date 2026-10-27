"""Reward sheets mixin for balance, rewards, and employee profile tracking."""
from __future__ import annotations

import logging
import re
import threading
from datetime import datetime
from typing import Any, Optional

from gspread.utils import rowcol_to_a1

from config import Config
from utils.time_utils import local_now
from utils.validators import normalize_name

logger = logging.getLogger(__name__)


class RewardSheetsMixin:
    """Mixin quản lý số dư ly thưởng, đổi thưởng, và thông tin nhân viên."""

    @staticmethod
    def _column_letter(index: int) -> str:
        """Chuyển đổi chỉ số cột 1-based thành chữ cái cột (1 -> 'A', 27 -> 'AA')."""
        return re.sub(r'\d+', '', rowcol_to_a1(1, index))

    @staticmethod
    def _number(raw, default=0.0) -> float:
        """Chuyển đổi chuỗi thành số thực an toàn."""
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

    def get_balance(self, nickname: str) -> int:
        """Lấy số dư từ sheet Mapping."""
        try:
            ws_map = self._get_mapping_worksheet()
            records = ws_map.get_all_values()
            if not records:
                return 0
            nick_col, _, bal_col = self._get_mapping_indices(records[0])

            target = normalize_name(nickname)
            for row in records[1:]:
                if len(row) > nick_col and normalize_name(row[nick_col]) == target:
                    if len(row) > bal_col:
                        try:
                            return int(row[bal_col].strip().replace(',', ''))
                        except Exception:
                            return 0
            return 0
        except Exception as e:
            logger.error(f"Error get_balance: {e}")
            return 0

    def get_all_balances(self) -> dict:
        """Lấy tất cả số dư từ Mapping."""
        balances = {}
        try:
            ws_map = self._get_mapping_worksheet()
            records = ws_map.get_all_values()
            if not records:
                return balances
            nick_col, rate_col, bal_col = self._get_mapping_indices(records[0])

            for row in records[1:]:
                if len(row) > nick_col and row[nick_col].strip():
                    nick = normalize_name(row[nick_col])
                    val = 0
                    if len(row) > bal_col:
                        try:
                            val = int(row[bal_col].strip().replace(',', ''))
                        except Exception:
                            pass
                    balances[nick] = val
            return balances
        except Exception:
            return balances

    def get_all_nicknames(self) -> list:
        """Lấy danh sách nickname hợp lệ từ Sheet Mapping."""
        try:
            ws = self._get_mapping_worksheet()
            records = ws.get_all_values()
            if not records:
                return []
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
        get_cache = getattr(self, "_get_cache", None)
        cached = get_cache("employees_detail", ttl_seconds=60.0) if get_cache else None
        if cached is not None:
            return [dict(e) for e in cached]
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
            set_cache = getattr(self, "_set_cache", None)
            if set_cache:
                set_cache("employees_detail", employees)
            return employees
        except Exception as e:
            logger.error(f"Error get_employees_detail: {e}")
            return []

    def update_balance(self, nickname: str, amount_change: int) -> bool:
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
        with self._write_lock:
            return self._update_balance_unlocked(nickname, amount_change)

    def _update_balance_unlocked(self, nickname: str, amount_change: int) -> bool:
        """Cập nhật số dư trong Mapping."""
        try:
            ws_map = self._get_mapping_worksheet()
            records = ws_map.get_all_values()
            if not records:
                return False
            nick_col, rate_col, bal_col = self._get_mapping_indices(records[0])

            target = normalize_name(nickname)
            for i, row in enumerate(records[1:], start=2):
                if len(row) > nick_col and normalize_name(row[nick_col]) == target:
                    current_val = 0
                    if len(row) > bal_col:
                        try:
                            current_val = int(row[bal_col].strip().replace(',', ''))
                        except Exception:
                            pass
                    new_val = current_val + amount_change
                    ws_map.update_cell(i, bal_col + 1, new_val)
                    invalidate = getattr(self, "_invalidate_cache", None)
                    if invalidate:
                        invalidate("employees_detail")
                    return True

            # Nếu chưa có, thêm mới
            new_row = [''] * (max(nick_col, bal_col) + 1)
            new_row[nick_col] = nickname
            new_row[bal_col] = amount_change
            ws_map.append_row(new_row, value_input_option='USER_ENTERED')
            invalidate = getattr(self, "_invalidate_cache", None)
            if invalidate:
                invalidate("employees_detail")
            return True
        except Exception as e:
            logger.error(f"Error update_balance: {e}")
            return False

    def batch_update_balances(self, nicknames: list, amount_change: int) -> bool:
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
        with self._write_lock:
            return self._batch_update_balances_unlocked(nicknames, amount_change)

    def _batch_update_balances_unlocked(self, nicknames: list, amount_change: int) -> bool:
        if not nicknames or amount_change == 0:
            return True
        try:
            ws_map = self._get_mapping_worksheet()
            records = ws_map.get_all_values()
            if not records:
                return False
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
                            except Exception:
                                pass
                        updates.append({
                            'range': f"{self._column_letter(bal_col + 1)}{i}",
                            'values': [[current_val + amount_change]],
                        })

            if updates:
                ws_map.batch_update(updates, value_input_option='USER_ENTERED')

            # Insert missing ones
            for nick_norm, original_nick in targets.items():
                if nick_norm not in found_targets:
                    self._update_balance_unlocked(original_nick, amount_change)

            invalidate = getattr(self, "_invalidate_cache", None)
            if invalidate:
                invalidate("employees_detail")
            return True
        except Exception as e:
            logger.error(f"Error batch_update_balances: {e}")
            return False

    def consume_reward(self, nickname: str) -> dict:
        """Giảm 1 ly."""
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
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

    def add_employee(self, nickname: str) -> dict:
        """Thêm nhân viên mới vào sheet Mapping."""
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
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
                ws.append_row(
                    [nickname, nickname, Config.DEFAULT_HOURLY_RATE_K, 0],
                    value_input_option='USER_ENTERED',
                )
                invalidate = getattr(self, "_invalidate_cache", None)
                if invalidate:
                    invalidate("employees_detail")
                return {'success': True}
            except Exception as e:
                return {'success': False, 'error': str(e)}

    def rename_employee(self, old_nickname: str, new_nickname: str) -> dict:
        """Đổi nickname nhất quán trên các sheet nghiệp vụ và Mapping."""
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
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

                invalidate = getattr(self, "_invalidate_cache", None)
                if invalidate:
                    invalidate("employees_detail")
                return {'success': True}
            except Exception as e:
                logger.error("Lỗi đổi tên %s -> %s: %s", old_nickname, new_nickname, e)
                return {'success': False, 'error': str(e)}

    def remove_employee(self, nickname: str) -> bool:
        """Xóa nhân viên khỏi sheet Mapping."""
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
        with self._write_lock:
            try:
                ws = self._get_mapping_worksheet()
                records = ws.get_all_values()
                if not records:
                    return False
                nick_col, _, _ = self._get_mapping_indices(records[0])
                target = normalize_name(nickname)
                for i, row in enumerate(records[1:], start=2):
                    if len(row) > nick_col and normalize_name(row[nick_col]) == target:
                        ws.delete_rows(i)
                        invalidate = getattr(self, "_invalidate_cache", None)
                        if invalidate:
                            invalidate("employees_detail")
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
                    'date': row[0].strip(),
                    'ca': row[1].strip() if len(row) > 1 else '',
                    'nickname': row_nick,
                    'time': row[3].strip() if len(row) > 3 else '',
                    'status': row[4].strip() if len(row) > 4 else '',
                    'revenue': row[5].strip() if len(row) > 5 else '',
                })
                if len(records) >= limit:
                    break
            return records
        except Exception as e:
            logger.error(f"Lỗi lấy lịch sử thưởng: {e}")
            return []

    def get_employee_personal_summary(self, nickname: str, store: Any = None) -> dict:
        """Lấy thống kê cá nhân của 1 nhân viên trong kỳ lương hiện tại (giờ công, OT, lương tạm tính, đi muộn, lịch sử chấm công)."""
        target = normalize_name(nickname)
        if not target:
            return {'success': False, 'error': 'Thiếu tên nhân viên'}
        try:
            month, year = self._current_salary_month()
            start_date, end_date = self._salary_period(month, year)
            if store is None:
                store = getattr(self, "store", None)

            emp_details = self.get_employees_detail()
            emp_info = next((e for e in emp_details if normalize_name(e.get('nickname', '')) == target), None)
            rate = float(emp_info.get('rate', Config.DEFAULT_HOURLY_RATE_K)) if emp_info else float(Config.DEFAULT_HOURLY_RATE_K)
            balance = int(emp_info.get('balance', 0)) if emp_info else 0
            display_nick = emp_info.get('nickname', nickname) if emp_info else nickname

            regular_hours = 0.0
            late_count = 0
            late_records = []
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
                            late_records.append((r_date_str, note))

            ot_summary_func = getattr(self, 'get_overtime_summary', None)
            ot_map = ot_summary_func(start_date, end_date) if ot_summary_func else {}
            ot_hours = 0.0
            for k, v in (ot_map or {}).items():
                if normalize_name(k) == target:
                    ot_hours += float(v or 0.0)

            total_hours = round(regular_hours + ot_hours, 2)
            base_salary_k = round(total_hours * rate, 1)

            penalties = store.get_penalties(nickname=target, start_date=start_date, end_date=end_date) if store else []
            penalty_count = len(penalties)
            penalty_amount_k = round(penalty_count * 10.0, 1)
            penalty_amount = penalty_count * 10000

            # Đi muộn chỉ trừ khi quản lý xác nhận '(không báo trước)'.
            # Nếu quản lý chưa chọn hoặc chọn '(đã báo trước)' thì không trừ.
            # Nếu đã ghi vào store penalties thì tránh trừ trùng.
            unreported_dates_in_store = {
                p.get("date") for p in penalties
                if "đi muộn" in (p.get("reason") or "").lower()
            }
            unreported_not_in_store = sum(
                1 for d_str, n in late_records
                if "(không báo trước)" in n.lower() and d_str not in unreported_dates_in_store
            )
            late_penalty_k = round(unreported_not_in_store * 10.0, 1)
            late_penalty_amount = int(late_penalty_k * 1000)

            estimated_pay_k = round(max(0.0, base_salary_k - late_penalty_k - penalty_amount_k), 1)

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
                'base_salary_k': base_salary_k,
                'late_penalty_k': late_penalty_k,
                'late_penalty_amount': late_penalty_amount,
                'penalty_count': penalty_count,
                'penalty_amount_k': penalty_amount_k,
                'penalty_amount': penalty_amount,
                'penalties': penalties[:10],
                'estimated_pay_k': estimated_pay_k,
                'balance': balance,
                'late_count': late_count,
                'recent_checkins': recent_checkins,
            }
        except Exception as e:
            logger.error("Lỗi lấy thống kê cá nhân %s: %s", nickname, e)
            return {'success': False, 'error': str(e)}
