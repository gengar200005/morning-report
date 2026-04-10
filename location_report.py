import os
import re
import json
import base64
import requests
from datetime import datetime
import pytz

GITHUB_TOKEN = os.environ["MORNINGREPOT"]
GITHUB_REPO  = "gengar200005/morning-report"

KST       = pytz.timezone("Asia/Seoul")
NOW       = datetime.now(KST)
TODAY_STR = NOW.strftime("%Y년 %m월 %d일")

def load_location_data():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/개원입지분석_v3.html"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    r    = requests.get(url, headers=headers, timeout=10)
    html = base64.b64decode(r.json()["content"]).decode("utf-8")

    match = re.search(r'const D=(\[.*?\]);', html, re.DOTALL)
    if not match:
        raise Exception("개원입지 데이터 파싱 실패")

    data = json.loads(match.group(1))
    return sorted(data, key=lambda x: x["composite_score"], reverse=True)

def pick_today(ranked):
    day_of_year = NOW.timetuple().tm_yday
    idx         = (day_of_year - 1) % len(ranked)
    next_idx    = (idx + 1) % len(ranked)
    return ranked[idx], ranked[next_idx], idx + 1

def build_text(ranked):
    today_zone, tomorrow_zone, today_rank = pick_today(ranked)
    z  = today_zone
    tz = tomorrow_zone

    lines = []
    lines.append(f"=== 개원입지 분석 데이터 ({TODAY_STR}) ===")
    lines.append(f"총 {len(ranked)}개 생활권 | 오늘 분석: {today_rank}위")
    lines.append("")
    lines.append(f"[TODAY_ZONE]")
    lines.append(f"순위: {today_rank}/{len(ranked)}")
    lines.append(f"생활권: {z['zone']} ({z['region']})")
    lines.append(f"종합점수: {z['composite_score']}")
    lines.append("")
    lines.append(f"[인구 현황]")
    lines.append(f"총인구: {z['population']:,}명")
    lines.append(f"0~14세: {z['age_0_14']:,}명 ({z['age_0_14']/z['population']*100:.1f}%)")
    lines.append(f"15~34세: {z['age_15_34']:,}명 ({z['age_15_34']/z['population']*100:.1f}%)")
    lines.append(f"35~54세: {z['age_35_54']:,}명 ({z['age_35_54']/z['population']*100:.1f}%)")
    lines.append(f"55~64세: {z['age_55_64']:,}명 ({z['age_55_64']/z['population']*100:.1f}%)")
    lines.append(f"65세이상: {z['age_65_plus']:,}명 ({z['age_65_plus']/z['population']*100:.1f}%)")
    lines.append(f"고령화율: {z['elderly_ratio']}%")
    lines.append(f"중장년비율(35~64세): {z['middle_aged_ratio']}%")
    lines.append("")
    lines.append(f"[의료 경쟁 현황]")
    lines.append(f"내과계 클리닉: {z['naegwa_clinics']}개")
    lines.append(f"병원급: {z['hospitals_count']}개")
    lines.append(f"전체 의원: {z['total_clinics']}개")
    lines.append(f"의사 수: 총 {z['total_doctors']}명 (전문의 {z['specialists']}명)")
    lines.append(f"인구당 내과수: {z['pop_per_naegwa']:,}명/개")
    lines.append(f"클리닉 밀도: {z['clinic_density']}개/천명")
    lines.append("")
    lines.append(f"[세부 점수]")
    lines.append(f"경쟁점수: {z['score_competition']}/100 (높을수록 경쟁 낮음)")
    lines.append(f"고령화점수: {z['score_elderly']}/100")
    lines.append(f"인구점수: {z['score_population']}/100")
    lines.append(f"중장년점수: {z['score_middle_aged']}/100")
    lines.append("")
    lines.append(f"[전체 TOP 5 비교]")
    for i, r in enumerate(ranked[:5], 1):
        mark = "◀ 오늘" if i == today_rank else ""
        lines.append(
            f"{i}위 {r['zone']} | 종합 {r['composite_score']} "
            f"| 고령화 {r['elderly_ratio']}% | 인구/내과 {r['pop_per_naegwa']:,}명 {mark}"
        )
    lines.append("")
    lines.append(f"[내일 예정]")
    lines.append(f"{ranked.index(tz)+1}위 {tz['zone']} ({tz['region']}) — 종합 {tz['composite_score']}점")

    return "\n".join(lines)

def save_to_github(content):
    fname   = "location_data.txt"
    url     = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{fname}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    sha = None
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        sha = r.json().get("sha")

    payload = {
        "message": f"개원입지 데이터 업데이트 — {TODAY_STR}",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"✅ location_data.txt 저장 완료")
    else:
        print(f"❌ 저장 실패: {r.status_code} {r.text[:200]}")

if __name__ == "__main__":
    print("📡 개원입지 데이터 파싱 중...")
    ranked = load_location_data()
    print(f"  {len(ranked)}개 생활권 로드 완료")

    today, tomorrow, rank = pick_today(ranked)
    print(f"  오늘 분석 대상: {rank}위 {today['zone']} (종합 {today['composite_score']}점)")

    text = build_text(ranked)

    print("💾 GitHub 저장 중...")
    save_to_github(text)
    print("🎉 완료!")
