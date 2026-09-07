import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.time_utils import local_now
from utils.decorators import group_only, admin_only
from utils.validators import (
    check_reward_eligibility,
    deduplicate_employees,
    normalize_name,
    parse_report_text,
)
from utils.auto_delete import GUIDE_MESSAGE, get_main_keyboard, get_admin_keyboard, delete_tracked_messages, track_message
from config import Config
from handlers.checkin_handler import (
    handle_checkin_button, handle_checkout_button,
    handle_checkin_employee_selected, handle_checkin_ca_selected,
    handle_checkout_employee_selected,
    handle_mark_reported_late, handle_mark_unreported_late
)
from handlers.overtime_handler import (
    handle_overtime_summary_button, handle_grant_admin_button,
    handle_grant_admin_input, handle_add_overtime_button,
    handle_overtime_employee_selected, handle_overtime_hours_input,
)
from handlers.management_handler import (
    handle_manage_nv_button, handle_checkin_history_button,
    handle_late_stats_button, handle_edit_report_button,
    handle_add_employee_input, handle_edit_revenue_input, handle_edit_salary_rate_input,

    handle_mgmt_callback, handle_edit_employee_name_input
)
from handlers.endshift_handler import (
    handle_endshift_button, handle_endshift_ca_selected,
    handle_endshift_role_selected, handle_endshift_send,
    handle_endshift_cancel, _cancel_endshift_tasks
)
from handlers.salary_handler import handle_salary_button, process_salary_input, handle_salary_modifier_request
from utils.admin import is_admin, is_super_admin

logger = logging.getLogger(__name__)

@group_only
async def use_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hiện xác nhận trừ thưởng: ``/dadung [nickname]``."""
    balances = await asyncio.to_thread(context.bot_data['sheets'].get_all_balances)
    if not balances:
        await update.message.reply_text("📉 Chưa có dữ liệu nhân viên trên hệ thống.")
        return

    requested = " ".join(context.args).strip()
    if requested:
        nickname = next(
            (nick for nick in balances if normalize_name(nick) == normalize_name(requested)),
            None,
        )
        if not nickname:
            await update.message.reply_text(f"❌ Không tìm thấy nhân viên: {requested}.")
            return
        if int(balances[nickname]) <= 0:
            await update.message.reply_text(f"❌ {nickname} không còn ly nào!")
            return
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Dùng ngay!", callback_data=f"urw_confirm_{nickname}"),
            InlineKeyboardButton("❌ Thôi", callback_data="urw_cancel"),
        ]])
        await update.message.reply_text(
            f"🥤 {nickname} chắc dùng 1 ly thưởng chứ? (Còn {balances[nickname]} ly)",
            reply_markup=markup,
        )
        return

    keyboard = _nickname_keyboard(balances, "use_reward_")
    await update.message.reply_text("❓ Ai đang dùng thưởng?", reply_markup=keyboard)

@group_only
async def check_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tra cứu thưởng: ``/thuong [nickname]``."""
    balances = await asyncio.to_thread(context.bot_data['sheets'].get_all_balances)
    if not balances:
        await update.message.reply_text("📉 Chưa có dữ liệu nhân viên trên hệ thống.")
        return

    requested = " ".join(context.args).strip()
    if requested:
        nickname = next(
            (nick for nick in balances if normalize_name(nick) == normalize_name(requested)),
            None,
        )
        if not nickname:
            await update.message.reply_text(f"❌ Không tìm thấy nhân viên: {requested}.")
            return
        await update.message.reply_text(f"🎁 {nickname}: {balances[nickname]} ly thưởng.")
        return

    await update.message.reply_text(
        "❓ Bạn muốn tra cứu thưởng của ai?",
        reply_markup=_nickname_keyboard(balances, "check_reward_"),
    )

