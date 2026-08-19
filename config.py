import os
import json
import logging
from logging.handlers import TimedRotatingFileHandler
from dotenv import load_dotenv

# Load biến môi trường trước khi cấu hình các thành phần phụ thuộc.
load_dotenv()

# Thiết lập logging đúng một lần. Trên Fly ưu tiên stdout; file log chỉ bật khi cần.
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

if not getattr(root_logger, '_sober_configured', False):
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    if os.getenv('LOG_TO_FILE', '').strip().lower() in {'1', 'true', 'yes'}:
        os.makedirs("logs", exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            "logs/bot.log",
            when="midnight",
            interval=1,
            backupCount=30,
            encoding='utf-8',
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    root_logger._sober_configured = True

logger = logging.getLogger(__name__)

# httpx ghi toàn bộ URL Telegram ở mức INFO; URL này chứa bot token.
# Chỉ giữ cảnh báo/lỗi để secret không xuất hiện trong log vận hành.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    
    # Chat ID phải được cấu hình trong .env - không có fallback
    # để tránh gửi dữ liệu nhầm sang ID của nhà phát triển
    try:
        GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID"))
        ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
    except (TypeError, ValueError):
        logger.error(
            "❌ LỖI CẤU HÌNH: GROUP_CHAT_ID hoặc ADMIN_CHAT_ID chưa được thiết lập trong file .env\n"
            "Vui lòng thêm các dòng sau vào file .env của bạn:\n"
            "GROUP_CHAT_ID=<chat_id_của_group>\n"
            "ADMIN_CHAT_ID=<chat_id_của_quản_lý>\n"
        )
        raise
    
    # Cấu hình Google
    GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    # Khi deploy trên server (Render...), paste toàn bộ nội dung credentials.json vào env var này
    GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")    # ID của Google Spreadsheet (File lưu dữ liệu chính)
    SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
    
    # ID của Google Spreadsheet (File Tính Lương)
    SALARY_SPREADSHEET_ID = os.getenv("SALARY_SPREADSHEET_ID")

    # Thư mục Google Drive lưu ảnh check-in
    DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")

    DEFAULT_HOURLY_RATE_K = float(os.getenv("DEFAULT_HOURLY_RATE_K", "16"))
    TIMEZONE = os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh")

    @classmethod
    def get_google_credentials_info(cls) -> dict:
        """Trả về dict credentials Google. Ưu tiên env var JSON, fallback về file."""
        if cls.GOOGLE_CREDENTIALS_JSON:
            return json.loads(cls.GOOGLE_CREDENTIALS_JSON.lstrip('\ufeff'))
        with open(cls.GOOGLE_CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    @classmethod
    def validate(cls):
        """Kiểm tra xem các biến môi trường bắt buộc đã được thiết lập chưa."""
        missing_keys = []
        if not cls.BOT_TOKEN: missing_keys.append("BOT_TOKEN")
        if not cls.SPREADSHEET_ID: missing_keys.append("SPREADSHEET_ID")
        if not cls.SALARY_SPREADSHEET_ID: missing_keys.append("SALARY_SPREADSHEET_ID")
        
        if missing_keys:
            error_msg = f"Thiếu các biến môi trường bắt buộc trong file .env: {', '.join(missing_keys)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

# Chạy kiểm tra cấu hình ngay khi file được import
Config.validate()
