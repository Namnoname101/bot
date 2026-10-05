import asyncio
import json
import logging
import re
import time
from pathlib import Path
from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

from config import Config
from handlers.inventory_handler import (
    _find_matching_materials,
    _get_group_icon,
    _parse_chunk_qty_and_query,
)
from handlers.overtime_handler import _salary_window
from utils.time_utils import local_now
from utils.validators import (
    _parse_amount_str,
    check_reward_eligibility,
    deduplicate_employees,
    normalize_name,
    validate_nickname,
)
from webapp.auth import create_auth_token, resolve_request_user, verify_auth_token
from webapp.store import WebAppStore, get_week_info

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

SHEETS_KEY = web.AppKey("sheets", object)
BOT_KEY = web.AppKey("bot", object)
BOT_DATA_KEY = web.AppKey("bot_data", dict)
STORE_KEY = web.AppKey("store", WebAppStore)
_ReqKey = getattr(web, "RequestKey", web.AppKey)
USER_KEY = _ReqKey("user", dict)


def _infer_ca(now) -> str:
    if now.hour < 12:
        return "Sáng"
    if now.hour < 18:
        return "Chiều"
    return "Tối"


def _get_employees_list(sheets, store=None) -> list:
    """Lấy danh sách nhân viên chi tiết kèm vị trí do Admin phân công."""
    if hasattr(sheets, "get_employees_detail"):
        try:
            details = sheets.get_employees_detail()
            if details:
                if store:
                    for d in details:
                        d["role"] = store.get_employee_role(d.get("nickname") or d.get("full_name") or "")
                return details
        except Exception:
            pass

    balances = {}
    rates = {}
    try:
        balances = sheets.get_all_balances() or {}
    except Exception:
        pass
    try:
        rates = sheets.get_all_salary_rates() or {}
    except Exception:
        pass

    rate_by_norm = {normalize_name(k): (k, v) for k, v in rates.items()}
    result = []
    seen = set()
    for nick, bal in balances.items():
        norm = normalize_name(nick)
        seen.add(norm)
        orig_nick, rate = rate_by_norm.get(norm, (nick, Config.DEFAULT_HOURLY_RATE_K))
        emp_role = store.get_employee_role(orig_nick or nick) if store else "Pha Chế"
        result.append({
            "nickname": orig_nick or nick,
            "key": norm,
            "full_name": orig_nick or nick,
            "rate": rate,
            "balance": int(bal or 0),
            "role": emp_role,
        })
    for norm, (orig_nick, rate) in rate_by_norm.items():
        if norm not in seen:
            emp_role = store.get_employee_role(orig_nick) if store else "Pha Chế"
            result.append({
                "nickname": orig_nick,
                "key": norm,
                "full_name": orig_nick,
                "rate": rate,
                "balance": 0,
                "role": emp_role,
            })
    return result


async def _safe_send_group(bot, text: str, parse_mode: str | None = "Markdown"):
    if not bot:
        return
    try:
        await bot.send_message(
            chat_id=Config.GROUP_CHAT_ID,
            text=text,
            parse_mode=parse_mode,
        )
    except Exception as e:
        logger.warning("Không gửi được thông báo Mini App vào group: %s", e)


