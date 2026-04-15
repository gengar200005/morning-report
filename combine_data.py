import os
import base64
import requests
from datetime import datetime
import pytz

GITHUB_TOKEN = os.environ["MORNINGREPOT"]
GIST_TOKEN   = os.environ.get("MORNING_GIST_TOKEN", "")  # PAT with gist scope
GITHUB_REPO  = "gengar200005/morning-report"
GITHUB_FILE  = "morning_data.txt"
GIST_ID_FILE = "morning_gist_id.txt"  # Gist ID 저장용

KST      = pytz.timezone("Asia/Seoul")
NOW      = datetime.now(KST)
DATE_STR = NOW.strftime("%Y년 %m월 %d일 (%a)")

FILES = ["us_data.txt", "kr_data.txt", "sector_data.txt"]

parts = [f"[ 모닝 데이터 통합본 — {DATE_STR} ]\n"]
for fname in FILES:
    if os.path.exists(fname):
        with open(fname, encoding="utf-8") as f:
            parts.append(f.read())
    else:
        parts.append(f"[{fname} 없음]\n")

content = "\n".join(parts)

# ── 1. GitHub 레포에 morning_data.txt 저장 ─────────────────────
repo_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
headers  = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}
sha = None
r = requests.get(repo_url, headers=headers)
if r.status_code == 200:
    sha = r.json().get("sha")

payload = {
    "message": f"모닝 데이터 통합 — {DATE_STR}",
    "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
}
if sha:
    payload["sha"] = sha

r = requests.put(repo_url, headers=headers, json=payload)
if r.status_code in (200, 201):
    print(f"✅ morning_data.txt 저장 완료 ({len(content)} chars)")
else:
    print(f"❌ 레포 저장 실패: {r.status_code} {r.text}")

# ── 2. GitHub Gist 업데이트 (MORNING_GIST_TOKEN 있을 때만) ──────
if not GIST_TOKEN:
    print("ℹ️  MORNING_GIST_TOKEN 없음 — Gist 업데이트 건너뜀")
else:
    gist_headers = {
        "Authorization": f"token {GIST_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    gist_payload = {
        "description": f"모닝 리포트 — {DATE_STR}",
        "files": {
            "morning_data.txt": {"content": content}
        }
    }

    # 기존 Gist ID 조회 (레포에 저장된 파일에서)
    gist_id = None
    id_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GIST_ID_FILE}"
    r = requests.get(id_url, headers=headers)
    if r.status_code == 200:
        raw = base64.b64decode(r.json()["content"]).decode("utf-8").strip()
        if raw:
            gist_id = raw

    if gist_id:
        # 기존 Gist 업데이트
        r = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers=gist_headers, json=gist_payload
        )
        if r.status_code == 200:
            gist_url = r.json()["html_url"]
            raw_url  = r.json()["files"]["morning_data.txt"]["raw_url"]
            print(f"✅ Gist 업데이트 완료")
            print(f"   Gist URL : {gist_url}")
            print(f"   Raw URL  : {raw_url}")
        else:
            print(f"❌ Gist 업데이트 실패: {r.status_code} {r.text}")
            gist_id = None  # 실패 시 새로 생성

    if not gist_id:
        # 신규 Gist 생성
        gist_payload["public"] = True
        r = requests.post(
            "https://api.github.com/gists",
            headers=gist_headers, json=gist_payload
        )
        if r.status_code == 201:
            new_id   = r.json()["id"]
            gist_url = r.json()["html_url"]
            raw_url  = r.json()["files"]["morning_data.txt"]["raw_url"]
            print(f"✅ Gist 신규 생성 완료")
            print(f"   Gist URL : {gist_url}")
            print(f"   Raw URL  : {raw_url}")

            # Gist ID를 레포에 저장
            id_sha = None
            r2 = requests.get(id_url, headers=headers)
            if r2.status_code == 200:
                id_sha = r2.json().get("sha")
            id_payload = {
                "message": "Gist ID 저장",
                "content": base64.b64encode(new_id.encode()).decode(),
            }
            if id_sha:
                id_payload["sha"] = id_sha
            requests.put(id_url, headers=headers, json=id_payload)
        else:
            print(f"❌ Gist 생성 실패: {r.status_code} {r.text}")
