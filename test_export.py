import asyncio
from google_sheets import GoogleSheetsService
import gspread.utils

async def test():
    gs = GoogleSheetsService()
    try:
        # Lấy client và id
        export_data = gs.gc.export(gs.sh.id, format=gspread.utils.ExportFormat.EXCEL)
        with open('backup.xlsx', 'wb') as f:
            f.write(export_data)
        print("Exported successfully.")
    except Exception as e:
        print(f"Lỗi: {e}")

if __name__ == '__main__':
    asyncio.run(test())
