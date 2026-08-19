from config import Config
import logging

logger = logging.getLogger(__name__)

def is_admin(user_id, context=None) -> bool:
    """Kiểm tra quyền theo Telegram user ID, không theo chat/group ID.
    
    Admin gốc (from env ADMIN_CHAT_ID) is always admin.
    Additional admins are stored in bot_data['admin_ids'] set.
    """
    if user_id == Config.ADMIN_CHAT_ID:
        return True
    if context and context.bot_data.get('admin_ids'):
        return user_id in context.bot_data['admin_ids']
    return False

def is_super_admin(user_id) -> bool:
    """Chỉ ADMIN_CHAT_ID cấu hình mới có quyền super admin."""
    return user_id == Config.ADMIN_CHAT_ID
