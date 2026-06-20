import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.auto_delete import delete_tracked_messages, track_message, get_main_keyboard, get_admin_keyboard, GUIDE_MESSAGE
from config import Config

logger = logging.getLogger(__name__)


def _build_employee_picker(nicknames: dict, callback_prefix: str):
    """Tạo inline keyboard danh sách nhân viên."""
    keyboard = []
    row = []
    for nick in nicknames.keys():
        row.append(InlineKeyboardButton(nick, callback_data=f"{callback_prefix}_{nick}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Hủy", callback_data=f"{callback_prefix}_cancel")])
    return InlineKeyboardMarkup(keyboard)


async def handle_checkin_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi nhân viên bấm nút '📥 Check In'"""
    sheets_service = context.bot_data['sheets']
    balances = await asyncio.to_thread(sheets_service.get_all_balances)
    
    if not balances:
        reply = await update.message.reply_text("📉 Chưa có dữ liệu nhân viên trên hệ thống.")
        if update.effective_chat.id == Config.GROUP_CHAT_ID:
            track_message(context, reply.message_id)
        return
    
    reply_markup = _build_employee_picker(balances, "ci_sel")
    reply = await update.message.reply_text("📥 **CHECK IN** — Bạn là ai?", reply_markup=reply_markup, parse_mode='Markdown')
    
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)


async def handle_checkout_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi nhân viên bấm nút '📤 Check Out'"""
    sheets_service = context.bot_data['sheets']
    checked_in_emps = await asyncio.to_thread(sheets_service.get_checked_in_employees)
    
    if not checked_in_emps:
        reply = await update.message.reply_text("📉 Không có nhân viên nào đang trong ca (chưa check-out).")
        if update.effective_chat.id == Config.GROUP_CHAT_ID:
            track_message(context, reply.message_id)
        return
    
    reply_markup = _build_employee_picker(checked_in_emps, "co_sel")
    reply = await update.message.reply_text("📤 **CHECK OUT** — Bạn là ai?", reply_markup=reply_markup, parse_mode='Markdown')
    
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)


async def handle_checkin_employee_selected(query, context: ContextTypes.DEFAULT_TYPE):
    """Callback khi nhân viên chọn tên để check-in → yêu cầu gửi ảnh"""
    nickname = query.data[len("ci_sel_"):]
    
    if nickname == "cancel":
        await _cancel_flow(query, context)
        return
    
    # Lưu trạng thái chờ ảnh check-in
    context.chat_data['awaiting_checkin_photo'] = nickname
    
    # Xóa message chọn tên
    if query.message and query.message.chat.id == Config.GROUP_CHAT_ID:
        await delete_tracked_messages(context, query.message.chat.id)
        try:
            await query.message.delete()
        except Exception:
            pass
    
    prompt = await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=f"📸 **{nickname}**, vui lòng gửi ảnh xác nhận check-in:",
        parse_mode='Markdown'
    )
    track_message(context, prompt.message_id)


async def handle_checkout_employee_selected(query, context: ContextTypes.DEFAULT_TYPE):
    """Callback khi nhân viên chọn tên để check-out (Xử lý trực tiếp, KHÔNG cần gửi ảnh)"""
    nickname = query.data[len("co_sel_"):]
    
    if nickname == "cancel":
        await _cancel_flow(query, context)
        return
    
    sheets_service = context.bot_data['sheets']
    
    # Sửa tin nhắn chọn tên thành trạng thái đang xử lý
    await query.edit_message_text(f"⏳ Đang ghi nhận check-out cho {nickname}...")
    
    result = await asyncio.to_thread(sheets_service.checkout, nickname)
    
    if not result['success']:
        error = result.get('error', '')
        if error == 'not_checked_in':
            await query.edit_message_text(
                f"⚠️ {nickname} chưa check-in hôm nay! Hãy bấm 📥 Check In trước."
            )
        else:
            await query.edit_message_text(f"❌ Lỗi check-out: {error}")
        return
    
    # Xóa message chọn tên, gửi 1 message kết quả + keyboard
    try:
        await query.message.delete()
    except Exception:
        pass

    confirm_text = f"✅ {nickname} ra ca — {time_str} ({total_hours}h)"
    keyboard = get_admin_keyboard() if query.message.chat.id == Config.ADMIN_CHAT_ID else get_main_keyboard()
    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=confirm_text,
        reply_markup=keyboard
    )