@admin_only
async def check_all_rewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh xem toàn bộ cho Quản lý: /bangthuong"""
    balances = await asyncio.to_thread(context.bot_data['sheets'].get_all_balances)
    if not balances:
        msg = await update.message.reply_text("📉 Chưa có dữ liệu thưởng trên hệ thống.")
        if update.effective_chat.id == Config.GROUP_CHAT_ID:
            track_message(context, msg.message_id)
        return
        
    sorted_bal = sorted(balances.items(), key=lambda x: -int(x[1]))
    lines = ["📊 *BẢNG THƯởNG:*"]
    for nick, bal in sorted_bal:
        icon = "🎁" if int(bal) > 0 else "⬜"
        lines.append(f"{icon} {nick}: {bal} ly")
    msg = "\n".join(lines)
    reply = await update.message.reply_text(msg, parse_mode='Markdown')
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)

@group_only
async def quick_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ghi báo cáo chữ: ``/baodoanhthu NV: a, b DT: 1500k``."""
    payload = update.message.text.partition(' ')[2].strip()
    if not payload:
        await update.message.reply_text(
            "Cách dùng: /baodoanhthu NV: ten1, ten2 DT: 1500k Ca: Sáng"
        )
        return

    employees, revenue, ca, error_msg = parse_report_text(payload)
    if error_msg:
        await update.message.reply_text(f"❌ {error_msg}")
        return
    employees = deduplicate_employees(employees)

    sheets = context.bot_data['sheets']
    valid_nicknames = await asyncio.to_thread(sheets.get_all_nicknames)
    invalid = [emp for emp in employees if normalize_name(emp) not in valid_nicknames]
    if invalid:
        await update.message.reply_text(f"❌ Sai tên nhân viên: {', '.join(invalid)}.")
        return

    report_key = f"quick:{update.effective_chat.id}:{update.message.message_id}"
    processed = context.bot_data.setdefault('processed_reports', set())
    if report_key in processed:
        await update.message.reply_text("ℹ️ Báo cáo này đã được xử lý trước đó.")
        return
    processed.add(report_key)

    now = local_now()
    result = await asyncio.to_thread(
        sheets.save_report,
        date=now.strftime("%d/%m/%Y"),
        employees=employees,
        revenue=revenue,
        ca=ca,
        report_key=report_key,
    )
    if not result:
        processed.discard(report_key)
        await update.message.reply_text("❌ Không thể lưu báo cáo. Vui lòng thử lại.")
        return
    if result == 'duplicate':
        await update.message.reply_text("ℹ️ Báo cáo này đã được xử lý trước đó.")
        return

    reward_count = check_reward_eligibility(len(employees), revenue)
    if reward_count and not await asyncio.to_thread(
        sheets.batch_update_balances, employees, reward_count
    ):
        await update.message.reply_text(
            "⚠️ Báo cáo đã lưu nhưng chưa cộng được thưởng; quản lý cần kiểm tra lại."
        )
        logger.error("Quick report %s lưu thành công nhưng cộng thưởng thất bại", report_key)
        return

    resolved_ca = ca or ('Sáng' if now.hour < 12 else 'Chiều' if now.hour < 18 else 'Tối')
    reward_line = f"\n🎁 +{reward_count} ly/người" if reward_count else ""
    await update.message.reply_text(
        f"✅ Đã ghi báo cáo {resolved_ca}: {', '.join(employees)} — "
        f"{revenue:,} VNĐ{reward_line}"
    )


