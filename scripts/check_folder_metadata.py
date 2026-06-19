import json
import traceback
import sys
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import Config

SCOPES = ['https://www.googleapis.com/auth/drive']

try:
    creds = service_account.Credentials.from_service_account_file(Config.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
    service = build('drive', 'v3', credentials=creds)
    folder_id = Config.DRIVE_FOLDER_ID

    print('Checking folder id:', folder_id)
    try:
        meta = service.files().get(fileId=folder_id, fields='id,name,mimeType,driveId', supportsAllDrives=True).execute()
        out = {
            'id': meta.get('id'),
            'name': meta.get('name'),
            'mimeType': meta.get('mimeType'),
            'driveId': meta.get('driveId')
        }
        print(json.dumps({'folder_metadata': out}, ensure_ascii=False))
    except Exception as e:
        print('ERROR_GET_FOLDER:', str(e))

    try:
        drives = service.drives().list(pageSize=100).execute()
        drives_list = [{'id': d.get('id'), 'name': d.get('name')} for d in drives.get('drives', [])]
        print(json.dumps({'shared_drives_accessible': drives_list}, ensure_ascii=False))
    except Exception as e:
        print('ERROR_LIST_DRIVES:', str(e))

except Exception as e:
    print('INIT_ERROR:', str(e))
    traceback.print_exc()
