"""Google Drive 업로드 유틸 (OAuth 사용자 위임 방식).

개인 Gmail 계정의 Drive에 업로드하려면 서비스 계정이 아닌
사용자 OAuth 리프레시 토큰이 필요하다
(서비스 계정은 개인 Drive에 저장 공간 할당이 0이기 때문).

환경변수 3종이 모두 있어야 업로드가 수행된다:
  - GDRIVE_OAUTH_CLIENT_ID
  - GDRIVE_OAUTH_CLIENT_SECRET
  - GDRIVE_OAUTH_REFRESH_TOKEN

이들 + GDRIVE_FOLDER_ID가 없으면 조용히 스킵하여 기존 GitHub 커밋
파이프라인과 독립적으로 동작한다.
"""

from __future__ import annotations

import io
import time
from typing import Optional


SCOPES = ["https://www.googleapis.com/auth/drive.file"]
MIME_TEXT = "text/plain"
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _build_service(client_id: str, client_secret: str, refresh_token: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
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
        ).execute()
        return updated["id"]

    metadata = {"name": filename, "parents": [folder_id]}
    created = service.files().create(
        body=metadata,
        media_body=media,
        fields="id",
    ).execute()
    return created["id"]


def upload_text(
    filename: str,
    content: str,
    folder_id: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    retries: int = 1,
) -> Optional[str]:
    """Drive 폴더에 텍스트 파일 업로드. 성공 시 file id, 실패 시 None."""
    service = _build_service(client_id, client_secret, refresh_token)
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
