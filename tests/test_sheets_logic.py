import threading
import unittest
from datetime import datetime
from unittest.mock import patch

from google_sheets import GoogleSheetsService


class ValuesWorksheet:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []
        self._properties = {'sheetId': 1}

    def get_all_values(self):
        return self.rows

    def update_cell(self, row, col, value):
        self.updates.append((row, col, value))
        while len(self.rows[row - 1]) < col:
            self.rows[row - 1].append('')
        self.rows[row - 1][col - 1] = str(value)

    def row_values(self, row):
        return self.rows[row - 1]

    def update(self, values, range_name=None, **kwargs):
        self.updates.append((range_name, values))


class Spreadsheet:
    def batch_update(self, body):
        return body


class SalarySpreadsheet:
    def __init__(self, mapping):
        self.mapping = mapping

    def worksheet(self, title):
        if title != 'Mapping':
            raise KeyError(title)
        return self.mapping


class SheetsLogicTests(unittest.TestCase):
    def service(self):
        service = GoogleSheetsService.__new__(GoogleSheetsService)
        service._write_lock = threading.RLock()
        return service

    def test_shift_boundaries(self):
        service = self.service()
        self.assertEqual(service._get_shift_info(datetime(2026, 8, 11, 11, 59))['ca'], 'Sáng')
        self.assertEqual(service._get_shift_info(datetime(2026, 8, 11, 12, 0))['ca'], 'Chiều')
        self.assertEqual(service._get_shift_info(datetime(2026, 8, 11, 18, 0))['ca'], 'Tối')

    def test_checkin_persists_actual_time(self):
        service = self.service()
        service.ws_checkin = ValuesWorksheet([
            ['Ngày', 'Nickname', 'Vào', 'Ra', 'Giờ', 'Ghi chú'],
        ])
        service.sh = Spreadsheet()
        with patch('google_sheets.local_now', return_value=datetime(2026, 8, 11, 6, 50, 0)):
            result = service.checkin('an', 'Ca Chính')
        self.assertTrue(result['success'])
        self.assertEqual(result['time'], '06:50:00')
        written = service.ws_checkin.updates[-1][1][0]
        self.assertEqual(written[2], '06:50:00')

    def test_early_checkin_records_scheduled_start_and_keeps_audit_time(self):
        service = self.service()
        service.ws_checkin = ValuesWorksheet([
            ['Ngày', 'Nickname', 'Vào', 'Ra', 'Giờ', 'Ghi chú'],
        ])
        service.sh = Spreadsheet()
        with patch('google_sheets.local_now', return_value=datetime(2026, 8, 11, 11, 40, 12)):
            result = service.checkin('an', 'Ca Chính', 'Chiều')

        self.assertTrue(result['success'])
        self.assertEqual(result['ca'], 'Chiều')
        self.assertEqual(result['time'], '12:00:00')
        self.assertEqual(result['actual_time'], '11:40:12')
        self.assertEqual(result['early_minutes'], 20)
        self.assertIn('Check-in sớm lúc 11:40:12', result['note'])
        written = service.ws_checkin.updates[-1][1][0]
        self.assertEqual(written[2], '12:00:00')

    def test_checkin_more_than_thirty_minutes_early_is_rejected(self):
        service = self.service()
        service.ws_checkin = ValuesWorksheet([
            ['Ngày', 'Nickname', 'Vào', 'Ra', 'Giờ', 'Ghi chú'],
        ])
        with patch('google_sheets.local_now', return_value=datetime(2026, 8, 11, 11, 29)):
            result = service.checkin('an', 'Ca Chính', 'Chiều')

        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'too_early')
        self.assertEqual(result['allowed_time'], '11:30')

    def test_early_broken_shift_starts_pay_at_1930(self):
        service = self.service()
        service.ws_checkin = ValuesWorksheet([
            ['Ngày', 'Nickname', 'Vào', 'Ra', 'Giờ', 'Ghi chú'],
        ])
        service.sh = Spreadsheet()
        with patch('google_sheets.local_now', return_value=datetime(2026, 8, 11, 19, 5)):
            result = service.checkin('an', 'Ca Gãy', 'Tối')

        self.assertTrue(result['success'])
        self.assertEqual(result['time'], '19:30:00')
        self.assertEqual(result['early_minutes'], 25)

    def test_checkout_before_recorded_shift_start_is_rejected(self):
        service = self.service()
        service.ws_checkin = ValuesWorksheet([
            ['Ngày', 'Nickname', 'Vào', 'Ra', 'Giờ', 'Ghi chú'],
            ['11/08/2026', 'an', '12:00:00', '', '',
             'Ca Chính - Đúng giờ - Ca Chiều - Check-in sớm lúc 11:40:00'],
        ])
        with patch('google_sheets.local_now', return_value=datetime(2026, 8, 11, 11, 45)):
            result = service.checkout('an', 'Ca Chính')

        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'checkout_before_start')
        self.assertEqual(service.ws_checkin.updates, [])

    def test_early_arrival_is_not_included_in_paid_hours(self):
        service = self.service()
        service.ws_checkin = ValuesWorksheet([
            ['Ngày', 'Nickname', 'Vào', 'Ra', 'Giờ', 'Ghi chú'],
            ['11/08/2026', 'an', '12:00:00', '', '',
             'Ca Chính - Đúng giờ - Ca Chiều - Check-in sớm lúc 11:40:00'],
        ])
        with patch('google_sheets.local_now', return_value=datetime(2026, 8, 11, 18, 0)):
            result = service.checkout('an', 'Ca Chính')

        self.assertTrue(result['success'])
        self.assertEqual(result['total_hours'], '6,0')

    def test_open_sessions_filter_date_and_ca(self):
        service = self.service()
        today = datetime.now().strftime('%d/%m/%Y')
        service.ws_checkin = ValuesWorksheet([
            ['Ngày', 'Nickname', 'Vào', 'Ra', 'Giờ', 'Ghi chú'],
            ['01/01/2020', 'old', '06:30:00', '', '', 'Ca Chính - Đúng giờ'],
            [today, 'morning', '06:45:00', '', '', 'Ca Chính - Đi muộn 15p'],
            [today, 'evening', '18:00:00', '', '', 'Ca Chính - Đúng giờ'],
        ])
        morning = service.get_open_checkin_sessions(ca='Sáng')
        self.assertEqual([item['nickname'] for item in morning], ['morning'])
        self.assertEqual(len(service.get_open_checkin_sessions()), 2)

    def test_salary_period_after_day_17_targets_next_month(self):
        self.assertEqual(
            GoogleSheetsService._current_salary_month(datetime(2026, 8, 17, 0, 0)),
            (9, 2026),
        )
        start, end = GoogleSheetsService._salary_period(9, 2026)
        self.assertEqual(start.isoformat(), '2026-08-17')
        self.assertEqual(end.isoformat(), '2026-09-16')

    def test_salary_rates_use_mapping_then_fallback(self):
        service = self.service()
        service.col_nickname_index = 1
        service.ws_balance = ValuesWorksheet([
            ['Nickname', 'Đã thưởng', 'Đã dùng', 'Còn lại', 'Mức Lương/Giờ'],
            ['an', '0', '0', '0', '16'],
            ['binh', '0', '0', '0', ''],
        ])
        service.sh_salary = SalarySpreadsheet(ValuesWorksheet([
            ['Tên Nhân Viên', 'Nickname Bot', 'Mức Lương/Giờ'],
            ['An', 'an', '18.5'],
        ]))
        rates = service.get_all_salary_rates()
        self.assertEqual(rates['an'], 18.5)
        self.assertEqual(rates['binh'], 16.0)

    def test_column_letter_supports_more_than_z(self):
        self.assertEqual(GoogleSheetsService._column_letter(27), 'AA')
        self.assertEqual(GoogleSheetsService._column_letter(46), 'AT')

    def test_unreported_late_is_not_counted_as_pre_reported(self):
        service = self.service()
        current_month = datetime.now().strftime('%m/%Y')
        today = datetime.now().strftime('%d/%m/%Y')
        service.ws_checkin = ValuesWorksheet([
            ['Ngày', 'Nickname', 'Vào', 'Ra', 'Giờ', 'Ghi chú'],
            [today, 'an', '06:50:00', '12:00:00', '5.2', 'Ca Chính - Đi muộn 20p (không báo trước)'],
        ])
        records = service.get_late_statistics(current_month)
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0]['pre_reported'])


if __name__ == '__main__':
    unittest.main()
