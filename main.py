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
from handlers.checkin_handler import handle_checkin_photo, send_checkout_reminder, alert_unclosed_sessions, midnight_auto_cleanup
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

    # Khởi tạo các Job Queue
    import datetime
    import pytz
    from handlers.checkin_handler import send_checkout_reminder, alert_unclosed_sessions, midnight_auto_cleanup

    tz = pytz.timezone('Asia/Ho_Chi_Minh')

    # 1. Quét dọn lúc 23:55 (Tự động chốt ca cho những người quên)
    application.job_queue.run_daily(
        midnight_auto_cleanup,
        time=datetime.time(hour=23, minute=55, tzinfo=tz),
        name='midnight_auto_cleanup'
    )

    # 2. Nhắc Check Out lúc kết ca
    checkout_shifts = [
        ('Sáng', datetime.time(hour=12, minute=0, tzinfo=tz)),
        ('Chiều', datetime.time(hour=18, minute=0, tzinfo=tz)),
        ('Tối', datetime.time(hour=22, minute=30, tzinfo=tz)),
    ]

    for shift_ca, shift_time in checkout_shifts:
        application.job_queue.run_daily(
            send_checkout_reminder,
            time=shift_time,
            data={'shift_ca': shift_ca},
            name=f'remind_checkout_{shift_ca}'
        )
        # Báo cáo các phiên quên check out sau 15 phút
        alert_time = (datetime.datetime.combine(datetime.date.today(), shift_time) + datetime.timedelta(minutes=15)).time().replace(tzinfo=tz)
        application.job_queue.run_daily(
            alert_unclosed_sessions,
            time=alert_time,
            data={'shift_ca': shift_ca},
            name=f'alert_unclosed_{shift_ca}'
        )

    # 3. Tạo/Cập nhật Bảng Lương hàng ngày lúc 00:05
    async def scheduled_salary_sheet_maintenance(context):
        """Tự động kiểm tra và tạo/cập nhật bảng lương hàng tháng lúc 00:05"""
        try:
            logger.info("Chạy tác vụ bảo trì Bảng Lương (00:05)...")
            sheets = context.bot_data['sheets']
            # Gọi hàm kiểm tra và tạo sheet tháng mới/cập nhật nếu cần
            await asyncio.to_thread(sheets.ensure_salary_worksheet)
            logger.info("Hoàn tất bảo trì Bảng Lương.")
        except Exception as e:
            logger.error(f"Lỗi bảo trì Bảng Lương: {e}")

    import asyncio
    application.job_queue.run_daily(
        scheduled_salary_sheet_maintenance,
        time=datetime.time(hour=0, minute=5, tzinfo=tz),
        name='salary-sheet-maintenance',
    )

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