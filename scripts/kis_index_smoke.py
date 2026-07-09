"""KIS 지수 엔드포인트(경로 수정 8fb771e) + 게이트 소스 스모크 테스트.

publish 부작용 없음 — 데이터 조회/출력만. GH Actions workflow_dispatch
(kis_index_smoke.yml) 로 실행. 검증 항목:
  1. 수정된 KIS 지수 경로 (inquire-daily-indexchartprice) 가 404 아닌
     정상 응답 (rt_cd=0) 을 주는가 — 만성 404 의 근본 수정 확인
  2. get_index() 체인 (snapshot → KIS → yfinance) 각 결과의 date/source
  3. get_market_context() 게이트가 LTD 종가 기준으로 판정되는가
     (kospi_data_date == LTD, stale=False)
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root

import kr_report as kr

kr._LTD = kr.latest_trading_day()
ltd = kr._get_ltd()
print(f"[LTD] {ltd}")

token = kr.get_token()
print("✅ KIS 토큰 발급")

# ── 1. 수정된 지수 엔드포인트 직접 호출 (snapshot 우회) ──
prev_day = kr.prev_trading_day()
date_from = (datetime.strptime(prev_day, "%Y%m%d") - timedelta(days=14)).strftime("%Y%m%d")
ok = True
for iscd, name in [("0001", "코스피"), ("1001", "코스닥")]:
    try:
        data = kr.kis_get(token,
            "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
            "FHKUP03500100",
            {
                "FID_COND_MRKT_DIV_CODE": "U",
                "FID_INPUT_ISCD":         iscd,
                "FID_INPUT_DATE_1":       date_from,
                "FID_INPUT_DATE_2":       prev_day,
                "FID_PERIOD_DIV_CODE":    "D",
                "FID_ORG_ADJ_PRC":        "0",
            })
        rt = data.get("rt_cd")
        rows = data.get("output2") or data.get("output1") or []
        if isinstance(rows, dict):
            rows = [rows]
        print(f"  {name}: rt_cd={rt} msg={data.get('msg1')} rows={len(rows)}")
        for r in rows[-3:]:
            print(f"    {r.get('stck_bsop_date')}  종가 {r.get('bstp_nmix_prpr')}")
        dates = [r.get("stck_bsop_date") for r in rows]
        if rt != "0" or prev_day not in dates:
            ok = False
            print(f"  ❌ {name}: rt_cd 비정상 또는 LTD({prev_day}) 봉 없음")
        else:
            print(f"  ✅ {name}: KIS 경로 정상 + LTD 봉 확인")
    except Exception as e:
        ok = False
        print(f"  ❌ {name} KIS 호출 실패: {e}")

# ── 2. get_index 체인 ──
indices = kr.get_index(token)
for name, d in indices.items():
    print(f"  get_index {name}: close={d.get('close')} date={d.get('date')} source={d.get('source')}")
    if d.get("date") != ltd:
        ok = False
        print(f"  ❌ {name}: LTD({ltd}) 종가 미확보")

# ── 3. 게이트 판정 ──
ctx = kr.get_market_context(token, indices)
keys = ["kospi_cur", "kospi_ma60", "kospi_above_ma60", "kospi_data_date", "kospi_stale", "vix", "vix_ok"]
print("  market_context:", {k: ctx.get(k) for k in keys})
if ctx.get("kospi_stale") or ctx.get("kospi_data_date") != ltd:
    ok = False
    print("  ❌ 게이트 입력이 LTD 기준이 아님")
else:
    expected = ctx["kospi_cur"] > ctx["kospi_ma60"]
    print(f"  ✅ 게이트 LTD 기준 판정: cur {ctx['kospi_cur']:,.2f} vs MA60 {ctx['kospi_ma60']:,.2f} → {'통과' if expected else '미통과'}")

print("\n" + ("🎉 스모크 테스트 전 항목 통과" if ok else "💥 스모크 테스트 실패 항목 있음"))
raise SystemExit(0 if ok else 1)
