import os
import base64
import requests
from datetime import datetime, date
import pytz

GITHUB_TOKEN  = os.environ["MORNINGREPOT"]
MORNING_PAT   = os.environ.get("MORNING_PAT", GITHUB_TOKEN)  # public 레포 쓰기용 PAT
GITHUB_REPO   = "gengar200005/morning-report"
PUBLIC_REPO   = "gengar200005/morning-data"
GITHUB_FILE   = "morning_data.txt"

KST      = pytz.timezone("Asia/Seoul")
NOW      = datetime.now(KST)
DATE_STR = NOW.strftime("%Y년 %m월 %d일 (%a)")
TODAY    = NOW.date()
YMD      = NOW.strftime("%Y%m%d")
YEAR     = NOW.strftime("%Y")
MONTH    = NOW.strftime("%m")

# ── 3순위: 매크로 캘린더 ────────────────────────────
# 2026-04-30 ADR (옵션 A): 하드코딩 일정 신뢰 못함 (FOMC 5/6 가짜 사고).
# 매크로 카드는 `/analyze` 가 신뢰 경제지 뉴스 (Reuters / Bloomberg / WSJ /
# CNBC / FT / 한경 / 매경 / 연합인포맥스 등) 기반으로 100% live 작성.
# 본 함수는 parser/template 호환을 위한 빈 stub 만 emit.
MACRO_EVENTS: dict = {}  # 의도적 빈 dict — 하드코딩 폐기

# 어닝시즌 월 (1월·4월·7월·10월 시작 후 약 6주)
EARNING_MONTHS = {1,2,4,5,7,8,10,11}

def build_macro_section():
    season = "진행 중 ⚠️  개별 변동성 주의" if TODAY.month in EARNING_MONTHS else "비수기"
    return "\n".join([
        "【 매크로 캘린더 】",
        "  (FOMC/NFP/CPI 일정·해석은 /analyze 가 신뢰 경제지 뉴스 기반 작성 — 하드코딩 폐기 ADR-015)",
        f"  어닝시즌   {season}",
    ])

# ── 데이터 파일 합치기 ──────────────────────────────
FILES = ["us_data.txt", "kr_data.txt", "sector_data.txt", "holdings_data.txt"]

parts = [f"[ 모닝 데이터 통합본 — {DATE_STR} ]\n"]
for fname in FILES:
    if os.path.exists(fname):
        with open(fname, encoding="utf-8") as f:
            parts.append(f.read())
    else:
        parts.append(f"[{fname} 없음]\n")

parts.append("\n" + build_macro_section())

content = "\n".join(parts)

# 로컬 workspace에도 저장 — Phase 2 렌더 파이프라인이 같은 워크플로우 내에서 읽음
with open(GITHUB_FILE, "w", encoding="utf-8") as f:
    f.write(content)

# ── 1. GitHub 레포에 morning_data.txt 저장 ─────────────
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}
repo_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
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

# ── 2. public 레포(morning-data)에도 저장 ─────────────
pub_headers = {
    "Authorization": f"token {MORNING_PAT}",
    "Accept": "application/vnd.github.v3+json",
}
pub_url = f"https://api.github.com/repos/{PUBLIC_REPO}/contents/{GITHUB_FILE}"
sha2 = None
r2 = requests.get(pub_url, headers=pub_headers)
if r2.status_code == 200:
    sha2 = r2.json().get("sha")

payload2 = {
    "message": f"모닝 데이터 업데이트 — {DATE_STR}",
    "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
}
if sha2:
    payload2["sha"] = sha2

r2 = requests.put(pub_url, headers=pub_headers, json=payload2)
if r2.status_code in (200, 201):
    raw_url = f"https://raw.githubusercontent.com/{PUBLIC_REPO}/main/{GITHUB_FILE}"
    print(f"✅ public 레포 저장 완료")
    print(f"   Raw URL: {raw_url}")
else:
    print(f"❌ public 레포 저장 실패: {r2.status_code} {r2.text}")

