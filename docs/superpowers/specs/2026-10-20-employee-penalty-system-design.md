# Đặc Tả Kỹ Thuật (Spec): Hệ Thống Phạt Kỷ Luật & Trừ Lương Tự Động (10k/lần)

## 1. Tổng Quan & Mục Tiêu

### 1.1 Bối cảnh
Trước đây, quán áp dụng mức trừ 10k/lần cho các ca đi muộn. Tuy nhiên, các lỗi vi phạm kỷ luật khác (như làm vỡ đồ, quên tắt thiết bị, đồng phục sai quy định, vi phạm quy trình phục vụ...) chưa có kênh ghi nhận chuẩn hóa, dẫn đến việc quản lý phải ghi chú thủ công hoặc nhắc nhở rời rạc.

### 1.2 Mục tiêu
1. **Thao tác nhanh trên Bot Telegram:** Quản lý bấm nút phạt, chọn nhân viên từ danh sách, nhập lý do; hệ thống tự động ghi nhận mức phạt cố định **10.000đ/lần**.
2. **Minh bạch công khai:** Tự động gửi thông báo kỷ luật vào nhóm Telegram của quán ngay khi phạt.
3. **Trừ lương tự động:** Tự động tổng hợp số tiền phạt trong kỳ lương (17 tháng trước → 16 tháng này) và trừ trực tiếp vào lương thực nhận.
4. **Hiển thị minh bạch trên WebApp:**
   - Nhân viên xem được chi tiết từng lần bị phạt (ngày giờ, lý do, quản lý phạt, số tiền).
   - Có bảng xếp hạng phạt (Leaderboard) theo tháng để nhân viên và quản lý cùng theo dõi.
5. **Lưu trữ & Đồng bộ:** Dữ liệu lưu bền vững trong `store.json` và đồng bộ tự động lên Google Sheets tab `Lịch Sử Phạt`.

---

## 2. Mô Hình Dữ Liệu & Lưu Trữ

### 2.1 Cấu trúc bản ghi Phạt (`penalties` trong `WebAppStore`)
```json
{
  "id": "pen_1729420000_123",
  "created_at": "14:30 20/10/2026",
  "date": "20/10/2026",
  "nickname": "Tuấn",
  "amount": 10000,
  "reason": "Quên tắt máy pha cà phê khi hết ca",
  "admin_name": "Anh Bình"
}
```

### 2.2 Đồng bộ Google Sheets (`services/sheets/sync.py`)
- Tab sheet: `Lịch Sử Phạt`
- Tiêu đề cột (Row 1):
  `["Mã Phạt", "Thời Gian", "Ngày", "Tên Nhân Viên", "Số Tiền", "Lý Do Vi Phạm", "Người Phạt"]`
- Định dạng: Font chuẩn, in đậm header. Khi ghi nhận phạt mới, append 1 dòng vào sheet bất đồng bộ không làm chậm phản hồi bot.

---

## 3. Luồng Hoạt Động & Giao Diện

### 3.1 Bot Telegram (Dành cho Quản Lý)
1. **Khởi tạo:**
   - Trong menu `⚙️ Quản Lý` (`handle_manage_nv_button`), thêm nút:
     `[ ⚠️ Phạt Nhân Viên (10k) ]` (callback_data: `mgmt_fine_list`).
   - Thêm command shortcut: `/phat` (chỉ admin dùng được).
2. **Chọn nhân viên:**
   - Bot hiển thị danh sách nhân viên dạng lưới inline buttons (lấy từ danh sách nhân viên hoạt động).
   - Nút `[ ❌ Hủy ]` để quay lại.
3. **Nhập lý do:**
   - Admin chọn nhân viên `nick`.
   - Bot gửi tin nhắn hướng dẫn:
     > ⚠️ **Lập biên bản phạt: {nick}**
     > 💵 Mức phạt cố định: **10.000đ**
     > 📝 Vui lòng nhập lý do/nội dung vi phạm:
   - Lưu trạng thái `context.user_data['awaiting_penalty_reason'] = {'nickname': nick}`.
4. **Xử lý & Thông báo nhóm:**
   - Admin nhập tin nhắn văn bản lý do.
   - Bot lưu bản ghi phạt vào `store.add_penalty(...)`.
   - Bot phản hồi riêng cho Admin: `✅ Đã lập biên bản phạt 10.000đ cho {nick}!`.
   - Bot gửi thông báo công khai vào Group Chat của quán (`Config.GROUP_CHAT_ID`):
     ```
     ⚠️ THÔNG BÁO KỶ LUẬT VI PHẠM
     👤 Nhân viên: Tuấn
     💸 Mức phạt: 10.000đ (tự động trừ vào lương kỳ này)
     📝 Lý do: Quên tắt máy pha cà phê khi hết ca
     👮 Người lập: Anh Bình
     📅 Thời gian: 14:30 20/10/2026
     ```

