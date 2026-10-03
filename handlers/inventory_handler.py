import asyncio
import difflib
import logging
import re
import unicodedata
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import Config
from utils.auto_delete import track_message, delete_tracked_messages, get_admin_keyboard, get_main_keyboard, safe_edit_message
from utils.admin import is_admin, is_super_admin

logger = logging.getLogger(__name__)

# Emoji icons cho từng nhóm
GROUP_ICONS = {
    'Chế phẩm từ sữa': '🥛',
    'Chế phẩm từ bột thô': '🌾',
    'Trà': '🍵',
    'Syrup,mứt': '🍯',
    'NVL phụ trợ': '🥫',
    'Bột cà phê': '☕',
    'Đường': '🍬',
    'Thuốc lá': '🚬',
    'Công cụ dụng cụ': '🥤',
}

COMMON_UNITS_RE = (
    r'(?:hộp|hop|lon|gói|goi|bịch|bich|chai|ký|ky|kg|lít|lit|'
    r'cây|cay|cái|cai|cuộn|cuon|xấp|xap|túi|tui|ly|ống|ong|hũ|hu)'
)


def _get_group_icon(group_name: str) -> str:
    for k, v in GROUP_ICONS.items():
        if k.lower() in group_name.lower():
            return v
    return '📦'


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(update.effective_user and is_admin(update.effective_user.id, context))


def _esc_md(text: str) -> str:
    """Escape ký tự đặc biệt của Telegram Markdown V1 (_, *, `, [)."""
    if not text:
        return ""
    return str(text).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")


def _strip_accents(s: str) -> str:
    """Bỏ dấu tiếng Việt, chuyển chữ thường và chuẩn hóa khoảng trắng."""
    if not s:
        return ''
    s = s.replace('đ', 'd').replace('Đ', 'd')
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s.lower()).strip()


def _find_matching_materials(query: str, materials: list) -> list:
    """Tìm NVL khớp với từ khóa (không dấu, viết tắt, gần đúng)."""
    q = _strip_accents(query)
    if not q:
        return []

    # 1. Khớp chính xác 100% tên
    exact = [m for m in materials if _strip_accents(m['name']) == q]
    if len(exact) == 1:
        return exact

    # 2. Khớp cụm từ con (substring) theo ranh giới từ trước, sau đó substring thường
    word_boundary_sub = []
    any_sub = []
    for m in materials:
        norm_name = _strip_accents(m['name'])
        if re.search(rf'(?:^|\s){re.escape(q)}(?:\s|$)', norm_name):
            word_boundary_sub.append(m)
        elif q in norm_name:
            any_sub.append(m)

    if word_boundary_sub:
        return word_boundary_sub
    if any_sub:
        return any_sub

    # 3. Tất cả các từ trong query đều xuất hiện trong tên NVL
    q_words = q.split()
    if len(q_words) > 1:
        word_matches = [
            m for m in materials
            if all(w in _strip_accents(m['name']) for w in q_words)
        ]
        if word_matches:
            return word_matches

    # 4. Fuzzy matching (phòng gõ sai chính tả nhẹ)
    scored = []
    for m in materials:
        norm_name = _strip_accents(m['name'])
        ratio = difflib.SequenceMatcher(None, q, norm_name).ratio()
        # Kiểm tra thêm độ khớp với từng từ trong tên
        for part in norm_name.split():
            part_ratio = difflib.SequenceMatcher(None, q, part).ratio()
            if part_ratio > ratio:
                ratio = part_ratio
        if ratio >= 0.65:
            scored.append((ratio, m))

    scored.sort(key=lambda x: -x[0])
    if scored:
        best_score = scored[0][0]
        # Nếu có 1 kết quả vượt trội hẳn (>0.85), ưu tiên lấy top
        return [m for sc, m in scored if sc >= best_score - 0.08][:6]
    return []


def _parse_chunk_qty_and_query(chunk: str, materials: list) -> tuple[float, str]:
    """Tách số lượng và tên món từ 1 cụm người dùng gõ.
    Hỗ trợ:
      - '2 sua tuoi' / '0.5 kg matcha' / '2 hộp sữa đặc'
      - 'sua tuoi 2' / 'sua dac x3'
      - 'sua tuoi' (mặc định SL = 1)
    """
    chunk = chunk.strip()
    # TH1: Số lượng ở đầu: '2 sua tuoi', '0,5 matcha', '2 hộp sữa tươi'
    m_start = re.match(
        rf'^(\d+(?:[.,]\d+)?)\s*(?:{COMMON_UNITS_RE}\s+)?(.+)$',
        chunk,
        re.IGNORECASE,
    )
    if m_start:
        qty = float(m_start.group(1).replace(',', '.'))
        query = m_start.group(2).strip()
        return qty, query

    # Kiểm tra nếu toàn bộ chunk khớp trực tiếp tên món có số ở cuối (VD: 'thuoc 555', 'mt35')
    norm_chunk = _strip_accents(chunk)
    for mat in materials:
        if norm_chunk == _strip_accents(mat['name']) or (
            any(ch.isdigit() for ch in norm_chunk) and norm_chunk in _strip_accents(mat['name'])
        ):
            return 1.0, chunk

    # TH2: Số lượng ở cuối: 'sua tuoi 2', 'sua dac x2', 'matcha 0.5'
    m_end = re.match(
        rf'^(.+?)\s+[xX*]?(\d+(?:[.,]\d+)?)\s*(?:{COMMON_UNITS_RE})?$',
        chunk,
        re.IGNORECASE,
    )
    if m_end:
        query = m_end.group(1).strip()
        qty = float(m_end.group(2).replace(',', '.'))
        return qty, query

    # Mặc định số lượng = 1
    return 1.0, chunk


# ─────────────────────────────────────────────────────────────────
# 1. Nhân viên — Lấy NVL (Gõ nhanh hoặc chọn danh mục)
# ─────────────────────────────────────────────────────────────────