# ── 3. 날짜 포함 파일 업로드 (CDN 캐시 우회용) ─────────
def put_public(path, commit_msg):
    url = f"https://api.github.com/repos/{PUBLIC_REPO}/contents/{path}"
    cur_sha = None
    g = requests.get(url, headers=pub_headers)
    if g.status_code == 200:
        cur_sha = g.json().get("sha")
    body = {
        "message": commit_msg,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
    }
    if cur_sha:
        body["sha"] = cur_sha
    resp = requests.put(url, headers=pub_headers, json=body)
    if resp.status_code in (200, 201):
        print(f"✅ {path} 저장 완료")
        print(f"   Raw URL: https://raw.githubusercontent.com/{PUBLIC_REPO}/main/{path}")
    else:
        print(f"❌ {path} 저장 실패: {resp.status_code} {resp.text}")

dated_name    = f"morning_data_{YMD}.txt"
archive_path  = f"{YEAR}/{MONTH}/{dated_name}"

put_public(dated_name,   f"모닝 데이터 {YMD} (최신 날짜 스냅샷)")
put_public(archive_path, f"모닝 데이터 아카이브 — {DATE_STR}")

# ── 3.5. 스크리닝 state 푸시 (쿨다운 추적 — private repo에만) ──
STATE_PATH = "reports/state/screening_history.json"
if os.path.exists(STATE_PATH):
    with open(STATE_PATH, encoding="utf-8") as _f:
        _state_content = _f.read()
    _state_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STATE_PATH}"
    _state_sha = None
    _rs = requests.get(_state_url, headers=headers)
    if _rs.status_code == 200:
        _state_sha = _rs.json().get("sha")
    _state_payload = {
        "message": f"스크리닝 state 업데이트 — {DATE_STR}",
        "content": base64.b64encode(_state_content.encode("utf-8")).decode("utf-8"),
    }
    if _state_sha:
        _state_payload["sha"] = _state_sha
    _rs = requests.put(_state_url, headers=headers, json=_state_payload)
    if _rs.status_code in (200, 201):
        print(f"✅ {STATE_PATH} 저장 완료")
    else:
        print(f"❌ state 저장 실패: {_rs.status_code} {_rs.text}")
else:
    print(f"⚠️ {STATE_PATH} 로컬에 없음 — state push 스킵")

# ── 4. Google Drive 업로드 (Claude 커넥터용, OAuth 사용자 위임) ─
# 실패해도 GitHub 커밋 파이프라인과 독립. Secrets 누락 시 조용히 스킵.
GDRIVE_FOLDER_ID     = os.environ.get("GDRIVE_FOLDER_ID")
GDRIVE_CLIENT_ID     = os.environ.get("GDRIVE_OAUTH_CLIENT_ID")
GDRIVE_CLIENT_SECRET = os.environ.get("GDRIVE_OAUTH_CLIENT_SECRET")
GDRIVE_REFRESH_TOKEN = os.environ.get("GDRIVE_OAUTH_REFRESH_TOKEN")

_gdrive_ready = all([
    GDRIVE_FOLDER_ID, GDRIVE_CLIENT_ID,
    GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN,
])

if _gdrive_ready:
    try:
        from gdrive_upload import upload_text

        fid_latest = upload_text(
            GITHUB_FILE, content, GDRIVE_FOLDER_ID,
            GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN,
        )
        if fid_latest:
            print(f"✅ Drive 업로드 완료: {GITHUB_FILE} (id={fid_latest})")

        fid_dated = upload_text(
            dated_name, content, GDRIVE_FOLDER_ID,
            GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN,
        )
        if fid_dated:
            print(f"✅ Drive 업로드 완료: {dated_name} (id={fid_dated})")
    except Exception as e:
        print(f"❌ Drive 업로드 중 예외: {e}")
else:
    print("⚠️  GDRIVE_* OAuth Secrets 누락 — Drive 업로드 스킵")
