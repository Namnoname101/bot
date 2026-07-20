import asyncio
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from utils.admin import is_admin
from utils.auto_delete import track_message

logger = logging.getLogger(__name__)


def _selected_salary_month(context: ContextTypes.DEFAULT_TYPE) -> tuple[int, int]:
    selected = context.chat_data.get('salary_month') or {}
    now = datetime.now()
    return int(selected.get('month', now.month)), int(selected.get('year', now.year))


def _set_salary_month(context: ContextTypes.DEFAULT_TYPE, month: int, year: int):
    context.chat_data['salary_month'] = {'month': int(month), 'year': int(year)}


def _salary_period_label(month: int, year: int) -> str:
    if month == 1:
        start_month, start_year = 12, year - 1
    else:
        start_month, start_year = month - 1, year
    return f"17/{start_month:02d}/{start_year}–16/{month:02d}/{year}"


def _current_salary_month() -> tuple[int, int]:
    now = datetime.now()
    if now.day >= 17:
        if now.month == 12:
            return 1, now.year + 1
        return now.month + 1, now.year
    return now.month, now.year


def _salary_report_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Nhập Ứng Lương", callback_data="salary_adv"),
         InlineKeyboardButton("🎁 Nhập Thưởng Tiền", callback_data="salary_bon")],
        [InlineKeyboardButton("🗓 Chọn Tháng Khác", callback_data="salary_choose_month")],
        [InlineKeyboardButton("✖ Đóng", callback_data="salary_cancel")],
    ])


def _salary_month_keyboard(options: list) -> InlineKeyboardMarkup:
    current_month, current_year = _current_salary_month()
    keyboard, row = [], []
    for option in options:
        month = int(option['month'])
        year = int(option['year'])
        is_current = month == current_month and year == current_year
        prefix = "📍 " if is_current else ""
        suffix = " ✨" if not option.get('exists') else ""
        label = f"{prefix}T{month}/{year} ({_salary_period_label(month, year)}){suffix}"
        row.append(InlineKeyboardButton(label, callback_data=f"salary_month_{year}_{month}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("✖ Đóng", callback_data="salary_cancel")])
    return InlineKeyboardMarkup(keyboard)


async def _load_month_options(sheets) -> list:
    options = await asyncio.to_thread(sheets.get_salary_month_options)
    if options:
        return options
    now = datetime.now()
    return [{'month': now.month, 'year': now.year, 'exists': False}]


async def _show_selected_report(query, context: ContextTypes.DEFAULT_TYPE):
    month, year = _selected_salary_month(context)
    sheets = context.bot_data['sheets']
    await query.edit_message_text(
        f"⏳ Đang tải bảng lương T{month}/{year} ({_salary_period_label(month, year)})..."
    )
    report = await asyncio.to_thread(sheets.get_salary_report, month, year)
    await query.edit_message_text(
        report,
        parse_mode="Markdown",
        reply_markup=_salary_report_keyboard(),
    )


async def handle_salary_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin bấm nút 💰 Tính Lương (QL) → chọn tháng cần xem."""
    logger.info(
        "handle_salary_button called by user %s in chat %s",
        update.effective_user.id,
        update.effective_chat.id,
    )
    if not is_admin(update.effective_chat.id, context):
        logger.info("User is not admin, ignoring.")
        return

    wait_msg = await update.message.reply_text("⏳ Đang tải danh sách tháng lương...")
    track_message(context, wait_msg.message_id)
    try:
        options = await _load_month_options(context.bot_data['sheets'])
        await wait_msg.edit_text(
            "💰 *TÍNH LƯƠNG* — Chọn tháng cần xem:\n"
            "_Dấu ✨ nghĩa là bảng tháng hiện tại sẽ được tạo từ form cũ khi mở._",
            parse_mode="Markdown",
            reply_markup=_salary_month_keyboard(options),
        )
    except Exception as e:
        logger.error(f"Lỗi tải danh sách tháng lương: {e}")
        await wait_msg.edit_text(f"❌ Lỗi: {e}")


async def handle_salary_modifier_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: str,
):
    """Yêu cầu ứng lương/thưởng cho đúng tháng đang được chọn."""
    action_name = "Ứng lương" if data == "salary_adv" else "Thưởng"
    context.chat_data['salary_action'] = "advance" if data == "salary_adv" else "bonus"
    month, year = _selected_salary_month(context)
    _set_salary_month(context, month, year)

    sheets = context.bot_data['sheets']
    try:
        balances = await asyncio.to_thread(sheets.get_all_balances)
        nicks = list(balances.keys())
        if not nicks:
            if update.callback_query:
                await update.callback_query.answer("Chưa có nhân viên nào!", show_alert=True)
            else:
                msg = await update.message.reply_text("Chưa có nhân viên nào!")
                track_message(context, msg.message_id)
            return

        kb = [[InlineKeyboardButton(nick, callback_data=f"sal_emp_{nick}")] for nick in nicks]
        if update.callback_query:
            kb.append([InlineKeyboardButton("🔙 Quay Lại", callback_data="salary_back_main")])
            await update.callback_query.edit_message_text(
                f"Chọn nhân viên để thêm *{action_name}* vào *T{month}/{year}* "
                f"({_salary_period_label(month, year)}):",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb),
            )
        else:
            kb.append([InlineKeyboardButton("✖ Hủy", callback_data="salary_cancel")])
            msg = await update.message.reply_text(
                f"Chọn nhân viên để thêm *{action_name}* vào *T{month}/{year}* "
                f"({_salary_period_label(month, year)}):",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb),
            )
            track_message(context, msg.message_id)
    except Exception as e:
        if update.callback_query:
            await update.callback_query.answer(f"Lỗi: {e}", show_alert=True)
        else:
            msg = await update.message.reply_text(f"Lỗi: {e}")
            track_message(context, msg.message_id)


async def salary_inline_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý toàn bộ nút inline của phần lương."""
    query = update.callback_query
    if not is_admin(update.effective_chat.id, context):
        try:
            await query.answer("⛔ Chỉ quản lý được dùng chức năng này.", show_alert=True)
        except Exception:
            pass
        return

    try:
        await query.answer()
    except Exception:
        pass

    data = query.data

    if data == "salary_cancel":
        await query.message.delete()
        context.chat_data.pop('salary_action', None)
        context.chat_data.pop('salary_emp', None)
        context.chat_data.pop('salary_month', None)
        return

    if data == "salary_choose_month":
        context.chat_data.pop('salary_action', None)
        context.chat_data.pop('salary_emp', None)
        options = await _load_month_options(context.bot_data['sheets'])
        await query.edit_message_text(
            "💰 *TÍNH LƯƠNG* — Chọn tháng cần xem:",
            parse_mode="Markdown",
            reply_markup=_salary_month_keyboard(options),
        )
        return

    if data.startswith("salary_month_"):
        try:
            _, _, year_str, month_str = data.split('_', 3)
            month, year = int(month_str), int(year_str)
            if month < 1 or month > 12:
                raise ValueError
        except (TypeError, ValueError):
            await query.answer("Tháng không hợp lệ.", show_alert=True)
            return
        _set_salary_month(context, month, year)
        await _show_selected_report(query, context)
        return

    if data in ("salary_adv", "salary_bon"):
        await handle_salary_modifier_request(update, context, data)
        return

    if data == "salary_back_main":
        context.chat_data.pop('salary_action', None)
        context.chat_data.pop('salary_emp', None)
        try:
            await _show_selected_report(query, context)
        except Exception as e:
            await query.answer(f"Lỗi: {e}", show_alert=True)
        return

    if data.startswith("sal_emp_"):
        emp_name = data[len("sal_emp_"):]
        context.chat_data['salary_emp'] = emp_name
        action = context.chat_data.get('salary_action')
        action_name = "Ứng lương" if action == "advance" else "Thưởng tiền"
        month, year = _selected_salary_month(context)
        await query.edit_message_text(
            f"Nhập số tiền **{action_name}** cho **{emp_name}** tại "
            f"**T{month}/{year}** ({_salary_period_label(month, year)}) "
            f"(ví dụ: `50` = 50,000đ):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Quay Lại", callback_data="salary_back_main")],
                [InlineKeyboardButton("✖ Hủy", callback_data="salary_cancel")],
            ]),
        )


