"""Tests for Employee Penalty System (10k fixed amount).
Covers store persistence, validation, filtering, leaderboard, and Google Sheets sync.
"""
from datetime import date, datetime
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config import Config
from services.sheets.sync import SyncSheetsMixin
from utils.time_utils import local_now
from webapp.store import WebAppStore


class PenaltyStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "store.json"
        self.store = WebAppStore(path=self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_penalty_success(self):
        item = self.store.add_penalty(
            nickname="  Huy  ",
            reason="  Đi muộn 15 phút  ",
            admin_name="  Admin Sober  ",
        )
        self.assertIn("id", item)
        self.assertTrue(item["id"].startswith("pen_"))
        self.assertEqual(item["nickname"], "Huy")
        self.assertEqual(item["reason"], "Đi muộn 15 phút")
        self.assertEqual(item["admin_name"], "Admin Sober")
        self.assertEqual(item["amount"], 10000)
        self.assertIn("created_at", item)
        self.assertIn("date", item)

        # Check persistence across reload
        reloaded_store = WebAppStore(path=self.db_path)
        all_pens = reloaded_store.get_penalties()
        self.assertEqual(len(all_pens), 1)
        self.assertEqual(all_pens[0]["id"], item["id"])
        self.assertEqual(all_pens[0]["nickname"], "Huy")
        self.assertEqual(all_pens[0]["amount"], 10000)

    def test_add_penalty_validation_errors(self):
        # Empty or whitespace nickname
        with self.assertRaises(ValueError):
            self.store.add_penalty(nickname="", reason="Quên dọn bar", admin_name="Admin")
        with self.assertRaises(ValueError):
            self.store.add_penalty(nickname="   ", reason="Quên dọn bar", admin_name="Admin")

        # Empty or whitespace reason
        with self.assertRaises(ValueError):
            self.store.add_penalty(nickname="Huy", reason="", admin_name="Admin")
        with self.assertRaises(ValueError):
            self.store.add_penalty(nickname="Huy", reason="   ", admin_name="Admin")

    def test_add_penalty_custom_created_at(self):
        custom_time = "08:30 15/05/2026"
        item = self.store.add_penalty(
            nickname="Thảo",
            reason="Mặc sai đồng phục",
            admin_name="Admin",
            created_at=custom_time,
        )
        self.assertEqual(item["created_at"], custom_time)
        self.assertEqual(item["date"], "15/05/2026")
        self.assertEqual(item["amount"], 10000)

    def test_get_penalties_ordering_newest_first(self):
        p1 = self.store.add_penalty(nickname="An", reason="Vi phạm 1", admin_name="Admin", created_at="08:00 10/05/2026")
        time.sleep(0.01)
        p2 = self.store.add_penalty(nickname="Bình", reason="Vi phạm 2", admin_name="Admin", created_at="09:00 11/05/2026")
        time.sleep(0.01)
        p3 = self.store.add_penalty(nickname="Chi", reason="Vi phạm 3", admin_name="Admin", created_at="10:00 12/05/2026")

        items = self.store.get_penalties()
        self.assertEqual(len(items), 3)
        # Newest first
        self.assertEqual(items[0]["id"], p3["id"])
        self.assertEqual(items[1]["id"], p2["id"])
        self.assertEqual(items[2]["id"], p1["id"])

    def test_get_penalties_filter_by_nickname_normalized(self):
        self.store.add_penalty(nickname="Hòa", reason="Lỗi 1", admin_name="Admin")
        self.store.add_penalty(nickname="Mai", reason="Lỗi 2", admin_name="Admin")
        self.store.add_penalty(nickname="hoa", reason="Lỗi 3", admin_name="Admin")

        # Filter by normalized name "Hoa" -> should match "Hòa" and "hoa"
        hoa_pens = self.store.get_penalties(nickname="Hoa")
        self.assertEqual(len(hoa_pens), 2)
        for p in hoa_pens:
            self.assertIn(p["nickname"].lower(), ["hòa", "hoa"])

        # Filter by "Mai"
        mai_pens = self.store.get_penalties(nickname="Mai")
        self.assertEqual(len(mai_pens), 1)
        self.assertEqual(mai_pens[0]["nickname"], "Mai")

    def test_get_penalties_filter_by_date_range(self):
        self.store.add_penalty(nickname="An", reason="L1", admin_name="Admin", created_at="08:00 05/05/2026")
        self.store.add_penalty(nickname="An", reason="L2", admin_name="Admin", created_at="08:00 15/05/2026")
        self.store.add_penalty(nickname="An", reason="L3", admin_name="Admin", created_at="08:00 25/05/2026")

        # Range 10/05/2026 to 20/05/2026
        filtered = self.store.get_penalties(
            nickname="An",
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 20),
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["reason"], "L2")

        # Open-ended range (from 15/05/2026 onward)
        filtered_after = self.store.get_penalties(start_date=date(2026, 5, 15))
        self.assertEqual(len(filtered_after), 2)

    def test_get_penalties_filter_unparseable_date_with_end_date_only(self):
        # Add a valid penalty
        self.store.add_penalty(nickname="An", reason="Valid", admin_name="Admin", created_at="08:00 10/05/2026")

        # Inject a penalty record with an unparseable date into store
        with self.store._lock:
            self.store._data["penalties"].append({
                "id": "pen_corrupt",
                "nickname": "An",
                "amount": 10000,
                "reason": "Corrupt date",
                "admin_name": "Admin",
                "date": "invalid-date",
                "created_at": "unknown",
            })
            self.store._save_unlocked()

        # Filter with only end_date specified -> unparseable date must be excluded
        filtered = self.store.get_penalties(end_date=date(2026, 5, 20))
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["reason"], "Valid")

    def test_get_penalties_leaderboard(self):
        # 3 penalties for Huy (30k)
        self.store.add_penalty(nickname="Huy", reason="L1", admin_name="Admin", created_at="08:00 10/05/2026")
        self.store.add_penalty(nickname="Huy", reason="L2", admin_name="Admin", created_at="08:00 11/05/2026")
        self.store.add_penalty(nickname="Huy", reason="L3", admin_name="Admin", created_at="08:00 12/05/2026")

        # 2 penalties for Thảo (20k)
        self.store.add_penalty(nickname="Thảo", reason="L4", admin_name="Admin", created_at="08:00 10/05/2026")
        self.store.add_penalty(nickname="Thảo", reason="L5", admin_name="Admin", created_at="08:00 15/05/2026")

        # 1 penalty for An (10k)
        self.store.add_penalty(nickname="An", reason="L6", admin_name="Admin", created_at="08:00 10/05/2026")

        # 1 penalty for An outside range (01/04/2026)
        self.store.add_penalty(nickname="An", reason="L0", admin_name="Admin", created_at="08:00 01/04/2026")

        # Overall leaderboard for May 2026
        lb = self.store.get_penalties_leaderboard(
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
        )
        self.assertEqual(len(lb), 3)
        self.assertEqual(lb[0]["nickname"], "Huy")
        self.assertEqual(lb[0]["count"], 3)
        self.assertEqual(lb[0]["total_amount"], 30000)

        self.assertEqual(lb[1]["nickname"], "Thảo")
        self.assertEqual(lb[1]["count"], 2)
        self.assertEqual(lb[1]["total_amount"], 20000)

        self.assertEqual(lb[2]["nickname"], "An")
        self.assertEqual(lb[2]["count"], 1)
        self.assertEqual(lb[2]["total_amount"], 10000)

    def test_store_async_sheets_integration(self):
        mock_sheets = MagicMock()
        mock_sheets.save_sheet_penalty = MagicMock()
        store_with_sheets = WebAppStore(path=self.db_path, sheets_service=mock_sheets)
        item = store_with_sheets.add_penalty(
            nickname="Bình",
            reason="Đi trễ",
            admin_name="Admin",
        )
        time.sleep(0.1)
        mock_sheets.save_sheet_penalty.assert_called_once_with(item)


