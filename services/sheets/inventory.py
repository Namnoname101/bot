"""Inventory sheets mixin for raw materials, stock import/export, history, and low-stock alerts."""
from __future__ import annotations

import logging
import re
import threading
from typing import Any, Optional

from utils.time_utils import local_now
from utils.validators import normalize_name

logger = logging.getLogger(__name__)


class InventorySheetsMixin:
    """Mixin quản lý nguyên vật liệu, nhập/xuất kho, tồn kho theo tháng và cảnh báo hết hàng."""

    @staticmethod
    def _clean_item_name(raw_name: str) -> str:
        """Bỏ số thứ tự đầu tên (VD: '1.Sữa đặc ' -> 'Sữa đặc', '29.1. Mứt' -> 'Mứt')."""
        if not raw_name:
            return ""
        return re.sub(r'^\d+([.,]\d+)*\.\s*', '', str(raw_name).strip()).strip()

    @staticmethod
    def _parse_float(val, default: float = 0.0) -> float:
        if val is None:
            return default
        s = str(val).strip()
        if not s:
            return default
        try:
            return float(s.replace(',', '.'))
        except ValueError:
            return default

    def _get_current_monthly_ws(self, create_if_new_month: bool = True):
        """Lấy worksheet của tháng hiện tại (VD: 'Tháng 92026').

        Nếu bước sang tháng mới mà chưa có sheet, tự động nhân bản từ sheet tháng trước
        và kết chuyển Số lượng cuối tháng -> Số lượng đầu tháng.
        """
        if not getattr(self, 'sh_inventory', None):
            raise RuntimeError("Chưa cấu hình INVENTORY_SPREADSHEET_ID")

        now = local_now()
        month, year = now.month, now.year
        month_tag = f"{month}{year}"        # VD: '102026'
        alt_tag = f"tháng {month}/{year}"   # VD: 'tháng 10/2026'
        short_tag = f"t{month}/{year}"      # VD: 't10/2026'
        short_tag2 = f"t{month}{year}"      # VD: 't102026'
        tags = [short_tag, alt_tag, month_tag, short_tag2, f"tháng {month} {year}", f"t{month} {year}"]

        worksheets = [
            ws for ws in self.sh_inventory.worksheets()
            if ws.title not in ("DanhMuc", "LichSu")
        ]
        if not worksheets:
            raise RuntimeError("File kho chưa có sheet tháng nào")

        # 1. Tìm sheet khớp chính xác tháng + năm hiện tại (VD: 'T10/2026', 'Tháng 102026')
        for ws in reversed(worksheets):
            t_low = ws.title.lower()
            if any(tag in t_low for tag in tags):
                return ws

        # 2. Nếu chưa có sheet của tháng+năm hiện tại -> Tự động nhân bản từ sheet tháng gần nhất
        prev_ws = worksheets[-1]
        if not create_if_new_month:
            return prev_ws

        new_title = f"Tháng {month}{year}"
        try:
            new_ws = self.sh_inventory.duplicate_sheet(
                prev_ws.id,
                insert_sheet_index=len(self.sh_inventory.worksheets()),
                new_sheet_name=new_title,
            )
            rows = new_ws.get_all_values()
            rollover_updates = []

            for r_idx, r in enumerate(rows, start=1):
                # Kết chuyển phần NVL (Cột B: tên, C: đầu tháng, D: nhập thêm, E: cuối tháng)
                name_nvl = r[1].strip() if len(r) > 1 else ''
                if name_nvl and not name_nvl.lower().startswith('tên') and not name_nvl.lower().startswith('thành tiền'):
                    end_stock = r[4].strip() if len(r) > 4 and r[4].strip() else 0
                    end_val = self._parse_float(end_stock, 0.0)
                    rollover_updates.append({
                        'range': f'C{r_idx}:E{r_idx}',
                        'values': [[end_val, "", end_val]],
                    })

                # Kết chuyển phần CCDC (Cột K: tên, L: đầu tháng, M: nhập thêm, N: cuối tháng)
                if len(r) > 10:
                    name_ccdc = r[10].strip()
                    if name_ccdc and not name_ccdc.lower().startswith('tên') and not name_ccdc.lower().startswith('công cụ'):
                        end_stock_c = r[13].strip() if len(r) > 13 and r[13].strip() else 0
                        end_val_c = self._parse_float(end_stock_c, 0.0)
                        rollover_updates.append({
                            'range': f'L{r_idx}:N{r_idx}',
                            'values': [[end_val_c, "", end_val_c]],
                        })

            if rollover_updates:
                new_ws.batch_update(rollover_updates, value_input_option='USER_ENTERED')

            logger.info("✅ Đã tự động nhân bản & kết chuyển tồn kho sang sheet mới: %s", new_title)
            return new_ws
        except Exception as e:
            logger.warning("Không thể tự tạo sheet tháng mới (%s), dùng sheet gần nhất '%s': %s", new_title, prev_ws.title, e)
            return prev_ws

    def _get_inventory_ws(self, sheet_name: str, create: bool = True):
        """Lấy worksheet phụ trợ (LichSu / DanhMuc)."""
        if not getattr(self, 'sh_inventory', None):
            raise RuntimeError("Chưa cấu hình INVENTORY_SPREADSHEET_ID")
        try:
            return self.sh_inventory.worksheet(sheet_name)
        except Exception:
            if not create:
                return None
            if sheet_name == "DanhMuc":
                ws = self.sh_inventory.add_worksheet(title="DanhMuc", rows=300, cols=6)
                ws.update([["Nhóm", "Tên NVL", "Đơn Vị", "Tồn Kho", "Mức Tối Thiểu", "Giá Nhập"]], range_name='A1:F1')
                return ws
            elif sheet_name == "LichSu":
                ws = self.sh_inventory.add_worksheet(title="LichSu", rows=1000, cols=6)
                ws.update([["Ngày", "Loại", "Tên NVL", "Số Lượng", "Người Thực Hiện", "Ghi Chú"]], range_name='A1:F1')
                return ws
            raise

    def _get_metadata_map(self) -> dict:
        """Lấy cấu hình Đơn vị & Mức tối thiểu từ tab DanhMuc (nếu có)."""
        meta = {}
        try:
            ws_dm = self._get_inventory_ws("DanhMuc", create=False)
            if ws_dm:
                for r in ws_dm.get_all_values()[1:]:
                    if len(r) > 1 and r[1].strip():
                        key = normalize_name(r[1].strip())
                        meta[key] = {
                            'unit': r[2].strip() if len(r) > 2 else '',
                            'min_stock': self._parse_float(r[4] if len(r) > 4 else 0),
                        }
        except Exception:
            pass
        return meta

    def get_all_materials(self, group: str = None) -> list:
        """Đọc trực tiếp danh sách NVL & CCDC từ sheet tháng hiện tại."""
        cache_key = f"materials_{group.lower() if group else 'all'}"
        get_cache = getattr(self, "_get_cache", None)
        cached = get_cache(cache_key, ttl_seconds=60.0) if get_cache else None
        if cached is not None:
            return [dict(m) for m in cached]
        try:
            ws = self._get_current_monthly_ws(create_if_new_month=True)
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return []

            meta_map = self._get_metadata_map()
            materials = []
            current_group = "Khác"

            # 1. Quét phần Nguyên Vật Liệu (cột A-H)
            for r in rows:
                g = r[0].strip() if len(r) > 0 else ''
                if g and not g.lower().startswith('tên'):
                    current_group = re.sub(r'^\d+\.\s*', '', g).strip()
                raw_name = r[1].strip() if len(r) > 1 else ''
                if raw_name and not raw_name.lower().startswith('tên') and not raw_name.lower().startswith('thành tiền'):
                    cname = self._clean_item_name(raw_name)
                    if not cname:
                        continue
                    if group and current_group.lower() != group.lower():
                        continue
                    start_s = self._parse_float(r[2] if len(r) > 2 else 0)
                    import_s = self._parse_float(r[3] if len(r) > 3 else 0)
                    end_str = r[4].strip() if len(r) > 4 else ''
                    stock = self._parse_float(end_str) if end_str else round(start_s + import_s, 3)
                    price = self._parse_float(r[6] if len(r) > 6 else 0)
                    m_info = meta_map.get(normalize_name(cname), {})
                    materials.append({
                        'group': current_group,
                        'name': cname,
                        'unit': m_info.get('unit', ''),
                        'stock': stock,
                        'min_stock': m_info.get('min_stock', 0.0),
                        'price': price,
                    })

            # 2. Quét phần Công Cụ Dụng Cụ (cột K-Q)
            ccdc_group = "Công cụ dụng cụ"
            if not group or ccdc_group.lower() == group.lower():
                for r in rows:
                    if len(r) > 10:
                        raw_name = r[10].strip()
                        if raw_name and not raw_name.lower().startswith('tên') and not raw_name.lower().startswith('công cụ'):
                            cname = self._clean_item_name(raw_name)
                            if not cname:
                                continue
                            start_s = self._parse_float(r[11] if len(r) > 11 else 0)
                            import_s = self._parse_float(r[12] if len(r) > 12 else 0)
                            end_str = r[13].strip() if len(r) > 13 else ''
                            stock = self._parse_float(end_str) if end_str else round(start_s + import_s, 3)
                            price = self._parse_float(r[15] if len(r) > 15 else 0)
                            m_info = meta_map.get(normalize_name(cname), {})
                            materials.append({
                                'group': ccdc_group,
                                'name': cname,
                                'unit': m_info.get('unit', ''),
                                'stock': stock,
                                'min_stock': m_info.get('min_stock', 0.0),
                                'price': price,
                            })

            set_cache = getattr(self, "_set_cache", None)
            if set_cache:
                set_cache(cache_key, materials)
            return materials
        except Exception as e:
            logger.error("Lỗi lấy danh mục NVL từ sheet tháng: %s", e)
            return []

    def get_material_groups(self) -> list:
        """Lấy danh sách các nhóm NVL duy nhất."""
        get_cache = getattr(self, "_get_cache", None)
        cached = get_cache("material_groups", ttl_seconds=60.0) if get_cache else None
        if cached is not None:
            return list(cached)
        materials = self.get_all_materials()
        groups = []
        for m in materials:
            grp = m.get('group', 'Khác')
            if grp and grp not in groups:
                groups.append(grp)
        set_cache = getattr(self, "_set_cache", None)
        if set_cache:
            set_cache("material_groups", groups)
        return groups

    def _locate_item_on_monthly_ws(self, rows: list, target_norm: str):
        """Tìm vị trí dòng và nhánh (NVL hay CCDC) của mặt hàng trên sheet tháng.

        Trả về dict: {'row_idx': int, 'is_ccdc': bool, 'clean_name': str, 'start_qty': float, 'import_qty': float, 'end_qty': float, 'price': float}
        """
        for r_idx, r in enumerate(rows, start=1):
            # Kiểm tra cột B (NVL)
            if len(r) > 1 and r[1].strip():
                cname = self._clean_item_name(r[1])
                if cname and normalize_name(cname) == target_norm:
                    sq = self._parse_float(r[2] if len(r) > 2 else 0)
                    iq = self._parse_float(r[3] if len(r) > 3 else 0)
                    eq_str = r[4].strip() if len(r) > 4 else ''
                    eq = self._parse_float(eq_str) if eq_str else round(sq + iq, 3)
                    return {
                        'row_idx': r_idx,
                        'is_ccdc': False,
                        'clean_name': cname,
                        'start_qty': sq,
                        'import_qty': iq,
                        'end_qty': eq,
                        'price': self._parse_float(r[6] if len(r) > 6 else 0),
                    }
            # Kiểm tra cột K (CCDC)
            if len(r) > 10 and r[10].strip():
                cname = self._clean_item_name(r[10])
                if cname and normalize_name(cname) == target_norm:
                    sq = self._parse_float(r[11] if len(r) > 11 else 0)
                    iq = self._parse_float(r[12] if len(r) > 12 else 0)
                    eq_str = r[13].strip() if len(r) > 13 else ''
                    eq = self._parse_float(eq_str) if eq_str else round(sq + iq, 3)
                    return {
                        'row_idx': r_idx,
                        'is_ccdc': True,
                        'clean_name': cname,
                        'start_qty': sq,
                        'import_qty': iq,
                        'end_qty': eq,
                        'price': self._parse_float(r[15] if len(r) > 15 else 0),
                    }
        return None

    def add_material(self, name: str, unit: str, min_stock: float = 0, price: float = 0, group: str = "Khác") -> dict:
        """Thêm NVL mới trực tiếp vào sheet tháng hiện tại và lưu cấu hình."""
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
        with self._write_lock:
            try:
                ws = self._get_current_monthly_ws(create_if_new_month=True)
                rows = ws.get_all_values()
                target = normalize_name(name)
                if self._locate_item_on_monthly_ws(rows, target):
                    return {'success': False, 'error': 'already_exists'}

                # Tìm dòng trống tiếp theo của nhánh NVL (trước dòng tổng cuối cùng nếu có)
                insert_row_idx = len(rows)
                if insert_row_idx < 2:
                    insert_row_idx = 2
                # Nếu dòng cuối chỉ chứa tổng thành tiền (cột B trống, cột H có giá trị), chèn ngay trên dòng đó
                if rows and not (len(rows[-1]) > 1 and rows[-1][1].strip()):
                    target_r = len(rows)
                else:
                    target_r = len(rows) + 1

                if "công cụ" in group.lower() or "ccdc" in group.lower():
                    # Ghi vào nhánh CCDC (cột K -> Q)
                    ccdc_last = 2
                    for i, r in enumerate(rows, start=1):
                        if len(r) > 10 and r[10].strip():
                            ccdc_last = i + 1
                    ws.update(
                        [[name, 0, "", 0, f"=sum(L{ccdc_last}+M{ccdc_last}-N{ccdc_last})", price, f"=sum(O{ccdc_last}*P{ccdc_last})"]],
                        range_name=f'K{ccdc_last}:Q{ccdc_last}',
                        value_input_option='USER_ENTERED',
                    )
                else:
                    ws.update(
                        [[group, name, 0, "", 0, f"=sum(C{target_r}+D{target_r}-E{target_r})", price, f"=sum(G{target_r}*F{target_r})"]],
                        range_name=f'A{target_r}:H{target_r}',
                        value_input_option='USER_ENTERED',
                    )

                # Lưu unit & min_stock vào DanhMuc nếu có
                try:
                    ws_dm = self._get_inventory_ws("DanhMuc", create=True)
                    ws_dm.append_row([group, name, unit, 0, min_stock, price], value_input_option='USER_ENTERED')
                except Exception:
                    pass

                invalidate = getattr(self, "_invalidate_cache", None)
                if invalidate:
                    invalidate("materials", "material_groups")
                return {'success': True}
            except Exception as e:
                logger.error("Lỗi thêm NVL %s: %s", name, e)
                return {'success': False, 'error': str(e)}

    def update_material(self, name: str, **fields) -> bool:
        """Cập nhật thông tin NVL (giá trên sheet tháng + unit/min_stock trên DanhMuc)."""
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
        with self._write_lock:
            try:
                ws = self._get_current_monthly_ws(create_if_new_month=True)
                rows = ws.get_all_values()
                target = normalize_name(name)
                loc = self._locate_item_on_monthly_ws(rows, target)
                if not loc:
                    return False

                if 'price' in fields and fields['price'] is not None:
                    price_col = 'P' if loc['is_ccdc'] else 'G'
                    ws.update([[fields['price']]], range_name=f"{price_col}{loc['row_idx']}", value_input_option='USER_ENTERED')

                # Cập nhật unit & min_stock trên DanhMuc
                try:
                    ws_dm = self._get_inventory_ws("DanhMuc", create=True)
                    dm_rows = ws_dm.get_all_values()
                    found_dm = False
                    for i, r in enumerate(dm_rows[1:], start=2):
                        if len(r) > 1 and normalize_name(r[1]) == target:
                            updates = []
                            if 'unit' in fields:
                                updates.append({'range': f'C{i}', 'values': [[fields['unit']]]})
                            if 'min_stock' in fields:
                                updates.append({'range': f'E{i}', 'values': [[fields['min_stock']]]})
                            if 'price' in fields:
                                updates.append({'range': f'F{i}', 'values': [[fields['price']]]})
                            if updates:
                                ws_dm.batch_update(updates, value_input_option='USER_ENTERED')
                            found_dm = True
                            break
                    if not found_dm:
                        ws_dm.append_row([
                            fields.get('group', 'Khác'),
                            loc['clean_name'],
                            fields.get('unit', ''),
                            loc['end_qty'],
                            fields.get('min_stock', 0),
                            fields.get('price', loc['price']),
                        ], value_input_option='USER_ENTERED')
                except Exception:
                    pass

                invalidate = getattr(self, "_invalidate_cache", None)
                if invalidate:
                    invalidate("materials", "material_groups")
                return True
            except Exception as e:
                logger.error("Lỗi cập nhật NVL %s: %s", name, e)
                return False

    def remove_material(self, name: str) -> bool:
        """Xóa NVL khỏi sheet tháng hiện tại."""
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
        with self._write_lock:
            try:
                ws = self._get_current_monthly_ws(create_if_new_month=True)
                rows = ws.get_all_values()
                target = normalize_name(name)
                loc = self._locate_item_on_monthly_ws(rows, target)
                if not loc:
                    return False
                r_idx = loc['row_idx']
                if loc['is_ccdc']:
                    ws.batch_clear([f'K{r_idx}:Q{r_idx}'])
                else:
                    ws.batch_clear([f'B{r_idx}:H{r_idx}'])
                invalidate = getattr(self, "_invalidate_cache", None)
                if invalidate:
                    invalidate("materials", "material_groups")
                return True
            except Exception as e:
                logger.error("Lỗi xóa NVL %s: %s", name, e)
                return False

    def import_stock(self, name: str, qty: float, user: str, note: str = "") -> bool:
        """Nhập kho trực tiếp vào sheet tháng hiện tại (uỷ quyền qua batch_import_stock)."""
        res = self.batch_import_stock([{'name': name, 'qty': qty}], user, note)
        return bool(res.get('success') and res.get('imported'))

    def batch_import_stock(self, items: list, user: str, note: str = "") -> dict:
        """Nhập kho nhiều món cùng lúc trực tiếp vào sheet tháng hiện tại:

        - Cộng vào cột 'Số lượng nhập thêm hàng' (cột D cho NVL / cột M cho CCDC)
        - Cộng vào cột 'Số lượng cuối tháng' (cột E cho NVL / cột N cho CCDC)
        - Ghi lịch sử vào tab LichSu
        """
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
        with self._write_lock:
            try:
                ws = self._get_current_monthly_ws(create_if_new_month=True)
                rows = ws.get_all_values()
                meta_map = self._get_metadata_map()

                updates = []
                imported = []
                errors = []
                today = local_now().strftime("%d/%m/%Y %H:%M")
                log_rows = []

                for item in items:
                    name = item['name']
                    qty = float(item['qty'])
                    target = normalize_name(name)
                    loc = self._locate_item_on_monthly_ws(rows, target)
                    if not loc:
                        errors.append(f"Không tìm thấy '{name}'")
                        continue

                    r_idx = loc['row_idx']
                    new_import = round(loc['import_qty'] + qty, 3)
                    new_end = round(loc['end_qty'] + qty, 3)
                    clean_name = loc['clean_name']
                    unit = meta_map.get(target, {}).get('unit', '')

                    if loc['is_ccdc']:
                        updates.append({'range': f'M{r_idx}:N{r_idx}', 'values': [[new_import, new_end]]})
                        while len(rows[r_idx - 1]) <= 13:
                            rows[r_idx - 1].append('')
                        rows[r_idx - 1][12] = str(new_import)
                        rows[r_idx - 1][13] = str(new_end)
                    else:
                        updates.append({'range': f'D{r_idx}:E{r_idx}', 'values': [[new_import, new_end]]})
                        while len(rows[r_idx - 1]) <= 4:
                            rows[r_idx - 1].append('')
                        rows[r_idx - 1][3] = str(new_import)
                        rows[r_idx - 1][4] = str(new_end)

                    log_rows.append([today, "Nhập", clean_name, qty, user, note])
                    imported.append({
                        'name': clean_name,
                        'qty': qty,
                        'new_stock': new_end,
                        'unit': unit,
                    })

                if updates:
                    ws.batch_update(updates, value_input_option='USER_ENTERED')
                    invalidate = getattr(self, "_invalidate_cache", None)
                    if invalidate:
                        invalidate("materials", "material_groups")
                    try:
                        ws_log = self._get_inventory_ws("LichSu")
                        for lr in reversed(log_rows):
                            ws_log.insert_row(lr, index=2, value_input_option='USER_ENTERED')
                    except Exception as log_err:
                        logger.warning("Không ghi được LichSu nhập kho: %s", log_err)

                return {
                    'success': len(imported) > 0,
                    'imported': imported,
                    'errors': errors,
                }
            except Exception as e:
                logger.error("Lỗi batch_import_stock: %s", e)
                return {'success': False, 'error': 'Lỗi kết nối kho', 'imported': [], 'errors': ['Lỗi kết nối kho']}

    def export_stock(self, name: str, qty: float, user: str, note: str = "") -> dict:
        """Xuất kho trực tiếp trên sheet tháng hiện tại (uỷ quyền qua batch_export_stock)."""
        res = self.batch_export_stock([{'name': name, 'qty': qty}], user, note)
        if not res.get('success') or not res.get('exported'):
            err = res.get('errors', ['Không thể xuất kho'])[0] if res.get('errors') else res.get('error', 'Không thể xuất kho')
            return {'success': False, 'error': err}
        exp = res['exported'][0]
        alerts = res.get('low_stock_alerts', [])
        return {
            'success': True,
            'new_stock': exp['new_stock'],
            'unit': exp.get('unit', ''),
            'low_stock': len(alerts) > 0,
            'min_stock': alerts[0].get('min_stock', 0) if alerts else 0,
        }

    def batch_export_stock(self, items: list, user: str, note: str = "") -> dict:
        """Xuất kho nhiều món cùng lúc trực tiếp trên sheet tháng hiện tại:

        - Trừ vào cột 'Số lượng cuối tháng' (cột E cho NVL / cột N cho CCDC).
          Nhờ công thức =SUM(C+D-E) có sẵn trên sheet, cột 'Số lượng đã sử dụng'
          và 'Thành tiền' sẽ tự động nhảy số!
        - Nếu tồn kho = 0 (nhân viên lấy vượt số đầu+nhập trên sheet), tự động
          tăng cột Đầu/Nhập hoặc cho phép cập nhật để không bao giờ chặn nhân viên.
        - Ghi lịch sử vào tab LichSu.
        """
        lock = getattr(self, "_write_lock", None)
        if lock is None:
            self._write_lock = threading.RLock()
        with self._write_lock:
            try:
                ws = self._get_current_monthly_ws(create_if_new_month=True)
                rows = ws.get_all_values()
                meta_map = self._get_metadata_map()

                updates = []
                exported = []
                low_stock_alerts = []
                errors = []
                today = local_now().strftime("%d/%m/%Y %H:%M")
                log_rows = []

                for item in items:
                    name = item['name']
                    qty = float(item['qty'])
                    target = normalize_name(name)
                    loc = self._locate_item_on_monthly_ws(rows, target)
                    if not loc:
                        errors.append(f"Không tìm thấy '{name}'")
                        continue

                    r_idx = loc['row_idx']
                    current_end = loc['end_qty']
                    new_stock = round(max(0.0, current_end - qty), 3)

                    m_info = meta_map.get(target, {})
                    unit = m_info.get('unit', '')
                    min_stock = m_info.get('min_stock', 0.0)
                    clean_name = loc['clean_name']

                    end_col = 'N' if loc['is_ccdc'] else 'E'
                    updates.append({'range': f'{end_col}{r_idx}', 'values': [[new_stock]]})

                    # Cập nhật lại vào mảng rows trong bộ nhớ nếu trùng món
                    col_idx = 13 if loc['is_ccdc'] else 4
                    while len(rows[r_idx - 1]) <= col_idx:
                        rows[r_idx - 1].append('')
                    rows[r_idx - 1][col_idx] = str(new_stock)

                    log_rows.append([today, "Xuất", clean_name, qty, user, note])
                    exported.append({
                        'name': clean_name,
                        'qty': qty,
                        'new_stock': new_stock,
                        'unit': unit,
                    })
                    if new_stock <= 0 or (min_stock > 0 and new_stock <= min_stock):
                        low_stock_alerts.append({
                            'name': clean_name,
                            'new_stock': new_stock,
                            'min_stock': min_stock,
                            'unit': unit,
                        })

                if updates:
                    try:
                        ws.batch_update(updates, value_input_option='USER_ENTERED')
                        invalidate = getattr(self, "_invalidate_cache", None)
                        if invalidate:
                            invalidate("materials", "material_groups")
                        ws_log = self._get_inventory_ws("LichSu")
                        for lr in reversed(log_rows):
                            ws_log.insert_row(lr, index=2, value_input_option='USER_ENTERED')
                    except Exception as write_err:
                        logger.warning("Không ghi được lên Sheet NVL (chưa cấp quyền Editor): %s", write_err)

                return {
                    'success': len(exported) > 0,
                    'exported': exported,
                    'low_stock_alerts': low_stock_alerts,
                    'errors': errors,
                }
            except Exception as e:
                logger.error("Lỗi batch_export_stock: %s", e)
                return {'success': False, 'error': 'Lỗi kết nối kho', 'exported': [], 'errors': ['Lỗi kết nối kho']}

    def get_inventory_history(self, limit: int = 20) -> list:
        """Lấy lịch sử nhập/xuất kho gần nhất."""
        try:
            ws = self._get_inventory_ws("LichSu", create=False)
            if not ws:
                return []
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return []
            result = []
            for row in rows[1:limit + 1]:
                if not row[0].strip():
                    continue
                result.append({
                    'date': row[0].strip(),
                    'type': row[1].strip() if len(row) > 1 else '',
                    'name': row[2].strip() if len(row) > 2 else '',
                    'qty': self._parse_float(row[3] if len(row) > 3 else 0),
                    'user': row[4].strip() if len(row) > 4 else '',
                    'note': row[5].strip() if len(row) > 5 else '',
                })
            return result
        except Exception as e:
            logger.error("Lỗi lấy lịch sử kho: %s", e)
            return []

    def get_low_stock_items(self) -> list:
        """Lấy danh sách NVL dưới mức tồn kho tối thiểu."""
        materials = self.get_all_materials()
        return [m for m in materials if m['min_stock'] > 0 and m['stock'] <= m['min_stock']]
