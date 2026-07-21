import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import Config
from utils.auto_delete import track_message, delete_tracked_messages, get_admin_keyboard
from utils.admin import is_admin, is_super_admin
from utils.validators import _parse_amount_str

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────

def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(update.effective_chat and is_admin(update.effective_chat.id, context))


def _fmt_revenue(raw) -> str:
    """Hiển thị doanh thu an toàn."""
    try:
        if raw and str(raw).strip():
            return f"{int(float(str(raw))):,}đ"
    except Exception:
        pass
    return "(chưa có)"


# ─────────────────────────────────────────────────────────────────
# 1. Quản Lý NV — inline menu
# ─────────────────────────────────────────────────────────────────

async def handle_manage_nv_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin bấm '🧾 Quản Lý NV ' → inline menu."""
    if not _is_admin(update, context):
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Thêm Nhân Viên", callback_data="mgmt_add_emp"),
         InlineKeyboardButton("❌ Xóa Nhân Viên", callback_data="mgmt_rem_list")],
        [InlineKeyboardButton("✏️ Sửa Tên Nhân Viên", callback_data="mgmt_edit_list"),
         InlineKeyboardButton("💵 Sửa Mức Lương", callback_data="mgmt_salary_list")],
        [InlineKeyboardButton("🎁 Lịch Sử Thưởng NV", callback_data="mgmt_rwd_list")],
        [InlineKeyboardButton("✖ Đóng", callback_data="mgmt_cancel")]
    ])
    reply = await update.message.reply_text(
        "🧾 *QUẢN LÝ NHÂN VIÊN*\nChọn chức năng:",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    track_message(context, reply.message_id)


# ─────────────────────────────────────────────────────────────────
# 2. Lịch Sử Check-In Hôm Nay
# ─────────────────────────────────────────────────────────────────

async def handle_checkin_history_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin bấm '📋 Lịch Sử Check-In' → danh sách hôm nay."""
    if not _is_admin(update, context):
        return

    sheets = context.bot_data['sheets']
    records = await asyncio.to_thread(sheets.get_checkin_history_today)
    today = datetime.now().strftime("%d/%m/%Y")

    if not records:
        reply = await update.message.reply_text(
            f"📋 *LỊCH SỬ CHECK-IN* ({today})\n\n"
            "Chưa có nhân viên nào check-in hôm nay.",
            parse_mode='Markdown'
        )
        track_message(context, reply.message_id)
        return

    lines = [f"📋 *LỊCH SỬ CHECK-IN* ({today}) — {len(records)} lượt\n{'─'*30}"]
    for r in records:
        status = "✅ Ra" if r['checkout_time'] else "🟡 Đang ca"
        hours = f" ({r['total_hours']}h)" if r['total_hours'] and r['checkout_time'] else ""
        cout = r['checkout_time'] or "—"
        lines.append(
            f"👤 *{r['nickname']}* {status}\n"
            f"   📥 {r['checkin_time']}  →  📤 {cout}{hours}\n"
            f"   📝 {r['note']}"
        )

    msg = "\n".join(lines)
    if len(msg) > 3900:
        msg = msg[:3900] + "\n_…bị cắt_"

    reply = await update.message.reply_text(msg, parse_mode='Markdown')
    track_message(context, reply.message_id)


# ─────────────────────────────────────────────────────────────────
# 3. Thống Kê Đi Muộn
# ─────────────────────────────────────────────────────────────────

