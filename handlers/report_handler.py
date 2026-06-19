import asyncio
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

from utils.decorators import group_only
from utils.validators import parse_report_text, check_reward_eligibility, deduplicate_employees
from utils.auto_delete import delete_tracked_messages, track_message

logger = logging.getLogger(__name__)

@group_only
async def handle_photo_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi có ảnh gửi vào group"""
    message = update.message
    if not message.photo:
        return

    caption = message.caption
    if not caption:
        return  # Bỏ qua ảnh không có chú thích

    # Kiểm tra nhanh xem caption có phải là báo cáo không
    if not any(k in caption.lower() for k in ['nv:', 'doanh thu:', 'dt:', 'nhân viên:']):
        return
        
    # Xóa các tin nhắn cũ vì đây là hành động mới
    await delete_tracked_messages(context, update.effective_chat.id)

    # Phân tích dữ liệu (bổ sung nhận diện 'Ca' nếu có)
    employees, revenue, ca, error_msg = parse_report_text(caption)
    if error_msg:
        err_reply = await message.reply_text(f"❌ {error_msg}")
        track_message(context, message.message_id)
        track_message(context, err_reply.message_id)
        return

    # Loại bỏ nhân viên trùng lặp
    employees = deduplicate_employees(employees)

    # Kiểm tra nickname có tồn tại trong hệ thống (Sheet SoDuThuong) không
    sheets_service = context.bot_data['sheets']
    valid_nicknames = await asyncio.to_thread(sheets_service.get_all_nicknames)
    # FIX VẤN ĐỀ 2: phải normalize cùng chuẩn với get_all_nicknames (xóa dấu, xóa khoảng trắng)
    # vì parse_report_text chỉ .lower() còn get_all_nicknames dùng _normalize_name_for_comparison
    import unicodedata, re as _re
    def _normalize(s: str) -> str:
        s = unicodedata.normalize('NFD', str(s).strip())
        s = ''.join(ch for ch in s if not unicodedata.combining(ch))
        s = _re.sub(r'[^0-9a-zA-Z]', '', s).lower()
        return s
    invalid_emps = [emp for emp in employees if _normalize(emp) not in valid_nicknames]
    
    if invalid_emps:
        err_reply = await message.reply_text(f"❌ Sai tên nhân viên: {', '.join(invalid_emps)}.\nVui lòng kiểm tra lại chính tả hoặc báo Quản lý thêm tên vào danh sách (Sheet SoDuThuong) trước khi báo cáo.")
        track_message(context, message.message_id)
        track_message(context, err_reply.message_id)
        return

    reward_count = check_reward_eligibility(len(employees), revenue)

    # Tự động lưu báo cáo vào Sheet (không cần duyệt)
    now = datetime.now()
    date_str = now.strftime("%d/%m/%Y")
    
    status_msg = await message.reply_text("⏳ Đang lưu báo cáo...")
    track_message(context, message.message_id)
    track_message(context, status_msg.message_id)

    # Lưu báo cáo vào sheet trong thread riêng
    success = await asyncio.to_thread(
        sheets_service.save_report,
        date=date_str,
        employees=", ".join(employees),
        revenue=revenue,
        ca=ca
    )

    if not success:
        await status_msg.edit_text("❌ Lỗi khi lưu báo cáo. Hãy thử lại!")
        return

    # Cộng thưởng nếu đạt chỉ tiêu
    if reward_count > 0:
        for emp in employees:
            await asyncio.to_thread(sheets_service.update_balance, emp, reward_count)

    # Gửi xác nhận đến group
    confirm_msg = f"✅ **ĐÃ GHI NHẬN BÁO CÁO**\n"
    confirm_msg += f"👥 Nhân viên: {', '.join(employees)}\n"
    confirm_msg += f"💰 Doanh thu: {revenue:,} VNĐ\n"
    if reward_count > 0:
        confirm_msg += f"🎁 Cộng {reward_count} ly thưởng cho mỗi bạn\n"
    # FIX VẤN ĐỀ 4: Hiển thị ca luôn luôn (kể cả khi cà được tự động phát hiện từ giờ)
    if not ca:
        now_inner = datetime.now()
        if now_inner.hour < 12:
            ca = 'Sáng'
        elif now_inner.hour < 18:
            ca = 'Chiều'
        else:
            ca = 'Tối'
    confirm_msg += f"⏰ Ca: {ca}"

    try:
        await status_msg.delete()
        # BUG-07 FIX: dùng .get() để tránh KeyError nếu 'to_delete' chưa tồn tại
        context.chat_data.get('to_delete', set()).discard(status_msg.message_id)
    except:
        pass

    confirm_sent = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=confirm_msg,
        parse_mode='Markdown',
        reply_to_message_id=message.message_id
    )
    track_message(context, confirm_sent.message_id)