import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.auto_delete import delete_tracked_messages, track_message, get_admin_keyboard, GUIDE_MESSAGE
from config import Config

logger = logging.getLogger(__name__)


async def handle_add_overtime_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin bấm nút '⏰ Thêm Giờ Làm Thêm' → hiển thị danh sách nhân viên"""
    # Chỉ admin mới dùng được
    if update.effective_chat.id != Config.ADMIN_CHAT_ID:
        reply = await update.message.reply_text("⛔ Chức năng này chỉ dành cho Quản lý.")
        track_message(context, reply.message_id)
        return
    
    sheets_service = context.bot_data['sheets']
    balances = await asyncio.to_thread(sheets_service.get_all_balances)
    
    if not balances:
        reply = await update.message.reply_text("📉 Chưa có dữ liệu nhân viên trên hệ thống.")
        track_message(context, reply.message_id)
        return
    
    # Tạo inline keyboard chọn nhân viên
    keyboard = []
    row = []
    for nick in balances.keys():
        row.append(InlineKeyboardButton(nick, callback_data=f"ot_sel_{nick}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Hủy", callback_data="ot_sel_cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    reply = await update.message.reply_text(
        f"⏰ Chọn nhân viên để thêm giờ OT:",
        reply_markup=reply_markup
    )
    track_message(context, reply.message_id)


async def handle_overtime_employee_selected(query, context: ContextTypes.DEFAULT_TYPE):
    """Callback khi admin chọn nhân viên để thêm giờ OT"""
    nickname = query.data[len("ot_sel_"):]
    
    if nickname == "cancel":
        await _cancel_overtime(query, context)
        return
    
    # Lưu trạng thái chờ nhập số giờ
    context.chat_data['awaiting_overtime_hours'] = nickname
    
    try:
        await query.message.delete()
    except Exception:
        pass
    
    prompt = await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=f"⏰ Nhập số giờ OT cho *{nickname}* (VD: 2, 1.5):",
        parse_mode='Markdown'
    )
    track_message(context, prompt.message_id)


async def handle_overtime_hours_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi admin nhập số giờ OT"""
    nickname = context.chat_data.get('awaiting_overtime_hours')
    if not nickname:
        return False  # Không phải đang chờ nhập giờ OT
    
    text = update.message.text.strip()
    
    # Parse số giờ
    try:
        hours = float(text.replace(',', '.'))
        if hours <= 0 or hours > 24:
            raise ValueError("Số giờ không hợp lệ")
    except (ValueError, TypeError):
        err_reply = await update.message.reply_text(
            "❌ Số giờ không hợp lệ. Vui lòng nhập số (VD: 1, 2, 1.5):"
        )
        track_message(context, err_reply.message_id)
        return True  # Đã xử lý (nhưng chờ nhập lại)
    
    # Xóa trạng thái chờ
    del context.chat_data['awaiting_overtime_hours']
    
    # Ghi vào sheet
    sheets_service = context.bot_data['sheets']
    
    try:
        status_msg = await update.message.reply_text(f"⏳ Đang ghi nhận {hours}h làm thêm cho {nickname}...")
        track_message(context, status_msg.message_id)
        
        success = await asyncio.to_thread(sheets_service.add_overtime, nickname, hours)
        
        if success:
            from datetime import datetime
            today = datetime.now().strftime("%d/%m/%Y")
            await status_msg.edit_text(
                f"✅ Đã thêm {hours}h OT cho {nickname} ({today})"
            )
        else:
            await status_msg.edit_text("❌ Có lỗi khi ghi vào hệ thống. Hãy thử lại.")
    except Exception as e:
        logger.error(f"Lỗi trong handle_overtime_hours_input: {e}")
        await update.message.reply_text(f"❌ Đã xảy ra lỗi: {e}")

    # Gửi lại bàn phím admin — gắn kèm vào status_msg không được (edit_text không nhận ReplyKeyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="↩️",
        reply_markup=get_admin_keyboard()
    )

    return True  # Đã xử lý


async def _cancel_overtime(query, context: ContextTypes.DEFAULT_TYPE):
    """Hủy flow thêm giờ OT và gửi lại bàn phím admin"""
    context.chat_data.pop('awaiting_overtime_hours', None)
    
    try:
        await query.message.delete()
    except Exception:
        pass
    
    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text="❌ Đã hủy.",
        reply_markup=get_admin_keyboard()
    )
