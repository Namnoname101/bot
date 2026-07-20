import asyncio
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from utils.auto_delete import get_admin_keyboard, track_message
from utils.admin import is_super_admin
from config import Config

logger = logging.getLogger(__name__)


async def handle_overtime_summary_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin xem thống kê tổng giờ làm thêm theo tháng (17→17)."""
    sheets_service = context.bot_data['sheets']
    
    now = datetime.now()
    
    # Tính khoảng ngày 17 tháng trước → 17 tháng này
    if now.day >= 17:
        start_date = now.replace(day=17, hour=0, minute=0, second=0, microsecond=0)
        # Tháng sau
        if now.month == 12:
            end_date = now.replace(year=now.year + 1, month=1, day=17, hour=23, minute=59, second=59)
        else:
            end_date = now.replace(month=now.month + 1, day=17, hour=23, minute=59, second=59)
    else:
        # start = 17 tháng trước
        if now.month == 1:
            start_date = now.replace(year=now.year - 1, month=12, day=17, hour=0, minute=0, second=0, microsecond=0)
        else:
            start_date = now.replace(month=now.month - 1, day=17, hour=0, minute=0, second=0, microsecond=0)
        end_date = now.replace(day=17, hour=23, minute=59, second=59)
    
    summary = await asyncio.to_thread(sheets_service.get_overtime_summary, start_date, end_date)
    
    # Tính còn bao nhiêu ngày
    days_left = (end_date.date() - now.date()).days
    
    period_str = f"{start_date.strftime('%d/%m')} → {end_date.strftime('%d/%m/%Y')}"
    
    if not summary:
        text = f"📊 **THỐNG KÊ GIỜ LÀM THÊM**\n📅 {period_str}\n\n_Chưa có dữ liệu._"
    else:
        lines = [f"📊 **THỐNG KÊ GIỜ LÀM THÊM**", f"📅 {period_str}", ""]
        
        total_all = 0
        for nick, hours in sorted(summary.items()):
            hours_rounded = round(hours, 1)
            total_all += hours_rounded
            lines.append(f"• {nick}: **{hours_rounded}h**")
        
        lines.append(f"\n🔢 Tổng cộng: **{round(total_all, 1)}h**")
        text = "\n".join(lines)
    
    if days_left > 0:
        text += f"\n\n⏳ _Còn {days_left} ngày nữa hết tháng._"
    elif days_left == 0:
        text += f"\n\n⏳ _Hôm nay là ngày cuối tháng!_"
    
    chat_id = update.effective_chat.id
    sup = is_super_admin(chat_id)
    reply = await update.message.reply_text(text, parse_mode='Markdown', reply_markup=get_admin_keyboard(is_super_admin=sup))
    if chat_id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)


async def handle_grant_admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Super admin bấm nút cấp quyền → yêu cầu nhập Telegram ID."""
    context.chat_data['awaiting_admin_id'] = True
    reply = await update.message.reply_text(
        "👑 **CẤP QUYỀN QUẢN LÝ**\n\n"
        "Vui lòng nhập Telegram ID của người muốn cấp quyền:\n"
        "_(Gõ /cancel để huỷ)_",
        parse_mode='Markdown'
    )
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)


async def handle_grant_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Xử lý input Telegram ID để cấp quyền admin."""
    text = update.message.text.strip()
    
    if text.startswith('/cancel'):
        context.chat_data.pop('awaiting_admin_id', None)
        await update.message.reply_text("❌ Đã huỷ cấp quyền.")
        return True
    
    try:
        telegram_id = int(text)
    except ValueError:
        await update.message.reply_text("⚠️ ID không hợp lệ. Vui lòng nhập số nguyên (VD: 123456789)")
        return True
    
    # Kiểm tra đã là admin chưa
    if telegram_id == Config.ADMIN_CHAT_ID:
        context.chat_data.pop('awaiting_admin_id', None)
        await update.message.reply_text("⚠️ ID này đã là Admin gốc rồi!")
        return True
    
    sheets_service = context.bot_data['sheets']
    existing = await asyncio.to_thread(sheets_service.get_admin_list)
    if telegram_id in existing:
        context.chat_data.pop('awaiting_admin_id', None)
        await update.message.reply_text(f"⚠️ ID {telegram_id} đã có quyền Admin rồi!")
        return True
    
    success = await asyncio.to_thread(sheets_service.add_admin, telegram_id, str(Config.ADMIN_CHAT_ID))
    context.chat_data.pop('awaiting_admin_id', None)
    
    if success:
        # Cập nhật cache
        if 'admin_ids' not in context.bot_data:
            context.bot_data['admin_ids'] = set()
        context.bot_data['admin_ids'].add(telegram_id)
        
        await update.message.reply_text(
            f"✅ Đã cấp quyền Quản Lý cho Telegram ID: `{telegram_id}`\n\n"
            f"Người đó cần gõ /start trong bot để kích hoạt bàn phím Admin.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Lỗi khi cấp quyền. Sheet AdminList có thể chưa được tạo.")
    
    return True