async def _safe_send_admin(bot, text: str, reply_markup=None, parse_mode: str | None = "Markdown"):
    if not bot:
        return
    try:
        await bot.send_message(
            chat_id=Config.ADMIN_CHAT_ID,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception as e:
        logger.warning("Không gửi được thông báo Mini App cho admin: %s", e)


PUBLIC_API_PATHS = {"/api/health", "/api/auth/login", "/api/auth/public-users"}


@web.middleware
async def auth_middleware(request: web.Request, handler):
    if not request.path.startswith("/api/") or request.path in PUBLIC_API_PATHS:
        return await handler(request)

    bot_data = request.app.get(BOT_DATA_KEY) or {}
    user = resolve_request_user(request, bot_data)
    if not user:
        return web.json_response(
            {
                "success": False,
                "error": "unauthorized",
                "message": "Phiên Telegram Mini App không hợp lệ hoặc đã hết hạn. Vui lòng mở lại từ Telegram.",
            },
            status=401,
        )
    request[USER_KEY] = user
    return await handler(request)


def _require_admin(request: web.Request) -> web.Response | None:
    user = request.get(USER_KEY) or {}
    if not user.get("is_admin"):
        return web.json_response(
            {"success": False, "error": "forbidden", "message": "⛔ Chức năng này chỉ dành cho Quản lý."},
            status=403,
        )
    return None


def _require_super_admin(request: web.Request) -> web.Response | None:
    user = request.get(USER_KEY) or {}
    if not user.get("is_super_admin"):
        return web.json_response(
            {"success": False, "error": "forbidden", "message": "⛔ Chỉ Admin gốc mới có quyền thực hiện."},
            status=403,
        )
    return None


# ── Handlers ─────────────────────────────────────────────────────────────────

async def handle_index(request: web.Request) -> web.Response:
    index_file = STATIC_DIR / "index.html"
    return web.FileResponse(index_file, headers={"Cache-Control": "no-cache"})


async def handle_health(request: web.Request) -> web.Response:
    now = local_now()
    return web.json_response({
        "status": "ok",
        "time": now.strftime("%d/%m/%Y %H:%M:%S"),
    })


_login_failures: dict[str, list[float]] = {}
_login_lock = asyncio.Lock()
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_WINDOW = 300.0  # 5 phút (300 giây)


def _get_client_ip(request: web.Request) -> str:
    fly_ip = request.headers.get("Fly-Client-IP")
    if fly_ip:
        return fly_ip.strip()
    x_forwarded = request.headers.get("X-Forwarded-For")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return getattr(request, "remote", None) or "127.0.0.1"


async def _check_rate_limit(key: str) -> bool:
    now = time.time()
    async with _login_lock:
        attempts = _login_failures.get(key, [])
        attempts = [t for t in attempts if now - t < LOGIN_LOCKOUT_WINDOW]
        _login_failures[key] = attempts
        return len(attempts) >= MAX_LOGIN_ATTEMPTS


async def _record_failed_attempt(key: str):
    async with _login_lock:
        attempts = _login_failures.setdefault(key, [])
        attempts.append(time.time())


async def _clear_failed_attempts(key: str):
    async with _login_lock:
        _login_failures.pop(key, None)


async def handle_auth_login(request: web.Request) -> web.Response:
    """Xử lý đăng nhập bằng Username và Mật khẩu (mặc định 123456789), có rate limiting chống brute-force."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "message": "Dữ liệu JSON không hợp lệ."}, status=400)

    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "").strip()
    req_role = str(data.get("role") or "").strip()
    preferred_role = req_role if req_role in ("Pha Chế", "Phục Vụ", "Quản Lý", "Thu Ngân") else None

    if not username:
        return web.json_response({"success": False, "message": "Vui lòng nhập Tên đăng nhập."}, status=400)
    if not password:
        return web.json_response({"success": False, "message": "Vui lòng nhập Mật khẩu (mặc định: 123456789)."}, status=400)

    # Rate limiting: kiểm tra số lần thử sai theo IP và Username
    client_ip = _get_client_ip(request)
    user_norm = normalize_name(username)
    rate_key = f"{client_ip}:{user_norm}"
    if await _check_rate_limit(rate_key) or await _check_rate_limit(client_ip):
        return web.json_response({
            "success": False,
            "error": "rate_limited",
            "message": "⛔ Bạn đã thử đăng nhập sai quá nhiều lần. Vui lòng đợi 5 phút trước khi thử lại.",
        }, status=429)

    sheets = request.app[SHEETS_KEY]
    store: WebAppStore = request.app[STORE_KEY]
    bot_data = request.app.get(BOT_DATA_KEY) or {}

    employees = await asyncio.to_thread(_get_employees_list, sheets, store)
    ok, user_info, err_msg = store.verify_login(
        username=username,
        password=password,
        employees=employees,
        bot_data=bot_data,
        preferred_role=preferred_role,
    )
    if not ok:
        await _record_failed_attempt(rate_key)
        await _record_failed_attempt(client_ip)
        return web.json_response({"success": False, "message": err_msg}, status=401)

    # Đăng nhập thành công -> xóa bộ đếm thất bại
    await _clear_failed_attempts(rate_key)

    token = create_auth_token(user_info)
    must_change = bool(user_info.get("must_change_password"))
    res_data = {
        "success": True,
        "token": token,
        "user": user_info,
        "role": user_info.get("role") or role,
        "must_change_password": must_change,
        "message": f"Chào mừng {user_info.get('full_name')} vào hệ thống!",
    }
    if must_change:
        res_data["warning"] = "⚠️ Bạn đang sử dụng mật khẩu mặc định (123456789). Vui lòng đổi mật khẩu để bảo vệ tài khoản!"

    return web.json_response(res_data)


async def handle_auth_public_users(request: web.Request) -> web.Response:
    """Trả về danh sách tài khoản cho màn hình đăng nhập (admin + danh sách nhân viên mới nhất)."""
    sheets = request.app[SHEETS_KEY]
    store: WebAppStore = request.app[STORE_KEY]
    employees = await asyncio.to_thread(_get_employees_list, sheets, store)
    names = ["admin"]
    emp_list = []
    for e in (employees or []):
        nick = str(e.get("nickname") or e.get("full_name") or "").strip()
        full = str(e.get("full_name") or nick).strip()
        if nick:
            if nick not in names:
                names.append(nick)
            emp_list.append({
                "nickname": nick,
                "full_name": full,
                "role": e.get("role") or "Pha Chế",
            })
    return web.json_response({
        "success": True,
        "users": names,
        "employees": emp_list,
    })


async def handle_auth_change_password(request: web.Request) -> web.Response:
    """Đổi mật khẩu tài khoản người dùng hoặc admin."""
    user = request.get(USER_KEY) or {}
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"success": False, "message": "Dữ liệu JSON không hợp lệ."}, status=400)

    old_pwd = str(data.get("old_password") or "").strip()
    new_pwd = str(data.get("new_password") or "").strip()
    if not old_pwd or not new_pwd:
        return web.json_response({"success": False, "message": "Vui lòng nhập đầy đủ mật khẩu cũ và mới."}, status=400)
    if len(new_pwd) < 4:
        return web.json_response({"success": False, "message": "Mật khẩu mới phải có ít nhất 4 ký tự."}, status=400)

    username = user.get("username") or user.get("nickname") or ""
    sheets = request.app[SHEETS_KEY]
    store: WebAppStore = request.app[STORE_KEY]
    bot_data = request.app.get(BOT_DATA_KEY) or {}

    employees = await asyncio.to_thread(_get_employees_list, sheets, store)
    ok, _, _ = store.verify_login(
        username=username,
        password=old_pwd,
        employees=employees,
        bot_data=bot_data,
    )
    if not ok:
        return web.json_response({"success": False, "message": "Mật khẩu hiện tại không chính xác."}, status=400)

    store.set_account_password(username, new_pwd)
    return web.json_response({"success": True, "message": "✅ Đã đổi mật khẩu thành công!"})


async def handle_bootstrap(request: web.Request) -> web.Response:
    sheets = request.app[SHEETS_KEY]
    bot_data = request.app[BOT_DATA_KEY]
    store: WebAppStore = request.app[STORE_KEY]
    user = request[USER_KEY]
    now = local_now()

    employees, open_sessions, materials, groups = await asyncio.gather(
        asyncio.to_thread(_get_employees_list, sheets, store),
        asyncio.to_thread(sheets.get_open_checkin_sessions),
        asyncio.to_thread(sheets.get_all_materials),
        asyncio.to_thread(sheets.get_material_groups),
    )

    group_items = [{"name": g, "icon": _get_group_icon(g)} for g in (groups or [])]
    pending_rewards = len((bot_data.get("reward_requests") or {})) if user.get("is_admin") else 0

    # Phân quyền: Của ai người đó xem! Ẩn số dư thưởng của người khác nếu không phải Quản lý
    user_norm = normalize_name(user.get("nickname") or user.get("username") or user.get("first_name") or "")
    is_user_admin = bool(user.get("is_admin"))
    filtered_employees = []
    for emp in (employees or []):
        emp_dict = dict(emp)
        if not is_user_admin and normalize_name(emp_dict.get("nickname") or emp_dict.get("full_name") or "") != user_norm:
            emp_dict["balance"] = None
        filtered_employees.append(emp_dict)

    w_info = get_week_info(0)
    current_roster = store.get_roster(w_info["week_key"])
    user_nick = user.get("nickname") or user.get("username") or ""
    my_notifs = store.get_notifications(user_nick) if user_nick else []
    my_swaps = store.get_swap_requests(nickname=user_nick) if user_nick else []
    pending_swaps_count = len(store.get_swap_requests(status="pending")) if is_user_admin else 0

    return web.json_response({
        "success": True,
        "user": user,
        "server_time": {
            "date": now.strftime("%d/%m/%Y"),
            "time": now.strftime("%H:%M"),
            "inferred_ca": _infer_ca(now),
        },
        "week_info": w_info,
        "current_roster": current_roster,
        "employees": filtered_employees,
        "open_sessions": open_sessions,
        "materials": materials,
        "material_groups": group_items,
        "pending_rewards_count": pending_rewards,
        "pending_swaps_count": pending_swaps_count,
        "checklists": store.get_checklists(),
        "recipes": store.get_recipes(),
        "shift_schedules": store.get_shift_schedules(),
        "petty_expenses": store.get_petty_expenses(15),
        "leave_requests": store.get_leave_requests(limit=20),
        "notifications": my_notifs,
        "swaps": my_swaps,
    })


# ── 1. Check-in / Check-out ──────────────────────────────────────────────────

def _is_kiosk_authorized(request: web.Request) -> bool:
    """Kiểm tra xem yêu cầu có đến từ thiết bị cố định tại quán (hoặc Quản lý) hay không."""
    user = request.get(USER_KEY) or {}
    if user.get("is_admin"):
        return True
    kiosk_key = (
        request.headers.get("X-Shop-Device-Key")
        or request.query.get("kiosk_key")
        or ""
    ).strip()
    return bool(kiosk_key and kiosk_key == Config.get_shop_kiosk_key())


async def handle_api_checkin(request: web.Request) -> web.Response:
    if not _is_kiosk_authorized(request):
        return web.json_response({
            "success": False,
            "error": "kiosk_required",
            "message": "🔒 Chức năng Chấm công chỉ được phép thực hiện trên máy điện thoại cố định tại quán."
        }, status=403)

    sheets = request.app[SHEETS_KEY]
    bot = request.app.get(BOT_KEY)
    data = await request.json()

    nickname = str(data.get("nickname") or "").strip()
    shift_type = str(data.get("shift_type") or "Ca Chính").strip()
    selected_ca = str(data.get("ca") or "").strip() or None

    if not nickname:
        return web.json_response({"success": False, "message": "Vui lòng chọn tên nhân viên."}, status=400)
    if shift_type == "Ca Gãy":
        selected_ca = "Tối"

    result = await asyncio.to_thread(sheets.checkin, nickname, shift_type, selected_ca)
    if not result.get("success"):
        err = result.get("error", "")
        if err == "already_checked_in":
            msg = f"⚠️ {nickname} đã check-in hôm nay lúc {result.get('time', '?')}. Hãy bấm Check Out khi kết thúc ca."
        elif err == "too_early":
            msg = f"⚠️ Ca {result.get('ca') or selected_ca} chỉ được check-in sớm tối đa 30 phút (từ {result.get('allowed_time', '?')})."
        elif err == "shift_ended":
            msg = f"⚠️ Ca {result.get('ca') or selected_ca} đã kết thúc. Vui lòng chọn đúng ca."
        elif err == "invalid_shift_ca":
            msg = "⚠️ Ca làm việc không hợp lệ."
        elif err == "invalid_shift_type":
            msg = "⚠️ Loại ca không hợp lệ."
        else:
            msg = f"❌ Lỗi check-in: {err}"
        return web.json_response({"success": False, "error": err, "message": msg}, status=400)

    time_str = result["time"]
    note = result["note"]
    ca = result["ca"]
    late_minutes = result.get("late_minutes", 0)
    date_str = result["date_str"]

    if late_minutes > 0 and bot:
        await _safe_send_admin(
            bot,
            f"📥 {nickname} — {time_str} Ca {ca} | {note}",
            parse_mode=None,
        )
        late_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Đã báo trước", callback_data=f"mark_reported_{date_str}_{nickname}"),
                InlineKeyboardButton("❌ Không báo trước", callback_data=f"mark_unreported_{date_str}_{nickname}"),
            ]
        ])
        await _safe_send_admin(
            bot,
            f"⚠️ {nickname} muộn {late_minutes}p (Ca {ca}) — báo trước?",
            reply_markup=late_kb,
            parse_mode=None,
        )

    await _safe_send_group(
        bot,
        f"✅ Cảm ơn {nickname}, đã ghi nhận check-in thành công! ({shift_type} — Ca {ca}, giờ tính công: {time_str})",
        parse_mode=None,
    )

    open_sessions = await asyncio.to_thread(sheets.get_open_checkin_sessions)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã ghi nhận Check-in cho {nickname} ({shift_type} — Ca {ca}, {time_str})!",
        "result": result,
        "open_sessions": open_sessions,
    })


async def handle_api_checkout(request: web.Request) -> web.Response:
    if not _is_kiosk_authorized(request):
        return web.json_response({
            "success": False,
            "error": "kiosk_required",
            "message": "🔒 Chức năng Check-out chỉ được phép thực hiện trên máy điện thoại cố định tại quán."
        }, status=403)

    sheets = request.app[SHEETS_KEY]
    bot = request.app.get(BOT_KEY)
    user = request[USER_KEY]
    data = await request.json()

    nickname = str(data.get("nickname") or "").strip()
    shift_type = str(data.get("shift_type") or "").strip() or None
    force_time = str(data.get("force_time") or "").strip() or None

    if not nickname:
        return web.json_response({"success": False, "message": "Vui lòng chọn phiên cần Check Out."}, status=400)
    if force_time and not user.get("is_admin"):
        force_time = None

    result = await asyncio.to_thread(sheets.checkout, nickname, shift_type, force_time)
    if not result.get("success"):
        err = result.get("error", "")
        if err == "not_checked_in":
            msg = f"⚠️ {nickname} chưa check-in hôm nay!"
        elif err == "checkout_before_start":
            msg = f"⚠️ Ca của {nickname} chưa bắt đầu (giờ tính công: {result.get('start_time', '?')}). Không thể Check Out lúc này."
        else:
            msg = f"❌ Lỗi check-out: {err}"
        return web.json_response({"success": False, "error": err, "message": msg}, status=400)

    await _safe_send_group(
        bot,
        f"✅ Cảm ơn {nickname}, đã ghi nhận check-out thành công! (Ra lúc {result['time']} — Tổng: {result['total_hours']}h)",
        parse_mode=None,
    )

    open_sessions = await asyncio.to_thread(sheets.get_open_checkin_sessions)
    return web.json_response({
        "success": True,
        "message": f"✅ Check-out thành công cho {nickname} ({result['total_hours']}h)!",
        "result": result,
        "open_sessions": open_sessions,
    })


# ── 2. Kho Nguyên Vật Liệu ───────────────────────────────────────────────────

async def handle_api_inventory(request: web.Request) -> web.Response:
    sheets = request.app[SHEETS_KEY]
    user = request[USER_KEY]

    materials, groups = await asyncio.gather(
        asyncio.to_thread(sheets.get_all_materials),
        asyncio.to_thread(sheets.get_material_groups),
    )
    history = []
    if user.get("is_admin"):
        history = await asyncio.to_thread(sheets.get_inventory_history, 30)

    low_stock = [m for m in materials if m.get("min_stock", 0) > 0 and m.get("stock", 0) <= m.get("min_stock", 0)]
    zero_stock = [m for m in materials if m.get("stock", 0) <= 0]

    return web.json_response({
        "success": True,
        "materials": materials,
        "groups": [{"name": g, "icon": _get_group_icon(g)} for g in (groups or [])],
        "low_stock": low_stock,
        "zero_stock": zero_stock,
        "history": history,
    })


async def handle_api_inventory_smart_parse(request: web.Request) -> web.Response:
    sheets = request.app[SHEETS_KEY]
    data = await request.json()
    text = str(data.get("text") or "").strip()
    if not text:
        return web.json_response({"success": False, "message": "Vui lòng nhập danh sách nguyên vật liệu."}, status=400)

    all_materials = await asyncio.to_thread(sheets.get_all_materials)
    if not all_materials:
        return web.json_response({"success": False, "message": "Kho hiện chưa có dữ liệu nguyên vật liệu."}, status=400)

    chunks = [c.strip() for c in re.split(r"[,;\n]+", text) if c.strip()]
    confirmed = []
    ambiguous = []
    not_found = []

    for chunk in chunks:
        qty, query = _parse_chunk_qty_and_query(chunk, all_materials)
        if qty <= 0:
            continue
        matches = _find_matching_materials(query, all_materials)
        if not matches:
            not_found.append(query)
        elif len(matches) == 1:
            m = matches[0]
            confirmed.append({
                "name": m["name"],
                "qty": qty,
                "stock": m["stock"],
                "unit": m.get("unit", ""),
            })
        else:
            ambiguous.append({
                "query": query,
                "qty": qty,
                "candidates": matches[:8],
            })

    return web.json_response({
        "success": True,
        "confirmed": confirmed,
        "ambiguous": ambiguous,
        "not_found": not_found,
    })


async def handle_api_inventory_export(request: web.Request) -> web.Response:
    sheets = request.app[SHEETS_KEY]
    bot = request.app.get(BOT_KEY)
    user = request[USER_KEY]
    data = await request.json()

    raw_items = data.get("items") or []
    note = str(data.get("note") or "").strip()
    actor = str(data.get("actor_name") or user.get("first_name") or "Nhân viên").strip()

    cleaned_items = []
    for item in raw_items:
        name = str(item.get("name") or "").strip()
        try:
            qty = float(str(item.get("qty", 0)).replace(",", "."))
        except (TypeError, ValueError):
            qty = 0
        if name and qty > 0:
            cleaned_items.append({"name": name, "qty": qty})

    if not cleaned_items:
        return web.json_response({"success": False, "message": "Danh sách xuất kho trống hoặc số lượng không hợp lệ."}, status=400)

    result = await asyncio.to_thread(sheets.batch_export_stock, cleaned_items, actor, note)
    if not result.get("success"):
        err_msg = "; ".join(result.get("errors") or []) or result.get("error") or "Không thể xuất kho."
        return web.json_response({"success": False, "message": f"❌ {err_msg}", "result": result}, status=400)

    lines = [f"📦 *XUẤT KHO NVL ({actor}):*"]
    for exp in result.get("exported", []):
        unit_s = f" {exp['unit']}" if exp.get("unit") else ""
        lines.append(f"• *{exp['name']}*: `-{exp['qty']:g}`{unit_s} (Còn: *{exp['new_stock']:g}*{unit_s})")
    await _safe_send_group(bot, "\n".join(lines))

    alerts = result.get("low_stock_alerts") or []
    if alerts and bot:
        alert_lines = [
            "⚠️ *CẢNH BÁO TỒN KHO THẤP*",
            f"👤 Người vừa lấy: {actor}",
            "─" * 24,
        ]
        for a in alerts:
            unit_s = f" {a['unit']}" if a.get("unit") else ""
            min_s = f" (Min: {a['min_stock']:g})" if a.get("min_stock", 0) > 0 else ""
            alert_lines.append(f"🔴 *{a['name']}*: còn *{a['new_stock']:g}*{unit_s}{min_s}")
        await _safe_send_admin(bot, "\n".join(alert_lines))

    materials = await asyncio.to_thread(sheets.get_all_materials)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã xuất kho {len(result.get('exported', []))} mặt hàng!",
        "result": result,
        "materials": materials,
    })


async def handle_api_inventory_import(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    user = request[USER_KEY]
    data = await request.json()

    name = str(data.get("name") or "").strip()
    note = str(data.get("note") or "").strip()
    try:
        qty = float(str(data.get("qty", 0)).replace(",", "."))
    except (TypeError, ValueError):
        qty = 0

    if not name or qty <= 0:
        return web.json_response({"success": False, "message": "Vui lòng chọn NVL và nhập số lượng > 0."}, status=400)

    actor = user.get("first_name") or "Quản lý"
    ok = await asyncio.to_thread(sheets.import_stock, name, qty, actor, note)
    if not ok:
        return web.json_response({"success": False, "message": f"❌ Không thể nhập kho cho {name}."}, status=400)

    materials = await asyncio.to_thread(sheets.get_all_materials)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã nhập thêm {qty:g} {name} vào kho!",
        "materials": materials,
    })


async def handle_api_material_add(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    data = await request.json()

    name = str(data.get("name") or "").strip()
    unit = str(data.get("unit") or "").strip()
    group = str(data.get("group") or "Khác").strip() or "Khác"
    try:
        min_stock = float(str(data.get("min_stock", 0) or 0).replace(",", "."))
    except (TypeError, ValueError):
        min_stock = 0.0
    try:
        price = float(str(data.get("price", 0) or 0).replace(",", "."))
    except (TypeError, ValueError):
        price = 0.0

    if not name or not unit:
        return web.json_response({"success": False, "message": "Vui lòng nhập Tên NVL và Đơn vị."}, status=400)

    res = await asyncio.to_thread(sheets.add_material, name, unit, min_stock, price, group)
    if not res.get("success"):
        err = res.get("error", "")
        msg = f"⚠️ {name} đã tồn tại trong danh mục!" if err == "already_exists" else f"❌ Lỗi: {err}"
        return web.json_response({"success": False, "message": msg}, status=400)

    materials = await asyncio.to_thread(sheets.get_all_materials)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã thêm {name} ({unit}) vào nhóm {group}!",
        "materials": materials,
    })


async def handle_api_material_update(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    data = await request.json()

    name = str(data.get("name") or "").strip()
    if not name:
        return web.json_response({"success": False, "message": "Thiếu tên NVL cần sửa."}, status=400)

    fields = {}
    if "unit" in data and str(data["unit"]).strip():
        fields["unit"] = str(data["unit"]).strip()
    if "group" in data and str(data["group"]).strip():
        fields["group"] = str(data["group"]).strip()
    if "min_stock" in data:
        try:
            fields["min_stock"] = float(str(data["min_stock"]).replace(",", "."))
        except (TypeError, ValueError):
            pass
    if "price" in data:
        try:
            fields["price"] = float(str(data["price"]).replace(",", "."))
        except (TypeError, ValueError):
            pass

    ok = await asyncio.to_thread(sheets.update_material, name, **fields)
    if not ok:
        return web.json_response({"success": False, "message": f"❌ Không thể cập nhật {name}."}, status=400)

    materials = await asyncio.to_thread(sheets.get_all_materials)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã cập nhật NVL {name}!",
        "materials": materials,
    })


async def handle_api_material_delete(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    data = await request.json()
    name = str(data.get("name") or "").strip()
    if not name:
        return web.json_response({"success": False, "message": "Thiếu tên NVL cần xóa."}, status=400)

    ok = await asyncio.to_thread(sheets.remove_material, name)
    if not ok:
        return web.json_response({"success": False, "message": f"❌ Không tìm thấy hoặc không thể xóa {name}."}, status=400)

    materials = await asyncio.to_thread(sheets.get_all_materials)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã xóa {name} khỏi danh mục kho!",
        "materials": materials,
    })


# ── 3. Thưởng, Báo Cáo Doanh Thu & Kết Ca ────────────────────────────────────

async def handle_api_reward_use(request: web.Request) -> web.Response:
    sheets = request.app[SHEETS_KEY]
    bot = request.app.get(BOT_KEY)
    user = request[USER_KEY]
    data = await request.json()
    nickname = str(data.get("nickname") or "").strip()
    if not nickname:
        return web.json_response({"success": False, "message": "Vui lòng chọn nhân viên."}, status=400)

    # Ràng buộc: Của ai người đó dùng!
    if not user.get("is_admin"):
        user_norm = normalize_name(user.get("nickname") or user.get("username") or user.get("first_name") or "")
        target_norm = normalize_name(nickname)
        if not user_norm or user_norm != target_norm:
            return web.json_response({
                "success": False,
                "message": "⛔ Bạn chỉ có thể sử dụng ly thưởng của chính mình."
            }, status=403)

    result = await asyncio.to_thread(sheets.consume_reward, nickname)
    if not result.get("success"):
        if result.get("error") == "insufficient_balance":
            return web.json_response({"success": False, "message": f"❌ {nickname} không còn ly thưởng nào!"}, status=400)
        return web.json_response({"success": False, "message": "❌ Lỗi khi trừ ly thưởng. Vui lòng thử lại."}, status=400)

    new_bal = result["balance"]
    await _safe_send_group(
        bot,
        f"🥤 {nickname} đã dùng 1 ly thưởng. Còn lại: {new_bal} ly.",
        parse_mode=None,
    )
    raw_employees = await asyncio.to_thread(_get_employees_list, sheets)
    user_norm = normalize_name(user.get("nickname") or user.get("username") or user.get("first_name") or "")
    is_user_admin = bool(user.get("is_admin"))
    employees = []
    for emp in (raw_employees or []):
        emp_dict = dict(emp)
        if not is_user_admin and normalize_name(emp_dict.get("nickname") or emp_dict.get("full_name") or "") != user_norm:
            emp_dict["balance"] = None
        employees.append(emp_dict)

    return web.json_response({
        "success": True,
        "message": f"✅ Đã trừ 1 ly thưởng của {nickname}. Còn lại: {new_bal} ly.",
        "balance": new_bal,
        "employees": employees,
    })


async def handle_api_reward_request(request: web.Request) -> web.Response:
    sheets = request.app[SHEETS_KEY]
    bot = request.app.get(BOT_KEY)
    bot_data = request.app[BOT_DATA_KEY]
    user = request[USER_KEY]
    data = await request.json()

    selected = deduplicate_employees([str(x).strip() for x in (data.get("employees") or []) if str(x).strip()])
    if not selected:
        return web.json_response({"success": False, "message": "⚠️ Bạn chưa chọn nhân viên nào!"}, status=400)

    now = local_now()
    ca = str(data.get("ca") or "").strip() or _infer_ca(now)

    if user.get("is_admin"):
        ok = await asyncio.to_thread(sheets.batch_update_balances, selected, 1)
        if not ok:
            return web.json_response({"success": False, "message": "❌ Không thể cộng thưởng vào Google Sheets."}, status=500)
        await _safe_send_group(bot, f"✅ +1 ly → {', '.join(selected)} (Ca {ca})", parse_mode=None)
        employees = await asyncio.to_thread(_get_employees_list, sheets)
        return web.json_response({
            "success": True,
            "approved": True,
            "message": f"✅ Đã cộng +1 ly thưởng cho: {', '.join(selected)} (Ca {ca})!",
            "employees": employees,
        })

    request_id = f"webapp_{user['id']}_{int(now.timestamp())}"
    temp_requests = bot_data.setdefault("reward_requests", {})
    temp_requests[request_id] = {
        "request_id": request_id,
        "group_chat_id": Config.GROUP_CHAT_ID,
        "employees": selected,
        "ca": ca,
        "sender": user.get("full_name") or "Nhân viên",
        "created_at": now.strftime("%H:%M %d/%m/%Y"),
    }

    if bot:
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Duyệt", callback_data=f"appr_rew_{request_id}"),
                InlineKeyboardButton("❌ Từ chối", callback_data=f"rej_rew_{request_id}"),
            ]
        ])
        await _safe_send_admin(
            bot,
            (
                f"🎁 **YÊU CẦU CỘNG THƯỞNG**\n\n"
                f"👤 Người gửi: {user.get('full_name')}\n"
                f"⏰ Ca: {ca}\n"
                f"👥 Nhân viên: {', '.join(selected)}\n\n"
                f"Bạn có đồng ý cộng 1 ly thưởng cho các nhân viên này không?"
            ),
            reply_markup=kb,
        )
        await _safe_send_group(
            bot,
            f"✅ Đã gửi yêu cầu cộng 1 ly thưởng cho: {', '.join(selected)} (Ca {ca}). Đang chờ Quản lý duyệt!",
            parse_mode=None,
        )

    return web.json_response({
        "success": True,
        "approved": False,
        "request_id": request_id,
        "message": f"✅ Đã gửi yêu cầu cộng 1 ly thưởng cho {', '.join(selected)} tới Quản lý!",
    })


async def handle_api_revenue_report(request: web.Request) -> web.Response:
    sheets = request.app[SHEETS_KEY]
    bot = request.app.get(BOT_KEY)
    bot_data = request.app[BOT_DATA_KEY]
    user = request[USER_KEY]

    photo_bytes = None
    employees_raw = []
    revenue_raw = ""
    ca = ""

    if request.content_type.startswith("multipart/"):
        reader = await request.multipart()
        async for part in reader:
            if part.name == "employees":
                val = (await part.read(decode=True)).decode("utf-8", errors="ignore")
                try:
                    employees_raw = json.loads(val)
                except Exception:
                    employees_raw = [x.strip() for x in val.split(",") if x.strip()]
            elif part.name == "revenue":
                revenue_raw = (await part.read(decode=True)).decode("utf-8", errors="ignore").strip()
            elif part.name == "ca":
                ca = (await part.read(decode=True)).decode("utf-8", errors="ignore").strip()
            elif part.name == "photo":
                data_bytes = await part.read(decode=False)
                if data_bytes:
                    photo_bytes = data_bytes
    else:
        data = await request.json()
        employees_raw = data.get("employees") or []
        if isinstance(employees_raw, str):
            employees_raw = [x.strip() for x in employees_raw.split(",") if x.strip()]
        revenue_raw = str(data.get("revenue") or "").strip()
        ca = str(data.get("ca") or "").strip()

    employees = deduplicate_employees([str(e).strip() for e in employees_raw if str(e).strip()])
    if not employees:
        return web.json_response({"success": False, "message": "Vui lòng chọn ít nhất 1 nhân viên trong ca."}, status=400)

    revenue = _parse_amount_str(revenue_raw)
    if revenue is None or revenue <= 0 or revenue > 100_000_000:
        return web.json_response(
            {"success": False, "message": "Doanh thu không hợp lệ (VD: 1500k, 1.5M, 1500000; tối đa 100M)."},
            status=400,
        )

    valid_nicknames = await asyncio.to_thread(sheets.get_all_nicknames)
    if valid_nicknames:
        invalid = [emp for emp in employees if normalize_name(emp) not in valid_nicknames]
        if invalid:
            return web.json_response(
                {"success": False, "message": f"❌ Sai tên nhân viên: {', '.join(invalid)}."},
                status=400,
            )

    now = local_now()
    resolved_ca = ca if ca in {"Sáng", "Chiều", "Tối"} else _infer_ca(now)
    date_str = now.strftime("%d/%m/%Y")
    report_key = f"webapp:{user['id']}:{date_str}:{resolved_ca}:{revenue}:{','.join(sorted(normalize_name(e) for e in employees))}"

    processed = bot_data.setdefault("processed_reports", set())
    if report_key in processed:
        return web.json_response({"success": False, "message": "ℹ️ Báo cáo này đã được ghi nhận trước đó."}, status=400)
    processed.add(report_key)

    save_res = await asyncio.to_thread(
        sheets.save_report,
        date=date_str,
        employees=employees,
        revenue=revenue,
        ca=resolved_ca,
        report_key=report_key,
    )
    if not save_res:
        processed.discard(report_key)
        return web.json_response({"success": False, "message": "❌ Không thể lưu báo cáo vào Google Sheets."}, status=500)
    if save_res == "duplicate":
        return web.json_response({"success": False, "message": "ℹ️ Báo cáo này đã được xử lý trước đó."}, status=400)

    reward_count = check_reward_eligibility(len(employees), revenue)
    reward_warning = ""
    if reward_count > 0:
        reward_ok = await asyncio.to_thread(sheets.batch_update_balances, employees, reward_count)
        if not reward_ok:
            reward_warning = " (⚠️ Chưa cộng được ly thưởng tự động, Quản lý cần kiểm tra lại)"

    confirm_msg = (
        f"✅ **ĐÃ GHI NHẬN BÁO CÁO**\n"
        f"👥 Nhân viên: {', '.join(employees)}\n"
        f"💰 Doanh thu: {revenue:,} VNĐ\n"
    )
    if reward_count > 0:
        confirm_msg += f"🎁 Cộng {reward_count} ly thưởng cho mỗi bạn\n"
    confirm_msg += f"⏰ Ca: {resolved_ca}"

    if bot:
        if photo_bytes:
            try:
                await bot.send_photo(
                    chat_id=Config.GROUP_CHAT_ID,
                    photo=photo_bytes,
                    caption=confirm_msg,
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.warning("Lỗi gửi ảnh báo cáo doanh thu vào group: %s", e)
                await _safe_send_group(bot, confirm_msg)
        else:
            await _safe_send_group(bot, confirm_msg)

    employees_list = await asyncio.to_thread(_get_employees_list, sheets)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã lưu báo cáo Ca {resolved_ca} ({revenue:,}đ){reward_warning}!",
        "reward_count": reward_count,
        "employees": employees_list,
    })


async def handle_api_endshift_upload(request: web.Request) -> web.Response:
    bot = request.app.get(BOT_KEY)
    user = request[USER_KEY]

    if not request.content_type.startswith("multipart/"):
        return web.json_response({"success": False, "message": "Yêu cầu multipart/form-data chứa ảnh."}, status=400)

    reader = await request.multipart()
    ca = ""
    role = ""
    actor_name = ""
    checklist_summary = ""
    photos = []

    async for part in reader:
        if part.name == "ca":
            ca = (await part.read(decode=True)).decode("utf-8", errors="ignore").strip()
        elif part.name == "role":
            role = (await part.read(decode=True)).decode("utf-8", errors="ignore").strip()
        elif part.name == "actor_name":
            actor_name = (await part.read(decode=True)).decode("utf-8", errors="ignore").strip()
        elif part.name == "checklist_summary":
            checklist_summary = (await part.read(decode=True)).decode("utf-8", errors="ignore").strip()
        elif part.name in ("photos", "photo"):
            content = await part.read(decode=False)
            if content:
                photos.append(content)

    if ca not in {"Sáng", "Chiều", "Tối"}:
        ca = _infer_ca(local_now())
    if role not in {"Phục Vụ", "Pha Chế"}:
        role = "Pha Chế"

    if not photos:
        return web.json_response({"success": False, "message": "⚠️ Vui lòng chọn ít nhất 1 ảnh kết ca."}, status=400)

    total = len(photos)
    now_str = local_now().strftime("%d/%m/%Y %H:%M")
    sender_label = actor_name or user.get("full_name") or "Nhân viên"
    checklist_line = f"\n📋 Checklist: {checklist_summary}" if checklist_summary else ""
    header = (
        f"🔚 **KẾT CA {ca.upper()} — {role}**\n"
        f"👤 {sender_label}  |  🕐 {now_str}  |  📷 {total} ảnh{checklist_line}"
    )

    if bot:
        try:
            chunks = [photos[i:i + 10] for i in range(0, total, 10)]
            for idx, chunk in enumerate(chunks):
                is_last = idx == len(chunks) - 1
                if len(chunk) == 1:
                    await bot.send_photo(
                        chat_id=Config.ADMIN_CHAT_ID,
                        photo=chunk[0],
                        caption=header if is_last else None,
                        parse_mode="Markdown" if is_last else None,
                    )
                else:
                    media = [
                        InputMediaPhoto(
                            media=img_bytes,
                            caption=header if (is_last and j == len(chunk) - 1) else None,
                            parse_mode="Markdown" if (is_last and j == len(chunk) - 1) else None,
                        )
                        for j, img_bytes in enumerate(chunk)
                    ]
                    await bot.send_media_group(chat_id=Config.ADMIN_CHAT_ID, media=media)
        except Exception as e:
            logger.exception("Không thể gửi ảnh kết ca từ Mini App: %s", e)
            return web.json_response(
                {"success": False, "message": "❌ Không thể gửi ảnh tới Quản lý. Vui lòng thử lại."},
                status=500,
            )

        await _safe_send_group(
            bot,
            f"✅ **{sender_label} đã gửi {total} ảnh kết ca {ca} — {role}** cho quản lý!{checklist_line}",
        )

    return web.json_response({
        "success": True,
        "total": total,
        "message": f"✅ Đã gửi {total} ảnh kết ca {ca} ({role}) cho Quản lý!",
    })


async def handle_api_feedback(request: web.Request) -> web.Response:
    bot = request.app.get(BOT_KEY)
    data = await request.json()
    message = str(data.get("message") or "").strip()
    if not message:
        return web.json_response({"success": False, "message": "Vui lòng nhập nội dung góp ý."}, status=400)

    await _safe_send_admin(
        bot,
        f"💡 GÓP Ý TỪ NHÂN VIÊN:\n\n{message}",
        parse_mode=None,
    )
    return web.json_response({
        "success": True,
        "message": "✅ Cảm ơn bạn! Đóng góp ẩn danh đã được gửi trực tiếp cho Quản lý.",
    })


# ── 4. Admin Endpoints ───────────────────────────────────────────────────────

async def handle_api_admin_overview(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    bot_data = request.app[BOT_DATA_KEY]
    store: WebAppStore = request.app[STORE_KEY]
    user = request[USER_KEY]

    now = local_now()
    month_year = now.strftime("%m/%Y")
    ot_start, ot_end = _salary_window(now)

    checkin_today, late_stats, recent_reports, ot_summary = await asyncio.gather(
        asyncio.to_thread(sheets.get_checkin_history_today),
        asyncio.to_thread(sheets.get_late_statistics, month_year),
        asyncio.to_thread(sheets.get_recent_revenue_reports, 12),
        asyncio.to_thread(sheets.get_overtime_summary, ot_start, ot_end),
    )

    pending_rewards = [
        {"id": req_id, **info}
        for req_id, info in (bot_data.get("reward_requests") or {}).items()
    ]

    admin_ids = []
    if user.get("is_super_admin"):
        admin_ids = sorted(list(bot_data.get("admin_ids") or set()))

    # Tính toán thống kê doanh thu & chi phí cho Dashboard
    by_ca = {"Sáng": 0, "Chiều": 0, "Tối": 0}
    total_recent_rev = 0
    for rep in (recent_reports or []):
        if not isinstance(rep, dict):
            continue
        amt = _parse_amount_str(str(rep.get("revenue") or "")) or 0
        total_recent_rev += amt
        ca_key = str(rep.get("ca") or "").strip()
        if ca_key in by_ca:
            by_ca[ca_key] += amt

    petty_expenses = store.get_petty_expenses(25)
    total_petty = sum(int(x.get("amount") or 0) for x in petty_expenses)

    return web.json_response({
        "success": True,
        "today": now.strftime("%d/%m/%Y"),
        "month_year": month_year,
        "checkin_today": checkin_today,
        "late_stats": late_stats,
        "recent_reports": recent_reports,
        "pending_rewards": pending_rewards,
        "leave_requests": store.get_leave_requests(limit=30),
        "shift_schedules": store.get_shift_schedules(),
        "petty_expenses": petty_expenses,
        "analytics": {
            "total_recent_revenue": total_recent_rev,
            "revenue_by_ca": by_ca,
            "total_petty_expenses": total_petty,
        },
        "overtime": {
            "period": f"{ot_start.strftime('%d/%m/%Y')} → {ot_end.strftime('%d/%m/%Y')}",
            "summary": ot_summary,
            "total_hours": round(sum(ot_summary.values()), 2) if ot_summary else 0.0,
        },
        "admin_ids": admin_ids,
    })


async def handle_api_admin_mark_late(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    data = await request.json()

    nickname = str(data.get("nickname") or "").strip()
    date_str = str(data.get("date") or "").strip()
    reported = bool(data.get("reported"))

    if not nickname or not date_str:
        return web.json_response({"success": False, "message": "Thiếu thông tin nhân viên hoặc ngày."}, status=400)

    fn = sheets.mark_reported_late if reported else sheets.mark_unreported_late
    ok = await asyncio.to_thread(fn, nickname, date_str)
    if not ok:
        return web.json_response(
            {"success": False, "message": "⚠️ Không tìm thấy bản ghi đi muộn hoặc đã được đánh dấu trước đó."},
            status=400,
        )

    label = "ĐÃ báo trước" if reported else "KHÔNG báo trước"
    return web.json_response({
        "success": True,
        "message": f"✅ Đã đánh dấu {nickname} ({date_str}): {label}.",
    })


async def handle_api_admin_reward_decide(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    bot = request.app.get(BOT_KEY)
    bot_data = request.app[BOT_DATA_KEY]
    data = await request.json()

    request_id = str(data.get("request_id") or "").strip()
    approve = bool(data.get("approve"))

    temp_requests = bot_data.get("reward_requests") or {}
    req_data = temp_requests.get(request_id)
    if not req_data:
        return web.json_response({"success": False, "message": "Yêu cầu này đã được xử lý hoặc không tồn tại."}, status=404)

    selected = req_data["employees"]
    ca = req_data["ca"]

    if approve:
        ok = await asyncio.to_thread(sheets.batch_update_balances, selected, 1)
        if not ok:
            return web.json_response({"success": False, "message": "❌ Lỗi khi cộng thưởng vào Google Sheets."}, status=500)
        await _safe_send_group(
            bot,
            f"🎉 **Quản lý đã DUYỆT cộng thưởng!**\n🎁 +1 ly → {', '.join(selected)} (Ca {ca})",
        )
        msg = f"✅ Đã duyệt cộng +1 ly cho {', '.join(selected)} (Ca {ca})."
    else:
        await _safe_send_group(
            bot,
            f"❌ **Quản lý đã TỪ CHỐI cộng thưởng!**\nNhân viên: {', '.join(selected)} (Ca {ca})",
        )
        msg = f"❌ Đã từ chối yêu cầu thưởng của {', '.join(selected)}."

    temp_requests.pop(request_id, None)
    return web.json_response({"success": True, "message": msg})


async def handle_api_admin_salary(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]

    options = await asyncio.to_thread(sheets.get_salary_month_options)
    cur_m, cur_y = sheets._current_salary_month()
    try:
        month = int(request.query.get("month") or cur_m)
        year = int(request.query.get("year") or cur_y)
    except (TypeError, ValueError):
        month, year = cur_m, cur_y

    salary_data = await asyncio.to_thread(sheets.get_salary_data, month, year)
    return web.json_response({
        "success": salary_data.get("success", False),
        "options": options,
        "salary": salary_data,
    })


async def handle_api_admin_salary_modifier(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    data = await request.json()

    nickname = str(data.get("nickname") or "").strip()
    mod_type = str(data.get("type") or "advance").strip()
    is_bonus = mod_type == "bonus"
    cur_m, cur_y = sheets._current_salary_month()
    try:
        month = int(data.get("month") or cur_m)
        year = int(data.get("year") or cur_y)
    except (TypeError, ValueError):
        month, year = cur_m, cur_y

    raw_amount = str(data.get("amount") or "").strip()
    if raw_amount.lower().endswith("k"):
        raw_amount = raw_amount[:-1]
    try:
        amount = int(float(raw_amount.replace(",", "").replace(".", "")))
        if amount <= 0 or amount > 1_000_000:
            raise ValueError
    except ValueError:
        return web.json_response({"success": False, "message": "Số tiền (đơn vị nghìn đồng) phải > 0 (VD: 50 = 50k)."}, status=400)

    if not nickname:
        return web.json_response({"success": False, "message": "Vui lòng chọn nhân viên."}, status=400)

    ok = await asyncio.to_thread(sheets.update_salary_modifier, nickname, is_bonus, amount, month, year)
    if not ok:
        return web.json_response({"success": False, "message": "❌ Không tìm thấy nhân viên trong bảng lương hoặc lỗi cập nhật."}, status=400)

    salary_data = await asyncio.to_thread(sheets.get_salary_data, month, year)
    action_label = "Thưởng tiền" if is_bonus else "Ứng lương"
    return web.json_response({
        "success": True,
        "message": f"✅ Đã thêm {action_label} {amount}k cho {nickname} (T{month}/{year})!",
        "salary": salary_data,
    })


async def handle_api_admin_overtime_add(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    data = await request.json()

    nickname = str(data.get("nickname") or "").strip()
    try:
        hours = float(str(data.get("hours") or "0").replace(",", "."))
        if hours <= 0 or hours > 24:
            raise ValueError
    except ValueError:
        return web.json_response({"success": False, "message": "Số giờ làm thêm phải > 0 và ≤ 24."}, status=400)

    if not nickname:
        return web.json_response({"success": False, "message": "Vui lòng chọn nhân viên."}, status=400)

    ok = await asyncio.to_thread(sheets.add_overtime, nickname, hours)
    if not ok:
        return web.json_response({"success": False, "message": "❌ Không thể lưu giờ làm thêm."}, status=500)

    now = local_now()
    ot_start, ot_end = _salary_window(now)
    ot_summary = await asyncio.to_thread(sheets.get_overtime_summary, ot_start, ot_end)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã thêm {hours:g}h làm thêm cho {nickname}!",
        "overtime": {
            "period": f"{ot_start.strftime('%d/%m/%Y')} → {ot_end.strftime('%d/%m/%Y')}",
            "summary": ot_summary,
            "total_hours": round(sum(ot_summary.values()), 2) if ot_summary else 0.0,
        },
    })


async def handle_api_admin_employee_add(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()
    nickname = str(data.get("nickname") or "").strip()
    role = str(data.get("role") or "").strip()

    valid, err_msg = validate_nickname(nickname)
    if not valid:
        return web.json_response({"success": False, "message": f"❌ {err_msg}"}, status=400)

    res = await asyncio.to_thread(sheets.add_employee, nickname)
    if not res.get("success"):
        err = res.get("error", "")
        msg = f"⚠️ {nickname} đã tồn tại trong hệ thống!" if err == "already_exists" else f"❌ Lỗi: {err}"
        return web.json_response({"success": False, "message": msg}, status=400)

    if role:
        store.set_employee_role(nickname, role)

    employees = await asyncio.to_thread(_get_employees_list, sheets, store)
    msg = f"✅ Đã thêm nhân viên {nickname} ({role})!" if role else f"✅ Đã thêm nhân viên {nickname}!"
    return web.json_response({
        "success": True,
        "message": msg,
        "employees": employees,
    })


async def handle_api_admin_employee_rename(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    data = await request.json()
    old_nickname = str(data.get("old_nickname") or "").strip()
    new_nickname = str(data.get("new_nickname") or "").strip()

    valid, err_msg = validate_nickname(new_nickname)
    if not valid:
        return web.json_response({"success": False, "message": f"❌ {err_msg}"}, status=400)

    res = await asyncio.to_thread(sheets.rename_employee, old_nickname, new_nickname)
    if not res.get("success"):
        err = res.get("error", "")
        if err == "already_exists":
            msg = "Tên mới đã tồn tại trong hệ thống."
        elif err == "not_found":
            msg = "Không tìm thấy nhân viên cần đổi tên."
        else:
            msg = err or "Không thể đổi tên."
        return web.json_response({"success": False, "message": f"❌ {msg}"}, status=400)

    employees = await asyncio.to_thread(_get_employees_list, sheets)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã đổi tên {old_nickname} → {new_nickname}!",
        "employees": employees,
    })


async def handle_api_admin_employee_remove(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    data = await request.json()
    nickname = str(data.get("nickname") or "").strip()
    if not nickname:
        return web.json_response({"success": False, "message": "Thiếu tên nhân viên."}, status=400)

    ok = await asyncio.to_thread(sheets.remove_employee, nickname)
    if not ok:
        return web.json_response({"success": False, "message": f"❌ Không tìm thấy {nickname} hoặc lỗi khi xóa."}, status=400)

    employees = await asyncio.to_thread(_get_employees_list, sheets)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã xóa nhân viên {nickname} khỏi hệ thống.",
        "employees": employees,
    })


async def handle_api_admin_salary_rate(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    data = await request.json()
    nickname = str(data.get("nickname") or "").strip()
    try:
        rate = float(str(data.get("rate") or "0").replace(",", "."))
        if rate <= 0 or rate > 1000:
            raise ValueError
    except ValueError:
        return web.json_response({"success": False, "message": "Mức lương/giờ không hợp lệ (VD: 16, 18.5)."}, status=400)

    ok = await asyncio.to_thread(sheets.update_salary_rate, nickname, str(rate))
    if not ok:
        return web.json_response({"success": False, "message": "❌ Không thể cập nhật mức lương/giờ."}, status=400)

    store: WebAppStore = request.app[STORE_KEY]
    employees = await asyncio.to_thread(_get_employees_list, sheets, store)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã cập nhật mức lương của {nickname} thành {rate:g}k/h!",
        "employees": employees,
    })


async def handle_api_admin_employee_role(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()
    nickname = str(data.get("nickname") or "").strip()
    role = str(data.get("role") or "Pha Chế").strip()
    if not nickname:
        return web.json_response({"success": False, "message": "Thiếu tên nhân viên."}, status=400)

    store.set_employee_role(nickname, role)
    employees = await asyncio.to_thread(_get_employees_list, sheets, store)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã xếp vị trí của {nickname} thành {role}!",
        "employees": employees,
    })


async def handle_api_admin_reward_history(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    nickname = str(request.query.get("nickname") or "").strip() or None
    records = await asyncio.to_thread(sheets.get_reward_history, nickname, 25)
    return web.json_response({
        "success": True,
        "nickname": nickname,
        "records": records,
    })


async def handle_api_admin_update_revenue(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    data = await request.json()
    session = data.get("session")
    raw_rev = str(data.get("new_revenue") or "").strip()

    new_revenue = _parse_amount_str(raw_rev)
    if new_revenue is None or new_revenue <= 0 or new_revenue > 100_000_000:
        return web.json_response(
            {"success": False, "message": "❌ Số tiền không hợp lệ (VD: 1500k, 2M, 1500000)."},
            status=400,
        )
    if not isinstance(session, dict):
        return web.json_response({"success": False, "message": "Thiếu thông tin ca báo cáo."}, status=400)

    ok = await asyncio.to_thread(sheets.update_report_revenue, session, new_revenue)
    if not ok:
        return web.json_response({"success": False, "message": "❌ Không tìm thấy dòng báo cáo để cập nhật."}, status=400)

    recent_reports = await asyncio.to_thread(sheets.get_recent_revenue_reports, 8)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã cập nhật doanh thu {session.get('date')} Ca {session.get('ca')} → {new_revenue:,}đ!",
        "recent_reports": recent_reports,
    })


async def handle_api_admin_announce(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    bot = request.app.get(BOT_KEY)
    data = await request.json()
    message = str(data.get("message") or "").strip()
    if not message:
        return web.json_response({"success": False, "message": "Vui lòng nhập nội dung thông báo."}, status=400)

    await _safe_send_group(bot, f"🚀 THÔNG BÁO CẬP NHẬT:\n\n{message}", parse_mode=None)
    return web.json_response({
        "success": True,
        "message": "✅ Đã gửi thông báo vào nhóm chung!",
    })


async def handle_api_admin_grant(request: web.Request) -> web.Response:
    if resp := _require_super_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    bot_data = request.app[BOT_DATA_KEY]
    user = request[USER_KEY]
    data = await request.json()

    try:
        telegram_id = int(str(data.get("telegram_id") or "").strip())
        if telegram_id <= 0:
            raise ValueError
    except ValueError:
        return web.json_response({"success": False, "message": "⚠️ Telegram ID phải là số nguyên dương."}, status=400)

    if telegram_id == Config.ADMIN_CHAT_ID:
        return web.json_response({"success": False, "message": "⚠️ ID này đã là Admin gốc."}, status=400)

    ok = await asyncio.to_thread(sheets.add_admin, telegram_id, str(user["id"]))
    if not ok:
        return web.json_response({"success": False, "message": "❌ Không thể cấp quyền quản lý."}, status=500)

    bot_data.setdefault("admin_ids", set()).add(telegram_id)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã cấp quyền Quản lý cho ID {telegram_id}!",
        "admin_ids": sorted(list(bot_data.get("admin_ids") or set())),
    })


# ── 5. Tính năng Mở rộng: Hồ sơ Cá nhân, Đơn từ, Lịch ca, Chi vặt, Công thức ─

async def handle_api_personal_summary(request: web.Request) -> web.Response:
    sheets = request.app[SHEETS_KEY]
    store: WebAppStore = request.app[STORE_KEY]
    nickname = str(request.query.get("nickname") or "").strip()
    if not nickname:
        return web.json_response({"success": False, "message": "Vui lòng chọn tên nhân viên."}, status=400)

    summary = await asyncio.to_thread(sheets.get_employee_personal_summary, nickname)
    if not summary.get("success"):
        return web.json_response(
            {"success": False, "message": summary.get("error") or "Không thể tải hồ sơ cá nhân."},
            status=400,
        )

    my_requests = store.get_leave_requests(nickname=nickname, limit=15)
    my_schedule = store.get_shift_schedules().get(nickname.strip()) or {}

    return web.json_response({
        "success": True,
        "summary": summary,
        "leave_requests": my_requests,
        "shift_schedule": my_schedule,
    })


async def handle_api_leave_request(request: web.Request) -> web.Response:
    bot = request.app.get(BOT_KEY)
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()

    nickname = str(data.get("nickname") or "").strip()
    role = str(data.get("role") or "Nhân viên").strip()
    req_type = str(data.get("type") or "late").strip()
    date_str = str(data.get("date") or local_now().strftime("%d/%m/%Y")).strip()
    ca = str(data.get("ca") or "Sáng").strip()
    reason = str(data.get("reason") or "").strip()
    extra = str(data.get("extra") or "").strip()

    if not nickname or not reason:
        return web.json_response(
            {"success": False, "message": "Vui lòng chọn tên nhân viên và nhập lý do."},
            status=400,
        )

    type_labels = {
        "late": "⏰ Xin đi muộn",
        "leave": "🏖 Xin nghỉ phép",
        "swap": "🔄 Xin đổi ca",
    }
    type_label = type_labels.get(req_type, "📝 Đơn xin phép")
    item = store.add_leave_request(nickname, role, req_type, date_str, ca, reason, extra)

    extra_line = f"\n📌 Chi tiết: {extra}" if extra else ""
    leave_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Duyệt Đơn", callback_data=f"leave_appr_{item['id']}"),
            InlineKeyboardButton("❌ Từ Chối", callback_data=f"leave_rejc_{item['id']}"),
        ]
    ])
    await _safe_send_admin(
        bot,
        f"📩 *ĐƠN MỚI TỪ NHÂN VIÊN*\n"
        f"👤 *{nickname}* ({role})\n"
        f"🏷 Loại: *{type_label}*\n"
        f"📅 Ngày: {date_str} — Ca {ca}{extra_line}\n"
        f"💬 Lý do: {reason}",
        reply_markup=leave_kb,
    )

    return web.json_response({
        "success": True,
        "message": f"✅ Đã gửi {type_label} tới Quản lý!",
        "item": item,
        "leave_requests": store.get_leave_requests(limit=20),
    })


async def handle_api_admin_leave_decide(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    bot = request.app.get(BOT_KEY)
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()

    req_id = str(data.get("id") or "").strip()
    approve = bool(data.get("approve"))

    decided = store.decide_leave_request(req_id, approve)
    if not decided:
        return web.json_response({"success": False, "message": "Không tìm thấy đơn này."}, status=404)

    nickname = decided.get("nickname", "")
    date_str = decided.get("date", "")
    ca = decided.get("ca", "")
    req_type = decided.get("type", "late")
    type_labels = {"late": "Xin đi muộn", "leave": "Xin nghỉ phép", "swap": "Xin đổi ca"}
    t_label = type_labels.get(req_type, "Đơn xin phép")

    if approve and req_type == "late":
        try:
            await asyncio.to_thread(sheets.mark_reported_late, nickname, date_str)
        except Exception:
            pass

    status_icon = "✅ ĐÃ DUYỆT" if approve else "❌ TỪ CHỐI"
    await _safe_send_group(
        bot,
        f"{status_icon} **{t_label}** — **{nickname}** ({date_str} • Ca {ca})",
    )

    return web.json_response({
        "success": True,
        "message": f"{status_icon}: {t_label} của {nickname}!",
        "leave_requests": store.get_leave_requests(limit=30),
    })


async def handle_api_schedule_register(request: web.Request) -> web.Response:
    bot = request.app.get(BOT_KEY)
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()

    nickname = str(data.get("nickname") or "").strip()
    role = str(data.get("role") or "Nhân viên").strip()
    slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
    note = str(data.get("note") or "").strip()
    week_label = str(data.get("week_label") or "Tuần tới").strip()
    target_shifts = int(data.get("target_shifts") or 5)

    if not nickname:
        return web.json_response({"success": False, "message": "Vui lòng chọn tên nhân viên."}, status=400)

    entry = store.save_shift_schedule(nickname, role, slots, note, week_label, target_shifts)
    total_shifts = sum(len(v) for v in slots.values() if isinstance(v, list))

    await _safe_send_admin(
        bot,
        f"📅 **BÁO LỊCH RẢNH ({week_label})**\n"
        f"👤 **{nickname}** ({role}) — Báo rảnh **{total_shifts} ca** trong tuần."
        + (f"\n📝 Ghi chú: {note}" if note else ""),
    )

    return web.json_response({
        "success": True,
        "message": f"✅ Đã lưu lịch rảnh ({total_shifts} ca) cho {nickname}!",
        "entry": entry,
        "shift_schedules": store.get_shift_schedules(),
    })


# ── 6. Weekly Roster, Shift Swaps & Notifications ────────────────────────────

async def handle_api_sync(request: web.Request) -> web.Response:
    """Lightweight real-time sync endpoint (<5ms, zero Google Sheets calls)"""
    store: WebAppStore = request.app[STORE_KEY]
    bot_data = request.app[BOT_DATA_KEY]
    user = request.get(USER_KEY) or {}
    try:
        offset = int(request.query.get("offset") or 0)
    except (TypeError, ValueError):
        offset = 0

    w_info = get_week_info(offset_weeks=offset)
    target_key = w_info["week_key"]
    roster = store.get_roster(target_key)
    schedules = store.get_shift_schedules()
    user_nick = user.get("nickname") or user.get("username") or ""
    my_notifs = store.get_notifications(user_nick) if user_nick else []
    pending_swaps = len(store.get_swap_requests(status="pending")) if user.get("is_admin") else 0
    pending_rewards = len(bot_data.get("reward_requests") or {}) if user.get("is_admin") else 0

    return web.json_response({
        "success": True,
        "week_info": w_info,
        "roster": roster,
        "shift_schedules": schedules,
        "notifications": my_notifs,
        "pending_swaps_count": pending_swaps,
        "pending_rewards_count": pending_rewards,
        "server_time": local_now().strftime("%H:%M:%S"),
    })


async def handle_api_roster_get(request: web.Request) -> web.Response:
    store: WebAppStore = request.app[STORE_KEY]
    week_key = request.query.get("week") or None
    try:
        offset = int(request.query.get("offset") or 0)
    except (TypeError, ValueError):
        offset = 0
    w_info = get_week_info(offset_weeks=offset)
    target_key = week_key or w_info["week_key"]
    roster = store.get_roster(target_key)
    return web.json_response({
        "success": True,
        "week_info": w_info,
        "roster": roster,
        "shift_schedules": store.get_shift_schedules(),
    })


async def handle_api_admin_roster_save_draft(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()
    week_key = str(data.get("week_key") or "").strip()
    shifts = data.get("shifts") or {}
    targets = data.get("targets") or None
    week_label = str(data.get("week_label") or "").strip()

    if not week_key:
        return web.json_response({"success": False, "message": "Thiếu mã tuần (week_key)."}, status=400)

    updated = store.save_roster_draft(week_key, shifts, targets, week_label)
    return web.json_response({
        "success": True,
        "message": "✅ Đã lưu bản nháp xếp lịch tuần!",
        "roster": updated,
    })


async def handle_api_admin_roster_publish(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    bot = request.app.get(BOT_KEY)
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()
    week_key = str(data.get("week_key") or "").strip()
    if not week_key:
        return web.json_response({"success": False, "message": "Thiếu mã tuần (week_key)."}, status=400)

    published = store.publish_roster(week_key)
    week_lbl = published.get("week_label") or "tuần mới"

    await _safe_send_group(
        bot,
        f"📅 **THÔNG BÁO LỊCH TUẦN CHÍNH THỨC**\n\n"
        f"Quản lý đã chốt lịch làm việc **{week_lbl}**!\n"
        f"Toàn bộ nhân sự vui lòng vào Web App kiểm tra ca làm và đăng ký đổi ca (nếu có nhu cầu) sớm nhất.",
        parse_mode="Markdown",
    )

    return web.json_response({
        "success": True,
        "message": f"🎉 Đã chốt và phát hành chính thức lịch {week_lbl}!",
        "roster": published,
    })


async def handle_api_admin_roster_assign(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()
    week_key = str(data.get("week_key") or "").strip()
    day_ca = str(data.get("day_ca") or "").strip()
    nickname = str(data.get("nickname") or "").strip()

    if not week_key or not day_ca or not nickname:
        return web.json_response({"success": False, "message": "Thiếu thông tin tuần, ca hoặc nhân viên."}, status=400)

    updated = store.assign_shift(week_key, day_ca, nickname)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã xếp {nickname} vào ca {day_ca}!",
        "roster": updated,
    })


async def handle_api_admin_roster_unassign(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()
    week_key = str(data.get("week_key") or "").strip()
    day_ca = str(data.get("day_ca") or "").strip()
    nickname = str(data.get("nickname") or "").strip()

    if not week_key or not day_ca or not nickname:
        return web.json_response({"success": False, "message": "Thiếu thông tin tuần, ca hoặc nhân viên."}, status=400)

    updated = store.unassign_shift(week_key, day_ca, nickname)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã bỏ {nickname} khỏi ca {day_ca}!",
        "roster": updated,
    })


async def handle_api_admin_roster_suggest(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    sheets = request.app[SHEETS_KEY]
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()
    week_key = str(data.get("week_key") or "").strip()
    if not week_key:
        week_key = get_week_info(0)["week_key"]

    employees = await asyncio.to_thread(_get_employees_list, sheets)
    suggested = store.suggest_roster(week_key, employees)
    return web.json_response({
        "success": True,
        "message": "💡 Đã tạo bản nháp gợi ý phân bổ ca cân bằng!",
        "roster": suggested,
    })


async def handle_api_swaps_get(request: web.Request) -> web.Response:
    store: WebAppStore = request.app[STORE_KEY]
    user = request[USER_KEY]
    status_filter = request.query.get("status") or None
    user_filter = request.query.get("nickname") or None

    if not user.get("is_admin") and not user_filter:
        user_filter = user.get("nickname") or user.get("username") or ""

    swaps = store.get_swap_requests(nickname=user_filter, status=status_filter)
    return web.json_response({
        "success": True,
        "swaps": swaps,
    })


async def handle_api_swaps_create(request: web.Request) -> web.Response:
    bot = request.app.get(BOT_KEY)
    store: WebAppStore = request.app[STORE_KEY]
    user = request[USER_KEY]
    data = await request.json()

    week_key = str(data.get("week_key") or "").strip()
    requester = str(data.get("requester") or user.get("nickname") or user.get("username") or "").strip()
    requester_role = str(data.get("requester_role") or user.get("role") or "Pha Chế").strip()
    requester_shift = data.get("requester_shift") or {}
    target = str(data.get("target") or "").strip()
    target_role = str(data.get("target_role") or "Pha Chế").strip()
    target_shift = data.get("target_shift") or {}
    reason = str(data.get("reason") or "").strip()

    if not requester or not target:
        return web.json_response({"success": False, "message": "Vui lòng chọn đầy đủ người đổi và người nhận."}, status=400)
    if not requester_shift or not target_shift:
        return web.json_response({"success": False, "message": "Vui lòng chọn ca của bạn và ca muốn đổi."}, status=400)
    if normalize_name(requester) == normalize_name(target):
        return web.json_response({"success": False, "message": "Không thể tự đổi ca với chính mình."}, status=400)

    item = store.create_swap_request(
        week_key=week_key,
        requester=requester,
        requester_role=requester_role,
        requester_shift=requester_shift,
        target=target,
        target_role=target_role,
        target_shift=target_shift,
        reason=reason,
    )

    swap_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Duyệt Đổi Ca", callback_data=f"swap_appr_{item['id']}"),
            InlineKeyboardButton("❌ Từ Chối", callback_data=f"swap_rejc_{item['id']}"),
        ]
    ])
    await _safe_send_admin(
        bot,
        f"🔄 *YÊU CẦU ĐỔI CA MỚI*\n\n"
        f"👤 *{requester}* ({requester_shift.get('day')} • Ca {requester_shift.get('ca')})\n"
        f"      ⇅\n"
        f"👤 *{target}* ({target_shift.get('day')} • Ca {target_shift.get('ca')})\n"
        + (f"💬 Lý do: {reason}\n" if reason else "")
        + f"👉 Quản lý vui lòng duyệt trên Web App.",
        reply_markup=swap_kb,
    )

    return web.json_response({
        "success": True,
        "message": f"✅ Đã gửi yêu cầu đổi ca với {target}! Đang chờ Quản lý duyệt.",
        "swap": item,
    })


async def handle_api_admin_swaps_decide(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    bot = request.app.get(BOT_KEY)
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()

    swap_id = str(data.get("swap_id") or data.get("id") or "").strip()
    approve = bool(data.get("approve"))

    if not swap_id:
        return web.json_response({"success": False, "message": "Thiếu mã yêu cầu đổi ca."}, status=400)

    decided = store.decide_swap_request(swap_id, approve)
    if not decided:
        return web.json_response({"success": False, "message": "Không tìm thấy yêu cầu đổi ca này."}, status=404)

    req_nick = decided.get("requester", "")
    tgt_nick = decided.get("target", "")
    req_s = decided.get("requester_shift", {})
    tgt_s = decided.get("target_shift", {})

    status_lbl = "✅ ĐÃ DUYỆT" if approve else "❌ ĐÃ TỪ CHỐI"
    await _safe_send_group(
        bot,
        f"{status_lbl} **ĐỔI CA**: **{req_nick}** ({req_s.get('day')} Ca {req_s.get('ca')}) ⇄ **{tgt_nick}** ({tgt_s.get('day')} Ca {tgt_s.get('ca')})!",
    )

    return web.json_response({
        "success": True,
        "message": f"{status_lbl}: Đổi ca giữa {req_nick} và {tgt_nick}!",
        "swap": decided,
        "roster": store.get_roster(decided.get("week_key")),
    })


async def handle_api_notifications_get(request: web.Request) -> web.Response:
    store: WebAppStore = request.app[STORE_KEY]
    user = request[USER_KEY]
    target_nick = request.query.get("nickname") or user.get("nickname") or user.get("username") or ""
    unread_only = request.query.get("unread_only") == "true"
    notifs = store.get_notifications(target_nick, unread_only)
    return web.json_response({
        "success": True,
        "notifications": notifs,
    })


async def handle_api_notifications_mark_read(request: web.Request) -> web.Response:
    store: WebAppStore = request.app[STORE_KEY]
    user = request[USER_KEY]
    data = await request.json()
    notif_id = str(data.get("id") or "").strip()
    target_nick = str(data.get("nickname") or user.get("nickname") or user.get("username") or "").strip()

    ok = store.mark_notification_read(notif_id, target_nick)
    return web.json_response({
        "success": ok,
        "message": "Đã đánh dấu đã đọc" if ok else "Không tìm thấy thông báo",
    })



async def handle_api_expenses_add(request: web.Request) -> web.Response:
    bot = request.app.get(BOT_KEY)
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()

    nickname = str(data.get("nickname") or "Nhân viên").strip() or "Nhân viên"
    role = str(data.get("role") or "Nhân viên").strip()
    ca = str(data.get("ca") or _infer_ca(local_now())).strip()
    reason = str(data.get("reason") or "").strip()
    raw_amount = str(data.get("amount") or "").strip()

    amount = _parse_amount_str(raw_amount)
    if amount is None or amount <= 0 or amount > 50_000_000:
        return web.json_response(
            {"success": False, "message": "Số tiền chi không hợp lệ (VD: 35k, 50000)."},
            status=400,
        )
    if not reason:
        return web.json_response({"success": False, "message": "Vui lòng nhập nội dung khoản chi."}, status=400)

    item = store.add_petty_expense(nickname, role, ca, amount, reason)
    exp_text = (
        f"🧾 *CHI TIỀN LẺ TẠI QUẦY (Ca {ca})*\n"
        f"👤 {nickname} ({role})\n"
        f"💸 Số tiền: *{amount:,}đ*\n"
        f"📝 Nội dung: {reason}"
    )
    await _safe_send_group(bot, exp_text)
    await _safe_send_admin(bot, exp_text)

    return web.json_response({
        "success": True,
        "message": f"✅ Đã ghi nhận khoản chi {amount:,}đ ({reason})!",
        "item": item,
        "petty_expenses": store.get_petty_expenses(15),
    })


async def handle_api_admin_recipe_save(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()

    name = str(data.get("name") or "").strip()
    ingredients = str(data.get("ingredients") or "").strip()
    if not name or not ingredients:
        return web.json_response(
            {"success": False, "message": "Vui lòng nhập Tên món và Định lượng nguyên liệu."},
            status=400,
        )

    saved = store.save_recipe(data)
    return web.json_response({
        "success": True,
        "message": f"✅ Đã lưu công thức món {saved['name']}!",
        "recipes": store.get_recipes(),
    })


async def handle_api_admin_recipe_delete(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    store: WebAppStore = request.app[STORE_KEY]
    data = await request.json()
    rid = str(data.get("id") or "").strip()
    if not rid or not store.delete_recipe(rid):
        return web.json_response({"success": False, "message": "Không tìm thấy công thức cần xóa."}, status=404)

    return web.json_response({
        "success": True,
        "message": "✅ Đã xóa công thức!",
        "recipes": store.get_recipes(),
    })


async def handle_manifest(request: web.Request) -> web.Response:
    manifest_file = STATIC_DIR / "manifest.json"
    if manifest_file.exists():
        return web.FileResponse(manifest_file, headers={"Content-Type": "application/manifest+json"})
    return web.Response(text="{}", content_type="application/json")


async def handle_api_kiosk_status(request: web.Request) -> web.Response:
    return web.json_response({
        "success": True,
        "is_kiosk": _is_kiosk_authorized(request),
    })


async def handle_api_admin_kiosk_activate(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    return web.json_response({
        "success": True,
        "kiosk_key": Config.get_shop_kiosk_key(),
        "message": "✅ Đã kích hoạt máy này làm Máy Điểm Danh Cố Định của quán!",
    })


async def handle_api_admin_kiosk_deactivate(request: web.Request) -> web.Response:
    if resp := _require_admin(request):
        return resp
    return web.json_response({
        "success": True,
        "message": "✅ Đã hủy kích hoạt máy điểm danh trên thiết bị này.",
    })


def create_webapp(sheets, bot=None, bot_data: dict | None = None, store: WebAppStore | None = None) -> web.Application:
    """Khởi tạo aiohttp Application cho Sober Telegram Mini App."""
    app = web.Application(
        middlewares=[auth_middleware],
        client_max_size=25 * 1024 * 1024,  # Hỗ trợ upload album ảnh kết ca lên tới 25MB
    )
    app[SHEETS_KEY] = sheets
    app[BOT_KEY] = bot
    app[BOT_DATA_KEY] = bot_data if bot_data is not None else {}
    if store is None:
        store = WebAppStore(sheets_service=sheets)
    else:
        store.init_from_sheets(sheets)
    app[STORE_KEY] = store
    if bot_data is not None:
        bot_data["store"] = store

    app.router.add_get("/", handle_index)
    app.router.add_get("/manifest.json", handle_manifest)
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/bootstrap", handle_bootstrap)
    app.router.add_get("/api/kiosk/status", handle_api_kiosk_status)
    app.router.add_post("/api/admin/kiosk/activate", handle_api_admin_kiosk_activate)
    app.router.add_post("/api/admin/kiosk/deactivate", handle_api_admin_kiosk_deactivate)

    # Attendance & Personal
    app.router.add_post("/api/checkin", handle_api_checkin)
    app.router.add_post("/api/checkout", handle_api_checkout)
    app.router.add_get("/api/personal/summary", handle_api_personal_summary)
    app.router.add_post("/api/requests/leave", handle_api_leave_request)
    app.router.add_post("/api/schedule/register", handle_api_schedule_register)
    app.router.add_post("/api/expenses/add", handle_api_expenses_add)

    # Inventory
    app.router.add_get("/api/inventory", handle_api_inventory)
    app.router.add_post("/api/inventory/smart-parse", handle_api_inventory_smart_parse)
    app.router.add_post("/api/inventory/export", handle_api_inventory_export)
    app.router.add_post("/api/inventory/import", handle_api_inventory_import)
    app.router.add_post("/api/inventory/material/add", handle_api_material_add)
    app.router.add_post("/api/inventory/material/update", handle_api_material_update)
    app.router.add_post("/api/inventory/material/delete", handle_api_material_delete)

    # Rewards, Revenue & End-shift
    app.router.add_post("/api/rewards/use", handle_api_reward_use)
    app.router.add_post("/api/rewards/request", handle_api_reward_request)
    app.router.add_post("/api/reports/revenue", handle_api_revenue_report)
    app.router.add_post("/api/endshift/upload", handle_api_endshift_upload)
    app.router.add_post("/api/feedback", handle_api_feedback)

    # Admin
    app.router.add_get("/api/admin/overview", handle_api_admin_overview)
    app.router.add_post("/api/admin/late/mark", handle_api_admin_mark_late)
    app.router.add_post("/api/admin/rewards/decide", handle_api_admin_reward_decide)
    app.router.add_post("/api/admin/requests/leave-decide", handle_api_admin_leave_decide)
    app.router.add_post("/api/admin/recipes/save", handle_api_admin_recipe_save)
    app.router.add_post("/api/admin/recipes/delete", handle_api_admin_recipe_delete)
    app.router.add_get("/api/admin/salary", handle_api_admin_salary)
    app.router.add_post("/api/admin/salary/modifier", handle_api_admin_salary_modifier)
    app.router.add_post("/api/admin/overtime/add", handle_api_admin_overtime_add)
    app.router.add_post("/api/admin/employee/add", handle_api_admin_employee_add)
    app.router.add_post("/api/admin/employee/rename", handle_api_admin_employee_rename)
    app.router.add_post("/api/admin/employee/remove", handle_api_admin_employee_remove)
    app.router.add_post("/api/admin/employee/salary-rate", handle_api_admin_salary_rate)
    app.router.add_post("/api/admin/employee/role", handle_api_admin_employee_role)
    app.router.add_get("/api/admin/employee/reward-history", handle_api_admin_reward_history)
    app.router.add_post("/api/admin/report/update-revenue", handle_api_admin_update_revenue)
    app.router.add_post("/api/admin/announce", handle_api_admin_announce)
    app.router.add_post("/api/admin/grant-admin", handle_api_admin_grant)

    # Auth routes (Username / Password)
    app.router.add_post("/api/auth/login", handle_auth_login)
    app.router.add_get("/api/auth/public-users", handle_auth_public_users)
    app.router.add_post("/api/auth/change-password", handle_auth_change_password)

    # Real-Time Sync & Weekly Roster
    app.router.add_get("/api/sync", handle_api_sync)
    app.router.add_get("/api/roster", handle_api_roster_get)
    app.router.add_post("/api/admin/roster/save-draft", handle_api_admin_roster_save_draft)
    app.router.add_post("/api/admin/roster/publish", handle_api_admin_roster_publish)
    app.router.add_post("/api/admin/roster/assign", handle_api_admin_roster_assign)
    app.router.add_post("/api/admin/roster/unassign", handle_api_admin_roster_unassign)
    app.router.add_post("/api/admin/roster/suggest", handle_api_admin_roster_suggest)

    # Shift Swaps
    app.router.add_get("/api/swaps", handle_api_swaps_get)
    app.router.add_post("/api/swaps/create", handle_api_swaps_create)
    app.router.add_post("/api/admin/swaps/decide", handle_api_admin_swaps_decide)

    # Notifications
    app.router.add_get("/api/notifications", handle_api_notifications_get)
    app.router.add_post("/api/notifications/mark-read", handle_api_notifications_mark_read)

    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR, show_index=False)

    return app


async def start_webapp_server(application) -> web.AppRunner | None:
    """Khởi chạy HTTP server cho Telegram Mini App song song với Telegram Bot."""
    if not Config.WEBAPP_ENABLED:
        logger.info("Telegram Mini App server đang tắt (WEBAPP_ENABLED=false).")
        return None

    webapp = create_webapp(
        sheets=application.bot_data["sheets"],
        bot=application.bot,
        bot_data=application.bot_data,
    )
    runner = web.AppRunner(webapp, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=Config.WEBAPP_HOST, port=Config.WEBAPP_PORT)
    await site.start()
    application.bot_data["webapp_runner"] = runner
    logger.info(
        "🌐 Sober Mini App Server đang chạy tại http://%s:%s",
        Config.WEBAPP_HOST,
        Config.WEBAPP_PORT,
    )
    return runner


async def stop_webapp_server(application):
    """Dừng HTTP server của Mini App khi tắt Bot."""
    runner: web.AppRunner | None = application.bot_data.pop("webapp_runner", None)
    if runner:
        await runner.cleanup()
        logger.info("🛑 Đã dừng Sober Mini App Server.")
