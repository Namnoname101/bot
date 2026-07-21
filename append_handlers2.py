with open('handlers/management_handler.py', 'a', encoding='utf-8') as f:
    f.write('''
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
''')
