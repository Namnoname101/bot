import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.auto_delete import delete_tracked_messages, track_message, get_main_keyboard, get_admin_keyboard, GUIDE_MESSAGE
from utils.admin import is_admin, is_super_admin
from config import Config

logger = logging.getLogger(__name__)


def _job_shift_ca(context) -> str:
    """Lấy ca được gắn vào JobQueue, an toàn khi callback chạy thủ công/test."""
    job = getattr(context, 'job', None)
    data = getattr(job, 'data', None) or {}
    return data.get('shift_ca', '')


def _open_sessions_text(sessions: list) -> str:
    lines = []
    for session in sessions:
        lines.append(
            f"• {session['nickname']} — {session.get('ca') or session.get('shift_type')} "
            f"(vào {session['checkin_time']})"
        )
    return "\n".join(lines)


async def send_checkout_reminder(context):
    """Nhắc group đúng giờ kết ca; không tự động chốt giờ ra."""
    shift_ca = _job_shift_ca(context)
    if not shift_ca:
        return

    try:
        sheets = context.bot_data['sheets']
        sessions = await asyncio.to_thread(sheets.get_open_checkin_sessions, shift_ca)
        if not sessions:
            return

        await context.bot.send_message(
            chat_id=Config.GROUP_CHAT_ID,
            text=(
                f"⏰ Đã đến giờ kết ca {shift_ca}.\n"
                f"Các phiên chưa Check Out:\n{_open_sessions_text(sessions)}\n\n"
                "Nếu vẫn đang dọn dẹp/làm thêm, cứ để ca mở và bấm Check Out sau khi xong."
            )
        )
        logger.info("Đã nhắc Check Out ca %s cho %d phiên.", shift_ca, len(sessions))
    except Exception as e:
        logger.error("Lỗi gửi nhắc Check Out ca %s: %s", shift_ca, e)


async def alert_unclosed_sessions(context):
    """Sau 15 phút, báo quản lý các phiên ca chính vẫn chưa chốt."""
    shift_ca = _job_shift_ca(context)
    if not shift_ca:
        return

    try:
        sheets = context.bot_data['sheets']
        sessions = await asyncio.to_thread(sheets.get_open_checkin_sessions, shift_ca)
        if not sessions:
            return

        await context.bot.send_message(
            chat_id=Config.ADMIN_CHAT_ID,
            text=(
                f"⚠️ Đã quá 15 phút sau giờ kết ca {shift_ca}, vẫn còn phiên chưa Check Out:\n"
                f"{_open_sessions_text(sessions)}\n\n"
                "Vui lòng kiểm tra nhân viên đang làm thêm hay quên thao tác. Không tự động đóng ca."
            )
        )
        logger.info("Đã báo quản lý các phiên mở quá hạn ca %s.", shift_ca)
    except Exception as e:
        logger.error("Lỗi báo phiên chưa Check Out ca %s: %s", shift_ca, e)


async def midnight_auto_cleanup(context):
    """Quét dọn lúc 23:55: Tự động chốt các phiên chưa check-out trong ngày."""
    try:
        sheets = context.bot_data['sheets']
        sessions = await asyncio.to_thread(sheets.get_open_checkin_sessions)
        if not sessions:
            logger.info("Midnight auto-cleanup: Không có phiên nào cần chốt.")
            return

        closed_count = 0
        for session in sessions:
            nickname = session['nickname']
            shift_ca = session.get('ca', '')
            shift_type = session.get('shift_type', '')
            
            # Chỉ tự động chốt cho Ca Chính. Ca Gãy bỏ qua hoặc có thể xử lý sau.
            if shift_type == "Ca Chính":
                force_time = None
                if shift_ca == 'Sáng':
                    force_time = "12:00:00"
                elif shift_ca == 'Chiều':
                    force_time = "18:00:00"
                elif shift_ca == 'Tối':
                    force_time = "23:00:00"
                
                if force_time:
                    result = await asyncio.to_thread(sheets.checkout, nickname, shift_type, force_time)
                    if result.get('success'):
                        closed_count += 1
                        
        if closed_count > 0:
            await context.bot.send_message(
                chat_id=Config.ADMIN_CHAT_ID,
                text=f"🧹 **Dọn Dẹp Cuối Ngày**: Đã tự động chốt ca (Auto-Checkout) thành công cho {closed_count} phiên chưa chốt với giờ mặc định.",
                parse_mode='Markdown'
            )
            logger.info(f"Midnight auto-cleanup: Đã tự động chốt {closed_count} phiên.")
    except Exception as e:
        logger.error(f"Lỗi khi auto-cleanup cuối ngày: {e}")


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


