#!/usr/bin/env python3
"""
sector_report.py — ADR-003 Amendment 2+ KOSPI200 11섹터 산식
IBD 6M(50) + Breadth MA50(25) × 100/75 | universe 164종목 기준

데이터: backtest/data/sector/*.parquet (주 1회 Colab 수동 갱신, plan-003 옵션 2).
구 18 ETF 산식(RS/추세/자금) 전면 폐기 (2026-04-23 #5).
"""
import os
import json
import base64
import requests
from pathlib import Path
from datetime import datetime
import pytz
import pandas as pd

import sector_breadth as sb

KST       = pytz.timezone("Asia/Seoul")
NOW       = datetime.now(KST)
TODAY_STR = NOW.strftime("%Y년 %m월 %d일 (%a)")

GITHUB_REPO  = "gengar200005/morning-report"
GITHUB_TOKEN = os.environ["MORNINGREPOT"]
STATE_FILE   = "sector_state.json"
OUTPUT_FILE  = "sector_data.txt"

SECTOR_MAP   = "backtest/data/sector/sector_map.parquet"
STOCKS_DAILY = "backtest/data/sector/stocks_daily.parquet"
OVERRIDES    = "reports/sector_overrides.yaml"


# ── 점수 계산 ────────────────────────────────────────
def compute_scores():
    overrides = sb.load_overrides(OVERRIDES)
    scores = sb.compute_sector_scores(
        sector_map_path=SECTOR_MAP,
        stocks_daily_path=STOCKS_DAILY,
        overrides=overrides,
    )
    sd = pd.read_parquet(STOCKS_DAILY, columns=["날짜"])
    ref_date = pd.to_datetime(sd["날짜"]).max().strftime("%Y-%m-%d")
    return scores, ref_date


# ── 상태 파일 (주간 변동용) ──────────────────────────
def load_state():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STATE_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}",
               "Accept": "application/vnd.github.v3+json"}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        try:
            return json.loads(base64.b64decode(r.json()["content"]).decode()), r.json()["sha"]
        except Exception:
            pass
    return {}, None


def save_state(state, sha=None):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{STATE_FILE}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}",
               "Accept": "application/vnd.github.v3+json"}
    payload = {
        "message": f"섹터 상태 업데이트 — {TODAY_STR}",
        "content": base64.b64encode(
            json.dumps(state, ensure_ascii=False, indent=2).encode()
        ).decode(),
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"✅ {STATE_FILE} 저장 완료")
    else:
        print(f"❌ {STATE_FILE} 저장 실패: {r.status_code}")


def detect_changes(current_scores, prev_state):
    """전주 대비 등급 변화 + 5점 이상 급변 감지.

    prev 섹터 이름이 current 와 교집합 0이면 산식 전환으로 간주 → 비교 생략.
    """
    prev = prev_state.get("scores", {})
    changes = {"new_leaders": [], "demoted": [], "score_jumps": [], "transition": False}

    if prev:
        cur_secs = set(current_scores.index)
        prev_secs = set(prev.keys())
        if not (cur_secs & prev_secs):
            changes["transition"] = True
            return changes

    for sector, row in current_scores.iterrows():
        cur_grade = row["grade"]
        cur_score = float(row["score"]) if pd.notna(row["score"]) else 0
        prev_info = prev.get(sector, {})
        prev_score = prev_info.get("score", 0) or 0
        prev_grade = prev_info.get("grade")

        if cur_grade == "주도" and prev_grade != "주도":
            changes["new_leaders"].append(sector)
        elif prev_grade == "주도" and cur_grade != "주도":
            changes["demoted"].append(f"{sector}({cur_grade})")

        if abs(cur_score - prev_score) >= 5 and prev_grade is not None:
            changes["score_jumps"].append({
                "sector": sector,
                "delta": round(cur_score - prev_score, 1),
            })
    return changes


