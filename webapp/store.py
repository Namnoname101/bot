import json
import logging
import os
import threading
import time
from pathlib import Path

from utils.time_utils import local_now

logger = logging.getLogger(__name__)

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
    """Lưu trữ dữ liệu mở rộng của Mini App (Đơn từ, Lịch ca, Chi vặt, Công thức, Checklist)."""

    def __init__(self, path: Path = STORE_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._data = {
            "leave_requests": [],     # Đơn xin đi muộn / nghỉ phép / đổi ca
            "shift_schedules": {},    # { "nickname": { "updated_at": ..., "week_label": ..., "slots": {...}, "note": "" } }
            "petty_expenses": [],     # Chi vặt tại quầy
            "recipes": list(DEFAULT_RECIPES),
            "checklists": dict(DEFAULT_CHECKLISTS),
        }
        self._load()

    def _load(self):
        with self._lock:
            try:
                if self.path.exists():
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        for k in ("leave_requests", "shift_schedules", "petty_expenses", "recipes", "checklists"):
                            if k in raw and raw[k]:
                                self._data[k] = raw[k]
            except Exception as e:
                logger.warning("Không đọc được webapp_store.json, dùng mặc định: %s", e)

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
            return item

    def delete_recipe(self, recipe_id: str) -> bool:
        with self._lock:
            recipes = list(self._data.get("recipes") or [])
            new_list = [r for r in recipes if r.get("id") != recipe_id]
            if len(new_list) == len(recipes):
                return False
            self._data["recipes"] = new_list
            self._save_unlocked()
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
            return item

    def get_leave_requests(self, nickname: str | None = None, limit: int = 30) -> list:
        with self._lock:
            reqs = list(self._data.get("leave_requests") or [])
            if nickname:
                low = nickname.strip().lower()
                reqs = [r for r in reqs if str(r.get("nickname", "")).strip().lower() == low]
            return reqs[:limit]

    def decide_leave_request(self, req_id: str, approve: bool) -> dict | None:
        with self._lock:
            reqs = list(self._data.get("leave_requests") or [])
            for r in reqs:
                if r.get("id") == req_id:
                    r["status"] = "approved" if approve else "rejected"
                    r["decided_at"] = local_now().strftime("%H:%M %d/%m/%Y")
                    self._save_unlocked()
                    return dict(r)
            return None

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
            return item

    def get_petty_expenses(self, limit: int = 30) -> list:
        with self._lock:
            return list(self._data.get("petty_expenses") or [])[:limit]
