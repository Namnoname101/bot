"""Google Sheets facade service maintaining 100% backward compatibility."""
from __future__ import annotations

import logging
import sys
import types

from services.sheets.admin import AdminSheetsMixin
from services.sheets.attendance import AttendanceSheetsMixin
from services.sheets.base import BaseSheetsService
from services.sheets.inventory import InventorySheetsMixin
from services.sheets.revenue import RevenueSheetsMixin
from services.sheets.reward import RewardSheetsMixin
from services.sheets.salary import SalarySheetsMixin
from services.sheets.sync import SyncSheetsMixin
from utils.time_utils import local_now
from utils.validators import normalize_name as _normalize_name_for_comparison

logger = logging.getLogger(__name__)

__all__ = [
    "GoogleSheetsService",
    "_normalize_name_for_comparison",
]


class GoogleSheetsService(
    BaseSheetsService,
    AttendanceSheetsMixin,
    RevenueSheetsMixin,
    AdminSheetsMixin,
    RewardSheetsMixin,
    SalarySheetsMixin,
    InventorySheetsMixin,
    SyncSheetsMixin,
):
    """Facade class tương thích ngược hoàn toàn với hệ thống cũ.

    Kế thừa BaseSheetsService (quản lý kết nối, cache, custom sheets)
    và 7 domain mixins từ services/sheets/.
    """
    pass


# Tương thích ngược với unittest.mock.patch('google_sheets.local_now', ...) trong test suites
class _GoogleSheetsModule(types.ModuleType):
    def __setattr__(self, name: str, value: object):
        super().__setattr__(name, value)
        if name == "local_now":
            import services.sheets.admin as _adm
            import services.sheets.attendance as _att
            import services.sheets.inventory as _inv
            import services.sheets.revenue as _rev
            import services.sheets.reward as _rew
            import services.sheets.salary as _sal
            import services.sheets.sync as _syn

            for mod in (_adm, _att, _inv, _rev, _rew, _sal, _syn):
                setattr(mod, "local_now", value)


sys.modules[__name__].__class__ = _GoogleSheetsModule
