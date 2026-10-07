import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.checkin_handler import alert_missing_checkins, handle_checkin_employee_selected
from webapp.store import WebAppStore, get_week_info
from config import Config


class CheckinAlertsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "store.json"
        self.store = WebAppStore(path=self.db_path)
        self.sheets = MagicMock()
        self.bot = AsyncMock()

    def tearDown(self):
        self.tmp.cleanup()

    async def test_alert_missing_checkins_when_staff_missing(self):
        """Khi có nhân viên được xếp ca nhưng chưa check-in -> báo Admin."""
        # 1. Setup roster for today's week
        w_info = get_week_info(0)
        from utils.time_utils import local_now
        now = local_now()
        weekday_map = {0: "T2", 1: "T3", 2: "T4", 3: "T5", 4: "T6", 5: "T7", 6: "CN"}
        day_code = weekday_map.get(now.weekday(), "T2")

        self.store.save_roster_draft(
            week_key=w_info["week_key"],
            shifts={f"{day_code}_Sáng": ["An", "Bình"]},
        )

        # 2. Mock sheets checkins: An checked in, Bình has not
        self.sheets.get_checkin_history_today.return_value = [
            {"nickname": "An", "checkin_time": "06:25:00", "note": "Ca Sáng - Đúng giờ"}
        ]

        # 3. Setup context
        context = MagicMock()
        context.job = MagicMock()
        context.job.data = {"shift_ca": "Sáng", "start_time_label": "06:30"}
        context.bot_data = {"sheets": self.sheets, "store": self.store}
        context.bot = self.bot

        await alert_missing_checkins(context)

        # 4. Verify admin received alert mentioning Bình
        self.bot.send_message.assert_called_once()
        call_args = self.bot.send_message.call_args[1]
        self.assertEqual(call_args["chat_id"], Config.ADMIN_CHAT_ID)
        self.assertIn("Bình", call_args["text"])
        self.assertNotIn("An", call_args["text"].split("nhưng nhân viên sau chưa check-in:\n👉")[1])

    async def test_alert_missing_checkins_when_all_checked_in(self):
        """Khi tất cả nhân viên được xếp ca đã check-in -> không gửi tin cảnh báo."""
        w_info = get_week_info(0)
        from utils.time_utils import local_now
        now = local_now()
        weekday_map = {0: "T2", 1: "T3", 2: "T4", 3: "T5", 4: "T6", 5: "T7", 6: "CN"}
        day_code = weekday_map.get(now.weekday(), "T2")

        self.store.save_roster_draft(
            week_key=w_info["week_key"],
            shifts={f"{day_code}_Sáng": ["An"]},
        )

        self.sheets.get_checkin_history_today.return_value = [
            {"nickname": "An", "checkin_time": "06:28:00", "note": "Ca Sáng - Đúng giờ"}
        ]

        context = MagicMock()
        context.job = MagicMock()
        context.job.data = {"shift_ca": "Sáng", "start_time_label": "06:30"}
        context.bot_data = {"sheets": self.sheets, "store": self.store}
        context.bot = self.bot

        await alert_missing_checkins(context)

        self.bot.send_message.assert_not_called()

    async def test_immediate_checkin_notification_on_time(self):
        """Kiểm tra check-in đúng giờ gửi thông báo ngay lập tức cho Admin."""
        query = MagicMock()
        query.data = "ci_sel_An"
        query.message = MagicMock()
        query.message.chat.id = 12345
        query.from_user.id = 12345
        query.answer = AsyncMock()

        status_msg = AsyncMock()
        context = MagicMock()
        context.bot = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=status_msg)
        context.bot_data = {"sheets": self.sheets}
        context.user_data = {
            "awaiting_checkin_type": "Ca Chính",
            "awaiting_checkin_ca": "Sáng",
        }

        self.sheets.checkin.return_value = {
            "success": True,
            "time": "06:28:00",
            "note": "Đúng giờ",
            "ca": "Sáng",
            "late_minutes": 0,
            "date_str": "07/10/2026",
        }

        with patch("handlers.checkin_handler.is_admin", return_value=False):
            await handle_checkin_employee_selected(query, context)

        # Kiểm tra Admin nhận thông báo đúng giờ
        admin_calls = [
            c for c in context.bot.send_message.call_args_list
            if c[1].get("chat_id") == Config.ADMIN_CHAT_ID
        ]
        self.assertTrue(len(admin_calls) >= 1)
        self.assertIn("Đúng giờ", admin_calls[0][1]["text"])
        self.assertIn("An", admin_calls[0][1]["text"])

    async def test_alert_missing_checkins_when_no_roster_empty_shop(self):
        """Khi chưa xếp lịch mà ca đó hoàn toàn chưa có ai check-in -> gửi nhắc nhở Admin."""
        self.sheets.get_checkin_history_today.return_value = []

        context = MagicMock()
        context.job = MagicMock()
        context.job.data = {"shift_ca": "Sáng", "start_time_label": "06:30"}
        context.bot_data = {"sheets": self.sheets, "store": self.store}
        context.bot = self.bot

        await alert_missing_checkins(context)

        self.bot.send_message.assert_called_once()
        call_args = self.bot.send_message.call_args[1]
        self.assertEqual(call_args["chat_id"], Config.ADMIN_CHAT_ID)
        self.assertIn("chưa có nhân viên nào check-in", call_args["text"])
