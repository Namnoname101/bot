import sys
import logging
from google_sheets import GoogleSheetsService

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO)
    try:
        s = GoogleSheetsService()
        ws = s.sh_salary.worksheet('T8-2026_New')
        
        orig_names = ['Thảo', 'Nghĩa', 'Ly', 'Toàn', 'Đại', 'Trân', 'Thư', 'Tuấn', 'Trường', 'Hân', 'trâm', 'Phúc', 'Hương', 'Mai']
        
        updates = []
        name_idx = 0
        for i in range(13, 100, 5):
            if name_idx < len(orig_names):
                updates.append({'range': f'C{i+1}', 'values': [[orig_names[name_idx]]]})
                name_idx += 1
                
        if updates:
            ws.batch_update(updates, value_input_option='USER_ENTERED')
            print("Đã khôi phục tên gốc.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
