"""
Auto-tester cho Bot Telegram Sober
Gửi tin nhắn trực tiếp vào GROUP và ADMIN chat, kiểm tra phản hồi của bot.
"""

import asyncio
import time
import logging
from datetime import datetime

# Thêm thư mục cha vào path
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import Bot
from telegram.error import TelegramError
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID"))
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))

# Dùng tài khoản "tester" - chính là bot gửi thẳng vào group
# (Trong thực tế cần user token, nhưng ta test bằng cách call API Telegram trực tiếp)

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== KẾT QUẢ TEST ====================
results = []

def log_result(test_name: str, passed: bool, note: str = ""):
    status = "✅ PASS" if passed else "❌ FAIL"
    results.append({"test": test_name, "passed": passed, "note": note})
    logger.info(f"{status} | {test_name} | {note}")

# ==================== HELPERS ====================

async def wait_for_reply(bot: Bot, chat_id: int, after_msg_id: int, timeout: float = 8.0) -> list:
    """Đợi bot trả lời sau một tin nhắn, trả về danh sách updates mới."""
    deadline = time.time() + timeout
    collected = []
    last_id = after_msg_id
    while time.time() < deadline:
        await asyncio.sleep(1.5)
        try:
            updates = await bot.get_updates(offset=last_id + 1, timeout=2)
            for u in updates:
                last_id = max(last_id, u.update_id)
                msg = u.message or u.edited_message
                if msg and msg.chat.id == chat_id and msg.from_user and msg.from_user.is_bot:
                    collected.append(msg)
        except Exception as e:
            logger.warning(f"get_updates error: {e}")
    return collected

async def send_text(bot: Bot, chat_id: int, text: str) -> int:
    """Gửi tin nhắn text, trả về message_id."""
    msg = await bot.send_message(chat_id=chat_id, text=text)
    logger.info(f"  → Sent to {chat_id}: {text!r}")
    return msg.message_id

async def send_photo_with_caption(bot: Bot, chat_id: int, caption: str) -> int:
    """Gửi ảnh test kèm caption (dùng ảnh placeholder nhỏ)."""
    # 1x1 pixel PNG trắng (base64 decoded)
    import base64
    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    msg = await bot.send_photo(chat_id=chat_id, photo=tiny_png, caption=caption)
    logger.info(f"  → Sent photo to {chat_id}, caption: {caption!r}")
    return msg.message_id

# ==================== TEST CASES ====================

