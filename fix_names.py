import sys
import logging
from google_sheets import GoogleSheetsService

def remove_accents(s):
    import unicodedata
    return unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8')

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO)
    try:
        s = GoogleSheetsService()
        ws = s.sh_salary.worksheet('T8-2026_New')
        
        all_data = ws.get_all_values()
        
        ws_checkin = s.sh_salary.worksheet('Data_Checkin')
        checkin_data = ws_checkin.get_all_values()
        nicknames = list(set([r[1] for r in checkin_data if len(r) > 1][1:]))
        
        updates = []
        for i in range(13, len(all_data), 5):
            if i >= len(all_data):
                break
            name = all_data[i][2].strip()
            if not name:
                continue
                
            matched_nickname = name
            for nick in nicknames:
                n1 = remove_accents(name.lower().replace(" ", ""))
                n2 = remove_accents(nick.lower().replace(" ", ""))
                if n1 in n2 or n2 in n1:
                    matched_nickname = nick
                    break
                    
            if matched_nickname != name:
                print(f"Mapping '{name}' -> '{matched_nickname}'")
                # Cột C (3) dòng i+1
                updates.append({'range': f'C{i+1}', 'values': [[matched_nickname]]})
        
        if updates:
            ws.batch_update(updates, value_input_option='USER_ENTERED')
            print("Đã tự động sửa tên thành công!")
        else:
            print("Không tìm thấy tên nào cần sửa.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
