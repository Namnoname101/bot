"""Tests verifying the GoogleSheetsService Facade and backward compatibility."""
import threading
from datetime import date, datetime
import unittest

import google_sheets
from google_sheets import GoogleSheetsService, _normalize_name_for_comparison

from services.sheets.admin import AdminSheetsMixin
from services.sheets.attendance import AttendanceSheetsMixin
from services.sheets.base import BaseSheetsService
from services.sheets.inventory import InventorySheetsMixin
from services.sheets.revenue import RevenueSheetsMixin
from services.sheets.reward import RewardSheetsMixin
from services.sheets.salary import SalarySheetsMixin
from services.sheets.sync import SyncSheetsMixin


class TestGoogleSheetsFacade(unittest.TestCase):
    """Test suite ensuring GoogleSheetsService acts as a 100% backward-compatible facade."""

    def test_inheritance_hierarchy(self):
        """GoogleSheetsService must inherit BaseSheetsService and all domain mixins."""
        self.assertTrue(issubclass(GoogleSheetsService, BaseSheetsService))
        self.assertTrue(issubclass(GoogleSheetsService, AttendanceSheetsMixin))
        self.assertTrue(issubclass(GoogleSheetsService, RevenueSheetsMixin))
        self.assertTrue(issubclass(GoogleSheetsService, AdminSheetsMixin))
        self.assertTrue(issubclass(GoogleSheetsService, RewardSheetsMixin))
        self.assertTrue(issubclass(GoogleSheetsService, SalarySheetsMixin))
        self.assertTrue(issubclass(GoogleSheetsService, InventorySheetsMixin))
        self.assertTrue(issubclass(GoogleSheetsService, SyncSheetsMixin))

    def test_module_exports(self):
        """Module must export GoogleSheetsService and _normalize_name_for_comparison."""
        self.assertIs(google_sheets.GoogleSheetsService, GoogleSheetsService)
        self.assertIs(google_sheets._normalize_name_for_comparison, _normalize_name_for_comparison)
        self.assertEqual(_normalize_name_for_comparison("Hòa"), "hoa")
        self.assertEqual(_normalize_name_for_comparison("Trần Thị Mai "), "tranthimai")

    def test_static_methods_direct_access(self):
        """Static methods must be directly callable on GoogleSheetsService class."""
        # _column_letter
        self.assertEqual(GoogleSheetsService._column_letter(1), "A")
        self.assertEqual(GoogleSheetsService._column_letter(26), "Z")
        self.assertEqual(GoogleSheetsService._column_letter(27), "AA")
        self.assertEqual(GoogleSheetsService._column_letter(52), "AZ")
        self.assertEqual(GoogleSheetsService._column_letter(53), "BA")

        # _current_salary_month
        self.assertEqual(GoogleSheetsService._current_salary_month(datetime(2026, 3, 10)), (3, 2026))
        self.assertEqual(GoogleSheetsService._current_salary_month(datetime(2026, 3, 17)), (4, 2026))
        self.assertEqual(GoogleSheetsService._current_salary_month(datetime(2026, 12, 17)), (1, 2027))

        # _salary_period
        self.assertEqual(
            GoogleSheetsService._salary_period(3, 2026),
            (date(2026, 2, 17), date(2026, 3, 16)),
        )
        self.assertEqual(
            GoogleSheetsService._salary_period(1, 2026),
            (date(2025, 12, 17), date(2026, 1, 16)),
        )

        # _number helper
        self.assertEqual(GoogleSheetsService._number("123,45"), 123.45)
        self.assertEqual(GoogleSheetsService._number("invalid", default=10.0), 10.0)

    def test_core_methods_presence_across_all_domains(self):
        """GoogleSheetsService must have all core methods from every domain."""
        core_methods = [
            # Base
            "_init_connections",
            "_get_cache",
            "_set_cache",
            "_invalidate_cache",
            "_get_or_create_custom_sheet",
            "_column_letter",
            # Attendance
            "checkin",
            "checkout",
            "_get_shift_info",
            "get_open_checkin_sessions",
            "get_checked_in_employees",
            "get_checkin_history_today",
            "get_late_statistics",
            "mark_reported_late",
            "mark_unreported_late",
            # Revenue
            "save_report",
            "get_recent_revenue_reports",
            "update_report_revenue",
            # Admin
            "get_admin_list",
            "add_admin",
            "add_overtime",
            "get_overtime_summary",
            # Reward
            "get_employees_detail",
            "get_all_nicknames",
            "get_balance",
            "get_all_balances",
            "update_balance",
            "batch_update_balances",
            "add_employee",
            "remove_employee",
            "rename_employee",
            "consume_reward",
            "get_reward_history",
            "get_employee_personal_summary",
            # Salary
            "get_salary_data",
            "get_salary_report",
            "get_salary_month_options",
            "get_all_salary_rates",
            "update_salary_rate",
            "update_salary_modifier",
            "ensure_salary_worksheet",
            "_current_salary_month",
            "_salary_period",
            # Inventory
            "get_all_materials",
            "get_material_groups",
            "get_low_stock_items",
            "get_inventory_history",
            "import_stock",
            "export_stock",
            "batch_import_stock",
            "batch_export_stock",
            "add_material",
            "update_material",
            "remove_material",
            # Sync
            "sync_sheet_employee_roles",
            "load_sheet_employee_roles",
            "sync_sheet_recipes",
            "load_sheet_recipes",
            "save_sheet_account",
            "load_sheet_accounts",
            "save_sheet_shift_schedule",
            "load_sheet_shift_schedules",
            "append_sheet_leave_request",
            "update_sheet_leave_request_status",
            "load_sheet_leave_requests",
            "append_sheet_petty_expense",
            "load_sheet_petty_expenses",
        ]

        for method_name in core_methods:
            with self.subTest(method=method_name):
                self.assertTrue(
                    hasattr(GoogleSheetsService, method_name),
                    f"Method {method_name} missing from GoogleSheetsService",
                )

    def test_instantiation_without_network(self):
        """GoogleSheetsService(max_retries=0) should initialize locks and cache without network calls."""
        service = GoogleSheetsService(max_retries=0)
        self.assertIsInstance(service._write_lock, type(threading.RLock()))
        self.assertIsInstance(service._cache_lock, type(threading.Lock()))
        self.assertIsInstance(service._cache, dict)

        # Cache test on instance
        service._set_cache("key1", "val1")
        self.assertEqual(service._get_cache("key1"), "val1")
        service._invalidate_cache("key1")
        self.assertIsNone(service._get_cache("key1"))
