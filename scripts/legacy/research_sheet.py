import asyncio
import gspread
from config import Config

def research_sheet():
    with open('sheet_research3.txt', 'w', encoding='utf-8') as f:
        try:
            gc = gspread.service_account_from_dict(Config.get_google_credentials_info())
            sheet_id = "170ThkLaXrriHsi9iUB2m-FyRZ73iz8SYpJwy6jU0sjU"
            sh = gc.open_by_key(sheet_id)
            
            ws = sh.worksheet('T7')
            # Lấy đến cột AZ
            rows = ws.get_values('A10:AZ30')
            for i, row in enumerate(rows):
                f.write(f"Row {i+10}: {row}\n")
        except Exception as e:
            f.write(f"Connection error: {e}\n")

if __name__ == '__main__':
    research_sheet()