### 3.2 Bot Telegram (Tra Cứu & Bảng Xếp Hạng)
1. **Lệnh `/bangphat`:**
   - Hiển thị bảng xếp hạng phạt trong kỳ lương hiện tại:
     ```
     🏆 BẢNG XẾP HẠNG PHẠT THÁNG 10/2026 (17/09 → 16/10)
     🥇 Tuấn: 3 lần — 30.000đ
     🥈 An: 1 lần — 10.000đ
     🥉 Bình: 1 lần — 10.000đ
     ---------------------------
     💰 Tổng tiền phạt toàn quán: 50.000đ
     ```
2. **Lệnh `/xemphat` (hoặc `/xemphat <tên>` cho admin):**
   - Nhân viên xem chi tiết các lần bị phạt của mình.

### 3.3 WebApp (Dành Cho Nhân Viên)
1. **Trang cá nhân (Dashboard NV):**
   - Trong thẻ *Bóc tách lương tạm tính*:
     Thêm dòng hiển thị:
     `⚠️ Phạt kỷ luật (10k/lần): -X0.000đ (X lần)`
   - Trong mục chi tiết hoặc modal:
     Hiển thị bảng/danh sách các lần bị phạt: Ngày, Giờ, Lý do, Người phạt.
2. **Tab Lương cá nhân:**
   - Cung cấp nút xem "🏆 Bảng xếp hạng phạt" toàn quán.

### 3.4 WebApp (Dành Cho Quản Lý)
1. **Tab Bảng Điều Khiển Quán (`tab-admin-overview`):**
   - Thêm widget "Bảng xếp hạng phạt kỷ luật" (Top nhân viên bị phạt nhiều nhất & Tổng quỹ phạt quán).
   - Nút "⚠️ Phạt nhân viên" mở modal nhanh để quản lý có thể phạt trực tiếp từ WebApp.
2. **Tab Quản Lý Công & Lương (`tab-admin-payroll`):**
   - Trong danh sách lương nhân viên, hiển thị rõ cột hoặc chi tiết: `Phạt vi phạm: -X0.000đ`.
   - Công thức Thực nhận cập nhật chuẩn:
     $$\text{Thực nhận} = (\text{Giờ làm} \times \text{Mức lương}) + \text{Thưởng} - \text{Ứng lương} - \text{Phạt đi muộn} - \text{Phạt kỷ luật}$$

---

## 4. API Endpoints Mới & Cập Nhật

1. `GET /api/penalties`
   - Query: `month`, `year`, `nickname` (optional)
   - Trả về danh sách phạt và thống kê xếp hạng (leaderboard).
2. `POST /api/admin/penalties/add`
   - Body: `{ nickname, reason }`
   - Mức phạt cố định tự động gán là `10000`.
   - Trả về bản ghi mới tạo và thông báo thành công.
3. `GET /api/bootstrap` & `GET /api/admin/overview`
   - Bổ sung `penalties_summary` và `personal_penalties`.
4. `GET /api/admin/salary`
   - Bổ sung `penalty_deduction` cho từng nhân viên trong bảng lương.

---

## 5. Kế Hoạch Kiểm Thử (Testing Plan)

1. **Unit Tests (`tests/test_penalties.py`):**
   - Test thêm biên bản phạt với mức cố định 10.000đ.
   - Test lấy danh sách phạt lọc theo kỳ lương (17 tháng trước → 16 tháng này).
   - Test bảng xếp hạng phạt (tính đúng số lần và sắp xếp giảm dần).
   - Test trừ tiền phạt vào bảng lương thực nhận.
   - Test validation: từ chối nếu tên nhân viên rỗng hoặc lý do rỗng.
2. **Integration Tests (`tests/test_webapp.py`):**
   - Test API `POST /api/admin/penalties/add` thành công và yêu cầu quyền Admin.
   - Test API `GET /api/penalties` nhân viên xem được của mình, admin xem được toàn bộ.
3. **Bot Flow Tests:**
   - Test chọn nhân viên từ inline keyboard, nhập lý do, hoàn tất flow và gửi tin nhóm.