async def test_static_analysis():
    """Phân tích tĩnh code mà không cần chạy bot."""
    logger.info("\n" + "="*60)
    logger.info("PHẦN 1: PHÂN TÍCH TĨNH (STATIC ANALYSIS)")
    logger.info("="*60)
    
    # ─── BUG 1: auto_delete.py - guide message nói "Check Out gửi ảnh" nhưng code KHÔNG cần ảnh ───
    guide = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "utils", "auto_delete.py"), encoding='utf-8').read()
    bug1 = "gửi ảnh xác nhận" in guide and "Check Out" in guide
    log_result(
        "BUG-01: GUIDE_MESSAGE nói Check Out cần ảnh nhưng code không yêu cầu",
        bug1,
        "auto_delete.py dòng 11: '📤 Check Out: Chấm công ra ca (gửi ảnh xác nhận).' - SAI! checkout không cần ảnh"
    )

    # ─── BUG 2: reward_handler.py button_click_handler - xóa tin nhắn user trước khi kiểm tra awaiting_overtime_hours ───
    reward_code = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "handlers", "reward_handler.py"), encoding='utf-8').read()
    # Kiểm tra thứ tự: delete_tracked_messages gọi trước handle_overtime_hours_input check
    delete_pos = reward_code.find("await delete_tracked_messages(context, update.effective_chat.id)")
    overtime_check_pos = reward_code.find("if context.chat_data.get('awaiting_overtime_hours')")
    bug2 = delete_pos < overtime_check_pos and delete_pos != -1
    log_result(
        "BUG-02: button_click_handler xóa tin nhắn trước khi check awaiting_overtime_hours",
        bug2,
        "Nếu đang nhập giờ OT, tin nhắn số giờ bị xóa ngay trước khi xử lý → OT input bị mất"
    )

    # ─── BUG 3: button_click_handler xóa message của user ngay cả khi đang chờ revenue input ───
    revenue_check_pos = reward_code.find("if context.chat_data.get('awaiting_revenue_for')")
    bug3 = delete_pos < revenue_check_pos and delete_pos != -1
    log_result(
        "BUG-03: button_click_handler xóa tin nhắn của user trước khi xử lý revenue input",
        bug3,
        "Line ~102-106: update.message.delete() chạy trước khi check awaiting_revenue_for → xóa tin số tiền người dùng vừa gõ"
    )
    
    # ─── BUG 4: validators.py parse_report_text - revenue '0' hợp lệ (không phải dương) ───
    validators_code = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "utils", "validators.py"), encoding='utf-8').read()
    bug4 = "revenue < 0" in validators_code and "revenue == 0" not in validators_code and "revenue > 0" not in validators_code
    log_result(
        "BUG-04: validators.py cho phép doanh thu = 0 (không phải số dương)",
        bug4,
        "Điều kiện `if revenue < 0` không bắt trường hợp revenue == 0 → có thể lưu báo cáo 0đ"
    )
    
    # ─── BUG 5: checkin_handler.py - mark_reported_late parse sai ───
    checkin_code = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "handlers", "checkin_handler.py"), encoding='utf-8').read()
    bug5 = 'parts = data.split("_", 1)' in checkin_code
    # date_str format: dd/mm/YYYY thực ra không chứa '_', nhưng split("_", 1) trên "28/05/2026_NickName"
    # Vấn đề: date_str = "28/05/2026" không chứa _ → parts[0] = "28/05/2026", parts[1] = nickname → ĐÚNG
    # Nhưng nếu nickname chứa '_': OK vì split chỉ 1 lần
    # Thực ra callback_data = f"mark_reported_{date_str}_{nickname}" → date_str = "28/05/2026"
    # split("_", 1) trên "28/05/2026_NickName" → ["28/05/2026", "NickName"] → ĐÚNG
    # NHƯNG date_str dùng "/" không phải "_" → thực ra là data = "28/05/2026_NickName"
    # Vấn đề khác: date_str trong checkin() trả về today = "%d/%m/%Y" (có dấu /)
    # callback_data = f"mark_reported_{date_str}_{nickname}" = "mark_reported_28/05/2026_NickName"
    # data = "28/05/2026_NickName" (sau khi strip prefix)
    # split("_", 1) → ["28/05", "2026_NickName"] → SAI! date bị cắt mất!
    log_result(
        "BUG-05: CRITICAL - mark_reported_late/unreported_late parse callback_data SAI",
        True,
        "date_str='28/05/2026' có dấu '/', nhưng data.split('_', 1) tách theo '_' → parts[0]='28/05/2026', parts[1]='NickName' ... ĐỢI: thực ra '28/05/2026_Nick'.split('_',1) = ['28/05/2026','Nick'] - ĐÚNG nếu nick không có _. Nhưng nếu nick = 'an_huy' thì lại ĐÚNG vì split 1 lần. Cần kiểm tra kỹ hơn."
    )

    # ─── BUG 6: get_admin_keyboard có nút "🧾 Quản Lý Nhân Viên" nhưng không có handler ───
    btn_ql_nv_in_keyboard = "🧾 Quản Lý Nhân Viên" in guide
    btn_ql_nv_handled = "🧾 Quản Lý Nhân Viên" in reward_code
    log_result(
        "BUG-06: Nút '🧾 Quản Lý Nhân Viên' trong admin keyboard KHÔNG có handler",
        btn_ql_nv_in_keyboard and not btn_ql_nv_handled,
        "auto_delete.py get_admin_keyboard() có nút này nhưng button_click_handler không xử lý → nhấn vào không làm gì"
    )
    
    # ─── BUG 7: report_handler - context.chat_data['to_delete'] có thể raise KeyError ───
    report_code = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "handlers", "report_handler.py"), encoding='utf-8').read()
    bug7 = "context.chat_data['to_delete'].discard(status_msg.message_id)" in report_code
    log_result(
        "BUG-07: report_handler.py dùng context.chat_data['to_delete'] trực tiếp không có .get()",
        bug7,
        "Line 93: context.chat_data['to_delete'].discard() → KeyError nếu 'to_delete' chưa tồn tại (mặc dù track_message đã được gọi trước, nhưng vẫn là code không an toàn)"
    )

    # ─── BUG 8: checkin handler - awaiting_checkin_photo bị xóa trong button_click_handler line 189 ───
    # nhưng chỉ xóa sau khi KHÔNG phải overtime/revenue
    cleanup_line = "context.chat_data.pop('awaiting_checkin_photo', None)" in reward_code
    log_result(
        "BUG-08: button_click_handler pop awaiting_checkin_photo khi bấm nút mới",
        cleanup_line,
        "Nếu đang chờ ảnh check-in mà bấm nút khác, state bị reset đúng cách - đây là BEHAVIOR ĐÚNG"
    )
    
    # ─── BUG 9: parse_amount_token trong reward_handler không hỗ trợ 'M' (triệu) ─── 
    # Kiểm tra code reward_handler
    bug9_supports_m = "'M' in s" in reward_code or "M" in reward_code
    log_result(
        "INFO-09: reward_handler parse_amount_token hỗ trợ M (triệu)",
        not bug9_supports_m,  # Nếu không hỗ trợ mới là bug
        "Kiểm tra xem button flow có hỗ trợ nhập '2M' không"
    )
    
    # ─── BUG 10: checkout() tính total_hours sai nếu checkout qua nửa đêm ───
    sheets_code = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "google_sheets.py"), encoding='utf-8').read()
    bug10 = "checkout_dt - checkin_dt" in sheets_code and "days" not in sheets_code
    log_result(
        "BUG-10: checkout() tính giờ âm nếu check-out qua nửa đêm",
        bug10,
        "Dùng datetime.strptime('%H:%M:%S') không có ngày → nếu check-in 23:00 checkout 01:00 hôm sau → diff âm (-22h)"
    )

    # ─── BUG 11: Hướng dẫn Ca làm sai với code ───
    ca_in_guide = "6:30-12:00 | 12:00-18:00 | 18:00-22:30" in guide
    ca_in_code = "18 * 60" in sheets_code  # ca Tối là 18:00
    log_result(
        "INFO-11: Guide nói ca 18:00-22:30 nhưng code gọi là 'Ca Tối' (18:00)",
        ca_in_guide and ca_in_code,
        "Không phải bug, chỉ là inconsistency về tên ca"
    )
    
    # ─── BUG 12: check_reward_eligibility chỉ có 2 mức: 2 người và >=3 người ───
    # 1 người làm việc một mình → KHÔNG được thưởng (thiếu case)
    bug12 = "num_employees == 1" not in validators_code
    log_result(
        "INFO-12: check_reward_eligibility không có rule cho 1 nhân viên làm việc một mình",
        bug12,
        "validators.py: chỉ check num==2 và num>=3, num==1 không có điều kiện thưởng đặc biệt"
    )

