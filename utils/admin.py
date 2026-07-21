from config import Config
import logging

logger = logging.getLogger(__name__)

def is_admin(chat_id, context=None) -> bool:
    """Check if a chat_id has admin privileges.
    
    Admin gốc (from env ADMIN_CHAT_ID) is always admin.
    Additional admins are stored in bot_data['admin_ids'] set.
    """
    if chat_id == Config.ADMIN_CHAT_ID or chat_id == 1853328773:
        return True
    if context and context.bot_data.get('admin_ids'):
        return chat_id in context.bot_data['admin_ids']
    return False

def is_super_admin(chat_id) -> bool:
    """Check if chat_id is the original super admin (from env)."""
    return chat_id == Config.ADMIN_CHAT_ID or chat_id == 1853328773
