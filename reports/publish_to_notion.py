"""
Notion 모닝리포트 publisher.

v5.0 §3.2 4단계:
  1. POST /v1/file_uploads     → file_upload slot
  2. POST upload_url           → PDF 바이너리 (multipart/form-data)
  3. POST /v1/pages            → 부모 아래 자식 페이지 생성
  4. PATCH /v1/blocks/{id}/children → notion_page_template.json children 주입

환경변수: NOTION_API_KEY, NOTION_PARENT_PAGE_ID
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
WEEKDAY_KO = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def create_file_upload_slot(token: str) -> dict:
    resp = requests.post(
        f"{NOTION_API_BASE}/file_uploads",
        headers=_headers(token),
        json={},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def upload_pdf_binary(token: str, upload_url: str, pdf_path: Path) -> dict:
    with pdf_path.open("rb") as f:
        files = {"file": (pdf_path.name, f, "application/pdf")}
        resp = requests.post(
            upload_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
            },
            files=files,
            timeout=180,
        )
    resp.raise_for_status()
    return resp.json()


def create_child_page(token: str, parent_page_id: str, title: str) -> dict:
    resp = requests.post(
        f"{NOTION_API_BASE}/pages",
        headers=_headers(token),
        json={
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "properties": {
                "title": {"title": [{"type": "text", "text": {"content": title}}]}
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def append_children(token: str, page_id: str, children: list) -> dict:
    resp = requests.patch(
        f"{NOTION_API_BASE}/blocks/{page_id}/children",
        headers=_headers(token),
        json={"children": children},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def load_template() -> dict:
    path = Path(__file__).resolve().parent.parent / "notion_page_template.json"
    return json.loads(path.read_text(encoding="utf-8"))


def render_children(template: dict, file_upload_id: str) -> list:
    raw = json.dumps(template["children"])
    return json.loads(raw.replace("{{FILE_UPLOAD_ID}}", file_upload_id))


def build_title(date_str: str) -> str:
    fmt = "%Y-%m-%d" if "-" in date_str else "%Y%m%d"
    dt = datetime.strptime(date_str, fmt)
    return f"모닝리포트 {dt.strftime('%Y-%m-%d')} ({WEEKDAY_KO[dt.weekday()]})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Notion 모닝리포트 publisher")
    parser.add_argument("--pdf", required=True, help="업로드할 PDF 경로")
    parser.add_argument("--date", required=True, help="YYYYMMDD 또는 YYYY-MM-DD")
    args = parser.parse_args()

    token = os.environ.get("NOTION_API_KEY")
    parent_page_id = os.environ.get("NOTION_PARENT_PAGE_ID")
    if not token:
        sys.exit("❌ NOTION_API_KEY 미설정")
    if not parent_page_id:
        sys.exit("❌ NOTION_PARENT_PAGE_ID 미설정")

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"❌ PDF 없음: {pdf_path}")

    title = build_title(args.date)
    print(f"[publish] PDF: {pdf_path} ({pdf_path.stat().st_size:,} bytes)")
    print(f"[publish] Parent: {parent_page_id}")
    print(f"[publish] Title: {title}")

    slot = create_file_upload_slot(token)
    file_upload_id = slot["id"]
    print(f"[1/4] file_upload slot → id={file_upload_id}")

    uploaded = upload_pdf_binary(token, slot["upload_url"], pdf_path)
    status = uploaded.get("status")
    if status != "uploaded":
        sys.exit(f"❌ [2/4] PDF upload status != 'uploaded' (got '{status}')")
    print(f"[2/4] PDF 바이너리 업로드 완료")

    page = create_child_page(token, parent_page_id, title)
    page_id = page["id"]
    page_url = page.get("url", "")
    print(f"[3/4] 자식 페이지 → {page_id}")

    template = load_template()
    children = render_children(template, file_upload_id)
    append_children(token, page_id, children)
    print(f"[4/4] children {len(children)} 블록 추가 완료")

    print(f"\n✅ Notion publish 완료: {page_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
