import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.endshift_handler import handle_endshift_send


class EndShiftTests(unittest.IsolatedAsyncioTestCase):
    def make_objects(self):
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=999),
            message=SimpleNamespace(delete=AsyncMock()),
        )
        bot = SimpleNamespace(
            send_photo=AsyncMock(),
            send_media_group=AsyncMock(),
            send_message=AsyncMock(),
        )
        context = SimpleNamespace(
            user_data={
                'awaiting_endshift_photo': {'ca': 'Tối', 'role': 'Pha Chế'},
                'endshift_all_photos': ['file-1'],
                'endshift_albums': {},
                'endshift_sent_count': 0,
                'ks_ca': 'Tối',
            },
            bot=bot,
        )
        return update, context

    async def test_one_photo_uses_send_photo_and_clears_state(self):
        update, context = self.make_objects()
        with patch('handlers.endshift_handler.asyncio.sleep', new=AsyncMock()):
            await handle_endshift_send(update, context)
        context.bot.send_photo.assert_awaited_once()
        context.bot.send_media_group.assert_not_awaited()
        self.assertNotIn('awaiting_endshift_photo', context.user_data)

    async def test_send_failure_keeps_files_for_retry(self):
        update, context = self.make_objects()
        context.bot.send_photo.side_effect = RuntimeError('network')
        with patch('handlers.endshift_handler.asyncio.sleep', new=AsyncMock()):
            await handle_endshift_send(update, context)
        self.assertEqual(context.user_data['endshift_all_photos'], ['file-1'])
        self.assertIn('awaiting_endshift_photo', context.user_data)
        failure_text = context.bot.send_message.await_args.kwargs['text']
        self.assertIn('thử lại', failure_text)


if __name__ == '__main__':
    unittest.main()
