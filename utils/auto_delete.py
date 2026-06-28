import asyncio
import logging
from telegram import KeyboardButton, ReplyKeyboardMarkup

logger = logging.getLogger(__name__)

GUIDE_MESSAGE = (
    "🤖 *BOT SOBER* — Hướng dẫn nhanh\n\n"
    "📥 *Check In:* Chấm công vào ca (gửi ảnh xác nhận).\n"
    "📤 *Check Out:* Chấm công ra ca (chọn tên là xong).\n"
    "⚡ *Thưởng Doanh Thu:* Chọn nhân viên có mặt để cộng 1 ly.\n"
    "🥤 *Báo Dùng Thưởng:* Chọn tên để trừ 1 ly đã dùng.\n"
    "🎁 *Tra Cứu Thưởng:* Xem số dư ly của bạn.\n"
    "💡 *Đóng Góp Ý Kiến:* Gửi ý kiến trực tiếp cho quản lý.\n\n"
    "⏰ _Ca làm: Sáng 6:30–12:00 | Chiều 12:00–18:00 | Tối 18:00–22:30_"
)

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📥 Check In"), KeyboardButton("📤 Check Out")],
        [KeyboardButton("⚡ Thưởng Doanh Thu"), KeyboardButton("🥤 Báo Dùng Thưởng")],
        [KeyboardButton("🎁 Tra Cứu Thưởng"), KeyboardButton("💡 Đóng Góp Ý Kiến")],
        [KeyboardButton("🔚 Kết Ca")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def get_admin_keyboard():
    """Reply keyboard dành riêng cho tài khoản Quản lý (Admin)."""
    keyboard = [
        [KeyboardButton("📊 Bảng Thưởng (QL)"), KeyboardButton("🧾 Quản Lý NV (QL)")],
        [KeyboardButton("📋 Lịch Sử Check-In"),  KeyboardButton("⚠️ Thống Kê Đi Muộn")],
        [KeyboardButton("⚡ Thưởng Doanh Thu"),      KeyboardButton("🥤 Báo Dùng Thưởng")],
        [KeyboardButton("✏️ Sửa Doanh Thu")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

async def delete_tracked_messages(context, chat_id: int, exclude: set | None = None):
    """Xóa các tin nhắn kết quả/prompt cũ khi có hành động mới.

    Args:
        context: handler context
        chat_id: chat id to delete messages in
        exclude: optional set of message IDs to skip (e.g. the message we're about to edit)
    """
    if exclude is None:
        exclude = set()

    to_delete = context.chat_data.get('to_delete', set())
    for msg_id in list(to_delete):
        if msg_id in exclude:
            continue
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass
    context.chat_data['to_delete'] = set()

def track_message(context, msg_id: int):
    """Đánh dấu tin nhắn để xóa vào lần thao tác sau."""
    if 'to_delete' not in context.chat_data:
        context.chat_data['to_delete'] = set()
    context.chat_data['to_delete'].add(msg_id)
