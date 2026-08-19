import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from config import Config
from handlers.reward_handler import check_reward, quick_report_command, use_reward


def make_update(text: str, message_id: int = 10):
    message = SimpleNamespace(
        text=text,
        message_id=message_id,
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(
        message=message,
        effective_chat=SimpleNamespace(id=Config.GROUP_CHAT_ID),
        effective_user=SimpleNamespace(id=12345),
    )


class RewardCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_reward_by_normalized_nickname(self):
        sheets = MagicMock()
        sheets.get_all_balances.return_value = {'Hòa': 2}
        update = make_update('/thuong hoa')
        context = SimpleNamespace(args=['hoa'], bot_data={'sheets': sheets})

        await check_reward(update, context)

        update.message.reply_text.assert_awaited_once_with('🎁 Hòa: 2 ly thưởng.')

    async def test_use_reward_requires_confirmation(self):
        sheets = MagicMock()
        sheets.get_all_balances.return_value = {'an': 1}
        update = make_update('/dadung an')
        context = SimpleNamespace(args=['an'], bot_data={'sheets': sheets})

        await use_reward(update, context)

        _, kwargs = update.message.reply_text.await_args
        self.assertIn('reply_markup', kwargs)
        self.assertEqual(sheets.consume_reward.call_count, 0)

    async def test_quick_report_saves_and_rewards_once(self):
        sheets = MagicMock()
        sheets.get_all_nicknames.return_value = {'an', 'binh'}
        sheets.save_report.return_value = True
        sheets.batch_update_balances.return_value = True
        update = make_update('/baodoanhthu NV: an, binh DT: 1.2M', message_id=22)
        context = SimpleNamespace(args=[], bot_data={'sheets': sheets, 'processed_reports': set()})

        await quick_report_command(update, context)

        sheets.save_report.assert_called_once()
        sheets.batch_update_balances.assert_called_once_with(['an', 'binh'], 1)

    async def test_quick_report_duplicate_does_not_reward_again(self):
        sheets = MagicMock()
        sheets.get_all_nicknames.return_value = {'an', 'binh'}
        sheets.save_report.return_value = 'duplicate'
        update = make_update('/baodoanhthu NV: an, binh DT: 1.2M', message_id=23)
        context = SimpleNamespace(args=[], bot_data={'sheets': sheets, 'processed_reports': set()})

        await quick_report_command(update, context)

        sheets.batch_update_balances.assert_not_called()


if __name__ == '__main__':
    unittest.main()