async def process_salary_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Bắt số tiền và cập nhật đúng bảng lương tháng đã chọn."""
    action = context.chat_data.get('salary_action')
    emp = context.chat_data.get('salary_emp')
    if not (action and emp):
        return False

    text = update.message.text.strip()
    track_message(context, update.message.message_id)
    try:
        if text.lower().endswith('k'):
            amount = int(text[:-1].replace(',', '').replace('.', ''))
        else:
            amount = int(text.replace(',', '').replace('.', ''))
        if amount <= 0:
            raise ValueError

        wait_msg = await update.message.reply_text("⏳ Đang cập nhật Google Sheets...")
        track_message(context, wait_msg.message_id)
        sheets = context.bot_data['sheets']
        month, year = _selected_salary_month(context)
        is_bonus = action == "bonus"

        await asyncio.to_thread(
            sheets.update_salary_modifier,
            emp,
            is_bonus,
            amount,
            month,
            year,
        )
        report = await asyncio.to_thread(sheets.get_salary_report, month, year)
        context.chat_data.pop('salary_action', None)
        context.chat_data.pop('salary_emp', None)

        try:
            await wait_msg.delete()
        except Exception:
            pass

        msg = await update.message.reply_text(
            f"✅ Đã thêm {amount}k cho {emp} tại T{month}/{year} "
            f"({_salary_period_label(month, year)}).\n\n{report}",
            parse_mode="Markdown",
            reply_markup=_salary_report_keyboard(),
        )
        track_message(context, msg.message_id)
    except ValueError:
        msg = await update.message.reply_text("❌ Vui lòng nhập số tiền lớn hơn 0.")
        track_message(context, msg.message_id)
    except Exception as e:
        logger.error(f"Lỗi nhập ứng/thưởng: {e}")
        msg = await update.message.reply_text(f"❌ Lỗi: {e}")
        track_message(context, msg.message_id)
    return True
