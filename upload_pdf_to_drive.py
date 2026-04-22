"""생성된 PDF 리포트를 Google Drive 에 업로드.

두 개의 이름으로 업로드:
  - report_YYYYMMDD.pdf  (날짜 스냅샷, 입력 파일명 그대로)
  - report_latest.pdf    (최신본 alias — Claude 가 고정 이름으로 읽을 수 있도록)

GDRIVE_* 환경변수가 하나라도 누락되면 조용히 스킵 (기존 정책과 동일).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from gdrive_upload import MIME_PDF, upload_binary


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: upload_pdf_to_drive.py <pdf_path>")
        return 1

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"⚠️ PDF 파일 없음: {pdf_path} — 스킵")
        return 0

    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    client_id = os.environ.get("GDRIVE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GDRIVE_OAUTH_CLIENT_SECRET")
    refresh_token = os.environ.get("GDRIVE_OAUTH_REFRESH_TOKEN")

    if not all([folder_id, client_id, client_secret, refresh_token]):
        print("⚠️ GDRIVE_* OAuth Secrets 누락 — Drive PDF 업로드 스킵")
        return 0

    # 1) 날짜 스냅샷 (report_YYYYMMDD.pdf)
    dated_name = pdf_path.name
    fid_dated = upload_binary(
        filename=dated_name,
        filepath=str(pdf_path),
        mimetype=MIME_PDF,
        folder_id=folder_id,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
    )
    if fid_dated:
        print(f"✅ Drive 업로드: {dated_name} (id={fid_dated})")

    # 2) 최신본 alias (report_latest.pdf)
    fid_latest = upload_binary(
        filename="report_latest.pdf",
        filepath=str(pdf_path),
        mimetype=MIME_PDF,
        folder_id=folder_id,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
    )
    if fid_latest:
        print(f"✅ Drive 업로드: report_latest.pdf (id={fid_latest})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
