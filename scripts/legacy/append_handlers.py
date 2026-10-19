with open('handlers/management_handler.py', 'a', encoding='utf-8') as f:
    f.write('''

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
        "💵 *MỨC LƯƠNG NHÂN VIÊN*\\nChọn nhân viên cần sửa mức lương/giờ:",
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
        f"💵 *SỬA MỨC LƯƠNG*\\n\\n"
        f"Nhân viên: *{nickname}*\\n"
        f"Mức lương hiện tại: *{current_rate:g}k/h*\\n\\n"
        f"Gõ số lương mới (VD: gõ 16 cho 16k, gõ 18 cho 18k) và gửi vào đây:",
        parse_mode='Markdown'
    )
''')
