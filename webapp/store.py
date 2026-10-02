import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path

from config import Config
from utils.admin import is_admin, is_super_admin
from utils.time_utils import local_now
from utils.validators import normalize_name

logger = logging.getLogger(__name__)

DEFAULT_PASSWORD = "123456789"


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Băm mật khẩu với salt ngẫu nhiên sử dụng SHA-256."""
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return hashed, salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    """Xác thực mật khẩu với hash và salt."""
    if not password or not hashed or not salt:
        return False
    calc = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return hmac.compare_digest(calc, hashed)

STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "webapp_store.json"

DEFAULT_CHECKLISTS = {
    "Pha Chế": [
        "Vệ sinh máy pha cà phê, xả họng pha & ngâm tay pha",
        "Kiểm tra hạn sử dụng sữa, kem béo & nguyên liệu trong tủ mát",
        "Đậy kín các hộp bột, trà, trân châu & сироp (syrup)",
        "Lau sạch mặt quầy bar, bồn rửa & đổ rác khu vực pha chế",
        "Kiểm tra tồn kho NVL cuối ca & tắt các thiết bị điện quầy bar",
    ],
    "Phục Vụ": [
        "Thu gom toàn bộ ly cốc, khay & rửa sạch/úp khô đúng vị trí",
        "Lau sạch toàn bộ bàn ghế, kệ trang trí & xếp gọn ghế",
        "Quét và lau sàn khu vực khách ngồi & lối đi",
        "Kiểm tra khu vực WC, bổ sung giấy/nước rửa tay & đổ rác",
        "Kiểm đếm tiền lẻ tại quầy, tắt điều hòa/quạt/đèn khi hết khách",
    ],
}

DEFAULT_RECIPES = [
    {
        "id": "rcp_bac_xiu",
        "group": "Cà Phê",
        "name": "Bạc Xỉu Sober",
        "size": "Size M (500ml)",
        "ingredients": "Sữa đặc: 35ml\nSữa tươi không đường: 80ml\nKem béo: 15ml\nEspresso / Cà phê phin: 30ml\nĐá bi đầy ly",
        "steps": "1. Khuấy đều sữa đặc + sữa tươi + kem béo ở đáy ly.\n2. Cho đá bi vào gần đầy ly.\n3. Đánh bọt nhẹ cà phê rồi rót lên trên cùng.",
    },
    {
        "id": "rcp_ca_phe_muoi",
        "group": "Cà Phê",
        "name": "Cà Phê Muối",
        "size": "Size M (500ml)",
        "ingredients": "Sữa đặc: 25ml\nCốt cà phê: 45ml\nKem muối (foam muối): 40ml\nBột cacao rắc mặt",
        "steps": "1. Đong sữa đặc dưới đáy ly, thêm đá.\n2. Rót cốt cà phê đã đánh bông nhẹ.\n3. Phủ lớp kem muối 40ml lên mặt và rắc nhẹ bột cacao.",
    },
    {
        "id": "rcp_matcha_latte",
        "group": "Matcha & Trà Sữa",
        "name": "Matcha Latte",
        "size": "Size M (500ml)",
        "ingredients": "Bột Matcha: 4g\nNước ấm (75°C): 35ml\nSữa tươi: 120ml\nSữa đặc / Đường nước: 20ml",
        "steps": "1. Dùng chổi chasen/máy đánh tan 4g bột matcha với 35ml nước ấm không vón cục.\n2. Khuấy sữa tươi + sữa đặc ở ly, thêm đá.\n3. Rót lớp matcha lên trên cùng tạo phân tầng.",
    },
    {
        "id": "rcp_tra_dao_cam_sa",
        "group": "Trà Trái Cây",
        "name": "Trà Đào Cam Sả",
        "size": "Size L (700ml)",
        "ingredients": "Cốt lục trà nhài: 150ml\nSyrup Đào: 25ml\nNước đường: 20ml\nNước cam tươi: 20ml\nĐào miếng: 3 lát, Sả cây + lát cam",
        "steps": "1. Cho cốt trà, syrup đào, nước đường, nước cam và đá vào bình lắc (shaker).\n2. Lắc đều tay 8-10 nhịp, đổ ra ly.\n3. Trang trí 3 miếng đào, lát cam và nhánh sả.",
    },
]


class WebAppStore:
    """Lưu trữ dữ liệu mở rộng của Mini App (Đơn từ, Lịch ca, Chi vặt, Công thức, Checklist) có đồng bộ Google Sheets."""

    def __init__(self, path: Path = STORE_PATH, sheets_service=None):
        self.path = path
        self.sheets = sheets_service
        self._lock = threading.Lock()
        self._data = {
            "leave_requests": [],     # Đơn xin đi muộn / nghỉ phép / đổi ca
            "shift_schedules": {},    # { "nickname": { "updated_at": ..., "week_label": ..., "slots": {...}, "note": "" } }
            "petty_expenses": [],     # Chi vặt tại quầy
            "recipes": list(DEFAULT_RECIPES),
            "checklists": dict(DEFAULT_CHECKLISTS),
            "accounts": {},           # { "username_norm": { "username": ..., "password_hash": ..., "salt": ..., "updated_at": ... } }
        }
        self._load()
        if self.sheets:
            self.init_from_sheets(self.sheets)

    def _load(self):
        with self._lock:
            try:
                if self.path.exists():
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        for k in ("leave_requests", "shift_schedules", "petty_expenses", "recipes", "checklists", "accounts"):
                            if k in raw and raw[k]:
                                self._data[k] = raw[k]
            except Exception as e:
                logger.warning("Không đọc được webapp_store.json, dùng mặc định: %s", e)

    def init_from_sheets(self, sheets_service):
        """Khởi tạo và kéo dữ liệu vĩnh viễn từ Google Sheets."""
        self.sheets = sheets_service
        def _bg_sync():
            try:
                # 1. Công thức
                if hasattr(self.sheets, "load_sheet_recipes"):
                    sheet_recipes = self.sheets.load_sheet_recipes()
                    if isinstance(sheet_recipes, list) and all(isinstance(x, dict) for x in sheet_recipes):
                        if sheet_recipes:
                            with self._lock:
                                self._data["recipes"] = sheet_recipes
                                self._save_unlocked()
                        else:
                            with self._lock:
                                cur_rcps = list(self._data.get("recipes") or DEFAULT_RECIPES)
                            self.sheets.sync_sheet_recipes(cur_rcps)

                # 2. Đơn xin phép
                if hasattr(self.sheets, "load_sheet_leave_requests"):
                    sheet_leaves = self.sheets.load_sheet_leave_requests(limit=100)
                    if isinstance(sheet_leaves, list) and all(isinstance(x, dict) for x in sheet_leaves):
                        if sheet_leaves:
                            with self._lock:
                                self._data["leave_requests"] = sheet_leaves
                                self._save_unlocked()

                # 3. Chi tiền lẻ
                if hasattr(self.sheets, "load_sheet_petty_expenses"):
                    sheet_exps = self.sheets.load_sheet_petty_expenses(limit=150)
                    if isinstance(sheet_exps, list) and all(isinstance(x, dict) for x in sheet_exps):
                        if sheet_exps:
                            with self._lock:
                                self._data["petty_expenses"] = sheet_exps
                                self._save_unlocked()

                # 4. Lịch ca
                if hasattr(self.sheets, "load_sheet_shift_schedules"):
                    sheet_sch = self.sheets.load_sheet_shift_schedules()
                    if isinstance(sheet_sch, dict) and all(isinstance(v, dict) for v in sheet_sch.values()):
                        if sheet_sch:
                            with self._lock:
                                self._data["shift_schedules"] = sheet_sch
                                self._save_unlocked()

                # 5. Tài khoản người dùng
                if hasattr(self.sheets, "load_sheet_accounts"):
                    sheet_accs = self.sheets.load_sheet_accounts()
                    if isinstance(sheet_accs, dict) and sheet_accs:
                        with self._lock:
                            self._data["accounts"] = sheet_accs
                            self._save_unlocked()

                logger.info("✅ Đã nạp dữ liệu WebApp từ Google Sheets thành công.")
            except Exception as e:
                logger.warning("Không thể nạp dữ liệu từ Google Sheets: %s", e)

        threading.Thread(target=_bg_sync, daemon=True).start()

    def _async_sheet_call(self, func, *args, **kwargs):
        if not self.sheets:
            return
        def _worker():
            try:
                func(*args, **kwargs)
            except Exception as e:
                logger.warning("Lỗi ghi Google Sheets bất đồng bộ: %s", e)
        threading.Thread(target=_worker, daemon=True).start()

    def _save_unlocked(self):
        try:
            os.makedirs(self.path.parent, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Không lưu được webapp_store.json: %s", e)

    # ── Checklists & Recipes ────────────────────────────────────────────────
    def get_checklists(self) -> dict:
        with self._lock:
            return dict(self._data.get("checklists") or DEFAULT_CHECKLISTS)

    def get_recipes(self) -> list:
        with self._lock:
            return list(self._data.get("recipes") or DEFAULT_RECIPES)

    def save_recipe(self, recipe: dict) -> dict:
        with self._lock:
            recipes = list(self._data.get("recipes") or [])
            rid = str(recipe.get("id") or "").strip() or f"rcp_{int(time.time() * 1000)}"
            item = {
                "id": rid,
                "group": str(recipe.get("group") or "Khác").strip() or "Khác",
                "name": str(recipe.get("name") or "").strip(),
                "size": str(recipe.get("size") or "Size M").strip() or "Size M",
                "ingredients": str(recipe.get("ingredients") or "").strip(),
                "steps": str(recipe.get("steps") or "").strip(),
            }
            updated = False
            for idx, existing in enumerate(recipes):
                if existing.get("id") == rid:
                    recipes[idx] = item
                    updated = True
                    break
            if not updated:
                recipes.append(item)
            self._data["recipes"] = recipes
            self._save_unlocked()

        if self.sheets and hasattr(self.sheets, "sync_sheet_recipes"):
            self._async_sheet_call(self.sheets.sync_sheet_recipes, list(self._data["recipes"]))
        return item

    def delete_recipe(self, recipe_id: str) -> bool:
        with self._lock:
            recipes = list(self._data.get("recipes") or [])
            new_list = [r for r in recipes if r.get("id") != recipe_id]
            if len(new_list) == len(recipes):
                return False
            self._data["recipes"] = new_list
            self._save_unlocked()

        if self.sheets and hasattr(self.sheets, "sync_sheet_recipes"):
            self._async_sheet_call(self.sheets.sync_sheet_recipes, list(self._data["recipes"]))
        return True

    # ── Leave / Late / Swap Requests ────────────────────────────────────────
    def add_leave_request(
        self,
        nickname: str,
        role: str,
        req_type: str,
        date_str: str,
        ca: str,
        reason: str,
        extra: str = "",
    ) -> dict:
        with self._lock:
            now_str = local_now().strftime("%H:%M %d/%m/%Y")
            item = {
                "id": f"lv_{int(time.time() * 1000)}",
                "nickname": nickname,
                "role": role or "Nhân viên",
                "type": req_type,  # 'late' | 'leave' | 'swap'
                "date": date_str,
                "ca": ca,
                "reason": reason,
                "extra": extra,
                "status": "pending",  # 'pending' | 'approved' | 'rejected'
                "created_at": now_str,
            }
            reqs = list(self._data.get("leave_requests") or [])
            reqs.insert(0, item)
            self._data["leave_requests"] = reqs[:100]
            self._save_unlocked()

        if self.sheets and hasattr(self.sheets, "append_sheet_leave_request"):
            self._async_sheet_call(self.sheets.append_sheet_leave_request, item)
        return item

    def get_leave_requests(self, nickname: str | None = None, limit: int = 30) -> list:
        with self._lock:
            reqs = list(self._data.get("leave_requests") or [])
            if nickname:
                low = nickname.strip().lower()
                reqs = [r for r in reqs if str(r.get("nickname", "")).strip().lower() == low]
            return reqs[:limit]

    def decide_leave_request(self, req_id: str, approve: bool) -> dict | None:
        decided_item = None
        with self._lock:
            reqs = list(self._data.get("leave_requests") or [])
            for r in reqs:
                if r.get("id") == req_id:
                    r["status"] = "approved" if approve else "rejected"
                    r["decided_at"] = local_now().strftime("%H:%M %d/%m/%Y")
                    decided_item = dict(r)
                    self._save_unlocked()
                    break

        if decided_item and self.sheets and hasattr(self.sheets, "update_sheet_leave_request_status"):
            self._async_sheet_call(
                self.sheets.update_sheet_leave_request_status,
                req_id,
                decided_item["status"],
                decided_item.get("decided_at", "")
            )
        return decided_item

    # ── Shift Schedule Registration ─────────────────────────────────────────
    def save_shift_schedule(
        self,
        nickname: str,
        role: str,
        slots: dict,
        note: str = "",
        week_label: str = "",
    ) -> dict:
        with self._lock:
            schedules = dict(self._data.get("shift_schedules") or {})
            entry = {
                "nickname": nickname,
                "role": role or "Nhân viên",
                "slots": slots,  # e.g. {"T2": ["Sáng", "Chiều"], "T3": ["Tối"], ...}
                "note": note,
                "week_label": week_label,
                "updated_at": local_now().strftime("%H:%M %d/%m/%Y"),
            }
            schedules[nickname.strip()] = entry
            self._data["shift_schedules"] = schedules
            self._save_unlocked()

        if self.sheets and hasattr(self.sheets, "save_sheet_shift_schedule"):
            self._async_sheet_call(self.sheets.save_sheet_shift_schedule, nickname, entry)
        return entry

    def get_shift_schedules(self) -> dict:
        with self._lock:
            return dict(self._data.get("shift_schedules") or {})

    # ── Petty Cash / Counter Expenses (Chi vặt tại quầy) ───────────────────
    def add_petty_expense(
        self,
        nickname: str,
        role: str,
        ca: str,
        amount: int,
        reason: str,
    ) -> dict:
        with self._lock:
            now = local_now()
            item = {
                "id": f"exp_{int(time.time() * 1000)}",
                "date": now.strftime("%d/%m/%Y"),
                "time": now.strftime("%H:%M"),
                "nickname": nickname,
                "role": role or "Nhân viên",
                "ca": ca,
                "amount": int(amount),
                "reason": reason,
            }
            exps = list(self._data.get("petty_expenses") or [])
            exps.insert(0, item)
            self._data["petty_expenses"] = exps[:150]
            self._save_unlocked()

        if self.sheets and hasattr(self.sheets, "append_sheet_petty_expense"):
            self._async_sheet_call(self.sheets.append_sheet_petty_expense, item)
        return item

    def get_petty_expenses(self, limit: int = 30) -> list:
        with self._lock:
            return list(self._data.get("petty_expenses") or [])[:limit]

    # ── Web Accounts & Authentication (Username / Pass mặc định 123456789) ──
    def get_account(self, username: str) -> dict | None:
        norm = normalize_name(username) if username else ""
        if not norm:
            return None
        with self._lock:
            return (self._data.get("accounts") or {}).get(norm)

    def set_account_password(self, username: str, new_password: str) -> bool:
        norm = normalize_name(username) if username else ""
        if not norm or not new_password:
            return False
        hashed, salt = hash_password(new_password)
        entry = {
            "username": username.strip(),
            "password_hash": hashed,
            "salt": salt,
            "updated_at": local_now().strftime("%d/%m/%Y %H:%M:%S"),
        }
        with self._lock:
            if "accounts" not in self._data:
                self._data["accounts"] = {}
            self._data["accounts"][norm] = entry
            self._save_unlocked()

        if self.sheets and hasattr(self.sheets, "save_sheet_account"):
            self._async_sheet_call(self.sheets.save_sheet_account, username.strip(), entry)
        return True

    def verify_login(
        self,
        username: str,
        password: str,
        employees: list,
        bot_data: dict | None = None,
        preferred_role: str = "Pha Chế",
    ) -> tuple[bool, dict | None, str]:
        """Xác thực đăng nhập theo Username và Mật khẩu (mặc định 123456789).

        Hỗ trợ:
        - Admin: username='admin' (hoặc admin chat id / quan ly), pass=123456789 hoặc WEBAPP_ADMIN_PIN.
        - Nhân viên: username là nickname/tên nhân viên, pass=123456789 (hoặc mật khẩu tùy chỉnh).
        """
        user_raw = (username or "").strip()
        pwd_raw = str(password or "").strip()
        user_norm = normalize_name(user_raw)

        if not user_raw or not user_norm:
            return False, None, "Vui lòng nhập Tên đăng nhập."
        if not pwd_raw:
            return False, None, "Vui lòng nhập Mật khẩu (mặc định: 123456789)."

        context_stub = type("ContextStub", (), {"bot_data": bot_data or {}})()

        # 1. Kiểm tra tài khoản Quản lý (Admin)
        is_admin_user = (
            user_norm in ("admin", "quanly", "chuquan")
            or (user_raw.isdigit() and int(user_raw) == Config.ADMIN_CHAT_ID)
        )
        if is_admin_user:
            acc = self.get_account("admin")
            valid_pass = False
            if acc and acc.get("password_hash") and acc.get("salt"):
                valid_pass = verify_password(pwd_raw, acc["password_hash"], acc["salt"])
            else:
                dyn_pin = str((bot_data or {}).get("webapp_admin_pin") or "").strip()
                valid_pass = (
                    pwd_raw == DEFAULT_PASSWORD
                    or (bool(Config.WEBAPP_ADMIN_PIN) and pwd_raw == Config.WEBAPP_ADMIN_PIN)
                    or (bool(dyn_pin) and pwd_raw == dyn_pin)
                    or pwd_raw == str(Config.ADMIN_CHAT_ID)
                )

            if not valid_pass:
                return False, None, "Mật khẩu Quản lý không đúng. Mật khẩu mặc định: 123456789."

            user_info = {
                "id": Config.ADMIN_CHAT_ID,
                "username": "admin",
                "nickname": "Quản lý",
                "full_name": "Quản lý (Admin)",
                "is_admin": True,
                "is_super_admin": True,
                "role": "Quản Lý",
                "authenticated": True,
            }
            return True, user_info, ""

        # 2. Kiểm tra tài khoản Nhân viên từ danh sách nhân sự
        matched_emp = None
        for emp in (employees or []):
            emp_nick = str(emp.get("nickname") or emp.get("full_name") or "")
            if normalize_name(emp_nick) == user_norm:
                matched_emp = emp
                break

        if not matched_emp:
            return False, None, f"Không tìm thấy tài khoản '{user_raw}'. Vui lòng nhập đúng tên nhân viên hoặc 'admin'."

        nick = str(matched_emp.get("nickname") or matched_emp.get("full_name") or user_raw).strip()
        emp_acc = self.get_account(user_norm)
        valid_pass = False
        if emp_acc and emp_acc.get("password_hash") and emp_acc.get("salt"):
            valid_pass = verify_password(pwd_raw, emp_acc["password_hash"], emp_acc["salt"])
        else:
            valid_pass = (pwd_raw == DEFAULT_PASSWORD)

        if not valid_pass:
            return False, None, "Mật khẩu không đúng. Mật khẩu mặc định: 123456789."

        emp_uid = int(matched_emp.get("id") or 0)
        is_adm = is_admin(emp_uid, context_stub) if emp_uid else False

        assigned_role = preferred_role if preferred_role in ("Pha Chế", "Phục Vụ") else "Pha Chế"
        user_info = {
            "id": emp_uid,
            "username": nick,
            "nickname": nick,
            "full_name": matched_emp.get("full_name") or nick,
            "is_admin": is_adm,
            "is_super_admin": False,
            "role": assigned_role,
            "authenticated": True,
        }
        return True, user_info, ""
