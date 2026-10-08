import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

from aiohttp.test_utils import TestClient, TestServer
from aiohttp import FormData

from config import Config
from handlers.reward_handler import open_mini_app_command
from webapp.auth import validate_telegram_init_data
from webapp.server import create_webapp
from webapp.store import WebAppStore


def build_signed_init_data(user_dict: dict, bot_token: str | None = None, auth_date: int | None = None) -> str:
    token = (bot_token or Config.BOT_TOKEN or "123456:TEST_TOKEN").strip()
    ts = int(auth_date if auth_date is not None else time.time())
    params = {
        "auth_date": str(ts),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(user_dict, ensure_ascii=False, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    sig = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    params["hash"] = sig
    return urlencode(params)


class WebAppAuthTests(unittest.TestCase):
    def test_valid_and_tampered_init_data(self):
        user = {"id": 111222, "first_name": "Tuấn", "last_name": "Anh", "username": "tuananh"}
        init_data = build_signed_init_data(user)
        verified = validate_telegram_init_data(init_data)
        self.assertIsNotNone(verified)
        self.assertEqual(verified["user"]["id"], 111222)

        tampered = init_data.replace("111222", "999999")
        self.assertIsNone(validate_telegram_init_data(tampered))

    def test_expired_init_data_rejected(self):
        user = {"id": 111222, "first_name": "An"}
        old_ts = int(time.time()) - 90000
        init_data = build_signed_init_data(user, auth_date=old_ts)
        self.assertIsNone(validate_telegram_init_data(init_data, max_age_seconds=3600))


class WebAppServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sheets = MagicMock()
        self.sheets.get_employees_detail.return_value = [
            {"nickname": "An", "key": "an", "full_name": "Nguyễn An", "rate": 18.0, "balance": 2},
            {"nickname": "Bình", "key": "binh", "full_name": "Trần Bình", "rate": 16.0, "balance": 0},
        ]
        self.sheets.get_all_nicknames.return_value = ["an", "binh"]
        self.sheets.get_open_checkin_sessions.return_value = [
            {"date": "28/09/2026", "nickname": "An", "checkin_time": "06:30:00", "shift_type": "Ca Chính", "ca": "Sáng", "note": "Đúng giờ"}
        ]
        self.sheets.get_material_groups.return_value = ["Chế phẩm từ sữa", "Trà"]
        self.sheets.get_all_materials.return_value = [
            {"group": "Chế phẩm từ sữa", "name": "Sữa tươi", "unit": "hộp", "stock": 10.0, "min_stock": 3.0, "price": 30000},
            {"group": "Trà", "name": "Matcha", "unit": "kg", "stock": 1.0, "min_stock": 2.0, "price": 250000},
        ]
        self.sheets._current_salary_month.return_value = (9, 2026)

        self.bot = SimpleNamespace(
            send_message=AsyncMock(),
            send_photo=AsyncMock(),
            send_media_group=AsyncMock(),
            get_me=AsyncMock(return_value=SimpleNamespace(username="sober_test_bot")),
        )
        self.bot_data = {"admin_ids": {777888}, "reward_requests": {}, "processed_reports": set()}
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.store = WebAppStore(path=Path(self._tmp_dir.name) / "store.json")

        self.app = create_webapp(self.sheets, bot=self.bot, bot_data=self.bot_data, store=self.store)
        self.server = TestServer(self.app)
        self.client = TestClient(self.server)
        await self.client.start_server()

        self.emp_headers = {
            "X-Telegram-Init-Data": build_signed_init_data({"id": 555666, "first_name": "An"})
        }
        self.kiosk_headers = {
            **self.emp_headers,
            "X-Shop-Device-Key": Config.get_shop_kiosk_key(),
        }
        self.sub_admin_headers = {
            "X-Telegram-Init-Data": build_signed_init_data({"id": 777888, "first_name": "Quản Lý Phụ"})
        }
        self.super_admin_headers = {
            "X-Telegram-Init-Data": build_signed_init_data({"id": Config.ADMIN_CHAT_ID, "first_name": "Chủ Quán"})
        }

    async def asyncTearDown(self):
        await self.client.close()
        self._tmp_dir.cleanup()

    async def test_static_and_health_endpoints(self):
        resp = await self.client.get("/api/health")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["status"], "ok")

        idx_resp = await self.client.get("/")
        self.assertEqual(idx_resp.status, 200)
        html = await idx_resp.text()
        self.assertIn("SOBER MINI APP", html)

    async def test_unauthorized_api_call_blocked(self):
        with patch.object(Config, "WEBAPP_DEV_MODE", False), patch.object(Config, "WEBAPP_ALLOW_BROWSER", False):
            resp = await self.client.get("/api/bootstrap")
            self.assertEqual(resp.status, 401)

        # When WEBAPP_ALLOW_BROWSER is True, browser gets employee role by default
        with patch.object(Config, "WEBAPP_DEV_MODE", False), patch.object(Config, "WEBAPP_ALLOW_BROWSER", True):
            emp_resp = await self.client.get("/api/bootstrap")
            self.assertEqual(emp_resp.status, 200)
            emp_data = await emp_resp.json()
            self.assertFalse(emp_data["user"]["is_admin"])

            # Raw ADMIN_CHAT_ID as admin_key should NOT grant admin (security fix)
            raw_id_resp = await self.client.get(
                "/api/bootstrap",
                headers={"X-Admin-Key": str(Config.ADMIN_CHAT_ID)},
            )
            raw_id_data = await raw_id_resp.json()
            self.assertFalse(raw_id_data["user"]["is_admin"], "Raw user ID must not grant admin access")

            # WEBAPP_ADMIN_PIN as admin_key SHOULD grant admin
            with patch.object(Config, "WEBAPP_ADMIN_PIN", "secret-pin-2026"):
                adm_resp = await self.client.get(
                    "/api/bootstrap",
                    headers={"X-Admin-Key": "secret-pin-2026"},
                )
                self.assertEqual(adm_resp.status, 200)
                adm_data = await adm_resp.json()
                self.assertTrue(adm_data["user"]["is_admin"])
                self.assertTrue(adm_data["user"]["is_super_admin"])

    async def test_bootstrap_returns_roles_and_data(self):
        resp = await self.client.get("/api/bootstrap", headers=self.emp_headers)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertFalse(data["user"]["is_admin"])
        self.assertEqual(len(data["employees"]), 2)

        adm_resp = await self.client.get("/api/bootstrap", headers=self.super_admin_headers)
        adm_data = await adm_resp.json()
        self.assertTrue(adm_data["user"]["is_admin"])
        self.assertTrue(adm_data["user"]["is_super_admin"])

    async def test_checkin_and_checkout_flow(self):
        # 1. Bị chặn 403 nếu check-in trên thiết bị cá nhân (thiếu key kiosk quán)
        blocked_resp = await self.client.post(
            "/api/checkin",
            json={"nickname": "An", "shift_type": "Ca Chính", "ca": "Sáng"},
            headers=self.emp_headers,
        )
        self.assertEqual(blocked_resp.status, 403)

        self.sheets.checkin.return_value = {
            "success": True,
            "time": "06:45:00",
            "actual_time": "06:45:00",
            "note": "Ca Chính - Đi muộn 15p - Ca Sáng",
            "late_minutes": 15,
            "early_minutes": 0,
            "ca": "Sáng",
            "date_str": "28/09/2026",
        }
        # 2. Thành công 200 khi gửi từ máy quán
        resp = await self.client.post(
            "/api/checkin",
            json={"nickname": "An", "shift_type": "Ca Chính", "ca": "Sáng"},
            headers=self.kiosk_headers,
        )
        self.assertEqual(resp.status, 200)
        # 2 messages to admin (late info + late buttons) + 1 message to group
        self.assertEqual(self.bot.send_message.await_count, 3)

        self.sheets.checkout.return_value = {
            "success": True,
            "time": "12:00:00",
            "total_hours": "5,2",
            "checkin_time": "06:45:00",
            "is_ca_gay": False,
        }
        co_resp = await self.client.post(
            "/api/checkout",
            json={"nickname": "An", "shift_type": "Ca Chính"},
            headers=self.kiosk_headers,
        )
        self.assertEqual(co_resp.status, 200)

    async def test_inventory_smart_parse_and_export(self):
        parse_resp = await self.client.post(
            "/api/inventory/smart-parse",
            json={"text": "2 sua tuoi, 0.5 matcha"},
            headers=self.emp_headers,
        )
        self.assertEqual(parse_resp.status, 200)
        parsed = await parse_resp.json()
        self.assertEqual(len(parsed["confirmed"]), 2)

        self.sheets.batch_export_stock.return_value = {
            "success": True,
            "exported": [{"name": "Sữa tươi", "qty": 2, "new_stock": 8, "unit": "hộp"}],
            "low_stock_alerts": [{"name": "Matcha", "new_stock": 0.5, "min_stock": 2.0, "unit": "kg"}],
            "errors": [],
        }
        exp_resp = await self.client.post(
            "/api/inventory/export",
            json={"items": [{"name": "Sữa tươi", "qty": 2}], "actor_name": "An"},
            headers=self.emp_headers,
        )
        self.assertEqual(exp_resp.status, 200)
        # Group export log + Admin low stock alert
        self.assertGreaterEqual(self.bot.send_message.await_count, 2)

    async def test_rewards_revenue_endshift_and_feedback(self):
        # 1. Use reward
        self.sheets.consume_reward.return_value = {"success": True, "balance": 1}
        use_resp = await self.client.post(
            "/api/rewards/use",
            json={"nickname": "An"},
            headers=self.emp_headers,
        )
        self.assertEqual(use_resp.status, 200)

        # 2. Employee reward request -> creates pending request
        req_resp = await self.client.post(
            "/api/rewards/request",
            json={"employees": ["An", "Bình"], "ca": "Sáng"},
            headers=self.emp_headers,
        )
        self.assertEqual(req_resp.status, 200)
        req_data = await req_resp.json()
        self.assertFalse(req_data["approved"])
        self.assertEqual(len(self.bot_data["reward_requests"]), 1)

        # 3. Revenue report (multipart with photo)
        self.sheets.save_report.return_value = True
        self.sheets.batch_update_balances.return_value = True
        fd = FormData()
        fd.add_field("employees", json.dumps(["An", "Bình"]))
        fd.add_field("revenue", "1.5M")
        fd.add_field("ca", "Sáng")
        fd.add_field("photo", b"fake-jpeg-bytes", filename="bill.jpg", content_type="image/jpeg")

        rev_resp = await self.client.post("/api/reports/revenue", data=fd, headers=self.emp_headers)
        self.assertEqual(rev_resp.status, 200)
        self.bot.send_photo.assert_awaited_once()

        # 4. Endshift upload (multiple photos)
        ks_fd = FormData()
        ks_fd.add_field("ca", "Tối")
        ks_fd.add_field("role", "Pha Chế")
        ks_fd.add_field("photos", b"img1", filename="1.jpg", content_type="image/jpeg")
        ks_fd.add_field("photos", b"img2", filename="2.jpg", content_type="image/jpeg")
        ks_resp = await self.client.post("/api/endshift/upload", data=ks_fd, headers=self.emp_headers)
        self.assertEqual(ks_resp.status, 200)
        self.bot.send_media_group.assert_awaited_once()

        # 5. Anonymous feedback
        fb_resp = await self.client.post(
            "/api/feedback",
            json={"message": "Quán cần mua thêm đá viên"},
            headers=self.emp_headers,
        )
        self.assertEqual(fb_resp.status, 200)

    async def test_admin_permissions_and_endpoints(self):
        # Regular employee blocked from admin overview
        forbidden = await self.client.get("/api/admin/overview", headers=self.emp_headers)
        self.assertEqual(forbidden.status, 403)

        # Admin allowed
        self.sheets.get_checkin_history_today.return_value = []
        self.sheets.get_late_statistics.return_value = []
        self.sheets.get_recent_revenue_reports.return_value = []
        self.sheets.get_overtime_summary.return_value = {"An": 2.0}

        ok_resp = await self.client.get("/api/admin/overview", headers=self.sub_admin_headers)
        self.assertEqual(ok_resp.status, 200)

        # Secondary admin blocked from granting admin
        grant_forbid = await self.client.post(
            "/api/admin/grant-admin",
            json={"telegram_id": 999888},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(grant_forbid.status, 403)

        # Super admin allowed to grant admin
        self.sheets.add_admin.return_value = True
        grant_ok = await self.client.post(
            "/api/admin/grant-admin",
            json={"telegram_id": 999888},
            headers=self.super_admin_headers,
        )
        self.assertEqual(grant_ok.status, 200)
        self.assertIn(999888, self.bot_data["admin_ids"])

    async def test_admin_crud_and_inventory_management_endpoints(self):
        # 1. Salary sheet & modifier
        self.sheets.get_salary_month_options.return_value = [
            {"label": "Tháng 9/2026", "month": 9, "year": 2026}
        ]
        self.sheets.get_salary_data.return_value = {
            "success": True,
            "month": 9,
            "year": 2026,
            "rows": [{"nickname": "An", "total_hours": 100.0, "net_salary": 1800000}],
            "total_payroll": 1800000,
        }
        sal_resp = await self.client.get("/api/admin/salary?month=9&year=2026", headers=self.sub_admin_headers)
        self.assertEqual(sal_resp.status, 200)
        sal_data = await sal_resp.json()
        self.assertEqual(sal_data["salary"]["total_payroll"], 1800000)

        self.sheets.update_salary_modifier.return_value = True
        mod_resp = await self.client.post(
            "/api/admin/salary/modifier",
            json={"nickname": "An", "type": "bonus", "amount": "50k", "month": 9, "year": 2026},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(mod_resp.status, 200)

        # 2. Overtime add
        self.sheets.add_overtime.return_value = True
        self.sheets.get_overtime_summary.return_value = {"An": 2.5}
        ot_resp = await self.client.post(
            "/api/admin/overtime/add",
            json={"nickname": "An", "hours": 2.5},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(ot_resp.status, 200)

        # 3. Employee CRUD + reward history
        self.sheets.add_employee.return_value = {"success": True}
        emp_add = await self.client.post(
            "/api/admin/employee/add",
            json={"nickname": "Chi"},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(emp_add.status, 200)

        self.sheets.rename_employee.return_value = {"success": True}
        emp_ren = await self.client.post(
            "/api/admin/employee/rename",
            json={"old_nickname": "Chi", "new_nickname": "Chi Le"},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(emp_ren.status, 200)

        self.sheets.update_salary_rate.return_value = True
        emp_rate = await self.client.post(
            "/api/admin/employee/salary-rate",
            json={"nickname": "An", "rate": 19.0},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(emp_rate.status, 200)

        self.sheets.remove_employee.return_value = True
        emp_del = await self.client.post(
            "/api/admin/employee/remove",
            json={"nickname": "Bình"},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(emp_del.status, 200)

        self.sheets.get_reward_history.return_value = [{"date": "28/09/2026", "ca": "Sáng", "revenue": "1,500,000"}]
        rew_hist = await self.client.get(
            "/api/admin/employee/reward-history?nickname=An",
            headers=self.sub_admin_headers,
        )
        self.assertEqual(rew_hist.status, 200)

        # 4. Revenue update & Late mark
        self.sheets.update_report_revenue.return_value = True
        self.sheets.get_recent_revenue_reports.return_value = []
        rev_upd = await self.client.post(
            "/api/admin/report/update-revenue",
            json={"session": {"date": "28/09/2026", "ca": "Sáng", "rows": [5]}, "new_revenue": "1.5M"},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(rev_upd.status, 200)

        self.sheets.mark_reported_late.return_value = True
        late_resp = await self.client.post(
            "/api/admin/late/mark",
            json={"date": "28/09/2026", "nickname": "An", "reported": True},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(late_resp.status, 200)

        # 5. Pending reward approve/reject
        self.bot_data["reward_requests"]["999"] = {
            "ca": "Sáng",
            "employees": ["An"],
            "requester_name": "An",
            "created_at": "08:00 28/09/2026",
        }
        self.sheets.batch_update_balances.return_value = True
        rew_dec = await self.client.post(
            "/api/admin/rewards/decide",
            json={"request_id": "999", "approve": True},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(rew_dec.status, 200)
        self.assertNotIn("999", self.bot_data["reward_requests"])

        # 6. Announce to group
        ann_resp = await self.client.post(
            "/api/admin/announce",
            json={"message": "Họp quán lúc 17h chiều nay"},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(ann_resp.status, 200)

        # 7. Inventory management (import, add, update, delete)
        self.sheets.import_stock.return_value = True
        imp_resp = await self.client.post(
            "/api/inventory/import",
            json={"name": "Sữa tươi", "qty": 5, "note": "Nhập thêm"},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(imp_resp.status, 200)

        self.sheets.add_material.return_value = {"success": True}
        mat_add = await self.client.post(
            "/api/inventory/material/add",
            json={"group": "Trà", "name": "Hồng trà", "unit": "kg", "min_stock": 1, "price": 180000},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(mat_add.status, 200)

        self.sheets.update_material.return_value = True
        mat_upd = await self.client.post(
            "/api/inventory/material/update",
            json={"name": "Sữa tươi", "price": "32000", "min_stock": "4"},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(mat_upd.status, 200)

        self.sheets.remove_material.return_value = True
        mat_del = await self.client.post(
            "/api/inventory/material/delete",
            json={"name": "Matcha"},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(mat_del.status, 200)

    async def test_personal_schedule_leave_expenses_and_recipes(self):
        # 1. Personal summary
        self.sheets.get_employee_personal_summary.return_value = {
            "success": True,
            "nickname": "An",
            "month": 9,
            "year": 2026,
            "period": "17/08/2026 → 16/09/2026",
            "regular_hours": 40.0,
            "overtime_hours": 2.0,
            "total_hours": 42.0,
            "rate": 18.0,
            "estimated_pay_k": 756.0,
            "balance": 2,
            "late_count": 0,
            "recent_checkins": [],
        }
        p_resp = await self.client.get("/api/personal/summary?nickname=An", headers=self.emp_headers)
        self.assertEqual(p_resp.status, 200)
        p_data = await p_resp.json()
        self.assertEqual(p_data["summary"]["total_hours"], 42.0)

        # 2. Leave / Late request & Admin decision
        lv_resp = await self.client.post(
            "/api/requests/leave",
            json={
                "nickname": "An",
                "role": "Pha Chế",
                "type": "late",
                "date": "28/09/2026",
                "ca": "Sáng",
                "extra": "15 phút",
                "reason": "Kẹt xe cầu vượt",
            },
            headers=self.emp_headers,
        )
        self.assertEqual(lv_resp.status, 200)
        lv_data = await lv_resp.json()
        req_id = lv_data["item"]["id"]

        self.sheets.mark_reported_late.return_value = True
        dec_resp = await self.client.post(
            "/api/admin/requests/leave-decide",
            json={"id": req_id, "approve": True},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(dec_resp.status, 200)

        # 3. Shift schedule registration
        sch_resp = await self.client.post(
            "/api/schedule/register",
            json={
                "nickname": "An",
                "role": "Pha Chế",
                "slots": {"T2": ["Sáng", "Chiều"], "T4": ["Tối"]},
                "note": "Thứ 6 bận học",
            },
            headers=self.emp_headers,
        )
        self.assertEqual(sch_resp.status, 200)

        # 4. Counter petty expense
        exp_resp = await self.client.post(
            "/api/expenses/add",
            json={"nickname": "Bình", "role": "Phục Vụ", "ca": "Chiều", "amount": "35k", "reason": "Mua 2 bao đá viên"},
            headers=self.emp_headers,
        )
        self.assertEqual(exp_resp.status, 200)

        # 5. Recipe CRUD (Admin)
        rcp_save = await self.client.post(
            "/api/admin/recipes/save",
            json={"name": "Trà Sữa Ô Long", "group": "Trà Sữa", "size": "Size M", "ingredients": "Trà: 120ml\nSữa: 30ml"},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(rcp_save.status, 200)
        rcp_data = await rcp_save.json()
        new_rcp = next(x for x in rcp_data["recipes"] if x["name"] == "Trà Sữa Ô Long")

        rcp_del = await self.client.post(
            "/api/admin/recipes/delete",
            json={"id": new_rcp["id"]},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(rcp_del.status, 200)

    async def test_username_password_auth_flow(self):
        # 1. Đăng nhập nhân viên thành công với mật khẩu mặc định 123456789
        emp_login = await self.client.post(
            "/api/auth/login",
            json={"username": "An", "password": "123456789", "role": "Pha Chế"},
        )
        self.assertEqual(emp_login.status, 200)
        emp_data = await emp_login.json()
        self.assertTrue(emp_data["success"])
        token = emp_data.get("token")
        self.assertTrue(bool(token))
        self.assertEqual(emp_data["user"]["nickname"], "An")
        self.assertEqual(emp_data["role"], "Pha Chế")
        self.assertTrue(emp_data.get("must_change_password"))
        self.assertIn("warning", emp_data)

        # 2. Dùng token xác thực qua header X-Auth-Token
        bs_resp = await self.client.get("/api/bootstrap", headers={"X-Auth-Token": token})
        self.assertEqual(bs_resp.status, 200)
        bs_data = await bs_resp.json()
        self.assertEqual(bs_data["user"]["nickname"], "An")

        # 3. Đăng nhập Admin với mật khẩu mặc định 123456789
        admin_login = await self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "123456789"},
        )
        self.assertEqual(admin_login.status, 200)
        adm_data = await admin_login.json()
        self.assertTrue(adm_data["user"]["is_admin"])
        self.assertTrue(adm_data.get("must_change_password"))

        # 4. Đăng nhập sai mật khẩu -> 401
        wrong_pwd = await self.client.post(
            "/api/auth/login",
            json={"username": "An", "password": "WrongPassword!"},
        )
        self.assertEqual(wrong_pwd.status, 401)

        # 5. Đăng nhập sai username -> 401
        unknown_user = await self.client.post(
            "/api/auth/login",
            json={"username": "KhongTonTai", "password": "123456789"},
        )
        self.assertEqual(unknown_user.status, 401)

        # 6. Đổi mật khẩu và đăng nhập lại
        change_pwd = await self.client.post(
            "/api/auth/change-password",
            json={"old_password": "123456789", "new_password": "newSecretPassword2026"},
            headers={"X-Auth-Token": token},
        )
        self.assertEqual(change_pwd.status, 200)

        # Mật khẩu cũ 123456789 không còn hợp lệ
        old_login = await self.client.post(
            "/api/auth/login",
            json={"username": "An", "password": "123456789"},
        )
        self.assertEqual(old_login.status, 401)

        # Mật khẩu mới hoạt động bình thường và không còn cảnh báo đổi mật khẩu
        new_login = await self.client.post(
            "/api/auth/login",
            json={"username": "An", "password": "newSecretPassword2026"},
        )
        self.assertEqual(new_login.status, 200)
        new_data = await new_login.json()
        self.assertFalse(new_data.get("must_change_password"))

        # 7. Admin thêm nhân viên mới -> Tự động có trên danh sách public và đăng nhập được ngay bằng pass mặc định 123456789
        self.sheets.add_employee.return_value = {"success": True}
        self.sheets.get_employees_detail.return_value = [
            {"nickname": "An", "key": "an", "full_name": "Nguyễn An", "rate": 18.0, "balance": 2},
            {"nickname": "Bình", "key": "binh", "full_name": "Trần Bình", "rate": 16.0, "balance": 0},
            {"nickname": "Hương", "key": "huong", "full_name": "Lê Hương", "rate": 18.0, "balance": 0},
        ]
        add_emp_resp = await self.client.post(
            "/api/admin/employee/add",
            json={"nickname": "Hương"},
            headers=self.sub_admin_headers,
        )
        self.assertEqual(add_emp_resp.status, 200)

        # Kiểm tra danh sách public users có nhân viên mới "Hương"
        pub_users = await self.client.get("/api/auth/public-users")
        self.assertEqual(pub_users.status, 200)
        pub_data = await pub_users.json()
        self.assertIn("Hương", pub_data["users"])
        self.assertTrue(any(e["nickname"] == "Hương" for e in pub_data["employees"]))

        # Nhân viên mới "Hương" đăng nhập ngay bằng mật khẩu mặc định 123456789
        huong_login = await self.client.post(
            "/api/auth/login",
            json={"username": "Hương", "password": "123456789", "role": "Phục Vụ"},
        )
        self.assertEqual(huong_login.status, 200)
        huong_data = await huong_login.json()
        self.assertTrue(huong_data["success"])
        self.assertEqual(huong_data["user"]["nickname"], "Hương")
        self.assertEqual(huong_data["role"], "Phục Vụ")

        # 8. Kiểm tra Rate Limiting: thử sai liên tục 5 lần -> lần 6 bị 429 Too Many Requests
        for _ in range(5):
            await self.client.post(
                "/api/auth/login",
                json={"username": "HackerTarget", "password": "BadPassword"},
                headers={"X-Forwarded-For": "192.168.1.99"},
            )
        rate_blocked = await self.client.post(
            "/api/auth/login",
            json={"username": "HackerTarget", "password": "BadPassword"},
            headers={"X-Forwarded-For": "192.168.1.99"},
        )
        self.assertEqual(rate_blocked.status, 429)
        block_data = await rate_blocked.json()
        self.assertEqual(block_data.get("error"), "rate_limited")

    async def test_reward_ownership_access_control(self):
        an_headers = {
            "X-Telegram-Init-Data": build_signed_init_data({"id": 1001, "first_name": "An"})
        }
        binh_headers = {
            "X-Telegram-Init-Data": build_signed_init_data({"id": 1002, "first_name": "Bình"})
        }

        # 1. Non-admin "Bình" cannot view other employee balances in bootstrap
        boot_resp = await self.client.get("/api/bootstrap", headers=binh_headers)
        self.assertEqual(boot_resp.status, 200)
        boot_data = await boot_resp.json()
        for emp in boot_data["employees"]:
            if emp["nickname"] == "An":
                self.assertIsNone(emp.get("balance"), "Other employee's balance must be hidden from non-admin")
            elif emp["nickname"] == "Bình":
                self.assertIsNotNone(emp.get("balance"), "Own balance must be visible")

        # 2. Admin CAN see all balances in bootstrap
        admin_boot_resp = await self.client.get("/api/bootstrap", headers=self.super_admin_headers)
        self.assertEqual(admin_boot_resp.status, 200)
        admin_boot_data = await admin_boot_resp.json()
        an_emp = next(e for e in admin_boot_data["employees"] if e["nickname"] == "An")
        self.assertEqual(an_emp.get("balance"), 2)

        # 3. Non-admin "Bình" trying to consume "An"'s reward -> 403 Forbidden
        use_other = await self.client.post(
            "/api/rewards/use",
            json={"nickname": "An"},
            headers=binh_headers,
        )
        self.assertEqual(use_other.status, 403)
        res_data = await use_other.json()
        self.assertFalse(res_data["success"])

        # 4. Non-admin "An" consuming "An"'s own reward -> 200 OK
        self.sheets.consume_reward.return_value = {"success": True, "balance": 1}
        use_own = await self.client.post(
            "/api/rewards/use",
            json={"nickname": "An"},
            headers=an_headers,
        )
        self.assertEqual(use_own.status, 200)

        # 5. Admin consuming "An"'s reward (support/admin on behalf) -> 200 OK
        use_admin = await self.client.post(
            "/api/rewards/use",
            json={"nickname": "An"},
            headers=self.super_admin_headers,
        )
        self.assertEqual(use_admin.status, 200)

    async def test_open_mini_app_bot_command(self):
        msg = SimpleNamespace(message_id=10, reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=123, type="private"),
            effective_user=SimpleNamespace(id=123),
            message=msg,
        )
        context = SimpleNamespace(bot_data={}, chat_data={}, bot=self.bot)
        with patch.object(Config, "WEBAPP_URL", "https://sober-bot.fly.dev"):
            await open_mini_app_command(update, context)
        msg.reply_text.assert_awaited_once()
        kwargs = msg.reply_text.await_args.kwargs
    async def test_employee_reward_request_and_admin_workflow(self):
        # 1. Reset bot mock
        self.bot.send_message.reset_mock()
        self.sheets.batch_update_balances.return_value = True

        # 2. Employee sends reward request
        req_resp = await self.client.post(
            "/api/rewards/request",
            json={"employees": ["An", "Bình"], "ca": "Sáng"},
            headers=self.emp_headers,
        )
        self.assertEqual(req_resp.status, 200)
        req_data = await req_resp.json()
        self.assertTrue(req_data["success"])
        self.assertFalse(req_data["approved"])
        self.assertIn("request_id", req_data)
        req_id = req_data["request_id"]

        # 3. Check Telegram alert sent to admin with inline approval keyboard
        self.assertGreaterEqual(self.bot.send_message.await_count, 1)
        admin_call = None
        for call_item in self.bot.send_message.await_args_list:
            if call_item.kwargs.get("chat_id") == Config.ADMIN_CHAT_ID:
                admin_call = call_item
                break
        self.assertIsNotNone(admin_call, "Admin must receive Telegram notification")
        self.assertIn("YÊU CẦU CỘNG THƯỞNG", admin_call.kwargs.get("text", ""))
        self.assertIsNotNone(admin_call.kwargs.get("reply_markup"))

        # 4. Check Admin Overview receives pending request
        self.sheets.get_checkin_history_today.return_value = []
        self.sheets.get_late_statistics.return_value = []
        self.sheets.get_recent_revenue_reports.return_value = []
        self.sheets.get_overtime_summary.return_value = {}
        ov_resp = await self.client.get("/api/admin/overview", headers=self.super_admin_headers)
        self.assertEqual(ov_resp.status, 200)
        ov_data = await ov_resp.json()
        pending = ov_data.get("pending_rewards", [])
        self.assertTrue(any(p.get("id") == req_id for p in pending))

        # 5. Admin approves reward via WebApp
        decide_resp = await self.client.post(
            "/api/admin/rewards/decide",
            json={"request_id": req_id, "approve": True},
            headers=self.super_admin_headers,
        )
        self.assertEqual(decide_resp.status, 200)
        decide_data = await decide_resp.json()
        self.assertTrue(decide_data["success"])
        self.sheets.batch_update_balances.assert_called_with(["An", "Bình"], 1)
        self.assertNotIn(req_id, self.bot_data.get("reward_requests", {}))

    async def test_safe_send_admin_markdown_fallback(self):
        from webapp.server import _safe_send_admin
        # Simulate Telegram markdown parse error on first attempt, success on fallback
        call_count = 0
        async def mock_send_message(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs.get("parse_mode") == "Markdown":
                raise Exception("Can't parse entities")
            return SimpleNamespace(message_id=999)

        mock_bot = SimpleNamespace(send_message=AsyncMock(side_effect=mock_send_message))
        await _safe_send_admin(mock_bot, "Test *broken_markdown", parse_mode="Markdown")
        self.assertEqual(call_count, 2, "Should attempt with Markdown, then fallback to plain text")


if __name__ == "__main__":
    unittest.main()