# ── 텍스트 출력 ──────────────────────────────────────
def build_text(scores, changes, ref_date):
    lines = []
    bar = "━" * 52
    lines.append(bar)
    lines.append(f"  📊 주도 섹터 현황 — {TODAY_STR}")
    lines.append(f"  산식: ADR-003 Amendment 2 (IBD 6M + Breadth MA50)")
    lines.append(f"  기준: universe 164종목 · 11섹터 · 기준일 {ref_date}")
    lines.append(bar)

    groups = [
        ("🔥 주도 (≥75점)",    lambda g: g == "주도"),
        ("📈 강세 (60~74점)",  lambda g: g == "강세"),
        ("〰️ 중립 (40~59점)",  lambda g: g == "중립"),
        ("📉 약세 (<40점)",    lambda g: g == "약세"),
    ]

    def _fmt_breadth(pct):
        return f"{pct * 100:>3.0f}%" if pd.notna(pct) else " N/A"

    for label, cond in groups:
        bucket = scores[scores["grade"].apply(cond)]
        if len(bucket) == 0:
            continue
        lines.append(f"\n{label}")
        for sector, row in bucket.iterrows():
            lines.append(
                f"  • {sector:<10} {row['score']:>5.1f}점  "
                f"({int(row['n_stocks']):>2}종목, breadth {_fmt_breadth(row['breadth_pct'])})"
            )

    # 표본부족 (N/A)
    na = scores[scores["grade"] == "N/A"]
    if len(na):
        lines.append(f"\n⚠ 표본부족 ({len(na)}섹터): "
                     + ", ".join(f"{s}({int(r['n_stocks'])}종목)" for s, r in na.iterrows()))

    # 주간 변동
    lines.append("\n⚡ 주간 변동 (전주 대비)")
    if changes.get("transition"):
        lines.append("  ℹ 산식 전환 후 첫 런 — 비교 생략 (다음 주부터 정상 감지)")
    elif not any([changes["new_leaders"], changes["demoted"], changes["score_jumps"]]):
        lines.append("  변동 없음")
    else:
        if changes["new_leaders"]:
            lines.append(f"  🆕 신규 주도 진입: {', '.join(changes['new_leaders'])}")
        if changes["demoted"]:
            lines.append(f"  ⬇️  주도 이탈: {', '.join(changes['demoted'])}")
        if changes["score_jumps"]:
            jumps = [
                f"{c['sector']} ({'+' if c['delta'] >= 0 else ''}{c['delta']}점)"
                for c in sorted(changes["score_jumps"], key=lambda x: abs(x["delta"]), reverse=True)
            ]
            lines.append(f"  📊 점수 급변: {', '.join(jumps)}")

    lines.append(bar)
    return "\n".join(lines)


# ── GitHub 파일 저장 ─────────────────────────────────
def save_to_github(filename, content):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}",
               "Accept": "application/vnd.github.v3+json"}
    r = requests.get(url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {
        "message": f"섹터 분석 — {TODAY_STR}",
        "content": base64.b64encode(content.encode()).decode(),
    }
    if sha:
        payload["sha"] = sha
    r2 = requests.put(url, headers=headers, json=payload)
    if r2.status_code in (200, 201):
        print(f"✅ {filename} 저장 완료")
    else:
        print(f"❌ {filename} 저장 실패: {r2.status_code} {r2.text[:100]}")


# ── 메인 ─────────────────────────────────────────────
if __name__ == "__main__":
    # parquet 누락 방어: 없으면 모닝리포트 전체 실패 없이 경고 출력만
    if not (Path(SECTOR_MAP).exists() and Path(STOCKS_DAILY).exists()):
        msg = (
            "━" * 52 + "\n"
            f"  📊 주도 섹터 현황 — {TODAY_STR}\n"
            f"  ⚠ 데이터 미수집: backtest/data/sector/ parquet 누락\n"
            f"  재생성: Colab 에서 notebooks/sector_data_fetch.ipynb 실행\n"
            + "━" * 52
        )
        print(msg)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(msg)
        save_to_github(OUTPUT_FILE, msg)
        raise SystemExit(0)

    print("📊 ADR-003 섹터 강도 계산 중...")
    scores, ref_date = compute_scores()
    print(f"✅ {len(scores)}섹터 점수 산출 (기준일 {ref_date})")

    print("📂 이전 상태 로드...")
    prev_state, state_sha = load_state()
    changes = detect_changes(scores, prev_state)

    text = build_text(scores, changes, ref_date)
    print("\n" + text)

    print("\n💾 저장 중...")
    new_state = {
        "date": TODAY_STR,
        "ref_date": ref_date,
        "scores": {
            sector: {
                "score": float(row["score"]) if pd.notna(row["score"]) else 0.0,
                "grade": row["grade"],
            }
            for sector, row in scores.iterrows()
        },
    }
    save_state(new_state, state_sha)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  로컬 저장 완료 → {OUTPUT_FILE}")
    save_to_github(OUTPUT_FILE, text)
    print("🎉 섹터 분석 완료!")
