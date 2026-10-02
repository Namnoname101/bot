import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from config import Config
from utils.admin import is_admin, is_super_admin


def validate_telegram_init_data(
    init_data: str,
    bot_token: str | None = None,
    max_age_seconds: int = 86400,
) -> dict | None:
    """Xác thực chữ ký HMAC-SHA256 của Telegram WebApp initData.

    Trả về dict chứa thông tin đã xác thực (bao gồm 'user') hoặc None nếu không hợp lệ.
    """
    if not init_data or not isinstance(init_data, str):
        return None

    token = (bot_token or Config.BOT_TOKEN or "").strip()
    if not token:
        return None

    try:
        parsed_pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received_hash = parsed_pairs.pop("hash", None)
    if not received_hash:
        return None

    if max_age_seconds > 0:
        try:
            auth_date = int(parsed_pairs.get("auth_date", "0"))
            if auth_date <= 0 or (time.time() - auth_date) > max_age_seconds:
                return None
        except (TypeError, ValueError):
            return None

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(parsed_pairs.items(), key=lambda item: item[0])
    )
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    user_raw = parsed_pairs.get("user")
    user_info = {}
    if user_raw:
        try:
            user_info = json.loads(user_raw)
        except Exception:
            return None

    parsed_pairs["user"] = user_info
    return parsed_pairs


def resolve_request_user(request, bot_data: dict | None = None) -> dict | None:
    """Xác định người dùng Telegram từ request header hoặc query (hỗ trợ DEV_MODE khi bật)."""
    init_data = (
        request.headers.get("X-Telegram-Init-Data")
        or request.query.get("initData")
        or ""
    ).strip()

    context_stub = type("ContextStub", (), {"bot_data": bot_data or {}})()

    if init_data:
        verified = validate_telegram_init_data(init_data)
        if verified and isinstance(verified.get("user"), dict) and verified["user"].get("id"):
            user_obj = verified["user"]
            uid = int(user_obj["id"])
            first_name = str(user_obj.get("first_name") or "").strip()
            last_name = str(user_obj.get("last_name") or "").strip()
            full_name = f"{first_name} {last_name}".strip() or user_obj.get("username") or f"User {uid}"
            return {
                "id": uid,
                "first_name": first_name or full_name,
                "last_name": last_name,
                "full_name": full_name,
                "username": user_obj.get("username") or "",
                "is_admin": is_admin(uid, context_stub),
                "is_super_admin": is_super_admin(uid),
                "authenticated": True,
            }
        return None

    if Config.WEBAPP_DEV_MODE:
        dev_uid_raw = (
            request.headers.get("X-Dev-User-Id")
            or request.query.get("dev_user_id")
            or str(Config.ADMIN_CHAT_ID)
        )
        try:
            uid = int(dev_uid_raw)
        except (TypeError, ValueError):
            uid = Config.ADMIN_CHAT_ID
        dev_name = (
            request.headers.get("X-Dev-User-Name")
            or request.query.get("dev_user_name")
            or ("Quản lý (Dev)" if is_admin(uid, context_stub) else "Nhân viên (Dev)")
        )
        return {
            "id": uid,
            "first_name": dev_name,
            "last_name": "",
            "full_name": dev_name,
            "username": "dev_user",
            "is_admin": is_admin(uid, context_stub),
            "is_super_admin": is_super_admin(uid),
            "authenticated": False,
            "dev_mode": True,
        }

    # Hỗ trợ mở trực tiếp trên trình duyệt web (Chrome / Safari) cho nhân viên không dùng Telegram
    admin_key = (
        request.headers.get("X-Admin-Key")
        or request.query.get("admin_key")
        or ""
    ).strip()
    if admin_key:
        valid_super = (
            admin_key == str(Config.ADMIN_CHAT_ID)
            or (bool(Config.WEBAPP_ADMIN_PIN) and admin_key == Config.WEBAPP_ADMIN_PIN)
        )
        valid_sub_admin = False
        sub_uid = 0
        if not valid_super:
            try:
                sub_uid = int(admin_key)
                valid_sub_admin = is_admin(sub_uid, context_stub)
            except (TypeError, ValueError):
                valid_sub_admin = False

        if valid_super or valid_sub_admin:
            uid = Config.ADMIN_CHAT_ID if valid_super else sub_uid
            return {
                "id": uid,
                "first_name": "Quản lý",
                "last_name": "",
                "full_name": "Quản lý (Web)",
                "username": "admin_web",
                "is_admin": True,
                "is_super_admin": valid_super,
                "authenticated": True,
                "web_mode": True,
            }

    if Config.WEBAPP_ALLOW_BROWSER:
        from urllib.parse import unquote
        emp_name = unquote(
            request.headers.get("X-Employee-Name")
            or request.query.get("emp")
            or "Nhân viên"
        ).strip() or "Nhân viên"
        return {
            "id": 0,
            "first_name": emp_name,
            "last_name": "",
            "full_name": emp_name,
            "username": "web_employee",
            "is_admin": False,
            "is_super_admin": False,
            "authenticated": False,
            "web_mode": True,
        }

    return None