def _build_checkout_picker(sessions: list):
    """Tạo picker checkout theo từng phiên, không gộp các ca cùng nickname."""
    keyboard = []
    row = []
    for session in sessions:
        nickname = session['nickname']
        shift_type = session.get('shift_type', 'Ca Chính')
        token = 'ot' if shift_type == 'Ca Gãy' else 'main'
        ca_label = session.get('ca') or shift_type.replace('Ca ', '')
        label = f"{nickname} — {ca_label}"
        row.append(InlineKeyboardButton(label, callback_data=f"co_sel_{token}_{nickname}"))
        if len(row) == 1:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Hủy", callback_data="co_sel_cancel")])
    return InlineKeyboardMarkup(keyboard)

async def handle_checkin_type_selected(query, context: ContextTypes.DEFAULT_TYPE):
    """Callback khi nhân viên chọn loại ca (Chính/Gãy)"""
    shift_type = query.data[len("ci_type_"):]
    if shift_type == "cancel":
        await _cancel_flow(query, context)
        return
        
    context.chat_data['awaiting_checkin_type'] = f"Ca {shift_type}"
    
    await query.edit_message_text("⏳ Đang tải danh sách nhân viên...")
    
    sheets_service = context.bot_data['sheets']
    balances = await asyncio.to_thread(sheets_service.get_all_balances)
    
    if not balances:
        await query.edit_message_text("📉 Chưa có dữ liệu nhân viên trên hệ thống.")
        return
        
    reply_markup = _build_employee_picker(balances, "ci_sel")
    await query.edit_message_text(f"📥 **CHECK IN** ({context.chat_data['awaiting_checkin_type']}) — Bạn là ai?", reply_markup=reply_markup, parse_mode='Markdown')



async def handle_checkin_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi nhân viên bấm nút '📥 Check In'"""
    keyboard = [
        [InlineKeyboardButton("🌞 Ca Chính", callback_data="ci_type_Chính"),
         InlineKeyboardButton("🌗 Ca Gãy", callback_data="ci_type_Gãy")],
        [InlineKeyboardButton("❌ Hủy", callback_data="ci_type_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    reply = await update.message.reply_text("📥 **CHECK IN** — Chọn loại ca làm việc:", reply_markup=reply_markup, parse_mode='Markdown')
    
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)


async def handle_checkout_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi nhân viên bấm nút '📤 Check Out'"""
    sheets_service = context.bot_data['sheets']
    sessions = await asyncio.to_thread(sheets_service.get_open_checkin_sessions)
    
    if not sessions:
        reply = await update.message.reply_text("📉 Không có nhân viên nào đang trong ca (chưa check-out).")
        if update.effective_chat.id == Config.GROUP_CHAT_ID:
            track_message(context, reply.message_id)
        return
    
    reply_markup = _build_checkout_picker(sessions)
    reply = await update.message.reply_text(
        "📤 **CHECK OUT** — Chọn đúng phiên làm việc:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)


async def handle_checkin_employee_selected(query, context: ContextTypes.DEFAULT_TYPE):
    """Callback khi nhân viên chọn tên để check-in (Xử lý trực tiếp, KHÔNG cần gửi ảnh)"""
    nickname = query.data[len("ci_sel_"):]
    
    if nickname == "cancel":
        await _cancel_flow(query, context)
        return
        
    shift_type = context.chat_data.pop('awaiting_checkin_type', '')
    sheets_service = context.bot_data['sheets']
    
    # Xóa message chọn tên
    if query.message and query.message.chat.id == Config.GROUP_CHAT_ID:
        await delete_tracked_messages(context, query.message.chat.id)
    try:
        await query.message.delete()
    except Exception:
        pass
        
    # Ghi nhận check-in
    status_msg = await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=f"⏳ Đang ghi nhận check-in cho {nickname}..."
    )
    
    result = await asyncio.to_thread(sheets_service.checkin, nickname, shift_type)
    
    if not result['success']:
        error = result.get('error', '')
        if error == 'already_checked_in':
            checkin_time = result.get('time', '?')
            text = (f"⚠️ **{nickname}** đã check-in hôm nay rồi!\n"
                    f"⏰ Giờ vào: {checkin_time}\n\n"
                    f"Hãy bấm 📤 **Check Out** khi kết thúc ca.")
        else:
            text = f"❌ Lỗi check-in: {error}"
            
        try:
            await status_msg.delete()
        except Exception:
            pass
        keyboard = get_admin_keyboard(is_super_admin=is_super_admin(query.message.chat.id)) if is_admin(query.message.chat.id, context) else get_main_keyboard()
        await context.bot.send_message(chat_id=query.message.chat.id, text=text, reply_markup=keyboard, parse_mode='Markdown')
        return

    time_str  = result['time']
    note      = result['note']
    ca        = result['ca']
    late_minutes = result['late_minutes']
    date_str  = result['date_str']

    # Gửi admin thông báo check-in
    try:
        admin_text = f"📥 {nickname} — {time_str} Ca {ca} | {note}"
        await context.bot.send_message(
            chat_id=Config.ADMIN_CHAT_ID,
            text=admin_text
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
        logger.warning(f"Không thể báo admin check-in: {e}")

    # Xóa ⏳, gửi 1 message kết quả + keyboard
    try:
        await status_msg.delete()
    except Exception:
        pass
    keyboard = get_admin_keyboard(is_super_admin=is_super_admin(query.message.chat.id)) if is_admin(query.message.chat.id, context) else get_main_keyboard()
    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=f"✅ Cảm ơn {nickname}, đã ghi nhận check-in thành công!",
        reply_markup=keyboard
    )




