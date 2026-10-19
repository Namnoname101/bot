import sys
import logging
from google_sheets import GoogleSheetsService

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO)
    try:
        s = GoogleSheetsService()
        ws = s.sh_salary.worksheet('T8-2026_New')
        
        all_data = ws.get_all_values()
        
        updates = []
        for i in range(13, len(all_data), 5):
            if i >= len(all_data):
                break
            name = all_data[i][2].strip()
            if name == 'Mai' or name == 'Đại':
                print(f"Fixing '{name}' -> 'Daitruong' at C{i+1}")
                updates.append({'range': f'C{i+1}', 'values': [['Daitruong']]})
        
        if updates:
            ws.batch_update(updates, value_input_option='USER_ENTERED')
            print("Đã tự động sửa tên Đại thành công!")
        else:
            print("Không tìm thấy tên nào cần sửa.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
