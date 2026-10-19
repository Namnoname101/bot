"""Sync sheets mixin for WebApp persistence synchronization (leaves, expenses, recipes, shift schedules, accounts, roles)."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

import gspread

from utils.time_utils import local_now
from utils.validators import normalize_name

logger = logging.getLogger(__name__)


class SyncSheetsMixin:
    """Mixin đồng bộ dữ liệu WebApp store với Google Sheets: đơn từ, chi tiêu, công thức, lịch ca, tài khoản và chức vụ."""

    def _get_or_create_custom_sheet(self, title: str, default_headers: list[str]) -> Optional[gspread.Worksheet]:
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

    def append_sheet_leave_request(self, item: dict) -> bool:
        """Lưu đơn xin nghỉ/đi muộn vào Google Sheets."""
        try:
            ws = self._get_or_create_custom_sheet(
                "DonXinNghi",
                ["ID", "ThoiGianTao", "Nickname", "ViTri", "LoaiDon", "NgayXin", "Ca", "LyDo", "ChiTiet", "TrangThai", "ThoiGianDuyet"]
            )
            if not ws:
                return False
            row = [
                str(item.get("id") or ""),
                str(item.get("created_at") or ""),
                str(item.get("nickname") or ""),
                str(item.get("role") or ""),
                str(item.get("type") or ""),
                str(item.get("date") or ""),
                str(item.get("ca") or ""),
                str(item.get("reason") or ""),
                str(item.get("extra") or ""),
                str(item.get("status") or "pending"),
                str(item.get("decided_at") or ""),
            ]
            lock = getattr(self, "_write_lock", None)
            if lock is None:
                self._write_lock = threading.RLock()
            with self._write_lock:
                ws.append_row(row, value_input_option='USER_ENTERED')
            return True
        except Exception as e:
            logger.error("Lỗi khi ghi đơn xin phép vào Google Sheets: %s", e)
            return False

    def update_sheet_leave_request_status(self, req_id: str, status: str, decided_at: str) -> bool:
        """Cập nhật trạng thái duyệt đơn trên Google Sheets."""
        try:
            ws = self._get_or_create_custom_sheet(
                "DonXinNghi",
                ["ID", "ThoiGianTao", "Nickname", "ViTri", "LoaiDon", "NgayXin", "Ca", "LyDo", "ChiTiet", "TrangThai", "ThoiGianDuyet"]
            )
            if not ws:
                return False
            lock = getattr(self, "_write_lock", None)
            if lock is None:
                self._write_lock = threading.RLock()
            with self._write_lock:
                all_ids = ws.col_values(1)
                for idx, rid in enumerate(all_ids, start=1):
                    if str(rid).strip() == str(req_id).strip():
                        ws.update_cell(idx, 10, status)
                        ws.update_cell(idx, 11, decided_at)
                        return True
            return False
        except Exception as e:
            logger.error("Lỗi khi cập nhật trạng thái đơn %s trên Google Sheets: %s", req_id, e)
            return False

    def load_sheet_leave_requests(self, limit: int = 50) -> list[dict]:
        """Tải danh sách đơn xin phép từ Google Sheets."""
        try:
            ws = self._get_or_create_custom_sheet(
                "DonXinNghi",
                ["ID", "ThoiGianTao", "Nickname", "ViTri", "LoaiDon", "NgayXin", "Ca", "LyDo", "ChiTiet", "TrangThai", "ThoiGianDuyet"]
            )
            if not ws:
                return []
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return []
            items = []
            for r in rows[1:]:
                if not r or not r[0].strip():
                    continue
                items.append({
                    "id": r[0].strip(),
                    "created_at": r[1].strip() if len(r) > 1 else "",
                    "nickname": r[2].strip() if len(r) > 2 else "",
                    "role": r[3].strip() if len(r) > 3 else "Nhân viên",
                    "type": r[4].strip() if len(r) > 4 else "late",
                    "date": r[5].strip() if len(r) > 5 else "",
                    "ca": r[6].strip() if len(r) > 6 else "Sáng",
                    "reason": r[7].strip() if len(r) > 7 else "",
                    "extra": r[8].strip() if len(r) > 8 else "",
                    "status": r[9].strip() if len(r) > 9 else "pending",
                    "decided_at": r[10].strip() if len(r) > 10 else "",
                })
            items.reverse()
            return items[:limit]
        except Exception as e:
            logger.error("Lỗi khi đọc đơn xin phép từ Google Sheets: %s", e)
            return []

    def append_sheet_petty_expense(self, exp: dict) -> bool:
        """Lưu khoản chi tiền lẻ vào Google Sheets."""
        try:
            ws = self._get_or_create_custom_sheet(
                "ChiTieuTienLe",
                ["ID", "Ngay", "Gio", "Nickname", "ViTri", "Ca", "SoTien", "LyDo"]
            )
            if not ws:
                return False
            row = [
                str(exp.get("id") or ""),
                str(exp.get("date") or ""),
                str(exp.get("time") or ""),
                str(exp.get("nickname") or ""),
                str(exp.get("role") or ""),
                str(exp.get("ca") or ""),
                int(exp.get("amount") or 0),
                str(exp.get("reason") or ""),
            ]
            lock = getattr(self, "_write_lock", None)
            if lock is None:
                self._write_lock = threading.RLock()
            with self._write_lock:
                ws.append_row(row, value_input_option='USER_ENTERED')
            return True
        except Exception as e:
            logger.error("Lỗi khi ghi chi tiền lẻ vào Google Sheets: %s", e)
            return False

    def load_sheet_petty_expenses(self, limit: int = 50) -> list[dict]:
        """Tải các khoản chi tiền lẻ từ Google Sheets."""
        try:
            ws = self._get_or_create_custom_sheet(
                "ChiTieuTienLe",
                ["ID", "Ngay", "Gio", "Nickname", "ViTri", "Ca", "SoTien", "LyDo"]
            )
            if not ws:
                return []
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return []
            items = []
            for r in rows[1:]:
                if not r or not r[0].strip():
                    continue
                try:
                    amt = int(r[6].strip().replace(",", "").replace(".", "")) if len(r) > 6 else 0
                except Exception:
                    amt = 0
                items.append({
                    "id": r[0].strip(),
                    "date": r[1].strip() if len(r) > 1 else "",
                    "time": r[2].strip() if len(r) > 2 else "",
                    "nickname": r[3].strip() if len(r) > 3 else "",
                    "role": r[4].strip() if len(r) > 4 else "Nhân viên",
                    "ca": r[5].strip() if len(r) > 5 else "Sáng",
                    "amount": amt,
                    "reason": r[7].strip() if len(r) > 7 else "",
                })
            items.reverse()
            return items[:limit]
        except Exception as e:
            logger.error("Lỗi khi đọc chi tiền lẻ từ Google Sheets: %s", e)
            return []

    def sync_sheet_recipes(self, recipes: list[dict]) -> bool:
        """Đồng bộ toàn bộ danh sách công thức vào Google Sheets."""
        try:
            ws = self._get_or_create_custom_sheet(
                "CongThuc",
                ["ID", "Nhom", "TenMon", "Size", "NguyenLieu", "CachLam"]
            )
            if not ws:
                return False
            data = [["ID", "Nhom", "TenMon", "Size", "NguyenLieu", "CachLam"]]
            for rcp in recipes:
                data.append([
                    str(rcp.get("id") or ""),
                    str(rcp.get("group") or ""),
                    str(rcp.get("name") or ""),
                    str(rcp.get("size") or ""),
                    str(rcp.get("ingredients") or ""),
                    str(rcp.get("steps") or ""),
                ])
            lock = getattr(self, "_write_lock", None)
            if lock is None:
                self._write_lock = threading.RLock()
            with self._write_lock:
                ws.clear()
                ws.update(data, range_name="A1", value_input_option='USER_ENTERED')
            return True
        except Exception as e:
            logger.error("Lỗi khi đồng bộ công thức vào Google Sheets: %s", e)
            return False

    def load_sheet_recipes(self) -> list[dict]:
        """Tải công thức pha chế từ Google Sheets."""
        try:
            ws = self._get_or_create_custom_sheet(
                "CongThuc",
                ["ID", "Nhom", "TenMon", "Size", "NguyenLieu", "CachLam"]
            )
            if not ws:
                return []
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return []
            items = []
            for r in rows[1:]:
                if not r or not r[0].strip() or not r[2].strip():
                    continue
                items.append({
                    "id": r[0].strip(),
                    "group": r[1].strip() if len(r) > 1 else "Khác",
                    "name": r[2].strip(),
                    "size": r[3].strip() if len(r) > 3 else "Size M",
                    "ingredients": r[4].strip() if len(r) > 4 else "",
                    "steps": r[5].strip() if len(r) > 5 else "",
                })
            return items
        except Exception as e:
            logger.error("Lỗi khi đọc công thức từ Google Sheets: %s", e)
            return []

    def save_sheet_shift_schedule(self, nickname: str, entry: dict) -> bool:
        """Lưu lịch ca đăng ký của nhân viên vào Google Sheets."""
        try:
            ws = self._get_or_create_custom_sheet(
                "LichCa",
                ["Nickname", "ViTri", "Tuan", "LichDangKyJson", "GhiChu", "CapNhatLuc"]
            )
            if not ws:
                return False
            nick_clean = nickname.strip()
            lock = getattr(self, "_write_lock", None)
            if lock is None:
                self._write_lock = threading.RLock()
            with self._write_lock:
                all_nicks = ws.col_values(1)
                row_idx = None
                for idx, n in enumerate(all_nicks, start=1):
                    if normalize_name(n) == normalize_name(nick_clean):
                        row_idx = idx
                        break
                slots_json = json.dumps(entry.get("slots") or {}, ensure_ascii=False)
                new_row = [
                    nick_clean,
                    str(entry.get("role") or ""),
                    str(entry.get("week_label") or ""),
                    slots_json,
                    str(entry.get("note") or ""),
                    str(entry.get("updated_at") or ""),
                ]
                if row_idx:
                    ws.update([new_row], range_name=f"A{row_idx}:F{row_idx}", value_input_option='USER_ENTERED')
                else:
                    ws.append_row(new_row, value_input_option='USER_ENTERED')
            return True
        except Exception as e:
            logger.error("Lỗi khi lưu lịch ca vào Google Sheets: %s", e)
            return False

    def load_sheet_shift_schedules(self) -> dict:
        """Tải toàn bộ lịch ca nhân viên đã đăng ký từ Google Sheets."""
        try:
            ws = self._get_or_create_custom_sheet(
                "LichCa",
                ["Nickname", "ViTri", "Tuan", "LichDangKyJson", "GhiChu", "CapNhatLuc"]
            )
            if not ws:
                return {}
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return {}
            schedules = {}
            for r in rows[1:]:
                if not r or not r[0].strip():
                    continue
                nick = r[0].strip()
                slots = {}
                if len(r) > 3 and r[3].strip():
                    try:
                        slots = json.loads(r[3].strip())
                    except Exception:
                        slots = {}
                schedules[nick] = {
                    "nickname": nick,
                    "role": r[1].strip() if len(r) > 1 else "Nhân viên",
                    "week_label": r[2].strip() if len(r) > 2 else "",
                    "slots": slots,
                    "note": r[4].strip() if len(r) > 4 else "",
                    "updated_at": r[5].strip() if len(r) > 5 else "",
                }
            return schedules
        except Exception as e:
            logger.error("Lỗi khi đọc lịch ca từ Google Sheets: %s", e)
            return {}

    def save_sheet_account(self, username: str, entry: dict) -> bool:
        """Lưu hoặc cập nhật mật khẩu tài khoản web trên Google Sheets."""
        try:
            ws = self._get_or_create_custom_sheet(
                "TaiKhoanWeb",
                ["Username", "PasswordHash", "Salt", "CapNhatLuc"]
            )
            if not ws:
                return False
            user_clean = username.strip()
            lock = getattr(self, "_write_lock", None)
            if lock is None:
                self._write_lock = threading.RLock()
            with self._write_lock:
                all_users = ws.col_values(1)
                row_idx = None
                for idx, u in enumerate(all_users, start=1):
                    if normalize_name(u) == normalize_name(user_clean):
                        row_idx = idx
                        break
                new_row = [
                    user_clean,
                    str(entry.get("password_hash") or ""),
                    str(entry.get("salt") or ""),
                    str(entry.get("updated_at") or local_now().strftime("%d/%m/%Y %H:%M:%S")),
                ]
                if row_idx:
                    ws.update([new_row], range_name=f"A{row_idx}:D{row_idx}", value_input_option='USER_ENTERED')
                else:
                    ws.append_row(new_row, value_input_option='USER_ENTERED')
            return True
        except Exception as e:
            logger.error("Lỗi khi lưu tài khoản web vào Google Sheets: %s", e)
            return False

    def load_sheet_accounts(self) -> dict:
        """Đọc danh sách tài khoản mật khẩu tùy chỉnh từ Google Sheets."""
        try:
            ws = self._get_or_create_custom_sheet(
                "TaiKhoanWeb",
                ["Username", "PasswordHash", "Salt", "CapNhatLuc"]
            )
            if not ws:
                return {}
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return {}
            accounts = {}
            for r in rows[1:]:
                if not r or not r[0].strip():
                    continue
                username = r[0].strip()
                norm = normalize_name(username)
                accounts[norm] = {
                    "username": username,
                    "password_hash": r[1].strip() if len(r) > 1 else "",
                    "salt": r[2].strip() if len(r) > 2 else "",
                    "updated_at": r[3].strip() if len(r) > 3 else "",
                }
            return accounts
        except Exception as e:
            logger.error("Lỗi khi đọc danh sách tài khoản từ Google Sheets: %s", e)
            return {}

    def sync_sheet_employee_roles(self, roles: dict) -> bool:
        """Lưu vai trò / vị trí nhân viên vào sheet ViTriNhanVienWeb."""
        try:
            ws = self._get_or_create_custom_sheet(
                "ViTriNhanVienWeb",
                ["NicknameKey", "Role", "CapNhatLuc"]
            )
            if not ws:
                return False
            now_str = local_now().strftime("%Y-%m-%d %H:%M:%S")
            rows = [["NicknameKey", "Role", "CapNhatLuc"]]
            for k, v in sorted(roles.items()):
                rows.append([str(k).strip(), str(v).strip(), now_str])
            lock = getattr(self, "_write_lock", None)
            if lock is None:
                self._write_lock = threading.RLock()
            with self._write_lock:
                ws.clear()
                ws.update("A1", rows, value_input_option="USER_ENTERED")
            return True
        except Exception as e:
            logger.error("Lỗi khi lưu vị trí nhân viên vào Google Sheets: %s", e)
            return False

    def load_sheet_employee_roles(self) -> dict:
        """Đọc vai trò / vị trí nhân viên từ sheet ViTriNhanVienWeb."""
        try:
            ws = self._get_or_create_custom_sheet(
                "ViTriNhanVienWeb",
                ["NicknameKey", "Role", "CapNhatLuc"]
            )
            if not ws:
                return {}
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return {}
            roles = {}
            for r in rows[1:]:
                if not r or not r[0].strip():
                    continue
                k = normalize_name(r[0].strip())
                role = r[1].strip() if len(r) > 1 and r[1].strip() else "Pha Chế"
                roles[k] = role
            return roles
        except Exception as e:
            logger.error("Lỗi khi đọc vị trí nhân viên từ Google Sheets: %s", e)
            return {}
