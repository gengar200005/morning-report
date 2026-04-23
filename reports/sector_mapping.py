"""종목명 → KOSPI200 11섹터 매핑 (ADR-003 Amendment 3).

sector_overrides.yaml 의 ticker_overrides (164종목) 를 로드하고
backtest/universe.py 의 (code, name) 리스트로 종목명 → 티커 역매핑을 구성한다.

Minervini 원칙상 "주도 섹터 소속 여부"가 진입 가점이므로,
해당 섹터가 `leaders` 또는 `strong` 티어에 있으면 ✓ 표시.

유지보수:
- 새 종목: `reports/sector_overrides.yaml` 의 `ticker_overrides` 에 추가
- 종목명 변경: `backtest/universe.py` 동기화
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from backtest.universe import UNIVERSE

OVERRIDES_PATH = Path(__file__).parent / "sector_overrides.yaml"


@lru_cache(maxsize=1)
def _load_ticker_to_sector() -> dict[str, str]:
    """sector_overrides.yaml::ticker_overrides → {ticker: sector_name}."""
    with open(OVERRIDES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return dict(data.get("ticker_overrides", {}))


@lru_cache(maxsize=1)
def _load_name_to_ticker() -> dict[str, str]:
    """backtest/universe.py::UNIVERSE → {name: ticker}."""
    return {name: code for code, name in UNIVERSE}


def resolve_sector(stock_name: str, sector_adr003: dict) -> dict:
    """종목명 → 섹터명 매핑 후 신 11섹터 등급/점수 포함해 반환.

    Args:
        stock_name: universe 에 등록된 종목명 (예: "삼성SDI").
        sector_adr003: morning_data_parser 의 sector_adr003 dict.
            키: leaders / strong / neutral / weak / na (list of items),
                각 item = {"name": "반도체", "score": 100.0, "n_stocks": 5, "breadth_pct": 1.0}.

    Returns:
        {
          "sector": "2차전지" or None,   # universe/overrides 매칭 실패 시 None
          "tier": "leaders"/"strong"/"neutral"/"weak"/"na"/None,
          "score": float or None,
          "in_leading": bool,            # leaders + strong 에 속하면 True
        }
    """
    name_to_ticker = _load_name_to_ticker()
    ticker_to_sector = _load_ticker_to_sector()

    ticker = name_to_ticker.get(stock_name)
    sector = ticker_to_sector.get(ticker) if ticker else None
    if not sector:
        return {"sector": None, "tier": None, "score": None, "in_leading": False}

    for tier in ("leaders", "strong", "neutral", "weak", "na"):
        for item in sector_adr003.get(tier, []) or []:
            if item.get("name") == sector:
                return {
                    "sector": sector,
                    "tier": tier,
                    "score": item.get("score"),
                    "in_leading": tier in ("leaders", "strong"),
                }
    return {"sector": sector, "tier": None, "score": None, "in_leading": False}
