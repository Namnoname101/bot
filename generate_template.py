import os
import sys
import logging
from google_sheets import GoogleSheetsService
from gspread.utils import a1_to_rowcol, rowcol_to_a1

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO)
    try:
        s = GoogleSheetsService()
        
        # Lấy danh sách nhân viên từ T8-2026 hiện tại
        ws_old = s.sh_salary.worksheet('T8-2026')
        all_old_data = ws_old.get_all_values()
        
        employees = []
        for row in all_old_data[13:]: # row 14 onwards
            if len(row) > 2 and row[2].strip():
                employees.append({
                    'stt': row[1].strip(),
                    'name': row[2].strip(),
                    'role': row[3].strip() if len(row) > 3 else ''
                })
        
        # --- TẠO DATA_GIOLAMTHEM ---
        try:
            ws_gl = s.sh_salary.worksheet('Data_GioLamThem')
        except:
            ws_gl = s.sh_salary.add_worksheet(title='Data_GioLamThem', rows=1000, cols=10)
            # URL của Data gốc
            url = "https://docs.google.com/spreadsheets/d/1gSMI8u_tvaDp1AM914wOE9B0IzlK8PNeuxBaLuV2uV8/edit?gid=1440926847#gid=1440926847"
            ws_gl.update_acell('A1', f'=IMPORTRANGE("{url}"; "GioLamThem!A:E")')
            print("Đã tạo Data_GioLamThem. Nhớ nhắc user Allow Access.")
            
        # --- TẠO TEMPLATE MỚI ---
        try:
            ws_new = s.sh_salary.worksheet('T8-2026_New')
            s.sh_salary.del_worksheet(ws_new)
        except:
            pass
            
        # Tạo sheet mới
        ws_new = s.sh_salary.add_worksheet(title='T8-2026_New', rows=300, cols=50)
        
        # Copy header từ cũ sang mới (13 dòng đầu)
        headers = all_old_data[:13]
        for i in range(len(headers)):
            while len(headers[i]) < 46:
                headers[i].append('')
        
        new_data = headers.copy()
        
        # Sinh 5 dòng cho mỗi nhân viên
        current_row = 14
        for emp in employees:
            row_sang = [''] * 46
            row_sang[1] = emp['stt']
            row_sang[2] = emp['name']
            row_sang[3] = "Sáng"
            
            row_chieu = [''] * 46
            row_chieu[3] = "Chiều"
            
            row_toi = [''] * 46
            row_toi[3] = "Tối"
            
            row_gay = [''] * 46
            row_gay[3] = "Gãy"
            
            row_tong = [''] * 46
            row_tong[3] = "Tổng"
            
            for col_idx in range(4, 35):
                col_letter = rowcol_to_a1(1, col_idx + 1).replace('1', '')
                let_vars = (
                    f'day_val; VALUE({col_letter}$12); '
                    f'month_val; IF(day_val>=17; IF($R$10=1; 12; $R$10-1); $R$10); '
                    f'year_val; IF(AND(day_val>=17; $R$10=1); $T$10-1; $T$10); '
                    f'target_date; TEXT(day_val; "00") & "/" & TEXT(month_val; "00") & "/" & year_val; '
                )
                
                f_sang = f'=IFERROR(LET({let_vars} total_hours; SUMIFS(Data_Checkin!$E:$E; Data_Checkin!$B:$B; $C{current_row}; Data_Checkin!$A:$A; target_date; Data_Checkin!$C:$C; "<14:00:00"); IF(total_hours=0; ""; total_hours)); "")'
                row_sang[col_idx] = f_sang
                
                f_chieu = f'=IFERROR(LET({let_vars} total_hours; SUMIFS(Data_Checkin!$E:$E; Data_Checkin!$B:$B; $C{current_row}; Data_Checkin!$A:$A; target_date; Data_Checkin!$C:$C; ">=14:00:00"; Data_Checkin!$C:$C; "<22:00:00"); IF(total_hours=0; ""; total_hours)); "")'
                row_chieu[col_idx] = f_chieu
                
                f_toi = f'=IFERROR(LET({let_vars} total_hours; SUMIFS(Data_Checkin!$E:$E; Data_Checkin!$B:$B; $C{current_row}; Data_Checkin!$A:$A; target_date; Data_Checkin!$C:$C; ">=22:00:00"); IF(total_hours=0; ""; total_hours)); "")'
                row_toi[col_idx] = f_toi
                
                f_gay = f'=IFERROR(LET({let_vars} total_hours; SUMIFS(Data_GioLamThem!$E:$E; Data_GioLamThem!$B:$B; $C{current_row}; Data_GioLamThem!$A:$A; target_date); IF(total_hours=0; ""; total_hours)); "")'
                row_gay[col_idx] = f_gay
                
                row_tong[col_idx] = f'=IF(SUM({col_letter}{current_row}:{col_letter}{current_row+3})=0; ""; SUM({col_letter}{current_row}:{col_letter}{current_row+3}))'
            
            # Cột 37, 38, 39: Tổng sáng chiều tối
            row_sang[37] = f'=SUM(E{current_row}:AI{current_row})'
            row_chieu[38] = f'=SUM(E{current_row+1}:AI{current_row+1})'
            row_toi[39] = f'=SUM(E{current_row+2}:AI{current_row+2})'
            row_gay[35] = f'=SUM(E{current_row+3}:AI{current_row+3})'
            
            row_tong[41] = f'=SUM(E{current_row+4}:AI{current_row+4})'
            
            new_data.extend([row_sang, row_chieu, row_toi, row_gay, row_tong])
            current_row += 5
            
        print("Updating new sheet with 5-row structure...")
        ws_new.update(values=new_data, range_name='A1:AT300', value_input_option='USER_ENTERED')
        
        print("Done!")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
