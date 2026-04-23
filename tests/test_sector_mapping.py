"""reports/sector_mapping.py 회귀 테스트.

resolve_sector 가 universe.py + sector_overrides.yaml 을 읽어
종목명 → 섹터명 → 티어/점수 정확히 반환하는지 확인.
"""
from __future__ import annotations

import pytest

from reports.sector_mapping import (
    _load_name_to_ticker,
    _load_ticker_to_sector,
    resolve_sector,
)


@pytest.fixture
def sample_adr003() -> dict:
    return {
        "leaders": [
            {"name": "반도체", "score": 100.0, "n_stocks": 5, "breadth_pct": 1.0},
            {"name": "건설", "score": 89.8, "n_stocks": 8, "breadth_pct": 0.88},
        ],
        "strong": [
            {"name": "2차전지", "score": 64.2, "n_stocks": 10, "breadth_pct": 0.80},
        ],
        "neutral": [
            {"name": "금융", "score": 57.9, "n_stocks": 24, "breadth_pct": 0.46},
            {"name": "자동차", "score": 56.8, "n_stocks": 9, "breadth_pct": 0.67},
        ],
        "weak": [
            {"name": "바이오", "score": 10.8, "n_stocks": 7, "breadth_pct": 0.14},
        ],
        "na": [],
    }


def test_load_name_to_ticker_covers_core():
    """universe.py 핵심 종목이 name→ticker 매핑에 들어와 있는지."""
    mapping = _load_name_to_ticker()
    assert mapping["삼성전자"] == "005930"
    assert mapping["삼성SDI"] == "006400"
    assert mapping["LG이노텍"] == "011070"


def test_load_ticker_to_sector_has_164():
    mapping = _load_ticker_to_sector()
    assert len(mapping) == 164
    assert mapping["006400"] == "2차전지"
    assert mapping["011070"] == "반도체"


def test_resolve_leading_stock(sample_adr003):
    r = resolve_sector("LG이노텍", sample_adr003)
    assert r["sector"] == "반도체"
    assert r["tier"] == "leaders"
    assert r["score"] == 100.0
    assert r["in_leading"] is True


def test_resolve_strong_stock(sample_adr003):
    r = resolve_sector("삼성SDI", sample_adr003)
    assert r["sector"] == "2차전지"
    assert r["tier"] == "strong"
    assert r["in_leading"] is True


def test_resolve_weak_stock(sample_adr003):
    r = resolve_sector("셀트리온", sample_adr003)
    assert r["sector"] == "바이오"
    assert r["tier"] == "weak"
    assert r["in_leading"] is False


def test_resolve_neutral_stock(sample_adr003):
    r = resolve_sector("KB금융", sample_adr003)
    assert r["sector"] == "금융"
    assert r["tier"] == "neutral"
    assert r["in_leading"] is False


def test_resolve_unknown_name(sample_adr003):
    r = resolve_sector("가상의회사", sample_adr003)
    assert r["sector"] is None
    assert r["tier"] is None
    assert r["in_leading"] is False


def test_resolve_known_stock_but_sector_not_in_scores(sample_adr003):
    """종목은 overrides 에 있으나 점수 dict 에 해당 섹터 없는 경우."""
    minimal = {"leaders": [], "strong": [], "neutral": [], "weak": [], "na": []}
    r = resolve_sector("LG이노텍", minimal)
    assert r["sector"] == "반도체"  # 매핑은 성공
    assert r["tier"] is None         # 점수 dict 에는 없음
    assert r["in_leading"] is False
