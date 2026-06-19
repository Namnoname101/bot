import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes
from utils.decorators import admin_only
from utils.validators import deduplicate_employees

logger = logging.getLogger(__name__)

@admin_only
async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi Quản lý bấm Duyệt / Từ chối"""
    query = update.callback_query
    await query.answer() # Phản hồi ngay cho Telegram để hết hiệu ứng "loading" ở nút

    action, report_id = query.data.split('_', 1)
    
    temp_reports = context.bot_data.get('temp_reports', {})
    report_data = temp_reports.get(report_id)

    if not report_data:
        await query.edit_message_text("❌ Báo cáo này đã được xử lý hoặc đã hết hạn (bot khởi động lại).")
        return

    sheets_service = context.bot_data['sheets']
    group_chat_id = report_data['group_chat_id']
    group_msg_id = report_data['group_msg_id']
    employees = [e.strip() for e in report_data['employees'].split(',')]
    # Loại bỏ nhân viên trùng lặp
    employees = deduplicate_employees(employees)

    if action == 'approve':
        # Lưu vào Sheet Lịch sử (chạy trong thread riêng để tránh block Event Loop)
        success = await asyncio.to_thread(
            sheets_service.save_report,
            date=report_data['date'],
            employees=report_data['employees'],
            revenue=report_data['revenue'],
            ca=report_data.get('ca')
        )

        if success:
            reward_count = report_data['reward_count']
            if reward_count > 0:
                # Cập nhật số dư cho mỗi nhân viên trong thread riêng
                for emp in employees:
                    await asyncio.to_thread(
                        sheets_service.update_balance,
                        emp,
                        reward_count
                    )

            await query.edit_message_text(f"✅ ĐÃ DUYỆT BÁO CÁO.\nNhân viên: {report_data['employees']}\nDoanh thu: {report_data['revenue']:,} VNĐ")
            msg_to_group = f"🎉 **Quản lý đã DUYỆT báo cáo!**\nDoanh thu: {report_data['revenue']:,} VNĐ"
            if reward_count > 0:
                msg_to_group += f"\n🎁 Cộng {reward_count} ly thưởng cho mỗi bạn: {report_data['employees']}."
            await context.bot.send_message(chat_id=group_chat_id, text=msg_to_group, parse_mode='Markdown', reply_to_message_id=group_msg_id)
        else:
            await query.edit_message_text("❌ Có lỗi xảy ra khi lưu dữ liệu vào Google Sheets.")
            await context.bot.send_message(chat_id=group_chat_id, text="❌ Quản lý đã duyệt nhưng bot gặp lỗi khi lưu dữ liệu. Báo IT kiểm tra lại!")
    
    elif action == 'reject':
        await query.edit_message_text(f"❌ ĐÃ TỪ CHỐI BÁO CÁO.\nNhân viên: {report_data['employees']}")
        await context.bot.send_message(chat_id=group_chat_id, text="❌ **Báo cáo của bạn đã bị Quản lý TỪ CHỐI!** Vui lòng kiểm tra lại.", parse_mode='Markdown', reply_to_message_id=group_msg_id)

    # Xóa dữ liệu tạm để giải phóng bộ nhớ
    del temp_reports[report_id]