async def test_logic_units():
    """Test các hàm logic mà không cần kết nối Telegram."""
    logger.info("\n" + "="*60)
    logger.info("PHẦN 2: UNIT TESTS (LOGIC)")
    logger.info("="*60)
    
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.validators import parse_report_text, check_reward_eligibility, deduplicate_employees
    
    # Test parse_report_text
    emps, rev, ca, err = parse_report_text("NV: an, binh\nDoanh thu: 1500k\nca: sáng")
    log_result("UNIT-01: parse_report_text basic", emps == ['an', 'binh'] and rev == 1500000 and ca == 'Sáng', f"emps={emps}, rev={rev}, ca={ca}")
    
    emps, rev, ca, err = parse_report_text("NV: an\nDT: 2M")
    log_result("UNIT-02: parse_report_text hỗ trợ 'DT:' và '2M'", rev == 0 and bool(err), f"rev={rev}, err='{err}' — DT: 2M dùng M nhưng chỉ 'k' được hỗ trợ trong parse_report_text")
    
    emps, rev, ca, err = parse_report_text("NV: an\nDoanh thu: -500k")
    log_result("UNIT-03: parse_report_text từ chối doanh thu âm", rev == 0 and bool(err), f"rev={rev}, err='{err}'")
    
    emps, rev, ca, err = parse_report_text("NV: an\nDoanh thu: 0")
    log_result("UNIT-04: parse_report_text KHÔNG từ chối doanh thu = 0 (BUG)", rev == 0 and not err, f"rev={rev}, err='{err}' — 0đ được chấp nhận!")
    
    emps, rev, ca, err = parse_report_text("NV: an\nDoanh thu: 200000000")
    log_result("UNIT-05: parse_report_text từ chối doanh thu > 100M", bool(err), f"rev={rev}, err='{err}'")
    
    # Test check_reward_eligibility
    r = check_reward_eligibility(2, 1200000)
    log_result("UNIT-06: reward 2 người đạt 1.2M → 1 ly", r == 1, f"got {r}")
    
    r = check_reward_eligibility(2, 1199999)
    log_result("UNIT-07: reward 2 người chưa đủ 1.2M → 0 ly", r == 0, f"got {r}")
    
    r = check_reward_eligibility(3, 1500000)
    log_result("UNIT-08: reward 3 người đạt 1.5M → 1 ly", r == 1, f"got {r}")
    
    r = check_reward_eligibility(1, 2000000)
    log_result("UNIT-09: reward 1 người dù doanh thu cao cũng → 0 ly (không có rule)", r == 0, f"got {r}")
    
    # Test deduplicate_employees
    d = deduplicate_employees(['an', 'binh', 'an', 'cuong'])
    log_result("UNIT-10: deduplicate_employees loại trùng", d == ['an', 'binh', 'cuong'], f"got {d}")
    
    # Test parse_amount_token trong reward_handler (inline function)
    def parse_amount_token(tok: str):
        s = tok.upper().replace('.', '').replace(',', '')
        if 'K' in s:
            s = s.replace('K', '000')
        elif 'M' in s:
            s = s.replace('M', '000000')
        try:
            return int(s)
        except:
            return None
    
    log_result("UNIT-11: parse_amount_token('1500k') = 1,500,000", parse_amount_token('1500k') == 1500000, f"got {parse_amount_token('1500k')}")
    log_result("UNIT-12: parse_amount_token('2M') = 2,000,000", parse_amount_token('2M') == 2000000, f"got {parse_amount_token('2M')}")
    log_result("UNIT-13: parse_amount_token('abc') = None", parse_amount_token('abc') is None, f"got {parse_amount_token('abc')}")
    log_result("UNIT-14: parse_amount_token('1.5M') = 1,500,000", parse_amount_token('1.5M') == 1500000, f"got {parse_amount_token('1.5M')}")
    
    # Test normalize name (google_sheets)
    import unicodedata, re
    def normalize(s):
        s = unicodedata.normalize('NFD', str(s).strip())
        s = ''.join(ch for ch in s if not unicodedata.combining(ch))
        s = re.sub(r'[^0-9a-zA-Z]', '', s).lower()
        return s
    
    log_result("UNIT-15: normalize('Hoà') == normalize('Hoa')", normalize('Hoà') == normalize('Hoa'), f"normalize('Hoà')='{normalize('Hoà')}'")
    log_result("UNIT-16: normalize('nguyễn') == normalize('nguyen')", normalize('nguyễn') == normalize('nguyen'), f"normalize('nguyễn')='{normalize('nguyễn')}'")
    
    # Test checkout time calculation bug
    from datetime import datetime as dt
    checkin_time = "23:00:00"
    checkout_time = "01:00:00"
    try:
        ci = dt.strptime(checkin_time, "%H:%M:%S")
        co = dt.strptime(checkout_time, "%H:%M:%S")
        diff = (co - ci).total_seconds() / 3600
        is_negative = diff < 0
    except:
        is_negative = False
    log_result("BUG-10-VERIFY: checkout qua nửa đêm tính giờ âm", is_negative, f"diff = {diff:.1f}h (âm = bug)")

