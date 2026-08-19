import unittest
from types import SimpleNamespace

from config import Config
from utils.admin import is_admin, is_super_admin
from utils.validators import (
    _parse_amount_str,
    check_reward_eligibility,
    deduplicate_employees,
    normalize_name,
    parse_report_text,
    validate_nickname,
)
from utils.time_utils import local_now


class ValidatorTests(unittest.TestCase):
    def test_amount_formats(self):
        cases = {
            '1500k': 1_500_000,
            '1.5M': 1_500_000,
            '1.500k': 1_500_000,
            '1.500.000': 1_500_000,
            '1,500,000': 1_500_000,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(_parse_amount_str(raw), expected)

    def test_report_requires_positive_revenue(self):
        for value in ('0', '-1', '100000001'):
            with self.subTest(value=value):
                _, _, _, error = parse_report_text(f'NV: an\nDT: {value}')
                self.assertTrue(error)

    def test_report_and_reward_boundaries(self):
        employees, revenue, ca, error = parse_report_text(
            'NV: Anh Tuyết, quốc bảo\nDoanh thu: 1.2M\nCa: sáng'
        )
        self.assertFalse(error)
        self.assertEqual(employees, ['anh tuyết', 'quốc bảo'])
        self.assertEqual(revenue, 1_200_000)
        self.assertEqual(ca, 'Sáng')
        self.assertEqual(check_reward_eligibility(2, revenue), 1)

    def test_deduplicate_uses_normalized_name(self):
        self.assertEqual(deduplicate_employees(['Hòa', 'hoa', 'Đại', 'dai']), ['Hòa', 'Đại'])
        self.assertEqual(normalize_name('Đặng Hồng Phước'), 'danghongphuoc')

    def test_nickname_callback_limits(self):
        self.assertEqual(validate_nickname('Nhân Viên 01'), (True, ''))
        self.assertFalse(validate_nickname('x' * 31)[0])
        self.assertFalse(validate_nickname('\n')[0])


class AdminTests(unittest.TestCase):
    def test_permissions_use_user_id(self):
        context = SimpleNamespace(bot_data={'admin_ids': {987654321}})
        self.assertTrue(is_admin(Config.ADMIN_CHAT_ID, context))
        self.assertTrue(is_admin(987654321, context))
        self.assertFalse(is_admin(Config.GROUP_CHAT_ID, context))
        self.assertTrue(is_super_admin(Config.ADMIN_CHAT_ID))
        self.assertFalse(is_super_admin(987654321))


class TimezoneTests(unittest.TestCase):
    def test_business_time_uses_configured_timezone(self):
        now = local_now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(getattr(now.tzinfo, 'key', None), Config.TIMEZONE)


if __name__ == '__main__':
    unittest.main()
