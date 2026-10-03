import unittest
from datetime import datetime

from handlers.overtime_handler import _salary_window


class OvertimeHandlerTests(unittest.TestCase):
    def test_salary_window_mid_month_after_17(self):
        # 20/08/2026 -> 17/08/2026 00:00:00 to 16/09/2026 23:59:59
        dt = datetime(2026, 8, 20, 10, 30)
        start, end = _salary_window(dt)
        self.assertEqual(start, datetime(2026, 8, 17, 0, 0, 0))
        self.assertEqual(end, datetime(2026, 9, 16, 23, 59, 59))

    def test_salary_window_mid_month_before_17(self):
        # 10/08/2026 -> 17/07/2026 00:00:00 to 16/08/2026 23:59:59
        dt = datetime(2026, 8, 10, 10, 30)
        start, end = _salary_window(dt)
        self.assertEqual(start, datetime(2026, 7, 17, 0, 0, 0))
        self.assertEqual(end, datetime(2026, 8, 16, 23, 59, 59))

    def test_salary_window_december_rollover(self):
        # 25/12/2026 -> 17/12/2026 to 16/01/2027
        dt = datetime(2026, 12, 25, 15, 0)
        start, end = _salary_window(dt)
        self.assertEqual(start, datetime(2026, 12, 17, 0, 0, 0))
        self.assertEqual(end, datetime(2027, 1, 16, 23, 59, 59))

    def test_salary_window_january_rollover(self):
        # 05/01/2027 -> 17/12/2026 to 16/01/2027
        dt = datetime(2027, 1, 5, 8, 0)
        start, end = _salary_window(dt)
        self.assertEqual(start, datetime(2026, 12, 17, 0, 0, 0))
        self.assertEqual(end, datetime(2027, 1, 16, 23, 59, 59))


if __name__ == '__main__':
    unittest.main()
