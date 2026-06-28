import logging
from telegram import BotCommand, Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, CallbackQueryHandler, ContextTypes

from config import Config
from utils.auto_delete import GUIDE_MESSAGE, get_main_keyboard
# Import các service (Hỗ trợ cả trường hợp bạn để file trong thư mục services/ hoặc ở ngoài thư mục gốc)
try:
    from services.google_sheets import GoogleSheetsService
    from services.google_drive import GoogleDriveService
except ImportError:
    from google_sheets import GoogleSheetsService
    from google_drive import GoogleDriveService

from handlers.report_handler import handle_photo_report
from handlers.reward_handler import use_reward, check_reward, check_all_rewards, help_command, start_command, button_click_handler, quick_report_command, inline_button_handler, announce_command
from handlers.checkin_handler import handle_checkin_photo
from handlers.endshift_handler import handle_endshift_photo

logger = logging.getLogger(__name__)


async def photo_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phân loại ảnh: check-in/check-out hoặc báo cáo doanh thu.
    
    Kiểm tra trạng thái chat_data để xác định ảnh này dùng cho mục đích gì.
    """
    if not update.effective_chat or update.effective_chat.id not in [Config.GROUP_CHAT_ID, Config.ADMIN_CHAT_ID]:
        return
    
    # ưu tiên xử lý check-in photo nếu đang chờ
    if context.chat_data.get('awaiting_checkin_photo'):
        await handle_checkin_photo(update, context)
        return

    # Ảnh kết ca
    if context.chat_data.get('awaiting_endshift_photo'):
        await handle_endshift_photo(update, context)
        return
    
    # Mặc định: xử lý như ảnh báo cáo doanh thu
    await handle_photo_report(update, context)

async def post_init(application):
    """Thiết lập Menu Commands mặc định cho Bot và gửi tin hướng dẫn ban đầu"""
    # Xóa toàn bộ menu lệnh (dấu "/") để người dùng tập trung vào các nút bấm (Reply Keyboard)
    await application.bot.delete_my_commands()

    # Gửi tin nhắn hướng dẫn ban đầu vào group (máy chung tại quán) kèm bàn phím luôn hiện
    # [ĐÃ TẮT ĐỂ TRÁNH SPAM - KHÔNG GỬI HƯỚNG DẪN KHI KHỞI ĐỘNG LẠI BOT NỮA]
    pass

def main():
    logger.info("Đang khởi động Bot...")

    # 1. Khởi tạo các Service kết nối Google
    try:
        sheets_service = GoogleSheetsService()
        drive_service = GoogleDriveService()
    except Exception as e:
        logger.error(f"Không thể khởi tạo Service. Bot sẽ dừng lại. Lỗi: {e}")
        return

    # 2. Khởi tạo Application của Telegram
    app = ApplicationBuilder().token(Config.BOT_TOKEN).post_init(post_init).build()

    # Truyền service vào bot_data để các handlers có thể gọi được mà không cần khởi tạo lại
    app.bot_data['sheets'] = sheets_service
    app.bot_data['drive'] = drive_service

    # 3. Đăng ký các Handlers
    # Nhận ảnh (check-in/check-out hoặc báo cáo)
    app.add_handler(MessageHandler(filters.PHOTO, photo_dispatcher))
    # Các lệnh liên quan đến thưởng
    app.add_handler(CommandHandler("dadung", use_reward))
    app.add_handler(CommandHandler("thuong", check_reward))
    app.add_handler(CommandHandler("bangthuong", check_all_rewards))
    app.add_handler(CommandHandler("baodoanhthu", quick_report_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("announce", announce_command))
    
    # Khởi động bàn phím ảo & Bắt sự kiện bấm nút
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_click_handler))
    
    # Bắt sự kiện bấm nút Inline Keyboard (Tra cứu thưởng / Báo dùng thưởng)
    app.add_handler(CallbackQueryHandler(inline_button_handler))

    # 4. Chạy bot
    logger.info("✅ Bot đã sẵn sàng và đang chạy! Nhấn Ctrl + C để dừng.")
    app.run_polling()

if __name__ == '__main__':
    main()