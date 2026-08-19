import os
import sys
import datetime
import gspread.utils

# Thêm đường dẫn project vào sys.path để import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_sheets import GoogleSheetsService

def run_backup():
    try:
        gs = GoogleSheetsService()
        
        # Đảm bảo thư mục backups tồn tại
        os.makedirs("backups", exist_ok=True)
        
        # Tên file backup theo ngày giờ
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"backups/backup_Sober_{timestamp}.xlsx"
        
        print(f"Đang tiến hành sao lưu dữ liệu từ Google Sheets (ID: {gs.sh.id})...")
        
        # Xuất file Excel bằng gspread export
        export_data = gs.gc.export(gs.sh.id, format=gspread.utils.ExportFormat.EXCEL)
        
        with open(backup_file, 'wb') as f:
            f.write(export_data)
            
        print(f"✅ Sao lưu thành công tại: {backup_file}")
        
    except Exception as e:
        print(f"❌ Lỗi khi sao lưu dữ liệu: {e}")

if __name__ == '__main__':
    run_backup()