def _nickname_keyboard(balances: dict, callback_prefix: str) -> InlineKeyboardMarkup:
    """Tạo lưới chọn nickname dùng chung cho lệnh và bàn phím chính."""
    rows, row = [], []
    for nickname in balances:
        row.append(InlineKeyboardButton(nickname, callback_data=f"{callback_prefix}{nickname}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /cancel để huỷ bỏ mọi trạng thái hiện tại và hiện lại bàn phím"""
    context.user_data.clear()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    keyboard = get_admin_keyboard(is_super_admin=is_super_admin(user_id)) if is_admin(user_id, context) else get_main_keyboard()
    msg = await update.message.reply_text("❌ Đã huỷ toàn bộ thao tác hiện tại.", reply_markup=keyboard)
    if chat_id == Config.GROUP_CHAT_ID:
        track_message(context, msg.message_id)

@admin_only
async def announce_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /announce <nội dung> để Admin gửi thông báo cập nhật vào group"""
    if not context.args:
        await update.message.reply_text("⚠️ Cách dùng: /announce [Nội dung thông báo]")
        return
        
    message = " ".join(context.args)
    announcement = f"🚀 THÔNG BÁO CẬP NHẬT:\n\n{message}"
    
    await context.bot.send_message(
        chat_id=Config.GROUP_CHAT_ID,
        text=announcement,
        parse_mode=None
    )
    if update.effective_chat.id != Config.GROUP_CHAT_ID:
        await update.message.reply_text("✅ Đã gửi thông báo vào nhóm chung!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh hướng dẫn sử dụng bot"""
    if not update.effective_chat or not update.effective_user or not (
        update.effective_chat.id == Config.GROUP_CHAT_ID or is_admin(update.effective_user.id, context)
    ):
        return

    user_id = update.effective_user.id
    keyboard = get_admin_keyboard(is_super_admin=is_super_admin(user_id)) if is_admin(user_id, context) else get_main_keyboard()
    reply = await update.message.reply_text(GUIDE_MESSAGE, parse_mode='Markdown', reply_markup=keyboard)
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /start để hiển thị bàn phím ảo (Reply Keyboard)"""
    if not update.effective_chat:
        return

    user_id = update.effective_user.id
    keyboard = get_admin_keyboard(is_super_admin=is_super_admin(user_id)) if is_admin(user_id, context) else get_main_keyboard()
    reply = await update.message.reply_text("👋 Bot Sô bơ — sử dụng các nút bên dưới:", reply_markup=keyboard)
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)

def build_multi_select_keyboard(selection: dict):
    keyboard = []
    row = []
    for nick, is_sel in selection.items():
        text = f"✅ {nick}" if is_sel else nick
        row.append(InlineKeyboardButton(text, callback_data=f"toggle_emp_{nick}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("➡️ Xác Nhận", callback_data="confirm_report_emps")])
    keyboard.append([InlineKeyboardButton("❌ Hủy", callback_data="cancel_report_emps")])
    
    return InlineKeyboardMarkup(keyboard)

async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi người dùng bấm vào các nút trên bàn phím ảo hoặc gõ text"""
    if not update.effective_chat or not update.effective_user or not (
        update.effective_chat.id == Config.GROUP_CHAT_ID or is_admin(update.effective_user.id, context)
    ):
        return
    user_id = update.effective_user.id
    text = update.message.text

    # ── KIỂM TRA TEXT INPUT ĐANG CHỜ TRƯỚC KHI XÓA STATE ──
    if context.user_data.get('awaiting_admin_id'):
        handled = await handle_grant_admin_input(update, context)
        if handled:
            return

    if context.user_data.get('awaiting_edit_emp_name'):
        handled = await handle_edit_employee_name_input(update, context)
        if handled:
            return

    if context.user_data.get('awaiting_overtime_hours'):
        handled = await handle_overtime_hours_input(update, context)
        if handled:
            return


    # ── Kiểm tra state management mới ──
    if context.user_data.get('awaiting_add_employee_name'):
        handled = await handle_add_employee_input(update, context)
        if handled:
            return

    if context.user_data.get('awaiting_edit_report_revenue'):
        handled = await handle_edit_revenue_input(update, context)
        if handled:
            return

    if context.user_data.get('awaiting_edit_salary_rate'):
        handled = await handle_edit_salary_rate_input(update, context)
        if handled:
            return

    if context.user_data.get('salary_action'):
        handled = await process_salary_input(update, context)
        if handled:
            return

    if context.user_data.get('awaiting_feedback'):
        if text.startswith('/cancel'):
            context.user_data.pop('awaiting_feedback', None)
            reply = await update.message.reply_text("❌ Đã huỷ gửi ý kiến.")
            if update.effective_chat.id == Config.GROUP_CHAT_ID:
                track_message(context, reply.message_id)
            return True

        # Gửi thẳng ý kiến cho admin
        await context.bot.send_message(
            chat_id=Config.ADMIN_CHAT_ID,
            text=f"💡 GÓP Ý TỪ NHÂN VIÊN:\n\n{text}",
        )
        
        # Xoá tin nhắn góp ý để giữ ẩn danh
        if update.effective_chat.id == Config.GROUP_CHAT_ID:
            try:
                await update.message.delete()
            except Exception:
                pass
                
        context.user_data.pop('awaiting_feedback', None)
        keyboard = get_admin_keyboard(is_super_admin=is_super_admin(user_id)) if is_admin(user_id, context) else get_main_keyboard()
        msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Cảm ơn bạn! Đóng góp của bạn đã được gửi trực tiếp cho Quản lý.", reply_markup=keyboard)
        if update.effective_chat.id == Config.GROUP_CHAT_ID:
            track_message(context, msg.message_id)
        return True

    # ── Nút kết ca gửi ảnh — xử lý TRƯỚC KHI clear state ──
    if text == "📤 Gửi ảnh kết ca":
        await handle_endshift_send(update, context)
        return

    # ── Dọn dẹp tin nhắn cũ khi có thao tác NÚT mới (không phải input) ──
    # Chỉ chạy đến đây nếu KHÔNG phải đang chờ OT hoặc revenue
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        await delete_tracked_messages(context, update.effective_chat.id)
        try:
            await update.message.delete()
        except Exception:
            pass

    # ── HỦY TẤT CẢ TRẠNG THÁI KHI BẤM NÚT MỚI ──
    context.user_data.pop('awaiting_checkin_photo', None)
    context.user_data.pop('awaiting_checkin_type', None)
    context.user_data.pop('awaiting_checkin_ca', None)
    context.user_data.pop('awaiting_overtime_hours', None)
    context.user_data.pop('awaiting_add_employee_name', None)
    context.user_data.pop('awaiting_edit_emp_name', None)
    context.user_data.pop('awaiting_edit_report_revenue', None)
    context.user_data.pop('awaiting_feedback', None)
    context.user_data.pop('awaiting_admin_id', None)
    _cancel_endshift_tasks(context)

    if text == "📖 Hướng Dẫn":
        await help_command(update, context)
        
    elif text == "💡 Đóng Góp Ý Kiến":
        context.user_data['awaiting_feedback'] = True
        reply = await update.message.reply_text(
            "💡 **ĐÓNG GÓP Ý KIẾN**\n\n"
            "Hãy gõ nội dung bạn muốn gửi cho Quản lý vào khung chat bên dưới rồi nhấn Gửi.\n"
            "_(Tin nhắn của bạn sẽ được ẩn danh và chỉ Quản lý mới đọc được)_\n\n"
            "Hoặc gõ /cancel để huỷ.",
            parse_mode='Markdown'
        )
        if update.effective_chat.id == Config.GROUP_CHAT_ID:
            track_message(context, reply.message_id)
    
    elif text == "📥 Check In":
        await handle_checkin_button(update, context)
    
    elif text == "📤 Check Out":
        await handle_checkout_button(update, context)

    elif text == "🔚 Kết Ca":
        await handle_endshift_button(update, context)
    elif text == "💸 Ứng Lương (QL)":
        await handle_salary_modifier_request(update, context, "salary_adv")
        
    elif text == "🎁 Thưởng Tiền (QL)":
        await handle_salary_modifier_request(update, context, "salary_bon")
        
    elif text == "⚡ Thưởng Doanh Thu":
        sheets_service = context.bot_data['sheets']
        balances = await asyncio.to_thread(sheets_service.get_all_balances)
        if not balances:
            reply = await update.message.reply_text("📉 Chưa có dữ liệu nhân viên trên hệ thống.")
            if update.effective_chat.id == Config.GROUP_CHAT_ID:
                track_message(context, reply.message_id)
            return

        context.user_data['report_selection'] = {nick: False for nick in balances.keys()}
        reply_markup = build_multi_select_keyboard(context.user_data['report_selection'])
        reply = await update.message.reply_text("⚡ Ca này gồm những ai? (Chạm để chọn):", reply_markup=reply_markup)
        if update.effective_chat.id == Config.GROUP_CHAT_ID:
            track_message(context, reply.message_id)
            
    elif text == "🎁 Tra Cứu Thưởng":
        sheets_service = context.bot_data['sheets']
        balances = await asyncio.to_thread(sheets_service.get_all_balances)
        if not balances:
            reply = await update.message.reply_text("📉 Chưa có dữ liệu nhân viên trên hệ thống.")
            if update.effective_chat.id == Config.GROUP_CHAT_ID:
                track_message(context, reply.message_id)
            return
            
        keyboard = []
        row = []
        for nick in balances.keys():
            row.append(InlineKeyboardButton(nick, callback_data=f"check_reward_{nick}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        reply = await update.message.reply_text("❓ Bạn muốn tra cứu thưởng của ai?", reply_markup=reply_markup)
        
        if update.effective_chat.id == Config.GROUP_CHAT_ID:
            track_message(context, reply.message_id)
            
    elif text == "🥤 Báo Dùng Thưởng":
        sheets_service = context.bot_data['sheets']
        balances = await asyncio.to_thread(sheets_service.get_all_balances)
        if not balances:
            reply = await update.message.reply_text("📉 Chưa có dữ liệu nhân viên trên hệ thống.")
            if update.effective_chat.id == Config.GROUP_CHAT_ID:
                track_message(context, reply.message_id)
            return
            
        keyboard = []
        row = []
        for nick in balances.keys():
            row.append(InlineKeyboardButton(nick, callback_data=f"use_reward_{nick}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        reply = await update.message.reply_text("❓ Ai đang dùng thưởng?", reply_markup=reply_markup)
        
        if update.effective_chat.id == Config.GROUP_CHAT_ID:
            track_message(context, reply.message_id)
            
    elif text == "📊 Bảng Thưởng (QL)":
        await check_all_rewards(update, context)

    elif text == "🧾 Quản Lý NV (QL)":
        await handle_manage_nv_button(update, context)

    elif text == "✏️ Sửa Doanh Thu":
        await handle_edit_report_button(update, context)

    elif text == "📋 Lịch Sử Check-In":
        await handle_checkin_history_button(update, context)

    elif text == "⚠️ Thống Kê Đi Muộn":
        await handle_late_stats_button(update, context)

    elif text == "📊 Thống Kê Giờ LT":
        await handle_overtime_summary_button(update, context)

    elif text == "➕ Giờ LT (QL)":
        await handle_add_overtime_button(update, context)

    elif text == "💰 Tính Lương (QL)":
        await handle_salary_button(update, context)

    elif text == "👑 Cấp Quyền QL":
        await handle_grant_admin_button(update, context)


async def inline_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý các nút bấm Inline Keyboard"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    sheets_service = context.bot_data['sheets']
    # Trước khi xử lý callback, xóa các tin nhắn tracked khác nhưng giữ lại message này
    if update.effective_chat and update.effective_chat.id == Config.GROUP_CHAT_ID:
        try:
            await delete_tracked_messages(context, update.effective_chat.id, exclude={query.message.message_id})
        except Exception:
            pass

    # query.message.message_id is inherently tracked because it was a prompt created via button_click_handler
    
    if data.startswith('mgmt_'):
        await handle_mgmt_callback(query, context)
        return

    if data.startswith('salary_') or data.startswith('sal_emp_'):
        from handlers.salary_handler import salary_inline_handler
        await salary_inline_handler(update, context)
        return

    if data.startswith('ks_ca_'):
        await handle_endshift_ca_selected(query, context)
        return

    if data.startswith('ks_role_'):
        await handle_endshift_role_selected(query, context)
        return

    if data == 'ks_cancel':
        await handle_endshift_cancel(query, context)
        return

    if data.startswith("ci_type_"):
        from handlers.checkin_handler import handle_checkin_type_selected
        await handle_checkin_type_selected(query, context)
        return

    if data.startswith("ci_ca_"):
        await handle_checkin_ca_selected(query, context)
        return

    if data.startswith("ci_sel_"):
        await handle_checkin_employee_selected(query, context)
        return
    
    if data.startswith("co_sel_"):
        await handle_checkout_employee_selected(query, context)
        return
    
    if data.startswith("ot_sel_"):
        await handle_overtime_employee_selected(query, context)
        return
    
    if data.startswith("mark_reported_"):
        await handle_mark_reported_late(query, context)
        return
        
    if data.startswith("mark_unreported_"):
        await handle_mark_unreported_late(query, context)
        return

    if data.startswith("toggle_emp_"):
        nickname = data[len("toggle_emp_"):]
        if 'report_selection' in context.user_data:
            context.user_data['report_selection'][nickname] = not context.user_data['report_selection'].get(nickname, False)
            reply_markup = build_multi_select_keyboard(context.user_data['report_selection'])
            await query.edit_message_reply_markup(reply_markup=reply_markup)
            
    elif data == "confirm_report_emps":
        is_user_admin = is_admin(query.from_user.id, context)
        if 'report_selection' not in context.user_data:
            await query.edit_message_text("❌ Phiên làm việc đã hết hạn. Vui lòng bấm '⚡ Thưởng Doanh Thu' lại.")
            return

        selected = [nick for nick, is_sel in context.user_data['report_selection'].items() if is_sel]
        if not selected:
            await query.answer("⚠️ Bạn chưa chọn nhân viên nào!", show_alert=True)
            return

        del context.user_data['report_selection']

        # Xóa inline prompt
        if update.effective_chat and update.effective_chat.id == Config.GROUP_CHAT_ID:
            await delete_tracked_messages(context, update.effective_chat.id)
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=query.message.message_id)
            except Exception:
                pass

        hour = local_now().hour
        ca = 'Sáng' if hour < 12 else ('Chiều' if hour < 18 else 'Tối')
        sheets_service = context.bot_data['sheets']

        if is_user_admin:
            success = await asyncio.to_thread(sheets_service.batch_update_balances, selected, 1)
            if not success:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ Không thể cộng thưởng. Dữ liệu chưa được xác nhận.",
                )
                return

            keyboard = get_admin_keyboard(is_super_admin=is_super_admin(query.from_user.id))
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ +1 ly → {', '.join(selected)} (Ca {ca})",
                reply_markup=keyboard
            )
        else:
            # Gửi yêu cầu duyệt cho admin
            request_id = f"{update.effective_chat.id}_{query.message.message_id}_{int(local_now().timestamp())}"
            temp_requests = context.bot_data.setdefault('reward_requests', {})
            temp_requests[request_id] = {
                'group_chat_id': update.effective_chat.id,
                'employees': selected,
                'ca': ca,
                'sender': query.from_user.full_name
            }
            
            keyboard = [
                [InlineKeyboardButton("✅ Duyệt", callback_data=f"appr_rew_{request_id}"),
                 InlineKeyboardButton("❌ Từ chối", callback_data=f"rej_rew_{request_id}")]
            ]
            await context.bot.send_message(
                chat_id=Config.ADMIN_CHAT_ID,
                text=f"🎁 **YÊU CẦU CỘNG THƯỞNG**\n\n👤 Người gửi: {query.from_user.full_name}\n⏰ Ca: {ca}\n👥 Nhân viên: {', '.join(selected)}\n\nBạn có đồng ý cộng 1 ly thưởng cho các nhân viên này không?",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            keyboard_main = get_main_keyboard()
            msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ Đã gửi yêu cầu cộng 1 ly thưởng cho: {', '.join(selected)}.\nĐang chờ Quản lý duyệt!",
                reply_markup=keyboard_main
            )
            track_message(context, msg.message_id)


    elif data == "cancel_report_emps":
        context.user_data.pop('report_selection', None)
        if update.effective_chat and update.effective_chat.id == Config.GROUP_CHAT_ID:
            await delete_tracked_messages(context, update.effective_chat.id)
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=query.message.message_id)
            except Exception:
                pass
            
            chat_id = update.effective_chat.id
            user_id = query.from_user.id
            keyboard = get_admin_keyboard(is_super_admin=is_super_admin(user_id)) if is_admin(user_id, context) else get_main_keyboard()
            msg = await context.bot.send_message(chat_id=chat_id, text="❌ Đã huỷ thao tác.", reply_markup=keyboard)
            track_message(context, msg.message_id)

    elif data.startswith("appr_rew_") or data.startswith("rej_rew_"):
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được duyệt.", show_alert=True)
            return

        action, request_id = data.split('_rew_')
        temp_requests = context.bot_data.get('reward_requests', {})
        req_data = temp_requests.get(request_id)
        
        if not req_data:
            await query.edit_message_text("❌ Yêu cầu này đã được xử lý hoặc đã hết hạn.")
            return
            
        group_chat_id = req_data['group_chat_id']
        selected = req_data['employees']
        ca = req_data['ca']
        
        if action == "appr":
            sheets_service = context.bot_data['sheets']
            success = await asyncio.to_thread(sheets_service.batch_update_balances, selected, 1)
            
            if success:
                await query.edit_message_text(f"✅ ĐÃ DUYỆT CỘNG THƯỞNG.\nNhân viên: {', '.join(selected)}\nCa: {ca}")
                await context.bot.send_message(
                    chat_id=group_chat_id,
                    text=f"🎉 **Quản lý đã DUYỆT cộng thưởng!**\n🎁 +1 ly → {', '.join(selected)} (Ca {ca})",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text("❌ Lỗi khi cộng thưởng vào Google Sheets.")
        else:
            await query.edit_message_text(f"❌ ĐÃ TỪ CHỐI CỘNG THƯỞNG.\nNhân viên: {', '.join(selected)}\nCa: {ca}")
            await context.bot.send_message(
                chat_id=group_chat_id,
                text=f"❌ **Quản lý đã TỪ CHỐI cộng thưởng!**\nNhân viên: {', '.join(selected)} (Ca {ca})",
                parse_mode='Markdown'
            )
            
        del temp_requests[request_id]

    elif data.startswith("check_reward_"):
        nickname = data[len("check_reward_"):]
        balance = await asyncio.to_thread(sheets_service.get_balance, nickname)
        if update.effective_chat and update.effective_chat.id == Config.GROUP_CHAT_ID:
            await delete_tracked_messages(context, update.effective_chat.id)
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=query.message.message_id)
            except Exception:
                pass
        result = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🎁 {nickname}: {balance} ly thưởng."
        )
        track_message(context, result.message_id)

    elif data.startswith("use_reward_") and not data.startswith("urw_"):
        nickname = data[len("use_reward_"):]
        current_balance = await asyncio.to_thread(sheets_service.get_balance, nickname)

        if current_balance <= 0:
            await query.edit_message_text(f"❌ {nickname} không còn ly nào!")
            return

        # Hiện confirm trước khi trừ
        await query.edit_message_text(
            f"🥤 {nickname} chắc dùng 1 ly thưởng chứ? (Còn {current_balance} ly)",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Dùng ngay!", callback_data=f"urw_confirm_{nickname}"),
                 InlineKeyboardButton("❌ Thôi", callback_data="urw_cancel")]
            ])
        )

    elif data.startswith("urw_confirm_"):
        nickname = data[len("urw_confirm_"):]
        result = await asyncio.to_thread(sheets_service.consume_reward, nickname)
        if result.get('error') == 'insufficient_balance':
            await query.edit_message_text(f"❌ {nickname} không còn ly nào!")
            return
        if result.get('success'):
            await query.edit_message_text(
                f"✅ Đã trừ 1 ly của {nickname}. Còn lại: {result['balance']} ly."
            )
        else:
            await query.edit_message_text("❌ Lỗi cập nhật. Hãy thử lại.")

    elif data == "urw_cancel":
        try:
            await query.message.delete()
        except Exception:
            pass
            
        chat_id = query.message.chat.id
        user_id = query.from_user.id
        keyboard = get_admin_keyboard(is_super_admin=is_super_admin(user_id)) if is_admin(user_id, context) else get_main_keyboard()
        msg = await context.bot.send_message(chat_id=chat_id, text="❌ Đã huỷ thao tác.", reply_markup=keyboard)
        track_message(context, msg.message_id)
