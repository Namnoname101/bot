import sys
import re

sys.stdout.reconfigure(encoding='utf-8')
with open('e:/Du An/Python/Sober/Bot/google_sheets.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: ensure_salary_worksheet
if 'ws.batch_clear' in content:
    content = content.replace("'E14:AI100',", "")
    content = content.replace('"E14:AI100",', "")
    content = content.replace("'E14:AI100'", "")
    content = content.replace('"E14:AI100"', "")

# Fix 2: add force_time_str to _do_checkout and checkout
content = content.replace(
    'def _do_checkout(self, ws, nickname: str) -> dict:',
    'def _do_checkout(self, ws, nickname: str, force_time_str: str = None) -> dict:'
)
content = content.replace(
    'time_str = now.strftime("%H:%M:%S")\n        \n        all_data = ws.get_all_values()',
    'time_str = force_time_str if force_time_str else now.strftime("%H:%M:%S")\n        \n        all_data = ws.get_all_values()'
)
content = content.replace(
    'total_hours = round(diff, 1)\n            ws.update_cell(target_row, 5, total_hours)',
    'total_hours = round(diff, 1)\n            total_hours_str = str(total_hours).replace(".", ",")\n            ws.update_cell(target_row, 5, total_hours_str)'
)
content = content.replace(
    "'total_hours': total_hours,",
    "'total_hours': str(total_hours).replace('.', ','),"
)

content = content.replace(
    'def checkout(self, nickname: str, shift_type: str = None) -> dict:',
    'def checkout(self, nickname: str, shift_type: str = None, force_time_str: str = None) -> dict:'
)
content = content.replace(
    'result = self._do_checkout(ws, nickname)',
    'result = self._do_checkout(ws, nickname, force_time_str)'
)

with open('e:/Du An/Python/Sober/Bot/google_sheets.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done!')