class PenaltySheetsSyncTests(unittest.TestCase):
    def setUp(self):
        self.service = SyncSheetsMixin()
        self.service._write_lock = None
        self.mock_sh = MagicMock()
        self.service.sh = self.mock_sh

    def test_save_sheet_penalty_success(self):
        mock_ws = MagicMock()
        self.mock_sh.worksheet.return_value = mock_ws

        penalty = {
            "id": "pen_1700000000_abc123",
            "created_at": "14:30 20/10/2026",
            "date": "20/10/2026",
            "nickname": "Huy",
            "amount": 10000,
            "reason": "Đi muộn 15 phút",
            "admin_name": "Admin Sober",
        }

        ok = self.service.save_sheet_penalty(penalty)
        self.assertTrue(ok)
        self.mock_sh.worksheet.assert_called_with("Lịch Sử Phạt")
        mock_ws.append_row.assert_called_once_with(
            [
                "pen_1700000000_abc123",
                "14:30 20/10/2026",
                "20/10/2026",
                "Huy",
                10000,
                "Đi muộn 15 phút",
                "Admin Sober",
            ],
            value_input_option="USER_ENTERED",
        )

    def test_save_sheet_penalty_error_handling(self):
        self.mock_sh.worksheet.side_effect = Exception("Sheets network failure")
        self.mock_sh.add_worksheet.side_effect = Exception("Create failed")

        ok = self.service.save_sheet_penalty({"id": "pen_1"})
        self.assertFalse(ok)

    def test_load_sheet_penalties_success(self):
        mock_ws = MagicMock()
        self.mock_sh.worksheet.return_value = mock_ws
        mock_ws.get_all_values.return_value = [
            ["Mã Phạt", "Thời Gian", "Ngày", "Tên Nhân Viên", "Số Tiền", "Lý Do Vi Phạm", "Người Phạt"],
            ["pen_1", "08:00 10/10/2026", "10/10/2026", "Huy", "10.000", "Đi muộn", "Admin"],
            ["pen_2", "09:00 11/10/2026", "11/10/2026", "Thảo", "10000", "Quên đồng phục", "Admin"],
        ]

        items = self.service.load_sheet_penalties()
        self.assertEqual(len(items), 2)
        # Newest first (reversed from spreadsheet append order)
        self.assertEqual(items[0]["id"], "pen_2")
        self.assertEqual(items[0]["nickname"], "Thảo")
        self.assertEqual(items[0]["amount"], 10000)
        self.assertEqual(items[1]["id"], "pen_1")
        self.assertEqual(items[1]["nickname"], "Huy")
        self.assertEqual(items[1]["amount"], 10000)

    def test_load_sheet_penalties_empty_or_missing(self):
        mock_ws = MagicMock()
        self.mock_sh.worksheet.return_value = mock_ws
        mock_ws.get_all_values.return_value = [
            ["Mã Phạt", "Thời Gian", "Ngày", "Tên Nhân Viên", "Số Tiền", "Lý Do Vi Phạm", "Người Phạt"]
        ]

        items = self.service.load_sheet_penalties()
        self.assertEqual(items, [])


class PayrollPenaltyDeductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "store.json"
        self.store = WebAppStore(path=self.db_path)

        # Instantiate GoogleSheetsService without calling network-bound __init__
        from google_sheets import GoogleSheetsService
        self.service = GoogleSheetsService.__new__(GoogleSheetsService)
        self.service._write_lock = threading.RLock()
        self.service._cache_lock = threading.Lock()
        self.service._cache = {}
        self.service.store = self.store

    def tearDown(self):
        self.tmp.cleanup()

    def test_get_salary_report_with_penalties_deduction(self):
        # 2 penalties for Huy in period (17/04/2026 -> 16/05/2026)
        self.store.add_penalty("Huy", "Đi muộn 15p", "Admin", created_at="08:00 20/04/2026")
        self.store.add_penalty("Huy", "Quên đồng phục", "Admin", created_at="08:00 25/04/2026")
        # 1 penalty outside period
        self.store.add_penalty("Huy", "Lỗi cũ", "Admin", created_at="08:00 10/04/2026")

        mock_ws_salary = MagicMock()
        mock_ws_salary.get_all_values.return_value = [
            ["Ngày Tạo", "Tháng", "Tên Nhân Viên", "Nickname Bot", "Tổng Giờ Làm", "Mức Lương/Giờ", "Thưởng Tiền", "Ứng Lương", "Nhận Thực Tế"]
        ]
        self.service._get_salary_worksheet = MagicMock(return_value=mock_ws_salary)
        self.service.get_all_salary_rates = MagicMock(return_value={"Huy": 25.0})

        mock_ws_checkin = MagicMock()
        mock_ws_checkin.get_all_values.return_value = [
            ["Ngày", "Tên Nhân Viên", "Giờ Vào", "Giờ Ra", "Tổng Giờ", "Ghi Chú"],
            ["20/04/2026", "Huy", "08:00", "16:00", "8.0", ""],
            ["22/04/2026", "Huy", "08:00", "20:00", "12.0", ""],
        ]
        self.service.ws_checkin = mock_ws_checkin

        report = self.service.get_salary_report(5, 2026)

        # 20h * 25k = 500k; 2 penalties = -20k; Net total = 480k
        self.assertIn("⚠️ Phạt kỷ luật (2 lần): -20k", report)
        self.assertIn("👉 *Thực nhận: 480k*", report)

        # Check that ws.append_row or ws.update saved 480.0 into Nhận Thực Tế
        mock_ws_salary.append_row.assert_called_once()
        appended_row = mock_ws_salary.append_row.call_args[0][0]
        self.assertEqual(appended_row[8], 480.0)

    def test_get_salary_report_no_penalties_backward_compatible(self):
        mock_ws_salary = MagicMock()
        mock_ws_salary.get_all_values.return_value = [
            ["Ngày Tạo", "Tháng", "Tên Nhân Viên", "Nickname Bot", "Tổng Giờ Làm", "Mức Lương/Giờ", "Thưởng Tiền", "Ứng Lương", "Nhận Thực Tế"]
        ]
        self.service._get_salary_worksheet = MagicMock(return_value=mock_ws_salary)
        self.service.get_all_salary_rates = MagicMock(return_value={"An": 20.0})

        mock_ws_checkin = MagicMock()
        mock_ws_checkin.get_all_values.return_value = [
            ["Ngày", "Tên Nhân Viên", "Giờ Vào", "Giờ Ra", "Tổng Giờ", "Ghi Chú"],
            ["20/04/2026", "An", "08:00", "18:00", "10.0", ""],
        ]
        self.service.ws_checkin = mock_ws_checkin

        report = self.service.get_salary_report(5, 2026)

        # No penalties
        self.assertNotIn("Phạt kỷ luật", report)
        self.assertIn("👉 *Thực nhận: 200k*", report)

    def test_get_salary_data_with_penalties_and_summary(self):
        # Huy: 2 penalties in period (20k)
        self.store.add_penalty("Huy", "Đi muộn", "Admin", created_at="08:00 20/04/2026")
        self.store.add_penalty("Huy", "Quên đồng phục", "Admin", created_at="08:00 25/04/2026")
        # Thảo: 1 penalty in period (10k)
        self.store.add_penalty("Thảo", "Lỗi pha chế", "Admin", created_at="08:00 22/04/2026")

        mock_ws_salary = MagicMock()
        mock_ws_salary.get_all_values.return_value = [
            ["Ngày Tạo", "Tháng", "Tên Nhân Viên", "Nickname Bot", "Tổng Giờ Làm", "Mức Lương/Giờ", "Thưởng Tiền", "Ứng Lương", "Nhận Thực Tế"],
            ["20/05/2026 10:00", "T5-2026", "Nguyễn Huy", "Huy", "20.0", "25.0", "0", "0", "480.0"],
            ["20/05/2026 10:00", "T5-2026", "Trần Thảo", "Thảo", "10.0", "20.0", "50.0", "10.0", "230.0"],
        ]
        self.service._get_salary_worksheet = MagicMock(return_value=mock_ws_salary)
        self.service.get_salary_report = MagicMock(return_value="report markdown")

        data = self.service.get_salary_data(5, 2026)
        self.assertTrue(data["success"])
        self.assertEqual(len(data["items"]), 2)

        huy = next(i for i in data["items"] if i["nickname"] == "Huy")
        self.assertEqual(huy["penalty_count"], 2)
        self.assertEqual(huy["penalty_amount"], 20000)
        self.assertEqual(huy["penalty_amount_k"], 20.0)
        self.assertEqual(huy["total"], 480.0)

        thao = next(i for i in data["items"] if i["nickname"] == "Thảo")
        self.assertEqual(thao["penalty_count"], 1)
        self.assertEqual(thao["penalty_amount"], 10000)
        self.assertEqual(thao["penalty_amount_k"], 10.0)
        self.assertEqual(thao["total"], 230.0)

        # Summary fields
        self.assertEqual(data["total_penalties_count"], 3)
        self.assertEqual(data["total_penalties_amount"], 30000)
        self.assertEqual(data["total_payout"], 710.0)

    def test_get_salary_data_without_store_backward_compatible(self):
        self.service.store = None
        mock_ws_salary = MagicMock()
        mock_ws_salary.get_all_values.return_value = [
            ["Ngày Tạo", "Tháng", "Tên Nhân Viên", "Nickname Bot", "Tổng Giờ Làm", "Mức Lương/Giờ", "Thưởng Tiền", "Ứng Lương", "Nhận Thực Tế"],
            ["20/05/2026 10:00", "T5-2026", "Nguyễn Huy", "Huy", "10.0", "25.0", "0", "0", "250.0"],
        ]
        self.service._get_salary_worksheet = MagicMock(return_value=mock_ws_salary)
        self.service.get_salary_report = MagicMock(return_value="report markdown")

        data = self.service.get_salary_data(5, 2026)
        self.assertTrue(data["success"])
        item = data["items"][0]
        self.assertEqual(item["penalty_count"], 0)
        self.assertEqual(item["penalty_amount"], 0)
        self.assertEqual(item["penalty_amount_k"], 0.0)
        self.assertEqual(item["total"], 250.0)
        self.assertEqual(data["total_penalties_count"], 0)
        self.assertEqual(data["total_penalties_amount"], 0)

    def test_get_employee_personal_summary_with_penalties(self):
        self.service._current_salary_month = MagicMock(return_value=(5, 2026))
        self.service._salary_period = MagicMock(return_value=(date(2026, 4, 17), date(2026, 5, 16)))
        self.service.get_employees_detail = MagicMock(return_value=[
            {"nickname": "Huy", "key": "huy", "rate": 25.0, "balance": 5}
        ])

        # 2 penalties for Huy in period (20k)
        self.store.add_penalty("Huy", "Lỗi 1", "Admin", created_at="08:00 20/04/2026")
        self.store.add_penalty("Huy", "Lỗi 2", "Admin", created_at="08:00 25/04/2026")

        mock_ws_checkin = MagicMock()
        mock_ws_checkin.get_all_values.return_value = [
            ["Ngày", "Tên Nhân Viên", "Giờ Vào", "Giờ Ra", "Tổng Giờ", "Ghi Chú"],
            ["20/04/2026", "Huy", "08:15", "18:00", "9.75", "Đi muộn 15p"],
        ]
        self.service.ws_checkin = mock_ws_checkin
        self.service.get_overtime_summary = MagicMock(return_value={})

        summary = self.service.get_employee_personal_summary("Huy")
        self.assertTrue(summary["success"])
        # Hours: 9.75 * 25.0 = 243.75 -> base_salary_k = 243.8
        # Late penalty: 1 * 10k = 10.0
        # Disciplinary penalties: 2 * 10k = 20.0
        # estimated_pay_k: max(0.0, 243.8 - 10.0 - 20.0) = 213.8
        self.assertEqual(summary["penalty_count"], 2)
        self.assertEqual(summary["penalty_amount_k"], 20.0)
        self.assertEqual(summary["penalty_amount"], 20000)
        self.assertEqual(len(summary["penalties"]), 2)
        self.assertEqual(summary["late_penalty_k"], 10.0)
        self.assertEqual(summary["estimated_pay_k"], 213.8)

    def test_get_employee_personal_summary_without_store_backward_compatible(self):
        self.service.store = None
        self.service._current_salary_month = MagicMock(return_value=(5, 2026))
        self.service._salary_period = MagicMock(return_value=(date(2026, 4, 17), date(2026, 5, 16)))
        self.service.get_employees_detail = MagicMock(return_value=[
            {"nickname": "An", "key": "an", "rate": 20.0, "balance": 0}
        ])

        mock_ws_checkin = MagicMock()
        mock_ws_checkin.get_all_values.return_value = [
            ["Ngày", "Tên Nhân Viên", "Giờ Vào", "Giờ Ra", "Tổng Giờ", "Ghi Chú"],
            ["20/04/2026", "An", "08:00", "18:00", "10.0", ""],
        ]
        self.service.ws_checkin = mock_ws_checkin
        self.service.get_overtime_summary = MagicMock(return_value={})

        summary = self.service.get_employee_personal_summary("An")
        self.assertTrue(summary["success"])
        self.assertEqual(summary["penalty_count"], 0)
        self.assertEqual(summary["penalty_amount_k"], 0.0)
        self.assertEqual(summary["penalty_amount"], 0)
        self.assertEqual(summary["penalties"], [])
        self.assertEqual(summary["estimated_pay_k"], 200.0)


class BotPenaltyFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "store.json"
        self.store = WebAppStore(path=self.db_path)
        self.admin_user = SimpleNamespace(id=Config.ADMIN_CHAT_ID, first_name="Quản Lý", full_name="Quản Lý Sober", username="admin_sober")
        self.staff_user = SimpleNamespace(id=88888, first_name="Huy", full_name="Gia Huy", username="huy_staff")

    def tearDown(self):
        self.tmp.cleanup()

    def _make_context(self, user_data=None, args=None, balances=None):
        sheets = MagicMock()
        sheets.get_all_balances.return_value = balances if balances is not None else {"Huy": 2, "Thảo": 0}
        sheets.get_admin_list.return_value = [Config.ADMIN_CHAT_ID]
        bot = MagicMock()
        bot.send_message = AsyncMock()
        return SimpleNamespace(
            bot=bot,
            user_data=user_data if user_data is not None else {},
            bot_data={
                "sheets": sheets,
                "store": self.store,
                "admin_ids": {Config.ADMIN_CHAT_ID},
            },
            args=args or [],
        )

    async def test_manage_nv_button_contains_penalty_button(self):
        from handlers.management_handler import handle_manage_nv_button
        update = SimpleNamespace(
            effective_user=self.admin_user,
            effective_chat=SimpleNamespace(id=Config.ADMIN_CHAT_ID),
            message=SimpleNamespace(reply_text=AsyncMock(return_value=SimpleNamespace(message_id=99))),
        )
        context = self._make_context()
        await handle_manage_nv_button(update, context)

        update.message.reply_text.assert_awaited_once()
        _, kwargs = update.message.reply_text.await_args
        reply_markup = kwargs.get("reply_markup")
        all_buttons = [btn for row in reply_markup.inline_keyboard for btn in row]
        fine_btn = next((b for b in all_buttons if b.callback_data == "mgmt_fine_list"), None)
        self.assertIsNotNone(fine_btn)
        self.assertIn("10k", fine_btn.text)

    async def test_mgmt_callback_routes_fine_list_and_fine_sel(self):
        from handlers.management_handler import handle_mgmt_callback
        context = self._make_context()

        # Route mgmt_fine_list
        query_list = SimpleNamespace(
            data="mgmt_fine_list",
            from_user=self.admin_user,
            edit_message_text=AsyncMock(),
            answer=AsyncMock(),
        )
        await handle_mgmt_callback(query_list, context)
        query_list.edit_message_text.assert_awaited_once()
        text_arg = query_list.edit_message_text.await_args[0][0]
        self.assertIn("LẬP BIÊN BẢN PHẠT", text_arg)

        # Route mgmt_fine_sel_Huy
        query_sel = SimpleNamespace(
            data="mgmt_fine_sel_Huy",
            from_user=self.admin_user,
            edit_message_text=AsyncMock(),
            answer=AsyncMock(),
        )
        await handle_mgmt_callback(query_sel, context)
        self.assertEqual(context.user_data.get("awaiting_penalty_reason"), {"nickname": "Huy"})
        query_sel.edit_message_text.assert_awaited_once()
        text_arg2 = query_sel.edit_message_text.await_args[0][0]
        self.assertIn("10.000đ", text_arg2)
        self.assertIn("Huy", text_arg2)

    async def test_show_fine_list_renders_employees_and_cancel(self):
        from handlers.management_handler import _show_fine_list
        context = self._make_context(balances={"Huy": 1, "Thảo": 2, "Nam": 0})
        query = SimpleNamespace(
            edit_message_text=AsyncMock(),
        )
        await _show_fine_list(query, context)
        query.edit_message_text.assert_awaited_once()
        args, kwargs = query.edit_message_text.await_args
        self.assertIn("LẬP BIÊN BẢN PHẠT (10K/LẦN)", args[0])
        markup = kwargs.get("reply_markup")
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertIn("mgmt_fine_sel_Huy", callbacks)
        self.assertIn("mgmt_fine_sel_Thảo", callbacks)
        self.assertIn("mgmt_fine_sel_Nam", callbacks)
        self.assertIn("mgmt_cancel", callbacks)

    async def test_start_fine_employee_sets_state(self):
        from handlers.management_handler import _start_fine_employee
        context = self._make_context()
        query = SimpleNamespace(
            edit_message_text=AsyncMock(),
        )
        await _start_fine_employee(query, context, "Thảo")
        self.assertEqual(context.user_data.get("awaiting_penalty_reason"), {"nickname": "Thảo"})
        query.edit_message_text.assert_awaited_once()
        args, _ = query.edit_message_text.await_args
        self.assertIn("Thảo", args[0])
        self.assertIn("10.000đ", args[0])

    async def test_handle_fine_reason_input_success_and_group_announcement(self):
        from handlers.management_handler import handle_fine_reason_input
        context = self._make_context(user_data={"awaiting_penalty_reason": {"nickname": "Huy"}})
        update = SimpleNamespace(
            effective_user=self.admin_user,
            effective_chat=SimpleNamespace(id=Config.ADMIN_CHAT_ID),
            message=SimpleNamespace(
                text="Quên tắt đèn quầy bar",
                reply_text=AsyncMock(),
            ),
        )

        handled = await handle_fine_reason_input(update, context)
        self.assertTrue(handled)
        self.assertNotIn("awaiting_penalty_reason", context.user_data)

        # Check penalty recorded in store
        penalties = self.store.get_penalties(nickname="Huy")
        self.assertEqual(len(penalties), 1)
        self.assertEqual(penalties[0]["amount"], 10000)
        self.assertEqual(penalties[0]["reason"], "Quên tắt đèn quầy bar")
        self.assertEqual(penalties[0]["admin_name"], "Quản Lý")

        # Confirmation to admin
        update.message.reply_text.assert_awaited_once()
        admin_reply = update.message.reply_text.await_args[0][0]
        self.assertIn("Đã lập biên bản phạt 10.000đ cho *Huy*", admin_reply)

        # Public announcement to group
        context.bot.send_message.assert_awaited_once()
        call_kwargs = context.bot.send_message.await_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], Config.GROUP_CHAT_ID)
        self.assertIn("THÔNG BÁO KỶ LUẬT VI PHẠM", call_kwargs["text"])
        self.assertIn("Huy", call_kwargs["text"])
        self.assertIn("10.000đ", call_kwargs["text"])
        self.assertIn("Quên tắt đèn quầy bar", call_kwargs["text"])

    async def test_handle_fine_reason_input_group_error_resilient(self):
        from handlers.management_handler import handle_fine_reason_input
        context = self._make_context(user_data={"awaiting_penalty_reason": {"nickname": "Thảo"}})
        # Simulate network error on group announcement
        context.bot.send_message.side_effect = Exception("Telegram Network Error")

        update = SimpleNamespace(
            effective_user=self.admin_user,
            effective_chat=SimpleNamespace(id=Config.ADMIN_CHAT_ID),
            message=SimpleNamespace(
                text="Đi muộn 20 phút không báo",
                reply_text=AsyncMock(),
            ),
        )

        handled = await handle_fine_reason_input(update, context)
        self.assertTrue(handled)
        # Verify penalty still saved despite group error
        penalties = self.store.get_penalties(nickname="Thảo")
        self.assertEqual(len(penalties), 1)
        update.message.reply_text.assert_awaited_once()

    async def test_handle_fine_reason_input_cancel(self):
        from handlers.management_handler import handle_fine_reason_input
        context = self._make_context(user_data={"awaiting_penalty_reason": {"nickname": "Huy"}})
        update = SimpleNamespace(
            effective_user=self.admin_user,
            effective_chat=SimpleNamespace(id=Config.ADMIN_CHAT_ID),
            message=SimpleNamespace(
                text="/cancel",
                reply_text=AsyncMock(),
            ),
        )

        handled = await handle_fine_reason_input(update, context)
        self.assertTrue(handled)
        self.assertNotIn("awaiting_penalty_reason", context.user_data)
        self.assertEqual(len(self.store.get_penalties()), 0)
        update.message.reply_text.assert_awaited_once()

    async def test_handle_fine_reason_input_empty_validation(self):
        from handlers.management_handler import handle_fine_reason_input
        context = self._make_context(user_data={"awaiting_penalty_reason": {"nickname": "Huy"}})
        update = SimpleNamespace(
            effective_user=self.admin_user,
            effective_chat=SimpleNamespace(id=Config.ADMIN_CHAT_ID),
            message=SimpleNamespace(
                text="    ",
                reply_text=AsyncMock(),
            ),
        )

        handled = await handle_fine_reason_input(update, context)
        self.assertTrue(handled)
        self.assertIn("awaiting_penalty_reason", context.user_data)
        self.assertEqual(len(self.store.get_penalties()), 0)

    async def test_phat_command_direct(self):
        from handlers.management_handler import phat_command
        context = self._make_context(args=["Huy", "Đi", "muộn", "15", "phút"])
        update = SimpleNamespace(
            effective_user=self.admin_user,
            effective_chat=SimpleNamespace(id=Config.ADMIN_CHAT_ID),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )

        await phat_command(update, context)

        penalties = self.store.get_penalties(nickname="Huy")
        self.assertEqual(len(penalties), 1)
        self.assertEqual(penalties[0]["amount"], 10000)
        self.assertEqual(penalties[0]["reason"], "Đi muộn 15 phút")
        update.message.reply_text.assert_awaited_once()
        context.bot.send_message.assert_awaited_once()

    async def test_phat_command_name_only_sets_state(self):
        from handlers.management_handler import phat_command
        context = self._make_context(args=["Huy"])
        update = SimpleNamespace(
            effective_user=self.admin_user,
            effective_chat=SimpleNamespace(id=Config.ADMIN_CHAT_ID),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )

        await phat_command(update, context)
        self.assertEqual(context.user_data.get("awaiting_penalty_reason"), {"nickname": "Huy"})
        update.message.reply_text.assert_awaited_once()
        self.assertEqual(len(self.store.get_penalties()), 0)

    async def test_phat_command_no_args_shows_selection_list(self):
        from handlers.management_handler import phat_command
        context = self._make_context(args=[], balances={"Huy": 0, "Thảo": 1})
        update = SimpleNamespace(
            effective_user=self.admin_user,
            effective_chat=SimpleNamespace(id=Config.ADMIN_CHAT_ID),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )

        await phat_command(update, context)
        update.message.reply_text.assert_awaited_once()
        args, kwargs = update.message.reply_text.await_args
        self.assertIn("LẬP BIÊN BẢN PHẠT (10K/LẦN)", args[0])
        self.assertIn("reply_markup", kwargs)

    async def test_phat_command_blocked_for_non_admin(self):
        from handlers.management_handler import phat_command
        context = self._make_context(args=["Huy", "Lỗi"])
        update = SimpleNamespace(
            effective_user=self.staff_user,
            effective_chat=SimpleNamespace(id=Config.GROUP_CHAT_ID),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )

        await phat_command(update, context)
        self.assertEqual(len(self.store.get_penalties()), 0)

    async def test_bangphat_command_leaderboard(self):
        from handlers.management_handler import bangphat_command
        now = local_now()
        cur_dmy = now.strftime("%d/%m/%Y")
        self.store.add_penalty("Huy", "Lỗi 1", "Admin", created_at=f"08:00 {cur_dmy}")
        self.store.add_penalty("Huy", "Lỗi 2", "Admin", created_at=f"09:00 {cur_dmy}")
        self.store.add_penalty("Thảo", "Lỗi 3", "Admin", created_at=f"10:00 {cur_dmy}")

        context = self._make_context()
        update = SimpleNamespace(
            effective_user=self.staff_user,
            effective_chat=SimpleNamespace(id=Config.GROUP_CHAT_ID),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )

        await bangphat_command(update, context)
        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.await_args[0][0]
        self.assertIn("BẢNG XẾP HẠNG VI PHẠM", reply)
        self.assertIn("3", reply)  # total 3 penalties
        self.assertIn("30,000đ", reply)
        self.assertIn("Huy", reply)
        self.assertIn("Thảo", reply)
        self.assertIn("🥇", reply)

    async def test_xemphat_command_specific_user(self):
        from handlers.management_handler import xemphat_command
        self.store.add_penalty("Huy", "Quên đóng cửa", "Admin")
        context = self._make_context(args=["Huy"])
        update = SimpleNamespace(
            effective_user=self.staff_user,
            effective_chat=SimpleNamespace(id=Config.GROUP_CHAT_ID),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )

        await xemphat_command(update, context)
        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.await_args[0][0]
        self.assertIn("LỊCH SỬ PHẠT — Huy", reply)
        self.assertIn("Quên đóng cửa", reply)
        self.assertIn("-10.000đ", reply)

    async def test_button_click_handler_intercepts_fine_reason(self):
        from handlers.reward_handler import button_click_handler
        context = self._make_context(user_data={"awaiting_penalty_reason": {"nickname": "Huy"}})
        update = SimpleNamespace(
            effective_user=self.admin_user,
            effective_chat=SimpleNamespace(id=Config.GROUP_CHAT_ID),
            message=SimpleNamespace(
                text="Không dọn rác",
                reply_text=AsyncMock(),
                delete=AsyncMock(),
            ),
        )

        await button_click_handler(update, context)
        self.assertNotIn("awaiting_penalty_reason", context.user_data)
        penalties = self.store.get_penalties(nickname="Huy")
        self.assertEqual(len(penalties), 1)
        self.assertEqual(penalties[0]["reason"], "Không dọn rác")

    async def test_bangphat_command_empty_period(self):
        from handlers.management_handler import bangphat_command
        context = self._make_context()
        update = SimpleNamespace(
            effective_user=self.staff_user,
            effective_chat=SimpleNamespace(id=Config.GROUP_CHAT_ID),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )

        await bangphat_command(update, context)
        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.await_args[0][0]
        self.assertIn("Chưa có nhân viên nào bị phạt", reply)

    async def test_xemphat_command_fallback_to_effective_user(self):
        from handlers.management_handler import xemphat_command
        # Staff user first_name is "Huy"
        self.store.add_penalty("Huy", "Vỡ ly thủy tinh", "Admin")
        context = self._make_context(args=[], balances={"Huy": 0, "Thảo": 1})
        update = SimpleNamespace(
            effective_user=self.staff_user,
            effective_chat=SimpleNamespace(id=Config.GROUP_CHAT_ID),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )

        await xemphat_command(update, context)
        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.await_args[0][0]
        self.assertIn("LỊCH SỬ PHẠT — Huy", reply)
        self.assertIn("Vỡ ly thủy tinh", reply)

    async def test_phat_command_multiword_nickname(self):
        from handlers.management_handler import phat_command
        context = self._make_context(
            args=["Bình", "An", "Quên", "lau", "máy", "pha"],
            balances={"Bình An": 0, "Huy": 1},
        )
        update = SimpleNamespace(
            effective_user=self.admin_user,
            effective_chat=SimpleNamespace(id=Config.ADMIN_CHAT_ID),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )

        await phat_command(update, context)
        penalties = self.store.get_penalties(nickname="Bình An")
        self.assertEqual(len(penalties), 1)
        self.assertEqual(penalties[0]["reason"], "Quên lau máy pha")
        self.assertEqual(penalties[0]["amount"], 10000)