async def handle_use_material_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nhân viên bấm '📦 Lấy NVL' → cho phép gõ nhanh nhiều món hoặc mở danh mục."""
    context.user_data['awaiting_material_qty'] = '__SMART_SEARCH__'
    context.user_data.pop('smart_export_state', None)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Chọn theo danh mục", callback_data="inv_uback"),
         InlineKeyboardButton("✖ Hủy", callback_data="inv_cancel")]
    ])

    reply = await update.message.reply_text(
        "📦 *BÁO LẤY NGUYÊN VẬT LIỆU*\n\n"
        "✍️ *Gõ trực tiếp số lượng + tên món* (lấy nhiều món cách nhau bằng dấu phẩy `,` hoặc xuống dòng, không cần dấu):\n"
        "📌 _VD: 2 sua tuoi, 1 sua dac, 0.5 matcha_\n\n"
        "Hoặc bấm *📂 Chọn theo danh mục* bên dưới:",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    track_message(context, reply.message_id)


async def _render_smart_export_next_step(update_or_query, context: ContextTypes.DEFAULT_TYPE, is_callback: bool = False):
    """Hiển thị câu hỏi chọn món (nếu còn món trùng tên) hoặc bảng xác nhận cuối cùng."""
    state = context.user_data.get('smart_export_state')
    if not state:
        return

    mode = state.get('mode', 'export')
    ambiguous = state.get('ambiguous', [])
    confirmed = state.get('confirmed', [])
    not_found = state.get('not_found', [])

    # Nếu còn món bị trùng tên nhiều kết quả → hỏi từng món
    if ambiguous:
        current_amb = ambiguous[0]
        query_str = _esc_md(current_amb['query'])
        qty = current_amb['qty']
        candidates = current_amb['candidates']

        buttons, row = [], []
        for idx, cand in enumerate(candidates):
            label = f"{cand['name']} (Tồn: {cand['stock']:g})" if mode == 'import' else cand['name']
            row.append(InlineKeyboardButton(label, callback_data=f"inv_amb_{idx}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([
            InlineKeyboardButton("⏭ Bỏ qua món này", callback_data="inv_amb_skip"),
            InlineKeyboardButton("✖ Hủy tất cả", callback_data="inv_cancel")
        ])

        action_verb = "nhập" if mode == 'import' else "lấy"
        msg = (
            f"❓ Từ khóa *\"{query_str}\"* (SL: `{qty:g}`) khớp với {len(candidates)} món.\n"
            f"Vui lòng chạm chọn đúng món bạn {action_verb}:"
        )
        if is_callback:
            await safe_edit_message(update_or_query, msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
        else:
            reply = await update_or_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
            track_message(context, reply.message_id)
        return

    # Đã giải quyết hết các món trùng → hiển thị bảng xác nhận
    if not confirmed:
        context.user_data.pop('smart_export_state', None)
        err_lines = ["❌ Không tìm thấy nguyên vật liệu nào khớp với nội dung bạn gõ."]
        if not_found:
            err_lines.append(f"Từ khóa không khớp: `{', '.join(not_found)}`")
        if mode == 'import':
            err_lines.append("\n💡 Hãy gõ lại (VD: `36 sua dac, 72 sua tuoi`) hoặc chọn theo danh mục:")
            context.user_data['awaiting_import_qty'] = '__SMART_IMPORT__'
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📂 Chọn theo danh mục", callback_data="inv_import_list"),
                 InlineKeyboardButton("✖ Hủy", callback_data="inv_cancel")]
            ])
        else:
            err_lines.append("\n💡 Hãy gõ lại (VD: `2 sua tuoi, 1 sua dac`) hoặc bấm nút bên dưới:")
            context.user_data['awaiting_material_qty'] = '__SMART_SEARCH__'
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📂 Chọn theo danh mục", callback_data="inv_uback"),
                 InlineKeyboardButton("✖ Hủy", callback_data="inv_cancel")]
            ])
        msg = "\n".join(err_lines)
        if is_callback:
            await safe_edit_message(update_or_query, msg, reply_markup=kb, parse_mode='Markdown')
        else:
            reply = await update_or_query.message.reply_text(msg, reply_markup=kb, parse_mode='Markdown')
            track_message(context, reply.message_id)
        return

    # Gộp các món trùng nhau nếu người dùng gõ 2 lần cùng 1 món
    merged = {}
    for item in confirmed:
        name = item['name']
        if name in merged:
            merged[name]['qty'] = round(merged[name]['qty'] + item['qty'], 3)
        else:
            merged[name] = dict(item)
    state['confirmed'] = list(merged.values())

    if mode == 'import':
        lines = [
            "📋 *XÁC NHẬN NHẬP KHO NVL*",
            f"{'─' * 26}"
        ]
        for item in state['confirmed']:
            unit_s = f" {_esc_md(item['unit'])}" if item.get('unit') else ""
            old_s = item['stock']
            new_s = round(old_s + item['qty'], 3)
            lines.append(f"• *{_esc_md(item['name'])}*: `+{item['qty']:g}`{unit_s} _(Tồn: {old_s:g} → {new_s:g})_")
        confirm_btn = "✅ Xác nhận nhập kho"
    else:
        lines = [
            "📋 *XÁC NHẬN BÁO LẤY NVL*",
            f"{'─' * 26}"
        ]
        for item in state['confirmed']:
            unit_s = f" {_esc_md(item['unit'])}" if item.get('unit') else ""
            lines.append(f"• *{_esc_md(item['name'])}*: `{item['qty']:g}`{unit_s}")
        confirm_btn = "✅ Xác nhận báo lấy"

    if not_found:
        lines.append(f"{'─' * 26}")
        lines.append(f"❓ _Không tìm thấy:_ `{', '.join(not_found)}`")

    lines.append(f"{'─' * 26}")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(confirm_btn, callback_data="inv_smart_ok"),
         InlineKeyboardButton("❌ Hủy", callback_data="inv_cancel")]
    ])

    msg = "\n".join(lines)
    if is_callback:
        await safe_edit_message(update_or_query, msg, reply_markup=kb, parse_mode='Markdown')
    else:
        reply = await update_or_query.message.reply_text(msg, reply_markup=kb, parse_mode='Markdown')
        track_message(context, reply.message_id)


# ─────────────────────────────────────────────────────────────────
# 2. Callback dispatcher
# ─────────────────────────────────────────────────────────────────

async def handle_inv_callback(query, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý tất cả callback có prefix 'inv_'."""
    data = query.data
    sheets = context.bot_data['sheets']

    # ── Đóng menu ──
    if data == "inv_cancel":
        context.user_data.pop('awaiting_material_qty', None)
        context.user_data.pop('awaiting_import_qty', None)
        context.user_data.pop('smart_export_state', None)
        await safe_edit_message(query, "✖ Đã đóng.")
        return

    # ── Mở nhanh báo lấy NVL (từ nút nhắc sau Kết Ca) ──
    if data == "inv_quick_start":
        context.user_data['awaiting_material_qty'] = '__SMART_SEARCH__'
        context.user_data.pop('smart_export_state', None)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 Chọn theo danh mục", callback_data="inv_uback"),
             InlineKeyboardButton("✖ Hủy", callback_data="inv_cancel")]
        ])
        await safe_edit_message(query, 
            "📦 *BÁO LẤY NGUYÊN VẬT LIỆU*\n\n"
            "✍️ *Gõ trực tiếp số lượng + tên món* (cách nhau bằng dấu phẩy `,` hoặc xuống dòng, không cần dấu):\n"
            "📌 _VD: 2 sua tuoi, 1 sua dac, 0.5 matcha_\n\n"
            "Hoặc bấm *📂 Chọn theo danh mục* bên dưới:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        return

    # ── Chọn món khi có nhiều kết quả trùng (ambiguous) ──
    if data.startswith("inv_amb_"):
        state = context.user_data.get('smart_export_state')
        if not state or not state.get('ambiguous'):
            await safe_edit_message(query, "❌ Phiên đã hết hạn. Vui lòng thử lại.")
            return

        action = data.replace("inv_amb_", "")
        current_amb = state['ambiguous'].pop(0)
        if action != "skip":
            try:
                c_idx = int(action)
                chosen = current_amb['candidates'][c_idx]
                state['confirmed'].append({
                    'name': chosen['name'],
                    'qty': current_amb['qty'],
                    'stock': chosen['stock'],
                    'unit': chosen.get('unit', ''),
                })
            except (ValueError, IndexError):
                pass

        await _render_smart_export_next_step(query, context, is_callback=True)
        return

    # ── Xác nhận xuất kho / nhập kho hàng loạt ──
    if data == "inv_smart_ok":
        state = context.user_data.pop('smart_export_state', None)
        context.user_data.pop('awaiting_material_qty', None)
        context.user_data.pop('awaiting_import_qty', None)
        if not state or not state.get('confirmed'):
            await safe_edit_message(query, "❌ Phiên đã hết hạn. Vui lòng thử lại.")
            return

        mode = state.get('mode', 'export')
        items = state['confirmed']
        user_display_name = query.from_user.first_name or ("Quản lý" if mode == 'import' else "Nhân viên")
        safe_user = _esc_md(user_display_name)

        if mode == 'import':
            await safe_edit_message(query, "⏳ Đang cập nhật nhập kho lên Sheet tháng...")
            result = await asyncio.to_thread(sheets.batch_import_stock, items, user_display_name, '')
            lines = []
            if result.get('imported'):
                lines.append(f"✅ *ĐÃ NHẬP KHO ({safe_user}):*")
                for imp in result['imported']:
                    unit_s = f" {_esc_md(imp['unit'])}" if imp.get('unit') else ""
                    lines.append(f" • *{_esc_md(imp['name'])}*: `+{imp['qty']:g}`{unit_s} _(Tồn mới: {imp['new_stock']:g}{unit_s})_")
            if result.get('errors'):
                if lines:
                    lines.append("")
                lines.append("❌ *Chưa nhập được:*")
                for err in result['errors']:
                    lines.append(f" • {_esc_md(err)}")
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu kho", callback_data="inv_menu")]])
            await safe_edit_message(query, "\n".join(lines) or "❌ Không thể nhập kho.", reply_markup=kb, parse_mode='Markdown')
            return

        await safe_edit_message(query, "⏳ Đang gửi báo cáo lấy NVL...")

        result = await asyncio.to_thread(sheets.batch_export_stock, items, user_display_name, '')

        lines = []
        if result.get('exported'):
            lines.append(f"✅ *ĐÃ BÁO LẤY NVL ({safe_user}):*")
            for exp in result['exported']:
                unit_s = f" {_esc_md(exp['unit'])}" if exp.get('unit') else ""
                lines.append(f" • *{_esc_md(exp['name'])}*: `{exp['qty']:g}`{unit_s}")

        if result.get('errors'):
            if lines:
                lines.append("")
            lines.append("❌ *Chưa ghi nhận được:*")
            for err in result['errors']:
                lines.append(f" • {_esc_md(err)}")

        await safe_edit_message(query, "\n".join(lines) or "❌ Không thể gửi báo cáo.", parse_mode='Markdown')

        # Gửi báo cáo + cảnh báo tồn kho về cho Admin
        if result.get('exported'):
            admin_lines = [
                f"📦 *BÁO CÁO LẤY NVL — {safe_user}*",
                f"{'─' * 24}"
            ]
            for exp in result['exported']:
                unit_s = f" {_esc_md(exp['unit'])}" if exp.get('unit') else ""
                admin_lines.append(
                    f" • *{_esc_md(exp['name'])}*: lấy `{exp['qty']:g}`{unit_s} (Còn: *{exp['new_stock']:g}*{unit_s})"
                )
            alerts = result.get('low_stock_alerts', [])
            if alerts:
                admin_lines.append(f"{'─' * 24}")
                admin_lines.append("⚠️ *Cần nhập thêm:* " + ", ".join(f"*{_esc_md(a['name'])}* ({a['new_stock']:g})" for a in alerts))
            try:
                await context.bot.send_message(
                    chat_id=Config.ADMIN_CHAT_ID,
                    text="\n".join(admin_lines),
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error("Lỗi gửi báo cáo kho cho admin: %s", e)
        return

    # ── Nhân viên: chọn nhóm NVL ──
    if data.startswith("inv_ugrp_"):
        idx = int(data.replace("inv_ugrp_", ""))
        groups = context.user_data.get('inv_groups') or await asyncio.to_thread(sheets.get_material_groups)
        if idx >= len(groups):
            await safe_edit_message(query, "❌ Nhóm không tồn tại hoặc đã hết hạn.")
            return
        selected_group = groups[idx]
        materials = await asyncio.to_thread(sheets.get_all_materials, selected_group)

        if not materials:
            await safe_edit_message(query, f"📦 Không có NVL nào trong nhóm *{selected_group}*.", parse_mode='Markdown')
            return

        context.user_data['inv_current_materials'] = materials
        buttons, row = [], []
        for m_idx, m in enumerate(materials):
            row.append(InlineKeyboardButton(m['name'], callback_data=f"inv_usel_{m_idx}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([
            InlineKeyboardButton("◀ Chọn nhóm khác", callback_data="inv_uback"),
            InlineKeyboardButton("✖ Hủy", callback_data="inv_cancel")
        ])

        await safe_edit_message(query, 
            f"📦 *NHÓM: {selected_group}*\nChọn món cần lấy (hoặc gõ trực tiếp tên món):",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='Markdown'
        )
        return

    # ── Nhân viên: quay lại chọn nhóm ──
    if data == "inv_uback":
        groups = context.user_data.get('inv_groups') or await asyncio.to_thread(sheets.get_material_groups)
        context.user_data['inv_groups'] = groups
        buttons, row = [], []
        for idx, grp in enumerate(groups):
            icon = _get_group_icon(grp)
            row.append(InlineKeyboardButton(f"{icon} {grp}", callback_data=f"inv_ugrp_{idx}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("✖ Hủy", callback_data="inv_cancel")])
        await safe_edit_message(query, 
            "📦 *LẤY NGUYÊN VẬT LIỆU*\nChọn nhóm nguyên vật liệu (hoặc gõ trực tiếp `2 sua tuoi, 1 sua dac`):",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='Markdown'
        )
        return

    # ── Nhân viên: chọn 1 NVL cụ thể từ danh mục ──
    if data.startswith("inv_usel_"):
        m_idx = int(data.replace("inv_usel_", ""))
        materials = context.user_data.get('inv_current_materials', [])
        if m_idx >= len(materials):
            await safe_edit_message(query, "❌ Lựa chọn không hợp lệ hoặc đã hết hạn.")
            return
        m = materials[m_idx]
        name = m['name']
        unit = m.get('unit', '')
        unit_str = f" ({unit})" if unit else ""
        context.user_data['awaiting_material_qty'] = name
        await safe_edit_message(query, 
            f"📦 Nhập số lượng *{name}*{unit_str} cần lấy:\n"
            f"_(Gõ /cancel để hủy)_",
            parse_mode='Markdown'
        )
        return

    # ── Admin: menu chính kho ──
    if data == "inv_menu":
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        keyboard = _get_inventory_menu_keyboard()
        await safe_edit_message(query, 
            "📦 *QUẢN LÝ KHO NGUYÊN VẬT LIỆU*\nChọn chức năng:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        return

    # ── Admin: chọn nhóm nhập kho hoặc gõ nhanh ──
    if data == "inv_import_list":
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        groups = await asyncio.to_thread(sheets.get_material_groups)
        if not groups:
            await safe_edit_message(query, "📦 Kho chưa có NVL nào. Hãy thêm NVL trước.")
            return

        context.user_data['inv_import_groups'] = groups
        context.user_data['awaiting_import_qty'] = '__SMART_IMPORT__'
        context.user_data.pop('smart_export_state', None)
        buttons, row = [], []
        for idx, grp in enumerate(groups):
            icon = _get_group_icon(grp)
            row.append(InlineKeyboardButton(f"{icon} {grp}", callback_data=f"inv_imgrp_{idx}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("◀ Quay lại", callback_data="inv_menu")])

        await safe_edit_message(query, 
            "➕ *NHẬP KHO NGUYÊN VẬT LIỆU*\n\n"
            "✍️ *Gõ trực tiếp danh sách hàng nhập* (cách nhau bằng dấu phẩy `,` hoặc xuống dòng):\n"
            "📌 _VD: 36 sua dac, 72 sua tuoi, 40 richs_\n\n"
            "Hoặc chọn nhóm NVL bên dưới:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='Markdown'
        )
        return

    # ── Admin: chọn nhóm để nhập kho ──
    if data.startswith("inv_imgrp_"):
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        idx = int(data.replace("inv_imgrp_", ""))
        groups = context.user_data.get('inv_import_groups') or await asyncio.to_thread(sheets.get_material_groups)
        if idx >= len(groups):
            await safe_edit_message(query, "❌ Nhóm không tồn tại.")
            return
        selected_group = groups[idx]
        materials = await asyncio.to_thread(sheets.get_all_materials, selected_group)

        context.user_data['inv_import_materials'] = materials
        buttons, row = [], []
        for m_idx, m in enumerate(materials):
            label = f"{m['name']} ({m['stock']:g})"
            row.append(InlineKeyboardButton(label, callback_data=f"inv_imsel_{m_idx}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("◀ Chọn nhóm khác", callback_data="inv_import_list")])

        await safe_edit_message(query, 
            f"➕ *NHẬP KHO — {selected_group}*\nChọn NVL cần nhập thêm:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='Markdown'
        )
        return

    # ── Admin: chọn NVL nhập kho ──
    if data.startswith("inv_imsel_"):
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        m_idx = int(data.replace("inv_imsel_", ""))
        materials = context.user_data.get('inv_import_materials', [])
        if m_idx >= len(materials):
            await safe_edit_message(query, "❌ Lựa chọn không hợp lệ.")
            return
        m = materials[m_idx]
        name = m['name']
        context.user_data['awaiting_import_qty'] = name
        await safe_edit_message(query, 
            f"➕ Nhập số lượng *{name}* cần nhập kho:\n"
            f"_(Tồn kho hiện tại: {m['stock']:g})_\n"
            f"_(Gõ /cancel để hủy)_",
            parse_mode='Markdown'
        )
        return

    # ── Admin: kiểm kho ──
    if data == "inv_check":
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        materials = await asyncio.to_thread(sheets.get_all_materials)
        if not materials:
            await safe_edit_message(query, "📦 Kho chưa có nguyên vật liệu nào.")
            return

        low_stock = [m for m in materials if m['min_stock'] > 0 and m['stock'] <= m['min_stock']]
        zero_stock = [m for m in materials if m['stock'] <= 0]

        lines = [
            f"📦 *TỔNG QUAN TỒN KHO* ({len(materials)} mặt hàng)",
            f"{'─' * 28}",
            f"📊 Tổng mặt hàng: *{len(materials)}*",
            f"🔴 Đã hết hàng (≤ 0): *{len(zero_stock)}* món",
            f"⚠️ Cảnh báo sắp hết: *{len(low_stock)}* món",
            f"{'─' * 28}",
        ]

        if zero_stock:
            lines.append("🔴 *HẾT HÀNG:*")
            for m in zero_stock[:10]:
                lines.append(f" • {m['name']}: *{m['stock']:g}* {m['unit']}")
            if len(zero_stock) > 10:
                lines.append(f" _...và {len(zero_stock) - 10} món khác_")
            lines.append("")

        if low_stock:
            lines.append("⚠️ *DƯỚI MỨC TỐI THIỂU:*")
            for m in low_stock[:10]:
                lines.append(f" • {m['name']}: {m['stock']:g} (Min: {m['min_stock']:g})")
            if len(low_stock) > 10:
                lines.append(f" _...và {len(low_stock) - 10} món khác_")

        msg = "\n".join(lines)
        if len(msg) > 3900:
            msg = msg[:3900] + "\n_...bị cắt_"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Xem chi tiết theo nhóm", callback_data="inv_check_groups")],
            [InlineKeyboardButton("◀ Quay lại", callback_data="inv_menu")]
        ])
        await safe_edit_message(query, msg, reply_markup=keyboard, parse_mode='Markdown')
        return

    # ── Admin: chọn nhóm để xem chi tiết tồn kho ──
    if data == "inv_check_groups":
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        groups = await asyncio.to_thread(sheets.get_material_groups)
        context.user_data['inv_check_groups'] = groups
        buttons, row = [], []
        for idx, grp in enumerate(groups):
            icon = _get_group_icon(grp)
            row.append(InlineKeyboardButton(f"{icon} {grp}", callback_data=f"inv_ckgrp_{idx}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("◀ Quay lại", callback_data="inv_check")])

        await safe_edit_message(query, 
            "🔍 *XEM CHI TIẾT TỒN KHO*\nChọn nhóm cần kiểm tra:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='Markdown'
        )
        return

    # ── Admin: chi tiết tồn kho của 1 nhóm ──
    if data.startswith("inv_ckgrp_"):
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        idx = int(data.replace("inv_ckgrp_", ""))
        groups = context.user_data.get('inv_check_groups') or await asyncio.to_thread(sheets.get_material_groups)
        if idx >= len(groups):
            await safe_edit_message(query, "❌ Nhóm không tồn tại.")
            return
        selected_group = groups[idx]
        materials = await asyncio.to_thread(sheets.get_all_materials, selected_group)

        lines = [
            f"📦 *TỒN KHO — {selected_group.upper()}*",
            f"{'─' * 28}"
        ]
        for m in materials:
            icon = "🔴" if m['stock'] <= 0 else ("⚠️" if m['min_stock'] > 0 and m['stock'] <= m['min_stock'] else "✅")
            min_str = f" (Min: {m['min_stock']:g})" if m['min_stock'] > 0 else ""
            lines.append(f"{icon} *{m['name']}*: {m['stock']:g} {m['unit']}{min_str}")

        msg = "\n".join(lines)
        if len(msg) > 3900:
            msg = msg[:3900] + "\n_...bị cắt_"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀ Chọn nhóm khác", callback_data="inv_check_groups")],
            [InlineKeyboardButton("🏠 Menu kho", callback_data="inv_menu")]
        ])
        await safe_edit_message(query, msg, reply_markup=keyboard, parse_mode='Markdown')
        return

    # ── Admin: lịch sử kho ──
    if data == "inv_history":
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        history = await asyncio.to_thread(sheets.get_inventory_history, 20)
        if not history:
            await safe_edit_message(query, 
                "📜 Chưa có lịch sử xuất/nhập kho.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀ Quay lại", callback_data="inv_menu")]]),
                parse_mode='Markdown'
            )
            return

        lines = [f"📜 *LỊCH SỬ KHO* (20 lượt gần nhất)\n{'─' * 28}"]
        for h in history:
            sign = "+" if h['type'] == 'Nhập' else "-"
            icon = "📥" if h['type'] == 'Nhập' else "📤"
            lines.append(f"{icon} {h['date']} | *{h['name']}* {sign}{h['qty']:g} | {h['user']}")

        lines.append(f"{'─' * 28}")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀ Quay lại", callback_data="inv_menu")]
        ])
        msg = "\n".join(lines)
        if len(msg) > 3900:
            msg = msg[:3900] + "\n_...bị cắt_"
        await safe_edit_message(query, msg, reply_markup=keyboard, parse_mode='Markdown')
        return

    # ── Admin: sub-menu quản lý NVL ──
    if data == "inv_manage":
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Thêm NVL", callback_data="inv_add_new")],
            [InlineKeyboardButton("✏️ Sửa NVL", callback_data="inv_edit_list")],
            [InlineKeyboardButton("❌ Xóa NVL", callback_data="inv_del_list")],
            [InlineKeyboardButton("◀ Quay lại", callback_data="inv_menu")]
        ])
        await safe_edit_message(query, 
            "🔧 *QUẢN LÝ NGUYÊN VẬT LIỆU*\nChọn thao tác:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        return

    # ── Admin: thêm NVL mới ──
    if data == "inv_add_new":
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        context.user_data['awaiting_new_material'] = True
        await safe_edit_message(query, 
            "➕ *THÊM NGUYÊN VẬT LIỆU MỚI*\n\n"
            "Nhập theo định dạng:\n"
            "`Tên | Đơn vị | Mức tối thiểu | Giá nhập | Nhóm`\n\n"
            "Ví dụ:\n"
            "`Cà phê hạt | kg | 5 | 150000 | Bột cà phê`\n\n"
            "_(Nhóm có thể bỏ qua, mặc định là Khác)_\n"
            "_(Gõ /cancel để hủy)_",
            parse_mode='Markdown'
        )
        return

    # ── Admin: chọn nhóm để sửa NVL ──
    if data == "inv_edit_list":
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        groups = await asyncio.to_thread(sheets.get_material_groups)
        context.user_data['inv_edit_groups'] = groups
        buttons, row = [], []
        for idx, grp in enumerate(groups):
            icon = _get_group_icon(grp)
            row.append(InlineKeyboardButton(f"{icon} {grp}", callback_data=f"inv_edgrp_{idx}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("◀ Quay lại", callback_data="inv_manage")])

        await safe_edit_message(query, 
            "✏️ *SỬA NVL*\nChọn nhóm NVL cần sửa:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='Markdown'
        )
        return

    # ── Admin: danh sách NVL trong nhóm để sửa ──
    if data.startswith("inv_edgrp_"):
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        idx = int(data.replace("inv_edgrp_", ""))
        groups = context.user_data.get('inv_edit_groups') or await asyncio.to_thread(sheets.get_material_groups)
        if idx >= len(groups):
            await safe_edit_message(query, "❌ Nhóm không tồn tại.")
            return
        selected_group = groups[idx]
        materials = await asyncio.to_thread(sheets.get_all_materials, selected_group)

        context.user_data['inv_edit_materials'] = materials
        buttons, row = [], []
        for m_idx, m in enumerate(materials):
            label = f"{m['name']}"
            row.append(InlineKeyboardButton(label, callback_data=f"inv_edsel_{m_idx}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("◀ Chọn nhóm khác", callback_data="inv_edit_list")])

        await safe_edit_message(query, 
            f"✏️ *SỬA NVL — {selected_group}*\nChọn món cần sửa:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='Markdown'
        )
        return

    # ── Admin: chọn món để sửa ──
    if data.startswith("inv_edsel_"):
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        m_idx = int(data.replace("inv_edsel_", ""))
        materials = context.user_data.get('inv_edit_materials', [])
        if m_idx >= len(materials):
            await safe_edit_message(query, "❌ Lựa chọn không hợp lệ.")
            return
        m = materials[m_idx]
        name = m['name']
        context.user_data['awaiting_edit_material'] = name
        await safe_edit_message(query, 
            f"✏️ *SỬA NVL: {name}*\n\n"
            f"Hiện tại: Đơn vị: `{m['unit'] or '(chưa có)'}`, Min: `{m['min_stock']:g}`, Giá: `{m['price']:g}`\n\n"
            "Nhập thông tin mới theo định dạng:\n"
            "`Đơn vị | Mức tối thiểu | Giá nhập`\n\n"
            "Ví dụ: `kg | 5 | 150000`\n\n"
            "_(Gõ /cancel để hủy)_",
            parse_mode='Markdown'
        )
        return

    # ── Admin: chọn nhóm để xóa NVL ──
    if data == "inv_del_list":
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        groups = await asyncio.to_thread(sheets.get_material_groups)
        context.user_data['inv_del_groups'] = groups
        buttons, row = [], []
        for idx, grp in enumerate(groups):
            icon = _get_group_icon(grp)
            row.append(InlineKeyboardButton(f"{icon} {grp}", callback_data=f"inv_dlgrp_{idx}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("◀ Quay lại", callback_data="inv_manage")])

        await safe_edit_message(query, 
            "❌ *XÓA NVL*\nChọn nhóm của món cần xóa:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='Markdown'
        )
        return

    # ── Admin: danh sách món trong nhóm để xóa ──
    if data.startswith("inv_dlgrp_"):
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        idx = int(data.replace("inv_dlgrp_", ""))
        groups = context.user_data.get('inv_del_groups') or await asyncio.to_thread(sheets.get_material_groups)
        if idx >= len(groups):
            await safe_edit_message(query, "❌ Nhóm không tồn tại.")
            return
        selected_group = groups[idx]
        materials = await asyncio.to_thread(sheets.get_all_materials, selected_group)

        context.user_data['inv_del_materials'] = materials
        buttons, row = [], []
        for m_idx, m in enumerate(materials):
            row.append(InlineKeyboardButton(f"❌ {m['name']}", callback_data=f"inv_dlsel_{m_idx}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("◀ Chọn nhóm khác", callback_data="inv_del_list")])

        await safe_edit_message(query, 
            f"❌ *XÓA NVL — {selected_group}*\nChọn món cần xóa:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='Markdown'
        )
        return

    # ── Admin: xác nhận xóa NVL ──
    if data.startswith("inv_dlsel_"):
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        m_idx = int(data.replace("inv_dlsel_", ""))
        materials = context.user_data.get('inv_del_materials', [])
        if m_idx >= len(materials):
            await safe_edit_message(query, "❌ Lựa chọn không hợp lệ.")
            return
        m = materials[m_idx]
        name = m['name']
        context.user_data['inv_del_target'] = name
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Xác nhận xóa {name}", callback_data="inv_dl_confirm")],
            [InlineKeyboardButton("◀ Quay lại", callback_data="inv_del_list")]
        ])
        await safe_edit_message(query, 
            f"⚠️ Bạn có chắc muốn xóa *{name}* khỏi danh sách NVL?\n"
            f"_(Thao tác này không thể hoàn tác)_",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        return

    # ── Admin: thực hiện xóa NVL ──
    if data == "inv_dl_confirm":
        if not is_admin(query.from_user.id, context):
            await query.answer("⛔ Chỉ quản lý được thao tác.", show_alert=True)
            return
        name = context.user_data.pop('inv_del_target', None)
        if not name:
            await safe_edit_message(query, "❌ Phiên đã hết hạn.")
            return
        result = await asyncio.to_thread(sheets.remove_material, name)
        if result:
            await safe_edit_message(query, 
                f"✅ Đã xóa *{name}* khỏi danh mục kho.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu kho", callback_data="inv_menu")]]),
                parse_mode='Markdown'
            )
        else:
            await safe_edit_message(query, 
                f"❌ Không thể xóa *{name}*. Vui lòng thử lại.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu kho", callback_data="inv_menu")]]),
                parse_mode='Markdown'
            )
        return


