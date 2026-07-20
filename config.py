import os
import json
import logging
from dotenv import load_dotenv

# Thiết lập logging cơ bản cho toàn bộ project để dễ dàng debug và theo dõi trên server
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load biến môi trường từ file .env
load_dotenv()

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
    SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1dE0_l25uY05q-0L5u3Q9mXW10Z-9mNn923S-T2_R")
    
    # ID của Google Spreadsheet (File Tính Lương)
    SALARY_SPREADSHEET_ID = os.getenv("SALARY_SPREADSHEET_ID", "170ThkLaXrriHsi9iUB2m-FyRZ73iz8SYpJwy6jU0sjU")

    # Thư mục Google Drive lưu ảnh check-in
    DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "1lJ9m_X-Z_R-K2m2k9_3L_Z_2-9_R_3_9")

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
        if not cls.DRIVE_FOLDER_ID: missing_keys.append("DRIVE_FOLDER_ID")
        
        if missing_keys:
            error_msg = f"Thiếu các biến môi trường bắt buộc trong file .env: {', '.join(missing_keys)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

# Chạy kiểm tra cấu hình ngay khi file được import
Config.validate()
