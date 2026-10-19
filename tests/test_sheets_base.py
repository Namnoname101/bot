import time
import unittest
from unittest.mock import MagicMock, patch
import gspread

from services.sheets.base import BaseSheetsService


class TestBaseSheetsService(unittest.TestCase):
    def test_cache_set_get_invalidate(self):
        svc = BaseSheetsService.__new__(BaseSheetsService)
        svc._cache = {}
        svc._cache_lock = None

        # Basic set and get
        svc._set_cache("key1", "val1")
        self.assertEqual(svc._get_cache("key1"), "val1")

        # Invalidate specific key
        svc._invalidate_cache("key1")
        self.assertIsNone(svc._get_cache("key1"))

        # Prefix invalidation
        svc._set_cache("user:1", "alice")
        svc._set_cache("user:2", "bob")
        svc._set_cache("item:1", "potion")
        svc._invalidate_cache("user:")
        self.assertIsNone(svc._get_cache("user:1"))
        self.assertIsNone(svc._get_cache("user:2"))
        self.assertEqual(svc._get_cache("item:1"), "potion")

        # Invalidate all
        svc._invalidate_cache()
        self.assertIsNone(svc._get_cache("item:1"))

    def test_cache_ttl_expiration(self):
        svc = BaseSheetsService.__new__(BaseSheetsService)
        svc._cache = {}
        svc._cache_lock = None

        svc._set_cache("temp_key", "temp_val")
        # With ttl_seconds=0, it should be expired immediately
        with patch("time.time", side_effect=[100.0, 105.0]):
            svc._set_cache("temp_key", "temp_val")
            self.assertIsNone(svc._get_cache("temp_key", ttl_seconds=2.0))

    def test_column_letter(self):
        self.assertEqual(BaseSheetsService._column_letter(1), "A")
        self.assertEqual(BaseSheetsService._column_letter(26), "Z")
        self.assertEqual(BaseSheetsService._column_letter(27), "AA")

    def test_get_or_create_custom_sheet_existing(self):
        svc = BaseSheetsService.__new__(BaseSheetsService)
        svc._write_lock = None
        mock_sheet = MagicMock()
        mock_ws = MagicMock()
        mock_sheet.worksheet.return_value = mock_ws
        svc.sh = mock_sheet

        ws = svc._get_or_create_custom_sheet("ExistingSheet", ["Col1", "Col2"])
        self.assertEqual(ws, mock_ws)
        mock_sheet.worksheet.assert_called_once_with("ExistingSheet")

    def test_get_or_create_custom_sheet_creates_new(self):
        svc = BaseSheetsService.__new__(BaseSheetsService)
        svc._write_lock = None
        mock_sheet = MagicMock()
        mock_sheet.worksheet.side_effect = gspread.exceptions.WorksheetNotFound()
        created_ws = MagicMock()
        mock_sheet.add_worksheet.return_value = created_ws
        svc.sh = mock_sheet

        ws = svc._get_or_create_custom_sheet("NewSheet", ["ID", "Name"])
        self.assertEqual(ws, created_ws)
        mock_sheet.add_worksheet.assert_called_once_with(title="NewSheet", rows=200, cols=10)
        created_ws.append_row.assert_called_once_with(["ID", "Name"], value_input_option="USER_ENTERED")

    @patch("services.sheets.base.Config")
    @patch("services.sheets.base.gspread.service_account_from_dict")
    def test_init_connections_success(self, mock_sa, mock_config):
        mock_config.get_google_credentials_info.return_value = {"type": "service_account"}
        mock_config.SPREADSHEET_ID = "spread_1"
        mock_config.SALARY_SPREADSHEET_ID = "salary_1"
        mock_config.INVENTORY_SPREADSHEET_ID = "inv_1"

        mock_gc = MagicMock()
        mock_sh = MagicMock()
        mock_salary = MagicMock()
        mock_inv = MagicMock()

        def open_by_key_mock(key):
            if key == "spread_1":
                return mock_sh
            elif key == "salary_1":
                return mock_salary
            elif key == "inv_1":
                return mock_inv
            raise ValueError(f"Unknown key: {key}")

        mock_gc.open_by_key.side_effect = open_by_key_mock
        mock_sa.return_value = mock_gc

        svc = BaseSheetsService(max_retries=1)

        self.assertEqual(svc.gc, mock_gc)
        self.assertEqual(svc.sh, mock_sh)
        self.assertEqual(svc.sh_salary, mock_salary)
        self.assertEqual(svc.sh_inventory, mock_inv)
        mock_sh.worksheet.assert_any_call("LichSuThuong")
        mock_sh.worksheet.assert_any_call("GioLamThem")
        mock_sh.worksheet.assert_any_call("Checkin")


if __name__ == "__main__":
    unittest.main()
