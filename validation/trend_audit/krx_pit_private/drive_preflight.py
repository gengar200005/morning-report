"""Validate an unshared Google Drive folder under the existing Drive OAuth app."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from gdrive_upload import _build_service

FOLDER_NAME = "KRX_PIT_GITHUB_ACTIONS_PRIVATE"
FOLDER_MIME = "application/vnd.google-apps.folder"


def main():
    keys = ("GDRIVE_OAUTH_CLIENT_ID", "GDRIVE_OAUTH_CLIENT_SECRET", "GDRIVE_OAUTH_REFRESH_TOKEN")
    if any(not os.environ.get(k) for k in keys):
        raise RuntimeError("Missing existing Drive OAuth credentials")
    drive = _build_service(*(os.environ[k] for k in keys))
    query = "name = '%s' and mimeType = '%s' and trashed = false" % (FOLDER_NAME, FOLDER_MIME)
    response = drive.files().list(q=query, spaces="drive", fields="nextPageToken,files(id,name,mimeType,shared)", pageSize=100).execute()
    found = response.get("files", [])
    if response.get("nextPageToken") or len(found) > 1:
        raise RuntimeError("Ambiguous target folder")
    if found:
        folder_id = found[0]["id"]
    else:
        result = drive.files().create(body={"name": FOLDER_NAME, "mimeType": FOLDER_MIME, "parents": ["root"]}, fields="id").execute()
        folder_id = result["id"]
    meta = drive.files().get(fileId=folder_id, fields="id,name,mimeType,shared").execute()
    if meta.get("name") != FOLDER_NAME or meta.get("mimeType") != FOLDER_MIME or meta.get("shared") is not False:
        raise RuntimeError("Private folder verification failed")
    print("DRIVE_PRIVATE_FOLDER_READY")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("PRIVATE_DRIVE_PREFLIGHT_FAILED: " + type(exc).__name__)
        sys.exit(2)
