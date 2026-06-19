import logging
from io import BytesIO
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError
import json
from datetime import datetime, timedelta
try:
    from google.cloud import storage as gcs_storage
except Exception:
    gcs_storage = None
from config import Config

logger = logging.getLogger(__name__)

class GoogleDriveService:
    def __init__(self):
        try:
            # Scope để upload và chia sẻ file
            # Use broader drive scope to allow setting file permissions and working with shared drives.
            scopes = ['https://www.googleapis.com/auth/drive']
            creds = service_account.Credentials.from_service_account_info(
                Config.get_google_credentials_info(), scopes=scopes)
            
            self.service = build('drive', 'v3', credentials=creds)
            self.folder_id = Config.DRIVE_FOLDER_ID
            # Optional: support uploading to Google Cloud Storage bucket instead of Drive
            self.gcs_bucket_name = getattr(Config, 'GCS_BUCKET_NAME', None)
            self.gcs_public = str(getattr(Config, 'GCS_PUBLIC', 'true')).lower() in ('1', 'true', 'yes')
            self.gcs_client = None
            self.gcs_bucket = None
            if self.gcs_bucket_name and gcs_storage:
                try:
                    self.gcs_client = gcs_storage.Client.from_service_account_info(Config.get_google_credentials_info())
                    self.gcs_bucket = self.gcs_client.bucket(self.gcs_bucket_name)
                    logger.info(f"GCS bucket configured: {self.gcs_bucket_name}")
                except Exception:
                    logger.exception('Không thể khởi tạo GCS client; sẽ dùng Google Drive thay thế.')
            logger.info("Kết nối Google Drive API thành công.")
        except Exception as e:
            logger.error(f"Lỗi kết nối Google Drive: {e}")
            raise

    