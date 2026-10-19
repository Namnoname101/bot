import sys
code = '''
    def ensure_salary_worksheet(self):
        """Tạo sheet lương tháng mới nếu chưa có hoặc cập nhật format."""
        try:
            from datetime import datetime
            now = datetime.now()
            month_str = f"T{now.month}-{now.year}"
            try:
                ws = self.sh_salary.worksheet(f"{month_str}_New")
                return ws
            except Exception:
                try:
                    ws = self.sh_salary.worksheet(month_str)
                    return ws
                except Exception:
                    pass
            logger.info(f"Tạo sheet lương mới: {month_str}")
            return None
        except Exception as e:
            logger.error(f"Lỗi ensure_salary_worksheet: {e}")
            return None
'''
with open('e:/Du An/Python/Sober/Bot/google_sheets.py', 'a', encoding='utf-8') as f:
    f.write('\n' + code + '\n')
