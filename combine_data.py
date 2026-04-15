import os
import base64
import requests
from datetime import datetime
import pytz

GITHUB_TOKEN = os.environ["MORNINGREPOT"]
GITHUB_REPO  = "gengar200005/morning-report"
GITHUB_FILE  = "morning_data.txt"

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

# GitHub 저장
url     = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}
sha = None
r = requests.get(url, headers=headers)
if r.status_code == 200:
    sha = r.json().get("sha")

payload = {
    "message": f"모닝 데이터 통합 — {DATE_STR}",
    "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
}
if sha:
    payload["sha"] = sha

r = requests.put(url, headers=headers, json=payload)
if r.status_code in (200, 201):
    print(f"✅ morning_data.txt 저장 완료 ({len(content)} chars)")
else:
    print(f"❌ 저장 실패: {r.status_code} {r.text}")