async def handle_checkout_employee_selected(query, context: ContextTypes.DEFAULT_TYPE):
    """Callback khi nhân viên chọn tên để check-out (Xử lý trực tiếp, KHÔNG cần gửi ảnh)"""
    payload = query.data[len("co_sel_"):]
    
    if payload == "cancel":
        await _cancel_flow(query, context)
        return

    # Callback mới có dạng co_sel_main_<nickname> hoặc co_sel_ot_<nickname>.
    # Vẫn chấp nhận payload cũ chỉ chứa nickname để không làm hỏng nút cũ.
    shift_type = None
    if payload.startswith("main_"):
        shift_type = "Ca Chính"
        nickname = payload[len("main_"):]
    elif payload.startswith("ot_"):
        shift_type = "Ca Gãy"
        nickname = payload[len("ot_"):]
    else:
        nickname = payload
    
    sheets_service = context.bot_data['sheets']
    
    # Sửa tin nhắn chọn tên thành trạng thái đang xử lý
    shift_label = f" ({shift_type})" if shift_type else ""
    await query.edit_message_text(f"⏳ Đang ghi nhận check-out cho {nickname}{shift_label}...")
    
    result = await asyncio.to_thread(sheets_service.checkout, nickname, shift_type)
    
    if not result['success']:
        error = result.get('error', '')
        if error == 'not_checked_in':
            text = f"⚠️ {nickname} chưa check-in hôm nay! Hãy bấm 📥 Check In trước."
        else:
            text = f"❌ Lỗi check-out: {error}"
            
        try:
            await query.message.delete()
        except Exception:
            pass
        keyboard = get_admin_keyboard(is_super_admin=is_super_admin(query.message.chat.id)) if is_admin(query.message.chat.id, context) else get_main_keyboard()
        await context.bot.send_message(chat_id=query.message.chat.id, text=text, reply_markup=keyboard)
        return
    
    # Xóa message chọn tên, gửi 1 message kết quả + keyboard
    try:
        await query.message.delete()
    except Exception:
        pass

    result_shift = result.get('shift_type') or shift_type or 'Ca làm việc'
    confirm_text = f"✅ {nickname} ra {result_shift} — {result['time']} ({result['total_hours']}h)"
        
    keyboard = get_admin_keyboard(is_super_admin=is_super_admin(query.message.chat.id)) if is_admin(query.message.chat.id, context) else get_main_keyboard()
    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=f"✅ Cảm ơn {nickname}, đã ghi nhận check-out thành công!",
        reply_markup=keyboard
    )

    # Gửi thông báo cho quản lý để xác nhận các ca ra muộn/làm thêm.
    try:
        await context.bot.send_message(
            chat_id=Config.ADMIN_CHAT_ID,
            text=(
                f"📤 Check Out cần quản lý kiểm tra\n"
                f"👤 {nickname}\n"
                f"🕐 {result_shift}: {result['time']}\n"
                f"⏱ Tổng thời gian: {result['total_hours']}h"
            )
        )
    except Exception as e:
        logger.warning(f"Không thể báo quản lý sau khi check-out: {e}")

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
    context.chat_data.pop('awaiting_checkin_type', None)
    context.chat_data.pop('awaiting_checkout_photo', None)
    
    chat_id = query.message.chat.id
    
    await delete_tracked_messages(context, chat_id)
    try:
        await query.message.delete()
    except Exception:
        pass
    
    keyboard = get_admin_keyboard(is_super_admin=is_super_admin(chat_id)) if is_admin(chat_id, context) else get_main_keyboard()
    msg = await context.bot.send_message(chat_id=chat_id, text="❌ Đã huỷ thao tác.", reply_markup=keyboard)
    track_message(context, msg.message_id)
