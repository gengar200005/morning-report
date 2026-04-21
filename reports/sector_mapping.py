"""종목명 → 주요 섹터 ETF 매핑.

v6.2 Readiness 카드에서 '주도 섹터 소속' 체크를 위해 사용.
섹터 ETF 스코어(leaders/strong/neutral/weak)와 교차해서 자동 판정.

Minervini 원칙상 "주도 섹터 소속 여부"가 진입 가점이므로,
여기에 없는 종목은 렌더러에서 `⚠ ETF 데이터 없음`으로 표시.

유지보수: 새 A등급 종목이 등장하면 여기 추가.
"""

# Mapping: 종목명 → 대응 섹터 ETF 이름 (morning_data.txt의 sector_etf에 등장하는 name과 정확히 일치해야 함)
STOCK_TO_SECTOR_ETF: dict[str, str] = {
    # 반도체
    "SK하이닉스": "KODEX 반도체",
    "DB하이텍": "KODEX 반도체",
    # IT·전자부품
    "삼성전기": "KODEX IT",
    "LG이노텍": "KODEX IT",
    "삼성전자": "KODEX IT",
    "LG전자": "KODEX IT",
    # 2차전지
    "삼성SDI": "KODEX 2차전지산업",
    "에코프로": "KODEX 2차전지산업",
    # 은행·금융지주
    "KB금융": "KODEX 은행",
    "신한지주": "KODEX 은행",
    "하나금융지주": "KODEX 은행",
    "우리금융지주": "KODEX 은행",
    # 증권
    "삼성증권": "KODEX 증권",
    "NH투자증권": "KODEX 증권",
    "미래에셋증권": "KODEX 증권",
    "한국금융지주": "KODEX 증권",
    "키움증권": "KODEX 증권",
    # 에너지화학
    "S-Oil": "KODEX 에너지화학",
    "SK이노베이션": "KODEX 에너지화학",
    "롯데케미칼": "KODEX 에너지화학",
    "OCI": "KODEX 에너지화학",
    # 방산 (K-방산 ETF)
    "한국항공우주": "KODEX K-방산",
    "한화시스템": "KODEX K-방산",
    "한화에어로스페이스": "KODEX K-방산",
    # 보험
    "삼성생명": "KODEX 보험",
    # 자동차
    "현대차": "KODEX 자동차",
    # 게임
    "엔씨소프트": "KODEX 게임산업",
    # 바이오
    # (현재 A등급에 없음)
    # 미디어/엔터
    # (현재 A등급에 없음)
    # --- 다음은 대응 ETF가 없거나 약한 종목 (미매핑) ---
    # SK, 두산에너빌리티, 두산, 효성, 한화, LS, 신세계, 현대건설기계, 동원F&B, 삼성엔지니어링,
    # 현대홈쇼핑, 대한유화 등
}


def resolve_sector(stock_name: str, sector_etf: dict) -> dict:
    """종목명 → 섹터 ETF 매핑 후 티어/점수 포함해 반환.

    Returns:
        {
          "etf_name": "KODEX 반도체" or None,
          "tier": "leaders"/"strong"/"neutral"/"weak" or None,
          "score": float or None,
          "in_leading": bool,   # leaders + strong 에 속하면 True
        }
    """
    etf_name = STOCK_TO_SECTOR_ETF.get(stock_name)
    if not etf_name:
        return {"etf_name": None, "tier": None, "score": None, "in_leading": False}

    for tier in ("leaders", "strong", "neutral", "weak"):
        for etf in sector_etf.get(tier, []):
            if etf["name"] == etf_name:
                return {
                    "etf_name": etf_name,
                    "tier": tier,
                    "score": etf["score"],
                    "in_leading": tier in ("leaders", "strong"),
                }
    return {"etf_name": etf_name, "tier": None, "score": None, "in_leading": False}
