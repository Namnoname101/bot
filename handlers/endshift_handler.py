import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from utils.auto_delete import delete_tracked_messages, track_message, get_main_keyboard, get_admin_keyboard
from utils.admin import is_admin, is_super_admin
from config import Config

logger = logging.getLogger(__name__)

_ALBUM_WAIT = 0.8  # giây gom ảnh cùng media_group_id trước khi xóa


def _get_endshift_keyboard():
    """Bàn phím chỉ có 1 nút Gửi kết ca."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📤 Gửi ảnh kết ca")]],
        resize_keyboard=True,
        is_persistent=True,
    )


# ── Bước 1: Bấm nút "🔚 Kết Ca" → chọn ca ──────────────────────────────────

async def handle_endshift_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("☀️ Ca Sáng", callback_data="ks_ca_Sáng"),
            InlineKeyboardButton("🌤 Ca Chiều", callback_data="ks_ca_Chiều"),
            InlineKeyboardButton("🌙 Ca Tối",   callback_data="ks_ca_Tối"),
        ],
        [InlineKeyboardButton("❌ Hủy", callback_data="ks_cancel")],
    ])
    reply = await update.message.reply_text(
        "🔚 **KẾT CA** — Bạn đang kết ca nào?",
        reply_markup=keyboard,
        parse_mode='Markdown',
    )
    if update.effective_chat.id == Config.GROUP_CHAT_ID:
        track_message(context, reply.message_id)


# ── Bước 2: Chọn ca → chọn bộ phận ─────────────────────────────────────────

async def handle_endshift_ca_selected(query, context: ContextTypes.DEFAULT_TYPE):
    ca = query.data[len("ks_ca_"):]
    context.chat_data['ks_ca'] = ca

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🍽 Phục Vụ", callback_data="ks_role_Phục Vụ"),
            InlineKeyboardButton("🥤 Pha Chế", callback_data="ks_role_Pha Chế"),
        ],
        [InlineKeyboardButton("❌ Hủy", callback_data="ks_cancel")],
    ])
    await query.edit_message_text(
        f"🔚 **KẾT CA {ca.upper()}** — Bạn thuộc bộ phận nào?",
        reply_markup=keyboard,
        parse_mode='Markdown',
    )


# ── Bước 3: Chọn bộ phận → hiện bàn phím "📤 Gửi ảnh kết ca" ───────────────

async def handle_endshift_role_selected(query, context: ContextTypes.DEFAULT_TYPE):
    role = query.data[len("ks_role_"):]
    ca   = context.chat_data.get('ks_ca', '?')

    context.chat_data['awaiting_endshift_photo'] = {'ca': ca, 'role': role}
    context.chat_data['endshift_all_photos'] = []
    context.chat_data['endshift_albums']     = {}

    if query.message and query.message.chat.id == Config.GROUP_CHAT_ID:
        await delete_tracked_messages(context, query.message.chat.id)
        try:
            await query.message.delete()
        except Exception:
            pass

    prompt = await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=(
            f"📸 **Ca {ca} — {role}** — Sẵn sàng!\n\n"
            f"Gửi tất cả ảnh kết ca vào đây.\n"
            f"Khi load xong ảnh, bấm **📤 Gửi ảnh kết ca**."
        ),
        reply_markup=_get_endshift_keyboard(),
        parse_mode='Markdown',
    )
    track_message(context, prompt.message_id)


# ── Nhận ảnh: gom theo album, xóa bên nhân viên, lưu file_id ───────────────

async def handle_endshift_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info = context.chat_data.get('awaiting_endshift_photo')
    if not info:
        return

    message  = update.message
    photo    = message.photo[-1]
    chat_id  = update.effective_chat.id
    group_id = message.media_group_id or f"single_{message.message_id}"

    context.chat_data.setdefault('endshift_all_photos', []).append(photo.file_id)

    albums: dict = context.chat_data.setdefault('endshift_albums', {})
    if group_id not in albums:
        albums[group_id] = {'msg_ids': [], 'task': None}

    album = albums[group_id]
    album['msg_ids'].append(message.message_id)

    old_task: asyncio.Task | None = album.get('task')
    if old_task and not old_task.done():
        old_task.cancel()

    album['task'] = asyncio.create_task(
        _delete_album(group_id, chat_id, context, update.get_bot())
    )


async def _delete_album(group_id: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE, bot):
    """Xóa ảnh 1 album bên nhân viên sau 0.8s."""
    try:
        await asyncio.sleep(_ALBUM_WAIT)
    except asyncio.CancelledError:
        return

    albums: dict = context.chat_data.get('endshift_albums', {})
    album = albums.pop(group_id, None)
    if not album or not album.get('msg_ids'):
        return

    if chat_id == Config.GROUP_CHAT_ID:
        try:
            await bot.delete_messages(chat_id=chat_id, message_ids=album['msg_ids'])
        except Exception:
            for mid in album['msg_ids']:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass


# ── Bấm "📤 Gửi ảnh kết ca" → gửi tất cả sang admin ────────────────────────

async def handle_endshift_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nhân viên bấm nút → chờ album cuối xóa xong → gửi toàn bộ sang admin."""
    info = context.chat_data.pop('awaiting_endshift_photo', None)
    if not info:
        return

    # Chờ các album đang pending xóa xong
    await asyncio.sleep(_ALBUM_WAIT + 0.3)

    all_photos = context.chat_data.pop('endshift_all_photos', [])
    context.chat_data.pop('endshift_albums', None)
    context.chat_data.pop('ks_ca', None)

    chat_id = update.effective_chat.id
    ca      = info['ca']
    role    = info['role']
    total   = len(all_photos)

    if chat_id == Config.GROUP_CHAT_ID:
        await delete_tracked_messages(context, chat_id)
        try:
            await update.message.delete()
        except Exception:
            pass

    if not all_photos:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Chưa có ảnh nào được gửi.",
            reply_markup=get_main_keyboard(),
        )
        return

    # Gửi tất cả sang admin — caption ở ảnh cuối cùng
    try:
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        header  = (
            f"🔚 **KẾT CA {ca.upper()} — {role}**\n"
            f"🕐 {now_str}  |  📷 {total} ảnh"
        )
        chunks = [all_photos[i:i + 10] for i in range(0, total, 10)]
        for idx, chunk in enumerate(chunks):
            is_last = (idx == len(chunks) - 1)
            media = [
                InputMediaPhoto(
                    media=fid,
                    caption=header if (is_last and j == len(chunk) - 1) else None,
                    parse_mode='Markdown',
                )
                for j, fid in enumerate(chunk)
            ]
            await context.bot.send_media_group(chat_id=Config.ADMIN_CHAT_ID, media=media)
    except Exception as e:
        logger.warning(f"Không thể forward ảnh kết ca: {e}")

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✅ **Đã gửi {total} ảnh kết ca {ca} — {role}** cho quản lý!",
        reply_markup=get_main_keyboard(),
        parse_mode='Markdown',
    )


# ── Hủy flow ────────────────────────────────────────────────────────────────

async def handle_endshift_cancel(query, context: ContextTypes.DEFAULT_TYPE):
    _cancel_endshift_tasks(context)

    chat_id = query.message.chat.id
    await delete_tracked_messages(context, chat_id)
    try:
        await query.message.delete()
    except Exception:
        pass

    keyboard = get_admin_keyboard(is_super_admin=is_super_admin(chat_id)) if is_admin(chat_id, context) else get_main_keyboard()
    msg = await context.bot.send_message(chat_id=chat_id, text="❌ Đã hủy kết ca.", reply_markup=keyboard)
    track_message(context, msg.message_id)


def _cancel_endshift_tasks(context: ContextTypes.DEFAULT_TYPE):
    albums: dict = context.chat_data.pop('endshift_albums', {})
    for album in albums.values():
        t = album.get('task')
        if t and not t.done():
            t.cancel()
    context.chat_data.pop('ks_ca', None)
    context.chat_data.pop('awaiting_endshift_photo', None)
    context.chat_data.pop('endshift_all_photos', None)
