import asyncio
import logging
from telegram import KeyboardButton, ReplyKeyboardMarkup

logger = logging.getLogger(__name__)

GUIDE_MESSAGE = (
    "🤖 *BOT SOBER* — Hướng dẫn nhanh (Máy cố định quán)\n\n"
    "📥 *Check In:* Chấm công vào ca (chọn ca và tên).\n"
    "📤 *Check Out:* Chấm công ra ca (chọn tên là xong).\n"
    "📦 *Lấy NVL:* Báo xuất/lấy nguyên vật liệu tại quầy/kho quán.\n"
    "🔚 *Kết Ca:* Bàn giao ca và nộp báo cáo kết ca.\n\n"
    "💡 _Bảng công, đổi ca, Báo Dùng Thưởng: dùng điện thoại cá nhân vào Webapp._\n"
    "⏰ _Ca làm: Sáng 6:30–12:00 | Chiều 12:00–18:00 | Tối 18:00–22:30_"
)

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📥 Check In"), KeyboardButton("📤 Check Out")],
        [KeyboardButton("📦 Lấy NVL"), KeyboardButton("🔚 Kết Ca")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def get_admin_keyboard(is_super_admin=False):
    keyboard = [
        [KeyboardButton("📱 Mở Mini App")],
        [KeyboardButton("📊 Bảng Thưởng (QL)"), KeyboardButton("🧾 Quản Lý NV (QL)")],
        [KeyboardButton("✏️ Sửa Doanh Thu"), KeyboardButton("📋 Lịch Sử Check-In")],
        [KeyboardButton("⚠️ Thống Kê Đi Muộn"), KeyboardButton("📊 Thống Kê Giờ LT")],
        [KeyboardButton("💰 Tính Lương (QL)"), KeyboardButton("➕ Giờ LT (QL)")],
        [KeyboardButton("⚡ Thưởng Doanh Thu"), KeyboardButton("🥤 Báo Dùng Thưởng")],
        [KeyboardButton("💸 Ứng Lương (QL)"), KeyboardButton("🎁 Thưởng Tiền (QL)")],
        [KeyboardButton("📦 Kho NVL (QL)")],
    ]
    if is_super_admin:
        keyboard.append([KeyboardButton("👑 Cấp Quyền QL")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

async def _bg_delete(bot, chat_id, msg_ids):
    for m_id in msg_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=m_id)
        except Exception:
            pass
        await asyncio.sleep(0.2)

async def delete_tracked_messages(context, chat_id: int, exclude: set | None = None):
    """Đã TẮT tính năng xoá tin nhắn tự động để tránh bị Telegram chặn vì rate limit (20 messages/minute/group)."""
    chat_data = getattr(context, 'chat_data', None)
    if isinstance(chat_data, dict):
        chat_data['to_delete'] = set()

def track_message(context, msg_id: int):
    """Đánh dấu tin nhắn để xóa vào lần thao tác sau."""
    chat_data = getattr(context, 'chat_data', None)
    if not isinstance(chat_data, dict):
        return
    if 'to_delete' not in chat_data:
        chat_data['to_delete'] = set()
    chat_data['to_delete'].add(msg_id)


async def safe_edit_message(query, text: str, **kwargs):
    """Wrapper an toàn cho query.edit_message_text — bắt BadRequest khi nội dung không đổi."""
    try:
        return await query.edit_message_text(text, **kwargs)
    except Exception as e:
        if "not modified" in str(e).lower():
            logger.debug("edit_message_text bị bỏ qua (nội dung không đổi)")
            return None
        raise


async def safe_edit_reply_markup(query, **kwargs):
    """Wrapper an toàn cho query.edit_message_reply_markup — bắt BadRequest khi markup không đổi."""
    try:
        return await query.edit_message_reply_markup(**kwargs)
    except Exception as e:
        if "not modified" in str(e).lower():
            logger.debug("edit_message_reply_markup bị bỏ qua (markup không đổi)")
            return None
        raise
