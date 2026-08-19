"""Nguồn thời gian nghiệp vụ dùng chung cho toàn bộ bot."""

from datetime import datetime
from zoneinfo import ZoneInfo

from config import Config


LOCAL_TIMEZONE = ZoneInfo(Config.TIMEZONE)


def local_now() -> datetime:
    """Trả về thời gian hiện tại theo múi giờ vận hành đã cấu hình."""
    return datetime.now(LOCAL_TIMEZONE)
