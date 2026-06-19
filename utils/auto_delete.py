import asyncio
import logging
from telegram import KeyboardButton, ReplyKeyboardMarkup

logger = logging.getLogger(__name__)

GUIDE_MESSAGE = (
    "🤖 **HƯỚNG DẪN SỬ DỤNG BOT - SOBER**\n\n"
    "👋 Chào bạn! Vui lòng dùng các **NÚT BẤM** ở dưới cùng màn hình:\n\n"
    "📥 **Check In:** Chấm công vào ca (gửi ảnh xác nhận).\n"
    "📤 **Check Out:** Chấm công ra ca (không cần ảnh, chọn tên là xong).\n"
    "⚡ **Báo Doanh Thu:** Chọn nhân viên và báo số tiền ca.\n"
    "🥤 **Báo Dùng Thưởng:** Chọn tên để trừ ly thưởng đã dùng.\n"
    "🎁 **Tra Cứu Thưởng:** Xem số dư ly thưởng của bạn.\n"
    "📊 **Bảng Thưởng (QL):** Xem toàn bộ bảng thưởng.\n\n"
    "📸 _Hoặc gửi Ảnh Bill kèm chú thích:_\n"
    "`Doanh thu: 1500k` hoặc `2M`\n\n"
    "⏰ _Ca làm: 6:30-12:00 | 12:00-18:00 | 18:00-22:30_\n\n"
    "👇 _Sử dụng các nút bên dưới để thao tác._"
)

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📥 Check In"), KeyboardButton("📤 Check Out")],
        [KeyboardButton("🔚 Kết Ca")],
        [KeyboardButton("⚡ Báo Doanh Thu"), KeyboardButton("🥤 Báo Dùng Thưởng")],
        [KeyboardButton("🎁 Tra Cứu Thưởng"), KeyboardButton("📊 Bảng Thưởng (QL)")],
        [KeyboardButton("📖 Hướng Dẫn")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def get_admin_keyboard():
    """Reply keyboard dành riêng cho tài khoản Quản lý (Admin)."""
    keyboard = [
        [KeyboardButton("📊 Bảng Thưởng (QL)"), KeyboardButton("🧾 Quản Lý NV (QL)")],
        [KeyboardButton("📋 Lịch Sử Check-In"),  KeyboardButton("⚠️ Thống Kê Đi Muộn")],
        [KeyboardButton("⏰ Thêm Giờ Làm Thêm"), KeyboardButton("✏️ Sửa Doanh Thu")],
        [KeyboardButton("⚡ Báo Doanh Thu"),      KeyboardButton("🥤 Báo Dùng Thưởng")],
        [KeyboardButton("📖 Hướng Dẫn")]
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
