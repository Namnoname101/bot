import functools
import logging
from telegram import Update
from telegram.ext import ContextTypes
from config import Config

logger = logging.getLogger(__name__)

def group_only(func):
    """Decorator: Chỉ cho phép nhận lệnh từ Group Chat ID của quán."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_chat:
            return
        if update.effective_chat.id != Config.GROUP_CHAT_ID:
            logger.warning(f"Từ chối truy cập GROUP_ONLY từ Chat ID: {update.effective_chat.id}")
            # Im lặng bỏ qua để không spam tin nhắn cho người lạ
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def admin_only(func):
    """Decorator: Chỉ cho phép Quản lý (Admin Chat ID) thao tác."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_chat:
            return
        
        if update.effective_chat.id != Config.ADMIN_CHAT_ID:
            logger.warning(f"Từ chối truy cập ADMIN_ONLY từ Chat ID: {update.effective_chat.id}")
            
            if update.callback_query:
                await update.callback_query.answer("⛔ Bạn không có quyền thao tác!", show_alert=True)
            elif update.message:
                await update.message.reply_text("⛔ Lệnh này chỉ dành cho Quản lý.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper