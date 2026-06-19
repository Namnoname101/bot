import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
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
    handle_add_overtime_button, handle_overtime_employee_selected,
    handle_overtime_hours_input
)
from handlers.management_handler import (
    handle_manage_nv_button, handle_checkin_history_button,
    handle_late_stats_button, handle_edit_report_button,
    handle_add_employee_input, handle_edit_revenue_input,
    handle_mgmt_callback
)
from handlers.endshift_handler import (
    handle_endshift_button, handle_endshift_ca_selected,
    handle_endshift_role_selected, handle_endshift_send,
    handle_endshift_cancel, _cancel_endshift_tasks
)

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
        
    msg = "📊 **BẢNG SỐ DƯ THƯỞNG:**\n\n"
    for nick, bal in balances.items():
        msg += f"👤 {nick}: {bal} ly\n"
    reply = await update.message.reply_text(msg, parse_mode='Markdown')
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)

@group_only
async def quick_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh báo doanh thu nhanh (Dự phòng)"""
    pass

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh hướng dẫn sử dụng bot"""
    if not update.effective_chat or update.effective_chat.id not in [Config.GROUP_CHAT_ID, Config.ADMIN_CHAT_ID]:
        return

    keyboard = get_admin_keyboard() if update.effective_chat.id == Config.ADMIN_CHAT_ID else get_main_keyboard()
    reply = await update.message.reply_text(GUIDE_MESSAGE, parse_mode='Markdown', reply_markup=keyboard)
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /start để hiển thị bàn phím ảo (Reply Keyboard)"""
    if not update.effective_chat or update.effective_chat.id not in [Config.GROUP_CHAT_ID, Config.ADMIN_CHAT_ID]:
        return

    keyboard = get_admin_keyboard() if update.effective_chat.id == Config.ADMIN_CHAT_ID else get_main_keyboard()
    reply = await update.message.reply_text(
        "👋 Chào mừng đến với Bot Quản Lý Doanh Thu & Thưởng!\n👇 Hãy sử dụng các nút bên dưới để thao tác nhanh:",
        reply_markup=keyboard
    )
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
    if not update.effective_chat or update.effective_chat.id not in [Config.GROUP_CHAT_ID, Config.ADMIN_CHAT_ID]:
        return
    text = update.message.text

    # ── KIỂM TRA TEXT INPUT ĐANG CHỜ TRƯỚC KHI XÓA STATE ──
    # Phải kiểm tra awaiting state TRƯỚC khi xóa tin nhắn, vì tin nhắn đó chứa dữ liệu cần xử lý
    if context.chat_data.get('awaiting_overtime_hours'):
        handled = await handle_overtime_hours_input(update, context)
        if handled:
            return

    if context.chat_data.get('awaiting_revenue_for'):
        employees = context.chat_data['awaiting_revenue_for']
        revenue_str = text
        
        def _clean_number_str_local(s: str, allow_decimal: bool = True) -> str:
            s = s.replace(',', '')
            if '.' not in s:
                return s
            parts = s.split('.')
            if len(parts) > 2:
                return ''.join(parts)
            integer_part, decimal_part = parts
            if len(decimal_part) == 3:
                # Dấu phân cách ngàn: 1.500 → 1500
                return integer_part + decimal_part
            else:
                if allow_decimal:
                    return integer_part + '.' + decimal_part
                return integer_part + decimal_part

        def parse_amount_token(tok: str):
            # BUG-1 FIX: Phân biệt dấu chấm là ngàn hay thập phân
            # 1.500k → 1.500.000 | 1.5k → 1.500 | 1.5M → 1.500.000
            s = tok.strip().upper()
            if not s:
                return None
            try:
                if s.endswith('M'):
                    num = _clean_number_str_local(s[:-1])
                    return int(float(num) * 1_000_000)
                if s.endswith('K'):
                    num = _clean_number_str_local(s[:-1])
                    return int(float(num) * 1_000)
                cleaned = _clean_number_str_local(s, allow_decimal=False)
                return int(cleaned)
            except Exception:
                return None
                
        revenue = parse_amount_token(revenue_str)
        
        # Xóa tin nhắn của user SAU KHI đã đọc được revenue_str
        if update.effective_chat.id == Config.GROUP_CHAT_ID:
            try:
                await update.message.delete()
            except:
                pass

        if revenue is None:
            err_reply = await update.message.reply_text("❌ Số tiền không hợp lệ. Vui lòng gõ lại (VD: 1500, 1.5M, 2M) hoặc bấm nút Hủy/nút khác.")
            if update.effective_chat.id == Config.GROUP_CHAT_ID:
                track_message(context, err_reply.message_id)
            return

        del context.chat_data['awaiting_revenue_for']
        
        from datetime import datetime
        now = datetime.now()
        if now.hour < 12:
            ca = 'Sáng'
        elif now.hour < 18:
            ca = 'Chiều'
        else:
            ca = 'Tối'
        reward_count = check_reward_eligibility(len(employees), revenue)
        
        sheets_service = context.bot_data['sheets']
        status_msg = await update.message.reply_text(f"⏳ Đang lưu báo cáo của {', '.join(employees)}...")
        if update.effective_chat.id == Config.GROUP_CHAT_ID:
            track_message(context, status_msg.message_id)
        
        ok = await asyncio.to_thread(
            sheets_service.save_report,
            date=now.strftime("%d/%m/%Y"),
            employees=", ".join(employees),
            revenue=revenue,
            ca=ca
        )
        
        keyboard = get_admin_keyboard() if update.effective_chat.id == Config.ADMIN_CHAT_ID else get_main_keyboard()
        if ok:
            if reward_count > 0:
                for emp in employees:
                    await asyncio.to_thread(sheets_service.update_balance, emp, reward_count)

            confirm_msg = f"✅ **BÁO CÁO ĐÃ ĐƯỢC LƯU**\n"
            confirm_msg += f"👥 Nhân viên: {', '.join(employees)}\n"
            confirm_msg += f"💰 Doanh thu: {revenue:,} VNĐ\n"
            if reward_count > 0:
                confirm_msg += f"🎁 Cộng {reward_count} ly thưởng cho mỗi bạn\n"
            confirm_msg += f"⏰ Ca: {ca}"

            # FIX: edit_text chỉ nhận InlineKeyboardMarkup, không nhận ReplyKeyboardMarkup
            # → edit message thuần text, rồi gửi keyboard ở message riêng
            try:
                await status_msg.edit_text(confirm_msg, parse_mode='Markdown')
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="✅ Xong!",
                reply_markup=keyboard
            )
        else:
            try:
                await status_msg.edit_text("❌ Có lỗi khi lưu báo cáo. Hãy thử lại.")
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Thử lại nhé!",
                reply_markup=keyboard
            )
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
    context.chat_data.pop('awaiting_revenue_for', None)
    context.chat_data.pop('awaiting_checkin_photo', None)
    context.chat_data.pop('awaiting_overtime_hours', None)
    context.chat_data.pop('awaiting_add_employee_name', None)
    context.chat_data.pop('awaiting_edit_report_revenue', None)
    _cancel_endshift_tasks(context)

    if text == "📖 Hướng Dẫn":
        await help_command(update, context)
    
    elif text == "📥 Check In":
        await handle_checkin_button(update, context)
    
    elif text == "📤 Check Out":
        await handle_checkout_button(update, context)

    elif text == "🔚 Kết Ca":
        await handle_endshift_button(update, context)
    
    elif text == "⏰ Thêm Giờ Làm Thêm":
        await handle_add_overtime_button(update, context)
        
    elif text == "⚡ Báo Doanh Thu":
        sheets_service = context.bot_data['sheets']
        balances = await asyncio.to_thread(sheets_service.get_all_balances)
        if not balances:
            reply = await update.message.reply_text("📉 Chưa có dữ liệu nhân viên trên hệ thống.")
            if update.effective_chat.id == Config.GROUP_CHAT_ID:
                track_message(context, reply.message_id)
            return
            
        context.chat_data['report_selection'] = {nick: False for nick in balances.keys()}
        reply_markup = build_multi_select_keyboard(context.chat_data['report_selection'])
        reply = await update.message.reply_text("👥 Ca này gồm những ai? (Chạm để chọn):", reply_markup=reply_markup)
        
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

    elif text == "✏️ Sửa Doanh Thu":
        await handle_edit_report_button(update, context)


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
        now = datetime.now()
        ca = 'Sáng' if now.hour < 12 else ('Chiều' if now.hour < 18 else 'Tối')

        sheets_service = context.bot_data['sheets']
        status_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"⏳ Đang cộng thưởng cho {', '.join(selected)}..."
        )
        if update.effective_chat and update.effective_chat.id == Config.GROUP_CHAT_ID:
            track_message(context, status_msg.message_id)

        # Cộng 1 ly thưởng cho mỗi nhân viên
        for emp in selected:
            await asyncio.to_thread(sheets_service.update_balance, emp, 1)

        keyboard = get_admin_keyboard() if update.effective_chat.id == Config.ADMIN_CHAT_ID else get_main_keyboard()
        confirm_msg = (
            f"✅ **ĐÃ CỘNG THƯỞNG**\n"
            f"👥 Nhân viên: {', '.join(selected)}\n"
            f"🎁 Mỗi người: +1 ly thưởng\n"
            f"⏰ Ca: {ca}"
        )
        try:
            await status_msg.edit_text(confirm_msg, parse_mode='Markdown')
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ Xong!",
            reply_markup=keyboard
        )



    elif data == "cancel_report_emps":
        context.chat_data.pop('report_selection', None)
        context.chat_data.pop('awaiting_revenue_for', None)

        if update.effective_chat and update.effective_chat.id == Config.GROUP_CHAT_ID:
            await delete_tracked_messages(context, update.effective_chat.id)
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=query.message.message_id)
            except Exception:
                pass

        cancel_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Đã hủy báo cáo doanh thu.")
        track_message(context, cancel_msg.message_id)
        
    elif data.startswith("check_reward_"):
        nickname = data[len("check_reward_"):]
        balance = await asyncio.to_thread(sheets_service.get_balance, nickname)

        # Clear tracked messages, delete inline prompt, then send result + guide
        if update.effective_chat and update.effective_chat.id == Config.GROUP_CHAT_ID:
            await delete_tracked_messages(context, update.effective_chat.id)
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=query.message.message_id)
            except Exception:
                pass

        result = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🎁 Bạn {nickname} hiện đang có {balance} ly thưởng.")
        track_message(context, result.message_id)
        
    elif data.startswith("use_reward_"):
        nickname = data[len("use_reward_"):]

        # Clear previous prompts and then announce processing/result as new messages
        if update.effective_chat and update.effective_chat.id == Config.GROUP_CHAT_ID:
            await delete_tracked_messages(context, update.effective_chat.id)
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=query.message.message_id)
            except Exception:
                pass

        processing = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"⏳ Đang xử lý cho {nickname}...")
        track_message(context, processing.message_id)

        current_balance = await asyncio.to_thread(sheets_service.get_balance, nickname)
        if current_balance <= 0:
            await processing.edit_text(f"❌ Bạn {nickname} không còn ly thưởng nào để dùng!")
            return

        if await asyncio.to_thread(sheets_service.update_balance, nickname, -1):
            await processing.edit_text(f"✅ Đã trừ 1 ly thưởng của {nickname}. Số dư còn lại: {current_balance - 1} ly.")
        else:
            await processing.edit_text("❌ Lỗi cập nhật dữ liệu. Hãy thử lại sau.")