async def handle_late_stats_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin bấm '⚠️ Thống Kê Đi Muộn' → tính trễ từ đầu tháng."""
    if not _is_admin(update, context):
        return

    sheets = context.bot_data['sheets']
    month_year = datetime.now().strftime("%m/%Y")
    records = await asyncio.to_thread(sheets.get_late_statistics, month_year)

    if not records:
        reply = await update.message.reply_text(
            f"⚠️ *THỐNG KÊ ĐI MUỘN* (Tháng {month_year})\n\n"
            "✅ Không có trường hợp đi muộn nào trong tháng này!",
            parse_mode='Markdown'
        )
        track_message(context, reply.message_id)
        return

    # Gom nhóm theo nhân viên
    by_emp: dict[str, list] = {}
    for r in records:
        by_emp.setdefault(r['nickname'], []).append(r)

    lines = [
        f"⚠️ *THỐNG KÊ ĐI MUỘN* (Tháng {month_year})",
        f"Tổng: {len(records)} lần / {len(by_emp)} nhân viên\n{'─'*30}"
    ]
    for nick, lates in sorted(by_emp.items(), key=lambda x: -len(x[1])):
        pre = sum(1 for l in lates if l['pre_reported'])
        no_pre = len(lates) - pre
        lines.append(
            f"👤 *{nick}*: {len(lates)} lần  "
            f"(✅ báo trước: {pre} | ❌ không báo: {no_pre})"
        )
        for l in lates:
            lines.append(f"   • {l['date']} lúc {l['checkin_time']} — {l['note']}")

    msg = "\n".join(lines)
    if len(msg) > 3900:
        msg = msg[:3900] + "\n_…bị cắt_"

    reply = await update.message.reply_text(msg, parse_mode='Markdown')
    track_message(context, reply.message_id)


# ─────────────────────────────────────────────────────────────────
# 4. Sửa Doanh Thu
# ─────────────────────────────────────────────────────────────────

async def handle_edit_report_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin bấm '✏️ Sửa Doanh Thu' → chọn ca gần đây."""
    if not _is_admin(update, context):
        return

    sheets = context.bot_data['sheets']
    sessions = await asyncio.to_thread(sheets.get_recent_revenue_reports, 8)

    if not sessions:
        reply = await update.message.reply_text(
            "✏️ *SỬA DOANH THU*\n\nChưa có báo cáo nào trong hệ thống.",
            parse_mode='Markdown'
        )
        track_message(context, reply.message_id)
        return

    # Lưu tạm trong bot_data để callback truy xuất
    context.bot_data['edit_report_sessions'] = sessions

    keyboard = []
    for i, s in enumerate(sessions):
        emps = ', '.join(s['employees'])
        rev = _fmt_revenue(s.get('revenue'))
        label = f"{s['date']} Ca {s['ca']} | {emps} | {rev}"
        if len(label) > 55:
            label = label[:52] + "…"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"mgmt_edit_rpt_{i}")])
    keyboard.append([InlineKeyboardButton("✖ Hủy", callback_data="mgmt_cancel")])

    reply = await update.message.reply_text(
        "✏️ *SỬA DOANH THU*\nChọn ca báo cáo cần sửa:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    track_message(context, reply.message_id)


# ─────────────────────────────────────────────────────────────────
# Text input handlers (called from button_click_handler)
# ─────────────────────────────────────────────────────────────────

async def handle_add_employee_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Xử lý khi admin nhập tên NV mới. Return True nếu đã xử lý."""
    if not context.chat_data.get('awaiting_add_employee_name'):
        return False

    nickname = update.message.text.strip()
    del context.chat_data['awaiting_add_employee_name']

    try:
        await update.message.delete()
    except Exception:
        pass

    if not nickname:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Tên không được để trống!",
            reply_markup=get_admin_keyboard(is_super_admin=is_super_admin(update.effective_chat.id))
        )
        return True

    sheets = context.bot_data['sheets']
    status_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"⏳ Đang thêm nhân viên *{nickname}*…",
        parse_mode='Markdown'
    )
    result = await asyncio.to_thread(sheets.add_employee, nickname)

    if result['success']:
        await status_msg.edit_text(
            f"✅ Đã thêm *{nickname}* (số dư: 0 ly)",
            parse_mode='Markdown',
            reply_markup=get_admin_keyboard(is_super_admin=is_super_admin(update.effective_chat.id))
        )
    else:
        err = result.get('error', '')
        if err == 'already_exists':
            await status_msg.edit_text(f"⚠️ *{nickname}* đã tồn tại trong hệ thống!", parse_mode='Markdown')
        else:
            await status_msg.edit_text(f"❌ Lỗi: {err}")

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="↩️",
        reply_markup=get_admin_keyboard(is_super_admin=is_super_admin(update.effective_chat.id))
    )
    return True

# ── Sửa tên nhân viên ──

async def _show_edit_list(query, context: ContextTypes.DEFAULT_TYPE):
    sheets = context.bot_data['sheets']
    balances = await asyncio.to_thread(sheets.get_all_balances)

    if not balances:
        await query.edit_message_text("❌ Chưa có nhân viên nào trong hệ thống.")
        return

    keyboard, row = [], []
    for nick in balances.keys():
        row.append(InlineKeyboardButton(f"✏️ {nick}", callback_data=f"mgmt_edit_sel_{nick}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("✖ Hủy", callback_data="mgmt_cancel")])

    await query.edit_message_text(
        "✏️ *SỬA TÊN NHÂN VIÊN*\nChọn nhân viên cần sửa tên:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def _start_edit_name(query, context: ContextTypes.DEFAULT_TYPE, nickname: str):
    context.chat_data['awaiting_edit_emp_name'] = nickname
    await query.edit_message_text(
        f"✏️ *SỬA TÊN NHÂN VIÊN*\n\n"
        f"Đang sửa tên cho: *{nickname}*\n"
        f"Vui lòng gõ *tên mới* và gửi vào đây:\n"
        f"_(Gõ /cancel để huỷ)_",
        parse_mode='Markdown'
    )


async def handle_edit_employee_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Xử lý input tên mới của nhân viên từ quản lý."""
    old_nickname = context.chat_data.get('awaiting_edit_emp_name')
    if not old_nickname:
        return False

    text = update.message.text.strip()
    if text.startswith('/cancel'):
        context.chat_data.pop('awaiting_edit_emp_name', None)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Đã huỷ thao tác sửa tên nhân viên.",
            reply_markup=get_admin_keyboard(is_super_admin=is_super_admin(update.effective_chat.id))
        )
        return True

    new_nickname = text
    if not new_nickname:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Tên không được để trống!",
            reply_markup=get_admin_keyboard(is_super_admin=is_super_admin(update.effective_chat.id))
        )
        return True

    # Gọi Google Sheets Service
    sheets = context.bot_data['sheets']
    status_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔄 Đang cập nhật tên từ `{old_nickname}` thành `{new_nickname}`...",
        parse_mode='Markdown'
    )
    result = await asyncio.to_thread(sheets.rename_employee, old_nickname, new_nickname)
    
    context.chat_data.pop('awaiting_edit_emp_name', None)

    try:
        await status_msg.delete()
    except Exception:
        pass

    if result.get('success'):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Đã đổi tên thành công:\n*{old_nickname}* ➡️ *{new_nickname}*",
            parse_mode='Markdown',
            reply_markup=get_admin_keyboard(is_super_admin=is_super_admin(update.effective_chat.id))
        )
    else:
        err = result.get('error', '')
        if err == 'empty_name':
            msg = "Tên không được để trống."
        elif err == 'already_exists':
            msg = "Tên mới đã tồn tại, vui lòng chọn tên khác."
        elif err == 'not_found':
            msg = "Không tìm thấy tên nhân viên cũ."
        else:
            msg = err
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Thất bại: {msg}",
            reply_markup=get_admin_keyboard(is_super_admin=is_super_admin(update.effective_chat.id))
        )

    return True


