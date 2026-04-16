"""
종목별 투자자 수급 API (FHKST01010900) raw 응답 확인용 테스트
- output vs output1 vs output2 중 어느 키에 데이터가 오는지 확인
- 필드명(frgn_ntby_qty, orgn_ntby_qty) 존재 여부 확인

Colab 사용법:
    1. 셀에 아래 코드 복붙
    2. 실행하면 APP_KEY / APP_SECRET 입력 프롬프트 뜸
    3. 결과로 어떤 output 키에 데이터가 있는지 바로 확인 가능
"""

import json
import requests
from getpass import getpass
from datetime import datetime, timedelta
import pytz

# ── Colab 입력 ─────────────────────────────────────
KIS_APP_KEY    = getpass("KIS_APP_KEY: ")
KIS_APP_SECRET = getpass("KIS_APP_SECRET: ")
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
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET,
        },
        timeout=10,
    )
    data = r.json()
    if "access_token" not in data:
        raise Exception(f"토큰 발급 실패: {data}")
    return data["access_token"]

def kis_get(token, path, tr_id, params):
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }
    r = requests.get(
        f"{KIS_BASE_URL}{path}",
        headers=headers,
        params=params,
        timeout=15,
    )
    return r.json()

# ── 테스트 종목 ────────────────────────────────────
TEST_STOCKS = [
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
]

# ══════════════════════════════════════════════════
#  테스트 1: 종목별 투자자 API (FHKST01010900)
#  → get_supply_20d()가 쓰는 API
# ══════════════════════════════════════════════════
def test_stock_investor(token):
    print("=" * 60)
    print("테스트 1: 종목별 투자자 API (FHKST01010900)")
    print("  → kr_report.py get_supply_20d()에서 사용")
    print("=" * 60)

    for code, name in TEST_STOCKS:
        print(f"\n{'─'*40}")
        print(f"▶ {name} ({code})")

        data = kis_get(token,
            "/uapi/domestic-stock/v1/quotations/inquire-investor",
            "FHKST01010900",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
            }
        )

        print(f"  rt_cd: {data.get('rt_cd')}")
        print(f"  msg1:  {data.get('msg1')}")

        # 핵심: 어떤 키에 데이터가 있는지 확인
        print(f"\n  ▶ 응답 top-level 키: {list(data.keys())}")
        for key in ["output", "output1", "output2"]:
            val = data.get(key)
            if val is None:
                print(f"  {key}: None (키 없음)")
            elif isinstance(val, list):
                print(f"  {key}: list, {len(val)}개 항목")
                if len(val) > 0:
                    print(f"    첫 항목 키: {list(val[0].keys())}")
            elif isinstance(val, dict):
                print(f"  {key}: dict, {len(val)}개 필드")
                print(f"    필드: {list(val.keys())}")
            else:
                print(f"  {key}: {type(val).__name__} = {val!r}")

        # 실제 데이터 찾아서 순매수 필드 확인
        for key in ["output", "output1", "output2"]:
            out = data.get(key)
            if not out:
                continue
            if isinstance(out, dict):
                out = [out]
            if isinstance(out, list) and len(out) > 0:
                row = out[0]
                print(f"\n  ▶ {key} 첫 번째 row 전체 ({len(row)}개 필드):")
                for k, v in row.items():
                    print(f"      {k:30s} = {v!r}")

                # 순매수 관련 필드 하이라이트
                ntby_keys = [k for k in row.keys() if "ntby" in k or "frgn" in k or "orgn" in k or "prsn" in k]
                if ntby_keys:
                    print(f"\n  ▶ 순매수 관련 필드:")
                    for k in ntby_keys:
                        print(f"      {k:30s} = {row[k]!r}")

                # 현재 코드 방식으로 계산해보기
                today_str = NOW.strftime("%Y%m%d")
                total, count = 0, 0
                for item in out:
                    if item.get("stck_bsop_date") == today_str:
                        continue
                    try:
                        frgn = int(item.get("frgn_ntby_qty", 0))
                        orgn = int(item.get("orgn_ntby_qty", 0))
                        total += frgn + orgn
                        count += 1
                    except:
                        pass
                    if count >= 20:
                        break
                print(f"\n  ▶ 20일 누적 계산 결과: {total:+,} (from {key}, {count}일)")
                print(f"     supply_ok = {total > 0}")
                break  # 첫 번째 유효 key만

        # 전체 JSON 저장
        with open(f"kis_stock_investor_{code}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n  → 전체 응답 저장: kis_stock_investor_{code}.json")

# ══════════════════════════════════════════════════
#  테스트 2: 시장 수급 API (FHPTJ04040000) — 비교용
#  → get_trading()이 쓰는 API (이건 정상 동작 확인됨)
# ══════════════════════════════════════════════════
def test_market_investor(token):
    print("\n\n" + "=" * 60)
    print("테스트 2: 시장 수급 API (FHPTJ04040000) — 비교용")
    print("  → kr_report.py get_trading()에서 사용 (정상 동작 확인됨)")
    print("=" * 60)

    prev_day = prev_trading_day()
    print(f"▶ 조회 날짜: {prev_day}")

    data = kis_get(token,
        "/uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market",
        "FHPTJ04040000",
        {
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": "0001",
            "FID_INPUT_DATE_1": prev_day,
            "FID_INPUT_ISCD_1": "KSP",
            "FID_INPUT_DATE_2": prev_day,
            "FID_INPUT_ISCD_2": "0001",
        }
    )

    print(f"  rt_cd: {data.get('rt_cd')}")
    print(f"  응답 top-level 키: {list(data.keys())}")

    out = data.get("output", [])
    if isinstance(out, list) and len(out) > 0:
        row = out[0]
        frgn = int(str(row.get("frgn_ntby_tr_pbmn", "0")).replace(",", "").strip() or "0") // 100
        orgn = int(str(row.get("orgn_ntby_tr_pbmn", "0")).replace(",", "").strip() or "0") // 100
        prsn = int(str(row.get("prsn_ntby_tr_pbmn", "0")).replace(",", "").strip() or "0") // 100
        print(f"  외국인: {frgn:+,}억  기관: {orgn:+,}억  개인: {prsn:+,}억")
    else:
        print(f"  output 비어있음")

# ══════════════════════════════════════════════════
if __name__ == "__main__":
    print("🔑 KIS 토큰 발급 중...")
    token = get_token()
    print("✅ 토큰 발급 완료\n")

    test_stock_investor(token)
    test_market_investor(token)

    print("\n\n" + "=" * 60)
    print("결론: 위 결과에서 확인할 것")
    print("  1. 종목 API가 output / output1 / output2 중 어디에 데이터를 넣는지")
    print("  2. frgn_ntby_qty / orgn_ntby_qty 필드명이 맞는지")
    print("  3. 20일 누적 계산 결과가 합리적인지")
    print("=" * 60)
