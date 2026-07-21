import asyncio
from google_sheets import GoogleSheetsService
from config import Config

async def test():
    gs = GoogleSheetsService()
    try:
        ws = gs.sh_salary.worksheet('T7')
        rows = ws.get_values("A14:AT25")
        for i in range(len(rows)):
            if len(rows[i]) > 2 and rows[i][2].strip():
                name = rows[i][2].strip()
                tong_gio = rows[i][41] if len(rows[i]) > 41 else "0"
                tong_luong = rows[i][44] if len(rows[i]) > 44 else "0"
                
                ung_luong = "0"
                thuong = "0"
                tong_nhan = "0"
                if i + 1 < len(rows):
                    row2 = rows[i+1]
                    ung_luong = row2[42] if len(row2) > 42 else "0"
                    thuong = row2[43] if len(row2) > 43 else "0"
                    tong_nhan = row2[45] if len(row2) > 45 else "0"
                    
                print(f"{name}: Lương {tong_luong}, Ứng {ung_luong}, Thưởng {thuong}, Nhận {tong_nhan}")
    except Exception as e:
        print(f"Lỗi: {e}")

if __name__ == '__main__':
    asyncio.run(test())