async def handle_edit_revenue_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Xử lý khi admin nhập doanh thu mới. Return True nếu đã xử lý."""
    if not context.chat_data.get('awaiting_edit_report_revenue'):
        return False

    session_info = context.chat_data.pop('awaiting_edit_report_revenue')
    raw = update.message.text.strip()

    try:
        await update.message.delete()
    except Exception:
        pass

    new_revenue = _parse_amount_str(raw)
    if new_revenue is None or new_revenue < 0:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Số tiền không hợp lệ. Vui lòng thử lại (VD: 1500k, 2M, 1500000).",
            reply_markup=get_admin_keyboard(is_super_admin=is_super_admin(query.message.chat.id))
        )
        return True

    sheets = context.bot_data['sheets']
    status_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⏳ Đang cập nhật doanh thu…"
    )
    success = await asyncio.to_thread(
        sheets.update_report_revenue,
        session_info['row_indices'],
        new_revenue
    )

    old_str = _fmt_revenue(session_info.get('old_revenue'))
    emps = ', '.join(session_info['employees'])

    if success:
        await status_msg.edit_text(
            f"✅ Đã cập nhật: {session_info['date']} Ca {session_info['ca']} — {old_str} → {new_revenue:,}đ",
            parse_mode='Markdown'
        )
    else:
        await status_msg.edit_text("❌ Có lỗi khi cập nhật. Hãy thử lại.")

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="↩️",
        reply_markup=get_admin_keyboard(is_super_admin=is_super_admin(query.message.chat.id))
    )
    return True


# ─────────────────────────────────────────────────────────────────
# Inline callback dispatcher (tất cả mgmt_*)
# ─────────────────────────────────────────────────────────────────

async def handle_mgmt_callback(query, context: ContextTypes.DEFAULT_TYPE):
    """Dispatcher cho mọi callback_data bắt đầu bằng 'mgmt_'."""
    data = query.data

    if data == 'mgmt_cancel':
        await query.edit_message_text("✖ Đã đóng.")
        return

    if data == 'mgmt_add_emp':
        await _start_add_employee(query, context)
        return

    if data == 'mgmt_rem_list':
        await _show_remove_list(query, context)
        return
    if data.startswith('mgmt_rem_sel_'):
        await _confirm_remove(query, context, data[len('mgmt_rem_sel_'):])
        return

    if data == 'mgmt_edit_list':
        await _show_edit_list(query, context)
        return

    if data.startswith('mgmt_edit_sel_'):
        await _start_edit_name(query, context, data[len('mgmt_edit_sel_'):])
        return

    if data.startswith('mgmt_rem_ok_'):
        await _do_remove(query, context, data[len('mgmt_rem_ok_'):])
        return

    if data == 'mgmt_rwd_list':
        await _show_reward_history_list(query, context)
        return

    if data.startswith('mgmt_rwd_'):
        await _show_reward_history(query, context, data[len('mgmt_rwd_'):])
        return

    if data.startswith('mgmt_edit_rpt_'):
        await _start_edit_report(query, context, data[len('mgmt_edit_rpt_'):])
        return

    if data == 'mgmt_salary_list':
        await _show_salary_list(query, context)
        return
        
    if data.startswith('mgmt_salary_sel_'):
        await _start_edit_salary_rate(query, context, data[len('mgmt_salary_sel_'):])
        return

# ── Private callback implementations ──


async def _start_add_employee(query, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data['awaiting_add_employee_name'] = True
    await query.edit_message_text(
        "➕ *THÊM NHÂN VIÊN MỚI*\n\n"
        "Vui lòng gõ *nickname* cho nhân viên mới và gửi vào đây:",
        parse_mode='Markdown'
    )


async def _show_remove_list(query, context: ContextTypes.DEFAULT_TYPE):
    sheets = context.bot_data['sheets']
    balances = await asyncio.to_thread(sheets.get_all_balances)

    if not balances:
        await query.edit_message_text("❌ Chưa có nhân viên nào trong hệ thống.")
        return

    keyboard, row = [], []
    for nick in balances.keys():
        row.append(InlineKeyboardButton(f"❌ {nick}", callback_data=f"mgmt_rem_sel_{nick}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("✖ Hủy", callback_data="mgmt_cancel")])

    await query.edit_message_text(
        "❌ *XÓA NHÂN VIÊN*\nChọn nhân viên cần xóa:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def _confirm_remove(query, context: ContextTypes.DEFAULT_TYPE, nickname: str):
    await query.edit_message_text(
        f"⚠️ *XÁC NHẬN XÓA*\n\n"
        f"Bạn có chắc muốn xóa *{nickname}* khỏi hệ thống?\n"
        f"_(Thao tác này không thể hoàn tác)_",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Xác nhận xóa {nickname}", callback_data=f"mgmt_rem_ok_{nickname}")],
            [InlineKeyboardButton("↩ Quay lại", callback_data="mgmt_rem_list")]
        ]),
        parse_mode='Markdown'
    )


async def _do_remove(query, context: ContextTypes.DEFAULT_TYPE, nickname: str):
    sheets = context.bot_data['sheets']
    success = await asyncio.to_thread(sheets.remove_employee, nickname)
    if success:
        await query.edit_message_text(
            f"✅ *ĐÃ XÓA NHÂN VIÊN*\n"
            f"👤 {nickname} đã được xóa khỏi hệ thống.",
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text(
            f"❌ Không tìm thấy *{nickname}* hoặc đã có lỗi xảy ra.",
            parse_mode='Markdown'
        )


async def _show_reward_history_list(query, context: ContextTypes.DEFAULT_TYPE):
    sheets = context.bot_data['sheets']
    balances = await asyncio.to_thread(sheets.get_all_balances)

    if not balances:
        await query.edit_message_text("❌ Chưa có nhân viên nào trong hệ thống.")
        return

    keyboard, row = [], []
    for nick, bal in balances.items():
        row.append(InlineKeyboardButton(f"{nick} ({bal}ly)", callback_data=f"mgmt_rwd_{nick}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("✖ Đóng", callback_data="mgmt_cancel")])

    await query.edit_message_text(
        "🎁 *LỊCH SỬ THƯỞNG*\nChọn nhân viên:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def _show_reward_history(query, context: ContextTypes.DEFAULT_TYPE, nickname: str):
    sheets = context.bot_data['sheets']
    records, balances = await asyncio.gather(
        asyncio.to_thread(sheets.get_reward_history, nickname, 20),
        asyncio.to_thread(sheets.get_all_balances)
    )
    current_balance = balances.get(nickname, 0)

    if not records:
        await query.edit_message_text(
            f"🎁 *LỊCH SỬ THƯỞNG — {nickname}*\n\n"
            f"💰 Số dư: *{current_balance} ly*\n\n"
            f"Chưa có báo cáo nào liên quan đến {nickname}.",
            parse_mode='Markdown'
        )
        return

    lines = [
        f"🎁 *LỊCH SỬ THƯỞNG — {nickname}*",
        f"💰 Số dư hiện tại: *{current_balance} ly*",
        f"{'─'*28}"
    ]
    for r in records:
        lines.append(f"• {r['date']} Ca {r['ca']}")

    msg = "\n".join(lines)
    if len(msg) > 3900:
        msg = msg[:3900] + "\n_…bị cắt_"

    await query.edit_message_text(msg, parse_mode='Markdown')


async def _start_edit_report(query, context: ContextTypes.DEFAULT_TYPE, idx_str: str):
    try:
        idx = int(idx_str)
        sessions = context.bot_data.get('edit_report_sessions', [])
        session = sessions[idx]
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Phiên đã hết hạn. Bấm '✏️ Sửa Doanh Thu' lại.")
        return

    # Lưu state
    context.chat_data['awaiting_edit_report_revenue'] = {
        'row_indices': session['row_indices'],
        'date':        session['date'],
        'ca':          session['ca'],
        'employees':   session['employees'],
        'old_revenue': session.get('revenue', '')
    }

    emps = ', '.join(session['employees'])
    old_str = _fmt_revenue(session.get('revenue'))

    await query.edit_message_text(
        f"✏️ *SỬA DOANH THU*\n"
        f"📅 {session['date']} Ca {session['ca']}\n"
        f"👥 {emps}\n"
        f"💰 Hiện tại: {old_str}\n\n"
        f"Gõ doanh thu mới (VD: 1500k, 2M, 1500000):",
        parse_mode='Markdown'
    )


async def _show_salary_list(query, context: ContextTypes.DEFAULT_TYPE):
    sheets = context.bot_data['sheets']
    import asyncio
    rates = await asyncio.to_thread(sheets.get_all_salary_rates)

    if not rates:
        await query.edit_message_text("❌ Chưa có nhân viên nào trong hệ thống.")
        return

    keyboard, row = [], []
    for nick, rate in rates.items():
        rate_str = f"{rate:g}k" if rate else "(chưa set)"
        row.append(InlineKeyboardButton(f"{nick} ({rate_str})", callback_data=f"mgmt_salary_sel_{nick}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("✖ Hủy", callback_data="mgmt_cancel")])

    await query.edit_message_text(
        "💵 *MỨC LƯƠNG NHÂN VIÊN*\nChọn nhân viên cần sửa mức lương/giờ:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def _start_edit_salary_rate(query, context: ContextTypes.DEFAULT_TYPE, nickname: str):
    context.chat_data['awaiting_edit_salary_rate'] = nickname
    
    sheets = context.bot_data['sheets']
    import asyncio
    rates = await asyncio.to_thread(sheets.get_all_salary_rates)
    current_rate = rates.get(nickname, 16.0)
    
    await query.edit_message_text(
        f"💵 *SỬA MỨC LƯƠNG*\n\n"
        f"Nhân viên: *{nickname}*\n"
        f"Mức hiện tại: *{current_rate}k/giờ*\n\n"
        f"Gõ mức lương/giờ mới (VD: 16, 18.5, 20):",
        parse_mode='Markdown'
    )

async def handle_edit_salary_rate_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    nickname = context.chat_data.pop('awaiting_edit_salary_rate', None)
    if not nickname:
        return False
        
    text = update.message.text.strip()
    try:
        new_rate = float(text.replace(',', '.'))
    except ValueError:
        reply = await update.message.reply_text("❌ Vui lòng nhập số hợp lệ (VD: 16 hoặc 16.5).")
        track_message(context, reply.message_id)
        return True
        
    sheets = context.bot_data['sheets']
    import asyncio
    success = await asyncio.to_thread(sheets.update_salary_rate, nickname, str(new_rate))
    
    if success:
        reply = await update.message.reply_text(
            f"✅ Đã cập nhật mức lương cho *{nickname}* thành *{new_rate:g}k/h*.",
            parse_mode='Markdown',
            reply_markup=get_admin_keyboard(is_super_admin=is_super_admin(update.effective_chat.id))
        )
    else:
        reply = await update.message.reply_text(
            f"❌ Không thể cập nhật mức lương cho *{nickname}*. Vui lòng thử lại.",
            parse_mode='Markdown',
            reply_markup=get_admin_keyboard(is_super_admin=is_super_admin(update.effective_chat.id))
        )
    track_message(context, reply.message_id)
    return True
