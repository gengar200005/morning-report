"""Google Drive 업로드 유틸.

서비스 계정 JSON 키 + 대상 폴더 ID를 받아 텍스트 파일을 업로드한다.
같은 이름의 파일이 폴더 안에 이미 있으면 내용을 덮어쓴다(버전 증가).
없으면 새로 생성한다.

환경변수가 없을 때는 조용히 스킵하여 기존 GitHub 커밋 파이프라인과
독립적으로 동작하도록 한다.
"""

from __future__ import annotations

import io
import json
import time
from typing import Optional


SCOPES = ["https://www.googleapis.com/auth/drive"]
MIME_TEXT = "text/plain"


def _build_service(creds_json: str):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_file_id(service, folder_id: str, filename: str) -> Optional[str]:
    safe_name = filename.replace("'", "\\'")
    query = (
        f"name = '{safe_name}' "
        f"and '{folder_id}' in parents "
        f"and trashed = false"
    )
    resp = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def _upload_once(service, folder_id: str, filename: str, content: str) -> str:
    from googleapiclient.http import MediaIoBaseUpload

    data = content.encode("utf-8")
    media = MediaIoBaseUpload(
        io.BytesIO(data), mimetype=MIME_TEXT, resumable=False
    )

    existing_id = _find_file_id(service, folder_id, filename)
    if existing_id:
        updated = service.files().update(
            fileId=existing_id,
            media_body=media,
            supportsAllDrives=True,
        ).execute()
        return updated["id"]

    metadata = {"name": filename, "parents": [folder_id]}
    created = service.files().create(
        body=metadata,
        media_body=media,
        fields="id",
        supportsAllDrives=True,
    ).execute()
    return created["id"]


def upload_text(
    filename: str,
    content: str,
    folder_id: str,
    creds_json: str,
    retries: int = 1,
) -> Optional[str]:
    """Drive 폴더에 텍스트 파일 업로드. 성공 시 file id, 실패 시 None."""
    service = _build_service(creds_json)
    attempt = 0
    last_err: Optional[Exception] = None
    while attempt <= retries:
        try:
            return _upload_once(service, folder_id, filename, content)
        except Exception as e:
            last_err = e
            attempt += 1
            if attempt <= retries:
                time.sleep(2)
    print(f"❌ Drive 업로드 실패 ({filename}): {last_err}")
    return None
