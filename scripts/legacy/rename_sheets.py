import sys
import logging
from google_sheets import GoogleSheetsService

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO)
    try:
        s = GoogleSheetsService()
        
        # 1. Đổi tên T8-2026 thành T8-2026_Old
        try:
            ws_old = s.sh_salary.worksheet('T8-2026')
            ws_old.update_title('T8-2026_Old')
            print("Đổi tên T8-2026 thành T8-2026_Old thành công.")
        except Exception as e:
            print("Không tìm thấy T8-2026 hoặc đã được đổi tên:", e)
            
        # 2. Đổi tên T8-2026_New thành T8-2026
        try:
            ws_new = s.sh_salary.worksheet('T8-2026_New')
            ws_new.update_title('T8-2026')
            print("Đổi tên T8-2026_New thành T8-2026 thành công.")
        except Exception as e:
            print("Không tìm thấy T8-2026_New:", e)
            
    except Exception as e:
        print(f"Lỗi: {e}")

if __name__ == '__main__':
    main()