async def handle_checkin_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý ảnh check-in: ghi giờ vào sheet, chuyển tiếp ảnh cho admin"""
    nickname = context.chat_data.pop('awaiting_checkin_photo', None)
    if not nickname:
        return
    
    message = update.message
    sheets_service = context.bot_data['sheets']
    
    # Xóa tin nhắn cũ
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        await delete_tracked_messages(context, update.effective_chat.id)
    
    # Ghi nhận check-in vào sheet
    status_msg = await message.reply_text(f"⏳ Đang ghi nhận check-in cho {nickname}...")
    track_message(context, status_msg.message_id)
    
    result = await asyncio.to_thread(sheets_service.checkin, nickname)
    
    if not result['success']:
        error = result.get('error', '')
        if error == 'already_checked_in':
            checkin_time = result.get('time', '?')
            await status_msg.edit_text(
                f"⚠️ **{nickname}** đã check-in hôm nay rồi!\n"
                f"⏰ Giờ vào: {checkin_time}\n\n"
                f"Hãy bấm 📤 **Check Out** khi kết thúc ca.",
                parse_mode='Markdown'
            )
        else:
            await status_msg.edit_text(f"❌ Lỗi check-in: {error}")
        return
    
    time_str  = result['time']
    note      = result['note']
    ca        = result['ca']
    late_minutes = result['late_minutes']
    date_str  = result['date_str']

    # Gửi admin ảnh check-in
    try:
        photo = message.photo[-1]
        admin_caption = f"📥 {nickname} — {time_str} Ca {ca} | {note}"
        await context.bot.send_photo(
            chat_id=Config.ADMIN_CHAT_ID,
            photo=photo.file_id,
            caption=admin_caption
        )
        if late_minutes > 0:
            late_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Đã báo trước",
                    callback_data=f"mark_reported_{date_str}_{nickname}"),
                 InlineKeyboardButton("❌ Không báo trước",
                    callback_data=f"mark_unreported_{date_str}_{nickname}")]
            ])
            await context.bot.send_message(
                chat_id=Config.ADMIN_CHAT_ID,
                text=f"⚠️ {nickname} muộn {late_minutes}p (Ca {ca}) — báo trước?",
                reply_markup=late_keyboard
            )
    except Exception as e:
        logger.warning(f"Không thể chuyển tiếp ảnh check-in cho admin: {e}")

    # Xóa ⏳, gửi 1 message kết quả + keyboard
    try:
        await status_msg.delete()
    except Exception:
        pass
    keyboard = get_admin_keyboard() if update.effective_chat.id == Config.ADMIN_CHAT_ID else get_main_keyboard()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"✅ {nickname} — {time_str} | Ca {ca} | {note}",
        reply_markup=keyboard
    )



async def handle_mark_reported_late(query, context: ContextTypes.DEFAULT_TYPE):
    """Admin bấm nút xác nhận nhân viên đã báo trước khi trễ"""
    # callback_data format: mark_reported_{date_str}_{nickname}
    data = query.data[len("mark_reported_"):]
    # date_str format: dd/mm/YYYY — split from the right since nickname may contain _
    parts = data.split("_", 1)
    if len(parts) != 2:
        await query.answer("❌ Dữ liệu không hợp lệ", show_alert=True)
        return
    
    date_str = parts[0]
    nickname = parts[1]
    
    sheets_service = context.bot_data['sheets']
    success = await asyncio.to_thread(sheets_service.mark_reported_late, nickname, date_str)
    
    if success:
        await query.edit_message_text(
            f"✅ {nickname} ngày {date_str}: ĐÃ báo trước."
        )
    else:
        await query.answer("⚠️ Không tìm thấy record hoặc đã đánh dấu rồi.", show_alert=True)

async def handle_mark_unreported_late(query, context: ContextTypes.DEFAULT_TYPE):
    """Admin bấm nút xác nhận nhân viên không báo trước khi trễ"""
    data = query.data[len("mark_unreported_"):]
    parts = data.split("_", 1)
    if len(parts) != 2:
        await query.answer("❌ Dữ liệu không hợp lệ", show_alert=True)
        return
    
    date_str = parts[0]
    nickname = parts[1]
    
    sheets_service = context.bot_data['sheets']
    success = await asyncio.to_thread(sheets_service.mark_unreported_late, nickname, date_str)
    
    if success:
        await query.edit_message_text(
            f"❌ {nickname} ngày {date_str}: KHÔNG báo trước."
        )
    else:
        await query.answer("⚠️ Không tìm thấy record hoặc đã đánh dấu rồi.", show_alert=True)


async def _cancel_flow(query, context: ContextTypes.DEFAULT_TYPE):
    """Hủy flow check-in/check-out và gửi lại bàn phím"""
    context.chat_data.pop('awaiting_checkin_photo', None)
    context.chat_data.pop('awaiting_checkout_photo', None)
    
    chat_id = query.message.chat.id
    
    if chat_id == Config.GROUP_CHAT_ID:
        await delete_tracked_messages(context, chat_id)
        try:
            await query.message.delete()
        except Exception:
            pass
    
    keyboard = get_admin_keyboard() if chat_id == Config.ADMIN_CHAT_ID else get_main_keyboard()
    await context.bot.send_message(
        chat_id=chat_id,
        text="❌ Đã hủy.",
        reply_markup=keyboard
    )
