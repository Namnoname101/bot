import asyncio
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import Config
from utils.admin import is_admin, is_super_admin
from utils.auto_delete import get_admin_keyboard, track_message
from utils.time_utils import local_now

logger = logging.getLogger(__name__)


def _salary_window(now: datetime) -> tuple[datetime, datetime]:
    if now.day >= 17:
        start = now.replace(day=17, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            end = now.replace(year=now.year + 1, month=1, day=16, hour=23, minute=59, second=59)
        else:
            end = now.replace(month=now.month + 1, day=16, hour=23, minute=59, second=59)
    else:
        if now.month == 1:
            start = now.replace(year=now.year - 1, month=12, day=17, hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(month=now.month - 1, day=17, hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(day=16, hour=23, minute=59, second=59)
    return start, end


async def handle_overtime_summary_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id, context):
        return
    now = local_now()
    start_date, end_date = _salary_window(now)
    summary = await asyncio.to_thread(
        context.bot_data['sheets'].get_overtime_summary,
        start_date,
        end_date,
    )
    period = f"{start_date.strftime('%d/%m/%Y')} → {end_date.strftime('%d/%m/%Y')}"
    lines = ["📊 *THỐNG KÊ GIỜ LÀM THÊM*", f"📅 {period}", ""]
    if summary:
        total = 0.0
        for nick, hours in sorted(summary.items()):
            total += hours
            lines.append(f"• {nick}: *{hours:g}h*")
        lines.append(f"\n🔢 Tổng cộng: *{total:g}h*")
    else:
        lines.append("_Chưa có dữ liệu._")
    reply = await update.message.reply_text(
        "\n".join(lines),
        parse_mode='Markdown',
        reply_markup=get_admin_keyboard(is_super_admin(update.effective_user.id)),
    )
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)


async def handle_add_overtime_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id, context):
        return
    balances = await asyncio.to_thread(context.bot_data['sheets'].get_all_balances)
    if not balances:
        await update.message.reply_text("📉 Chưa có nhân viên nào trong hệ thống.")
        return
    keyboard = [[InlineKeyboardButton(nick, callback_data=f"ot_sel_{nick}")] for nick in balances]
    keyboard.append([InlineKeyboardButton("❌ Hủy", callback_data="ot_sel_cancel")])
    await update.message.reply_text(
        "➕ *GIỜ LÀM THÊM* — Chọn nhân viên:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_overtime_employee_selected(query, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(query.from_user.id, context):
        await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
        return
    nickname = query.data[len("ot_sel_"):]
    if nickname == "cancel":
        context.user_data.pop('awaiting_overtime_hours', None)
        await query.edit_message_text("❌ Đã hủy.")
        return
    context.user_data['awaiting_overtime_hours'] = nickname
    await query.edit_message_text(
        f"Nhập số giờ làm thêm cho *{nickname}* (VD: `1.5`):",
        parse_mode='Markdown',
    )


async def handle_overtime_hours_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    nickname = context.user_data.get('awaiting_overtime_hours')
    if not nickname:
        return False
    if not update.effective_user or not is_admin(update.effective_user.id, context):
        context.user_data.pop('awaiting_overtime_hours', None)
        return False
    try:
        hours = float(update.message.text.strip().replace(',', '.'))
        if hours <= 0 or hours > 24:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Số giờ phải lớn hơn 0 và không quá 24.")
        return True
    success = await asyncio.to_thread(context.bot_data['sheets'].add_overtime, nickname, hours)
    if success:
        context.user_data.pop('awaiting_overtime_hours', None)
        await update.message.reply_text(f"✅ Đã thêm {hours:g}h làm thêm cho {nickname}.")
    else:
        await update.message.reply_text("❌ Không thể lưu giờ làm thêm. Vui lòng thử lại.")
    return True


async def handle_grant_admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_super_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Chỉ admin gốc được cấp quyền quản lý.")
        return
    context.user_data['awaiting_admin_id'] = True
    await update.message.reply_text(
        "👑 *CẤP QUYỀN QUẢN LÝ*\n\nNhập Telegram user ID cần cấp quyền:\n_(Gõ /cancel để hủy)_",
        parse_mode='Markdown',
    )


async def handle_grant_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_user or not is_super_admin(update.effective_user.id):
        context.user_data.pop('awaiting_admin_id', None)
        return False
    text = update.message.text.strip()
    if text.startswith('/cancel'):
        context.user_data.pop('awaiting_admin_id', None)
        await update.message.reply_text("❌ Đã hủy cấp quyền.")
        return True
    try:
        telegram_id = int(text)
        if telegram_id <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ ID không hợp lệ. Vui lòng nhập số nguyên dương.")
        return True
    if telegram_id == Config.ADMIN_CHAT_ID:
        context.user_data.pop('awaiting_admin_id', None)
        await update.message.reply_text("⚠️ ID này đã là admin gốc.")
        return True
    success = await asyncio.to_thread(
        context.bot_data['sheets'].add_admin,
        telegram_id,
        str(update.effective_user.id),
    )
    if success:
        context.bot_data.setdefault('admin_ids', set()).add(telegram_id)
        context.user_data.pop('awaiting_admin_id', None)
        await update.message.reply_text(f"✅ Đã cấp quyền quản lý cho `{telegram_id}`.", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Không thể cấp quyền. Vui lòng kiểm tra log.")
    return True
