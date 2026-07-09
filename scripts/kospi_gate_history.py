"""코스피 시장 게이트 (종가 > MA60 & VIX < 35) 히스토리 복기 — 진단용, publish 없음.

KIS inquire-daily-indexchartprice 로 2023-09 ~ 현재 코스피 일봉을 60일
윈도우로 수집 → MA60 계산 → 게이트 ON/OFF 전환점 + 구간 길이 출력.
VIX 는 yfinance ^VIX 히스토리 (calendar ffill 정렬).
"""
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import kr_report as kr
import yfinance as yf

token = kr.get_token()
print("✅ KIS 토큰 발급")

START = datetime(2023, 9, 1)   # MA60 워밍업 포함 (2024-01 부터 판정 유효)
END   = datetime.strptime(kr._get_ltd(), "%Y%m%d")

# ── 코스피 일봉 수집 (60일 윈도우) ──
closes = {}  # "YYYYMMDD" -> float
cur = START
while cur <= END:
    win_end = min(cur + timedelta(days=59), END)
    try:
        data = kr.kis_get(token,
            "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
            "FHKUP03500100",
            {
                "FID_COND_MRKT_DIV_CODE": "U",
                "FID_INPUT_ISCD":         "0001",
                "FID_INPUT_DATE_1":       cur.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2":       win_end.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE":    "D",
                "FID_ORG_ADJ_PRC":        "0",
            })
        rows = data.get("output2") or []
        if isinstance(rows, dict):
            rows = [rows]
        for r in rows:
            d = r.get("stck_bsop_date")
            c = float(r.get("bstp_nmix_prpr") or 0)
            if d and c > 0:
                closes[d] = c
    except Exception as e:
        print(f"  ⚠ {cur:%Y%m%d}~{win_end:%Y%m%d} 실패: {e}")
    time.sleep(0.3)
    cur = win_end + timedelta(days=1)

dates = sorted(closes)
print(f"✅ 코스피 일봉 {len(dates)}개 ({dates[0]} ~ {dates[-1]})")

# ── VIX 히스토리 (calendar ffill) ──
vix_hist = yf.Ticker("^VIX").history(period="3y")["Close"].dropna()
vix_by_date = {}
prev = None
d0 = min(vix_hist.index).date()
d1 = datetime.strptime(dates[-1], "%Y%m%d").date()
vh = {ts.date(): float(v) for ts, v in vix_hist.items()}
d = d0
while d <= d1:
    if d in vh:
        prev = vh[d]
    if prev is not None:
        vix_by_date[d.strftime("%Y%m%d")] = prev
    d += timedelta(days=1)
print(f"✅ VIX {len(vix_hist)}개 ({min(vh)} ~ {max(vh)})")

# ── MA60 + 게이트 전환점 ──
vals = [closes[d] for d in dates]
print("\n[게이트 전환 타임라인 — 2024-01 이후 / K=코스피>MA60, V=VIX<35]")
state = None
seg_start = None
transitions = []
for i, d in enumerate(dates):
    if i < 59 or d < "20240101":
        continue
    ma60 = sum(vals[i-59:i+1]) / 60
    k_ok = vals[i] > ma60
    vix = vix_by_date.get(d)
    v_ok = (vix is not None and vix < 35)
    gate = k_ok and v_ok
    if state is None:
        state, seg_start = gate, d
        continue
    if gate != state:
        n_days = sum(1 for x in dates if seg_start <= x < d)
        transitions.append((seg_start, d, state, n_days))
        print(f"  {seg_start} ~ {d} 직전 : {'🟢 ON ' if state else '🔴 OFF'} ({n_days}거래일)"
              + ("" if state else f"  → {d} 재진입 (종가 {vals[i]:,.2f} > MA60 {ma60:,.2f}, VIX {vix:.1f})"))
        state, seg_start = gate, d
# 마지막 구간
n_days = sum(1 for x in dates if x >= seg_start)
print(f"  {seg_start} ~ 현재     : {'🟢 ON ' if state else '🔴 OFF'} ({n_days}거래일)")

# ── 참고: OFF 사유 분해 (최근 12개월 K/V 각각) ──
print("\n[최근 18개월 월말 스냅샷: 종가 / MA60 / VIX / 게이트]")
last_in_month = {}
for i, d in enumerate(dates):
    if i >= 59 and d >= "20250101":
        last_in_month[d[:6]] = i
for ym, i in sorted(last_in_month.items()):
    d = dates[i]
    ma60 = sum(vals[i-59:i+1]) / 60
    vix = vix_by_date.get(d)
    k_ok = vals[i] > ma60
    v_ok = (vix is not None and vix < 35)
    print(f"  {d}: {vals[i]:>9,.2f} / MA60 {ma60:>9,.2f} {'✓' if k_ok else '✗'} / VIX {vix:>5.1f} {'✓' if v_ok else '✗'} → {'🟢' if (k_ok and v_ok) else '🔴'}")

print("\n🎉 게이트 히스토리 복기 완료")
