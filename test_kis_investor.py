"""
KIS 시장별 투자자매매동향(일별) API raw 응답 확인용 테스트 스크립트
kr_report.py 전체를 돌리지 않고 수급 API 호출 결과만 빠르게 확인.

사용:
    export KIS_APP_KEY=...
    export KIS_APP_SECRET=...
    python test_kis_investor.py
"""

import os
import json
import requests
from datetime import datetime, timedelta
import pytz

KIS_APP_KEY    = os.environ["KIS_APP_KEY"]
KIS_APP_SECRET = os.environ["KIS_APP_SECRET"]
KIS_BASE_URL   = "https://openapi.koreainvestment.com:9443"

KST = pytz.timezone("Asia/Seoul")
NOW = datetime.now(KST)

def prev_trading_day():
    d = NOW.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")

def get_token():
    r = requests.post(
        f"{KIS_BASE_URL}/oauth2/tokenP",
        headers={"Content-Type": "application/json"},
        json={
            "grant_type": "client_credentials",
            "appkey":     KIS_APP_KEY,
            "appsecret":  KIS_APP_SECRET,
        },
        timeout=10,
    )
    return r.json()["access_token"]

def test_investor_api(token):
    prev_day = prev_trading_day()
    print(f"▶ 조회 날짜: {prev_day}")

    headers = {
        "Content-Type":  "application/json",
        "authorization": f"Bearer {token}",
        "appkey":        KIS_APP_KEY,
        "appsecret":     KIS_APP_SECRET,
        "tr_id":         "FHPTJ04040000",
        "custtype":      "P",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "U",
        "FID_INPUT_ISCD":         "0001",
        "FID_INPUT_DATE_1":       prev_day,
        "FID_INPUT_ISCD_1":       "KSP",
        "FID_INPUT_DATE_2":       prev_day,
        "FID_INPUT_ISCD_2":       "0001",
    }

    r = requests.get(
        f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market",
        headers=headers,
        params=params,
        timeout=15,
    )
    data = r.json()

    print(f"\n▶ rt_cd: {data.get('rt_cd')}")
    print(f"▶ msg1:  {data.get('msg1')}")

    out = data.get("output", [])
    print(f"▶ output 개수: {len(out) if isinstance(out, list) else 'NOT LIST'}")

    if isinstance(out, list) and len(out) > 0:
        print(f"\n▶ 첫 번째 row 전체 필드({len(out[0])}개):")
        for k, v in out[0].items():
            print(f"    {k:30s} = {v!r}")

        print(f"\n▶ 투자자 관련 필드만:")
        row = out[0]
        invest_keys = [k for k in row.keys()
                       if any(x in k for x in ("frgn", "orgn", "prsn", "ntby", "pbmn", "scrt", "ivtr", "bank", "insu", "fund"))]
        for k in invest_keys:
            print(f"    {k:30s} = {row[k]!r}")

    # 전체 응답 JSON 저장 (분석용)
    with open("kis_raw_response.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n▶ 전체 응답 → kis_raw_response.json 저장 완료")

if __name__ == "__main__":
    print("🔑 KIS 토큰 발급 중...")
    token = get_token()
    print("✅ 토큰 발급 완료\n")
    test_investor_api(token)
