import sys
import logging
from google_sheets import GoogleSheetsService
from gspread.utils import rowcol_to_a1

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO)
    try:
        s = GoogleSheetsService()
        
        # 1. Tạo sheet Mapping
        try:
            ws_map = s.sh_salary.worksheet('Mapping')
        except:
            ws_map = s.sh_salary.add_worksheet(title='Mapping', rows=100, cols=2)
            
        # Điền dữ liệu cơ bản vào Mapping
        mapping_data = [
            ['Tên Bảng Lương', 'Nickname Bot'],
            ['Thảo', 'thao'],
            ['Đại', 'Daitruong'],
            ['Toàn', 'Tantoan'],
            ['Thư', 'thathu'],
            ['Tuấn ', 'Tuanchotim'],
            ['Trường', 'truongg'],
            ['Hân', 'Khahan'],
            ['Phúc', 'Phuc'],
            ['Ly', 'kly'],
            ['Nghĩa', 'ngocanh'],
            ['trâm', 'hoanglan']
        ]
        ws_map.update(values=mapping_data, range_name='A1:B12', value_input_option='USER_ENTERED')
        
        # 2. Cập nhật lại công thức SUMIFS trong T8-2026_New
        ws_new = s.sh_salary.worksheet('T8-2026_New')
        all_data = ws_new.get_all_values()
        
        updates = []
        current_row = 14
        
        # Loop qua từng nhân viên (mỗi nv 5 dòng)
        for i in range(13, len(all_data), 5):
            if i >= len(all_data):
                break
                
            name = all_data[i][2].strip()
            if not name:
                current_row += 5
                continue
                
            row_sang = [''] * 46
            row_chieu = [''] * 46
            row_toi = [''] * 46
            row_gay = [''] * 46
            
            for col_idx in range(4, 35):
                col_letter = rowcol_to_a1(1, col_idx + 1).replace('1', '')
                let_vars = (
                    f'day_val; VALUE({col_letter}$12); '
                    f'month_val; IF(day_val>=17; IF($R$10=1; 12; $R$10-1); $R$10); '
                    f'year_val; IF(AND(day_val>=17; $R$10=1); $T$10-1; $T$10); '
                    f'target_date; TEXT(day_val; "00") & "/" & TEXT(month_val; "00") & "/" & year_val; '
                    f'bot_nick; IFERROR(VLOOKUP($C{current_row}; Mapping!$A:$B; 2; FALSE); $C{current_row}); '
                )
                
                f_sang = f'=IFERROR(LET({let_vars} total_hours; SUMIFS(Data_Checkin!$E:$E; Data_Checkin!$B:$B; bot_nick; Data_Checkin!$A:$A; target_date; Data_Checkin!$C:$C; "<14:00:00"); IF(total_hours=0; ""; total_hours)); "")'
                row_sang[col_idx] = f_sang
                
                f_chieu = f'=IFERROR(LET({let_vars} total_hours; SUMIFS(Data_Checkin!$E:$E; Data_Checkin!$B:$B; bot_nick; Data_Checkin!$A:$A; target_date; Data_Checkin!$C:$C; ">=14:00:00"; Data_Checkin!$C:$C; "<22:00:00"); IF(total_hours=0; ""; total_hours)); "")'
                row_chieu[col_idx] = f_chieu
                
                f_toi = f'=IFERROR(LET({let_vars} total_hours; SUMIFS(Data_Checkin!$E:$E; Data_Checkin!$B:$B; bot_nick; Data_Checkin!$A:$A; target_date; Data_Checkin!$C:$C; ">=22:00:00"); IF(total_hours=0; ""; total_hours)); "")'
                row_toi[col_idx] = f_toi
                
                f_gay = f'=IFERROR(LET({let_vars} total_hours; SUMIFS(Data_GioLamThem!$E:$E; Data_GioLamThem!$B:$B; bot_nick; Data_GioLamThem!$A:$A; target_date); IF(total_hours=0; ""; total_hours)); "")'
                row_gay[col_idx] = f_gay
                
            updates.append({'range': f'E{current_row}:AI{current_row}', 'values': [row_sang[4:35]]})
            updates.append({'range': f'E{current_row+1}:AI{current_row+1}', 'values': [row_chieu[4:35]]})
            updates.append({'range': f'E{current_row+2}:AI{current_row+2}', 'values': [row_toi[4:35]]})
            updates.append({'range': f'E{current_row+3}:AI{current_row+3}', 'values': [row_gay[4:35]]})
            
            current_row += 5
            
        print("Cập nhật lại công thức VLOOKUP...")
        ws_new.batch_update(updates, value_input_option='USER_ENTERED')
        print("Done!")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