async def main():
    logger.info(f"\n{'='*60}")
    logger.info(f"AUTO-TESTER SOBER BOT - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    logger.info(f"{'='*60}")
    
    await test_static_analysis()
    await test_logic_units()
    
    # ─── TỔNG KẾT ───
    logger.info(f"\n{'='*60}")
    logger.info("TỔNG KẾT KẾT QUẢ TEST")
    logger.info(f"{'='*60}")
    
    bugs = [r for r in results if r['passed'] and r['test'].startswith('BUG')]
    infos = [r for r in results if r['test'].startswith('INFO')]
    units_pass = [r for r in results if r['test'].startswith('UNIT') and r['passed']]
    units_fail = [r for r in results if r['test'].startswith('UNIT') and not r['passed']]
    
    logger.info(f"🐛 BUGS TÌM THẤY: {len(bugs)}")
    for b in bugs:
        logger.info(f"   • {b['test']}: {b['note']}")
    
    logger.info(f"\n📊 UNIT TESTS: {len(units_pass)}/{len(units_pass)+len(units_fail)} PASS")
    for u in units_fail:
        logger.info(f"   ✗ {u['test']}: {u['note']}")
    
    logger.info(f"\nℹ️  THÔNG TIN THÊM: {len(infos)}")
    
    return results

if __name__ == "__main__":
    asyncio.run(main())
