import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.decorators import group_only, admin_only
from utils.validators import check_reward_eligibility
from utils.auto_delete import GUIDE_MESSAGE, get_main_keyboard, get_admin_keyboard, delete_tracked_messages, track_message
from config import Config
from handlers.checkin_handler import (
    handle_checkin_button, handle_checkout_button,
    handle_checkin_employee_selected, handle_checkout_employee_selected,
    handle_mark_reported_late, handle_mark_unreported_late
)
from handlers.overtime_handler import (
    handle_overtime_summary_button, handle_grant_admin_button,
    handle_grant_admin_input
)
from handlers.management_handler import (
    handle_manage_nv_button, handle_checkin_history_button,
    handle_late_stats_button, handle_edit_report_button,
    handle_add_employee_input, handle_edit_revenue_input,
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
    """Lệnh trừ thưởng (Dự phòng)"""
    pass

@group_only
async def check_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh tra cứu (Dự phòng)"""
    pass

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
    """Lệnh báo doanh thu nhanh (Dự phòng)"""
    pass

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /cancel để huỷ bỏ mọi trạng thái hiện tại và hiện lại bàn phím"""
    context.chat_data.clear()
    chat_id = update.effective_chat.id
    keyboard = get_admin_keyboard(is_super_admin=is_super_admin(chat_id)) if is_admin(chat_id, context) else get_main_keyboard()
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
    announcement = f"🚀 **THÔNG BÁO CẬP NHẬT:**\n\n{message}"
    
    await context.bot.send_message(
        chat_id=Config.GROUP_CHAT_ID,
        text=announcement,
        parse_mode='Markdown'
    )
    if update.effective_chat.id != Config.GROUP_CHAT_ID:
        await update.message.reply_text("✅ Đã gửi thông báo vào nhóm chung!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh hướng dẫn sử dụng bot"""
    if not update.effective_chat or not (update.effective_chat.id == Config.GROUP_CHAT_ID or is_admin(update.effective_chat.id, context)):
        return

    keyboard = get_admin_keyboard(is_super_admin=is_super_admin(update.effective_chat.id)) if is_admin(update.effective_chat.id, context) else get_main_keyboard()
    reply = await update.message.reply_text(GUIDE_MESSAGE, parse_mode='Markdown', reply_markup=keyboard)
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /start để hiển thị bàn phím ảo (Reply Keyboard)"""
    if not update.effective_chat or not (update.effective_chat.id == Config.GROUP_CHAT_ID or is_admin(update.effective_chat.id, context)):
        return

    keyboard = get_admin_keyboard(is_super_admin=is_super_admin(update.effective_chat.id)) if is_admin(update.effective_chat.id, context) else get_main_keyboard()
    reply = await update.message.reply_text("👋 Bot Sô bơ — sử dụng các nút bên dưới:", reply_markup=keyboard)
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)

def build_multi_select_keyboard(selection: dict):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
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
    if not update.effective_chat or not (update.effective_chat.id == Config.GROUP_CHAT_ID or is_admin(update.effective_chat.id, context)):
        return
    text = update.message.text

    # ── KIỂM TRA TEXT INPUT ĐANG CHỜ TRƯỚC KHI XÓA STATE ──
    if context.chat_data.get('awaiting_admin_id'):
        handled = await handle_grant_admin_input(update, context)
        if handled:
            return

    if context.chat_data.get('awaiting_edit_emp_name'):
        handled = await handle_edit_employee_name_input(update, context)
        if handled:
            return

    if context.chat_data.get('awaiting_overtime_hours'):
        handled = await handle_overtime_hours_input(update, context)
        if handled:
            return


    # ── Kiểm tra state management mới ──
    if context.chat_data.get('awaiting_add_employee_name'):
        handled = await handle_add_employee_input(update, context)
        if handled:
            return

    if context.chat_data.get('awaiting_edit_report_revenue'):
        handled = await handle_edit_revenue_input(update, context)
        if handled:
            return

    if context.chat_data.get('salary_action'):
        handled = await process_salary_input(update, context)
        if handled:
            return

    if context.chat_data.get('awaiting_feedback'):
        if text.startswith('/cancel'):
            context.chat_data.pop('awaiting_feedback', None)
            reply = await update.message.reply_text("❌ Đã huỷ gửi ý kiến.")
            if update.effective_chat.id == Config.GROUP_CHAT_ID:
                track_message(context, reply.message_id)
            return True

        # Gửi thẳng ý kiến cho admin
        await context.bot.send_message(
            chat_id=Config.ADMIN_CHAT_ID,
            text=f"💡 **GÓP Ý TỪ NHÂN VIÊN:**\n\n{text}",
            parse_mode='Markdown'
        )
        
        # Xoá tin nhắn góp ý để giữ ẩn danh
        if update.effective_chat.id == Config.GROUP_CHAT_ID:
            try:
                await update.message.delete()
            except Exception:
                pass
                
        context.chat_data.pop('awaiting_feedback', None)
        keyboard = get_admin_keyboard(is_super_admin=is_super_admin(update.effective_chat.id)) if is_admin(update.effective_chat.id, context) else get_main_keyboard()
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
    context.chat_data.pop('awaiting_checkin_photo', None)
    context.chat_data.pop('awaiting_overtime_hours', None)
    context.chat_data.pop('awaiting_add_employee_name', None)
    context.chat_data.pop('awaiting_edit_emp_name', None)
    context.chat_data.pop('awaiting_edit_report_revenue', None)
    context.chat_data.pop('awaiting_feedback', None)
    context.chat_data.pop('awaiting_admin_id', None)
    _cancel_endshift_tasks(context)

    if text == "📖 Hướng Dẫn":
        await help_command(update, context)
        
    elif text == "💡 Đóng Góp Ý Kiến":
        context.chat_data['awaiting_feedback'] = True
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

        context.chat_data['report_selection'] = {nick: False for nick in balances.keys()}
        reply_markup = build_multi_select_keyboard(context.chat_data['report_selection'])
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
            
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
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
            
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
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

    elif text == "📋 Lịch Sử Check-In":
        await handle_checkin_history_button(update, context)

    elif text == "⚠️ Thống Kê Đi Muộn":
        await handle_late_stats_button(update, context)

    elif text == "📊 Thống Kê Giờ LT":
        await handle_overtime_summary_button(update, context)

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
        if 'report_selection' in context.chat_data:
            context.chat_data['report_selection'][nickname] = not context.chat_data['report_selection'].get(nickname, False)
            reply_markup = build_multi_select_keyboard(context.chat_data['report_selection'])
            await query.edit_message_reply_markup(reply_markup=reply_markup)
            
    elif data == "confirm_report_emps":
        if 'report_selection' not in context.chat_data:
            await query.edit_message_text("❌ Phiên làm việc đã hết hạn. Vui lòng bấm '⚡ Báo Doanh Thu' lại.")
            return

        selected = [nick for nick, is_sel in context.chat_data['report_selection'].items() if is_sel]
        if not selected:
            await query.answer("⚠️ Bạn chưa chọn nhân viên nào!", show_alert=True)
            return

        del context.chat_data['report_selection']

        # Xóa inline prompt
        if update.effective_chat and update.effective_chat.id == Config.GROUP_CHAT_ID:
            await delete_tracked_messages(context, update.effective_chat.id)
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=query.message.message_id)
            except Exception:
                pass

        from datetime import datetime
        ca = 'Sáng' if datetime.now().hour < 12 else ('Chiều' if datetime.now().hour < 18 else 'Tối')
        sheets_service = context.bot_data['sheets']

        for emp in selected:
            await asyncio.to_thread(sheets_service.update_balance, emp, 1)

        keyboard = get_admin_keyboard(is_super_admin=is_super_admin(query.message.chat.id)) if is_admin(query.message.chat.id, context) else get_main_keyboard()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ +1 ly → {', '.join(selected)} (Ca {ca})",
            reply_markup=keyboard
        )


    elif data == "cancel_report_emps":
        context.chat_data.pop('report_selection', None)
        if update.effective_chat and update.effective_chat.id == Config.GROUP_CHAT_ID:
            await delete_tracked_messages(context, update.effective_chat.id)
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=query.message.message_id)
            except Exception:
                pass
            
            chat_id = update.effective_chat.id
            keyboard = get_admin_keyboard(is_super_admin=is_super_admin(chat_id)) if is_admin(chat_id, context) else get_main_keyboard()
            msg = await context.bot.send_message(chat_id=chat_id, text="❌ Đã huỷ thao tác.", reply_markup=keyboard)
            track_message(context, msg.message_id)

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
        current_balance = await asyncio.to_thread(sheets_service.get_balance, nickname)
        if current_balance <= 0:
            await query.edit_message_text(f"❌ {nickname} không còn ly nào!")
            return
        if await asyncio.to_thread(sheets_service.update_balance, nickname, -1):
            await query.edit_message_text(
                f"✅ Đã trừ 1 ly của {nickname}. Còn lại: {current_balance - 1} ly."
            )
        else:
            await query.edit_message_text("❌ Lỗi cập nhật. Hãy thử lại.")

    elif data == "urw_cancel":
        try:
            await query.message.delete()
        except Exception:
            pass
            
        chat_id = query.message.chat.id
        keyboard = get_admin_keyboard(is_super_admin=is_super_admin(chat_id)) if is_admin(chat_id, context) else get_main_keyboard()
        msg = await context.bot.send_message(chat_id=chat_id, text="❌ Đã huỷ thao tác.", reply_markup=keyboard)
        track_message(context, msg.message_id)