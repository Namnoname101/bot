import os
import sys
import logging
from google_sheets import GoogleSheetsService

def main():
    logging.basicConfig(level=logging.INFO)
    try:
        s = GoogleSheetsService()
        ws = s.sh_salary.worksheet('T8-2026')
        
        formulas = []
        for row_idx in range(14, 101):
            row_formulas = []
            for col_idx in range(5, 36):
                # col 5 is E, 35 is AI
                if col_idx <= 26:
                    col_letter = chr(ord('A') + col_idx - 1)
                else:
                    col_letter = 'A' + chr(ord('A') + col_idx - 27)
                    
                formula = (
                    f'=IFERROR(LET('
                    f'day_val; VALUE({col_letter}$12); '
                    f'month_val; IF(day_val>=17; IF($R$10=1; 12; $R$10-1); $R$10); '
                    f'year_val; IF(AND(day_val>=17; $R$10=1); $T$10-1; $T$10); '
                    f'target_date; TEXT(day_val; "00") & "/" & TEXT(month_val; "00") & "/" & year_val; '
                    f'total_hours; SUMIFS(Data_Checkin!$E:$E; Data_Checkin!$B:$B; $C{row_idx}; Data_Checkin!$A:$A; target_date); '
                    f'IF(total_hours=0; ""; total_hours)'
                    f'); "")'
                )
                row_formulas.append(formula)
            formulas.append(row_formulas)
            
        print("Updating E14:AI100 with formulas using semicolons...")
        ws.update(values=formulas, range_name='E14:AI100', value_input_option='USER_ENTERED')
        print("Done!")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