def _get_inventory_menu_keyboard() -> InlineKeyboardMarkup:
    """Trả về bàn phím inline menu kho."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Nhập Kho", callback_data="inv_import_list"),
         InlineKeyboardButton("📋 Kiểm Kho", callback_data="inv_check")],
        [InlineKeyboardButton("📜 Lịch Sử", callback_data="inv_history"),
         InlineKeyboardButton("🔧 Quản Lý NVL", callback_data="inv_manage")],
        [InlineKeyboardButton("✖ Đóng", callback_data="inv_cancel")]
    ])


# ─────────────────────────────────────────────────────────────────
# 3. Admin — Menu kho (từ Reply Keyboard)
# ─────────────────────────────────────────────────────────────────

async def handle_inventory_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin bấm nút menu kho → inline menu."""
    if not _is_admin(update, context):
        return

    keyboard = _get_inventory_menu_keyboard()
    reply = await update.message.reply_text(
        "📦 *QUẢN LÝ KHO NGUYÊN VẬT LIỆU*\nChọn chức năng:",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    track_message(context, reply.message_id)


# ─────────────────────────────────────────────────────────────────
# 4. Nhân viên — Xử lý gõ nhanh nhiều món HOẶC nhập số lượng 1 món
# ─────────────────────────────────────────────────────────────────

async def handle_material_qty_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Xử lý khi nhân viên gõ nhanh danh sách NVL hoặc nhập số lượng cho 1 món."""
    target_state = context.user_data.get('awaiting_material_qty')
    if not target_state:
        return False

    text = update.message.text.strip()
    if text.startswith('/cancel'):
        context.user_data.pop('awaiting_material_qty', None)
        context.user_data.pop('smart_export_state', None)
        await update.message.reply_text("❌ Đã hủy thao tác lấy NVL.")
        return True

    # Nếu người dùng bấm nút khác trên Reply Keyboard thì nhường cho button_click_handler
    if text in {
        "📱 Mở Mini App",
        "📥 Check In", "📤 Check Out", "⚡ Thưởng Doanh Thu", "🥤 Báo Dùng Thưởng",
        "🎁 Tra Cứu Thưởng", "💡 Đóng Góp Ý Kiến", "📦 Lấy NVL", "🔚 Kết Ca",
        "📊 Bảng Thưởng (QL)", "🧾 Quản Lý NV (QL)", "✏️ Sửa Doanh Thu",
        "📋 Lịch Sử Check-In", "⚠️ Thống Kê Đi Muộn", "📊 Thống Kê Giờ LT",
        "💰 Tính Lương (QL)", "➕ Giờ LT (QL)", "💸 Ứng Lương (QL)",
        "🎁 Thưởng Tiền (QL)", "📦 Kho NVL (QL)", "👑 Cấp Quyền QL", "📖 Hướng Dẫn",
    }:
        return False

    sheets = context.bot_data['sheets']

    # Chế độ 1: Gõ nhanh tự nhiên (VD: "2 sua tuoi, 1 sua dac, 0.5 matcha")
    if target_state == '__SMART_SEARCH__':
        all_materials = await asyncio.to_thread(sheets.get_all_materials)
        if not all_materials:
            context.user_data.pop('awaiting_material_qty', None)
            await update.message.reply_text("📦 Kho hiện chưa có dữ liệu nguyên vật liệu.")
            return True

        chunks = [c.strip() for c in re.split(r'[,;\n]+', text) if c.strip()]
        if not chunks:
            return True

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
                    'name': m['name'],
                    'qty': qty,
                    'stock': m['stock'],
                    'unit': m.get('unit', ''),
                })
            else:
                ambiguous.append({
                    'query': query,
                    'qty': qty,
                    'candidates': matches[:8],
                })

        context.user_data.pop('awaiting_material_qty', None)
        context.user_data['smart_export_state'] = {
            'confirmed': confirmed,
            'ambiguous': ambiguous,
            'not_found': not_found,
        }
        await _render_smart_export_next_step(update, context, is_callback=False)
        return True

    # Chế độ 2: Đã chọn 1 món từ danh mục, giờ chỉ nhập số lượng
    name = target_state
    try:
        qty = float(text.replace(',', '.'))
        if qty <= 0:
            raise ValueError
    except ValueError:
        reply = await update.message.reply_text(
            "❌ Số lượng không hợp lệ. Vui lòng nhập số lớn hơn 0 (VD: 1 hoặc 0.5):",
            parse_mode='Markdown'
        )
        track_message(context, reply.message_id)
        return True

    user_display_name = update.effective_user.first_name or "Nhân viên"
    result = await asyncio.to_thread(sheets.export_stock, name, qty, user_display_name, '')

    context.user_data.pop('awaiting_material_qty', None)

    if not result.get('success'):
        err = result.get('error', '')
        msg = f"❌ Lỗi: {err or 'Không thể gửi báo cáo.'}"
        reply = await update.message.reply_text(msg, parse_mode='Markdown')
        track_message(context, reply.message_id)
        return True

    unit_str = f" {result.get('unit')}" if result.get('unit') else ""
    reply = await update.message.reply_text(
        f"✅ Đã báo lấy *{qty:g}*{unit_str} *{name}*.",
        parse_mode='Markdown'
    )
    track_message(context, reply.message_id)

    try:
        warn = f"\n⚠️ *Cần nhập thêm!* (Còn: {result['new_stock']:g}{unit_str})" if result.get('low_stock') else f" (Còn: {result['new_stock']:g}{unit_str})"
        await context.bot.send_message(
            chat_id=Config.ADMIN_CHAT_ID,
            text=f"📦 *BÁO CÁO LẤY NVL — {user_display_name}*\n"
                 f" • *{name}*: lấy `{qty:g}`{unit_str}{warn}",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error("Lỗi gửi báo cáo kho cho admin: %s", e)

    return True


# ─────────────────────────────────────────────────────────────────
# 5. Admin — Nhập số lượng nhập kho
# ─────────────────────────────────────────────────────────────────

async def handle_import_qty_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Xử lý nhập số lượng NVL nhập kho (gõ nhanh nhiều món hoặc nhập SL cho 1 món). Trả về True nếu đã xử lý."""
    name = context.user_data.get('awaiting_import_qty')
    if not name:
        return False

    text = update.message.text.strip()
    if text.startswith('/cancel'):
        context.user_data.pop('awaiting_import_qty', None)
        context.user_data.pop('smart_export_state', None)
        await update.message.reply_text(
            "❌ Đã hủy thao tác nhập kho.",
            reply_markup=get_admin_keyboard(is_super_admin=is_super_admin(update.effective_user.id))
        )
        return True

    if text in {
        "📱 Mở Mini App",
        "📥 Check In", "📤 Check Out", "⚡ Thưởng Doanh Thu", "🥤 Báo Dùng Thưởng",
        "🎁 Tra Cứu Thưởng", "💡 Đóng Góp Ý Kiến", "📦 Lấy NVL", "🔚 Kết Ca",
        "📊 Bảng Thưởng (QL)", "🧾 Quản Lý NV (QL)", "✏️ Sửa Doanh Thu",
        "📋 Lịch Sử Check-In", "⚠️ Thống Kê Đi Muộn", "📊 Thống Kê Giờ LT",
        "💰 Tính Lương (QL)", "➕ Giờ LT (QL)", "💸 Ứng Lương (QL)",
        "🎁 Thưởng Tiền (QL)", "📦 Kho NVL (QL)", "👑 Cấp Quyền QL", "📖 Hướng Dẫn",
    }:
        return False

    sheets = context.bot_data['sheets']

    # Chế độ 1: Gõ nhanh nhiều món nhập kho (VD: '36 sua dac, 72 sua tuoi')
    if name == '__SMART_IMPORT__':
        all_materials = await asyncio.to_thread(sheets.get_all_materials)
        if not all_materials:
            context.user_data.pop('awaiting_import_qty', None)
            await update.message.reply_text("📦 Kho hiện chưa có dữ liệu nguyên vật liệu.")
            return True

        chunks = [c.strip() for c in re.split(r'[,;\n]+', text) if c.strip()]
        if not chunks:
            return True

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
                    'name': m['name'],
                    'qty': qty,
                    'stock': m['stock'],
                    'unit': m.get('unit', ''),
                })
            else:
                ambiguous.append({
                    'query': query,
                    'qty': qty,
                    'candidates': matches[:8],
                })

        context.user_data.pop('awaiting_import_qty', None)
        context.user_data['smart_export_state'] = {
            'mode': 'import',
            'confirmed': confirmed,
            'ambiguous': ambiguous,
            'not_found': not_found,
        }
        await _render_smart_export_next_step(update, context, is_callback=False)
        return True

    # Chế độ 2: Đã chọn 1 món cụ thể, nhập số lượng
    try:
        qty = float(text.replace(',', '.'))
        if qty <= 0:
            raise ValueError
    except ValueError:
        reply = await update.message.reply_text(
            "❌ Số lượng không hợp lệ. Vui lòng nhập số lớn hơn 0 (VD: 5 hoặc 10.5):",
            parse_mode='Markdown'
        )
        track_message(context, reply.message_id)
        return True

    user_display_name = update.effective_user.first_name or "Quản lý"
    result = await asyncio.to_thread(sheets.import_stock, name, qty, user_display_name, '')

    context.user_data.pop('awaiting_import_qty', None)

    keyboard = get_admin_keyboard(is_super_admin=is_super_admin(update.effective_user.id))
    safe_name = _esc_md(name)
    if result:
        reply = await update.message.reply_text(
            f"✅ Đã nhập thêm *{qty:g}* *{safe_name}* vào kho thành công.",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    else:
        reply = await update.message.reply_text(
            f"❌ Không thể nhập kho *{safe_name}*. Vui lòng thử lại.",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    track_message(context, reply.message_id)
    return True


# ─────────────────────────────────────────────────────────────────
# 6. Admin — Thêm NVL mới
# ─────────────────────────────────────────────────────────────────

async def handle_new_material_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Xử lý thêm NVL mới. Trả về True nếu đã xử lý."""
    if not context.user_data.get('awaiting_new_material'):
        return False

    text = update.message.text.strip()
    keyboard = get_admin_keyboard(is_super_admin=is_super_admin(update.effective_user.id))
    if text.startswith('/cancel'):
        context.user_data.pop('awaiting_new_material', None)
        await update.message.reply_text("❌ Đã hủy thêm NVL mới.", reply_markup=keyboard)
        return True

    parts = [p.strip() for p in text.split('|')]
    if len(parts) < 2:
        reply = await update.message.reply_text(
            "❌ Sai định dạng. Vui lòng nhập:\n`Tên | Đơn vị | Mức tối thiểu | Giá nhập | Nhóm`",
            parse_mode='Markdown'
        )
        track_message(context, reply.message_id)
        return True

    name = parts[0]
    unit = parts[1]
    try:
        min_stock = float(parts[2].replace(',', '.')) if len(parts) > 2 and parts[2] else 0
    except ValueError:
        min_stock = 0
    try:
        price = float(parts[3].replace(',', '.')) if len(parts) > 3 and parts[3] else 0
    except ValueError:
        price = 0
    group = parts[4] if len(parts) > 4 and parts[4] else "Khác"

    sheets = context.bot_data['sheets']
    result = await asyncio.to_thread(sheets.add_material, name, unit, min_stock, price, group)

    context.user_data.pop('awaiting_new_material', None)

    if result.get('success'):
        reply = await update.message.reply_text(
            f"✅ Đã thêm *{name}* ({unit}) vào nhóm *{group}*.",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    else:
        err = result.get('error', '')
        if err == 'already_exists':
            msg = f"⚠️ *{name}* đã tồn tại trong danh mục!"
        else:
            msg = f"❌ Lỗi: {err or 'Không thể thêm NVL.'}"
        reply = await update.message.reply_text(msg, reply_markup=keyboard, parse_mode='Markdown')
    track_message(context, reply.message_id)
    return True


# ─────────────────────────────────────────────────────────────────
# 7. Admin — Sửa NVL
# ─────────────────────────────────────────────────────────────────

async def handle_edit_material_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Xử lý sửa thông tin NVL. Trả về True nếu đã xử lý."""
    name = context.user_data.get('awaiting_edit_material')
    if not name:
        return False

    text = update.message.text.strip()
    keyboard = get_admin_keyboard(is_super_admin=is_super_admin(update.effective_user.id))
    if text.startswith('/cancel'):
        context.user_data.pop('awaiting_edit_material', None)
        await update.message.reply_text("❌ Đã hủy sửa NVL.", reply_markup=keyboard)
        return True

    parts = [p.strip() for p in text.split('|')]
    if len(parts) < 1 or not parts[0]:
        reply = await update.message.reply_text(
            "❌ Sai định dạng. Vui lòng nhập:\n`Đơn vị | Mức tối thiểu | Giá nhập`",
            parse_mode='Markdown'
        )
        track_message(context, reply.message_id)
        return True

    unit = parts[0]
    try:
        min_stock = float(parts[1].replace(',', '.')) if len(parts) > 1 and parts[1] else 0
    except ValueError:
        min_stock = 0
    try:
        price = float(parts[2].replace(',', '.')) if len(parts) > 2 and parts[2] else 0
    except ValueError:
        price = 0

    sheets = context.bot_data['sheets']
    result = await asyncio.to_thread(sheets.update_material, name, unit=unit, min_stock=min_stock, price=price)

    context.user_data.pop('awaiting_edit_material', None)

    if result:
        reply = await update.message.reply_text(
            f"✅ Đã cập nhật NVL *{name}* thành công.",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    else:
        reply = await update.message.reply_text(
            f"❌ Không thể cập nhật *{name}*. Vui lòng thử lại.",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    track_message(context, reply.message_id)
    return True
