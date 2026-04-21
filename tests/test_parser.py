"""morning_data_parser 회귀 테스트.

fixture는 실제 2026-04-21 morning_data.txt. 포맷이 변경될 때마다
fixture도 업데이트하면서 기대값을 같이 수정한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reports.parsers.morning_data_parser import parse_morning_data

FIXTURE = Path(__file__).parent / "fixtures" / "morning_data_20260421.txt"


@pytest.fixture(scope="module")
def data() -> dict:
    return parse_morning_data(FIXTURE)


def test_date_and_weekday(data):
    assert data["date"] == "2026-04-21"
    assert data["weekday"] == "Tue"


def test_us_indices(data):
    assert len(data["us_indices"]) == 4
    sp500 = data["us_indices"][0]
    assert sp500["name"] == "S&P 500"
    assert sp500["value"] == 7109.14
    assert sp500["change_pct"] == -0.24
    assert sp500["ma20"] is True

    russell = data["us_indices"][3]
    assert russell["name"] == "Russell 2000"
    assert russell["change_pct"] == 0.58


def test_vix(data):
    assert data["vix"]["value"] == 18.87
    assert data["vix"]["status"] == "안정"


def test_rates_fx(data):
    fx = data["rates_fx"]
    assert fx["us10y"]["value"] == 4.25
    assert fx["us10y"]["change_pct"] == 0.09
    assert fx["us2y"]["value"] == 3.60
    assert fx["usd_krw"]["value"] == 1470.56
    assert fx["yield_spread"] == 0.65


def test_commodities(data):
    c = data["commodities"]
    assert c["wti"]["value"] == 85.89
    assert c["wti"]["change_pct"] == 2.43
    assert c["gold"]["value"] == 4841.0
    assert c["gold"]["change_pct"] == -0.34


def test_us_sectors(data):
    sectors = data["us_sectors"]
    assert len(sectors) == 7
    soxx = next(s for s in sectors if s["ticker"] == "SOXX")
    assert soxx["name"] == "반도체"
    assert soxx["change_pct"] == 0.44
    xlv = next(s for s in sectors if s["ticker"] == "XLV")
    assert xlv["change_pct"] == -0.93
    assert xlv["ma60"] is False
    assert xlv["ma120"] is False


def test_kr_indices(data):
    kospi, kosdaq = data["kr_indices"]
    assert kospi["name"] == "KOSPI"
    assert kospi["value"] == 6191.92
    assert kospi["change_pct"] == -0.55
    assert kospi["trend_5d"] == 5.7
    assert kospi["trend_20d"] == 7.1
    assert kospi["pct_from_52w_high"] == -1.8
    assert kospi["is_20d_new_high"] is False

    assert kosdaq["name"] == "KOSDAQ"
    assert kosdaq["is_20d_new_high"] is True
    assert kosdaq["pct_from_52w_high"] == -1.9


def test_kospi_flow(data):
    flow = data["kospi_flow"]
    assert flow["foreign"] == -2338
    assert flow["institution"] == 2937
    assert flow["retail"] == -3159


def test_market_context(data):
    ctx = data["market_context"]
    assert ctx["vix"] == 18.87
    assert ctx["vix_ok"] is True
    assert ctx["kospi_ma20"] == 5633.05
    assert ctx["kospi_ma60_ok"] is True
    assert ctx["kosdaq_ma120"] == 1013.73


def test_minervini_counts(data):
    m = data["minervini"]
    assert m["total"] == 162
    assert m["counts"] == {"A": 24, "B": 40, "C": 5, "D": 93}
    assert len(m["grade_a"]) == 24
    assert len(m["grade_b"]) == 40
    assert m["grade_c"] == ["DL이앤씨", "한전KPS", "SK네트웍스", "현대백화점", "현대엘리베이터"]


def test_minervini_grade_a_first(data):
    sk = data["minervini"]["grade_a"][0]
    assert sk["name"] == "SK하이닉스"
    assert sk["code"] == "000660"
    assert sk["rs"] == 99
    assert sk["price"] == 1166000
    assert sk["ma50"] == 961860
    assert sk["per"] == 40.6
    assert sk["roe"] == 26.8
    assert sk["stop_price"] == 1084380
    assert sk["supply_ok"] is True
    assert sk["supply_20d"] == 231723
    assert sk["pct_from_52w_high"] == 0.0


def test_minervini_grade_b_new_badge(data):
    new_rows = [b for b in data["minervini"]["grade_b"] if b["is_new"]]
    names = {b["name"] for b in new_rows}
    assert "이마트" in names
    assert "동국제강" in names
    for row in new_rows:
        assert row["signal_days"] == 0


def test_sector_etf_tiers(data):
    etf = data["sector_etf"]
    assert len(etf["leaders"]) == 1
    assert etf["leaders"][0]["name"] == "KODEX IT"
    assert etf["leaders"][0]["score"] == 99.0
    assert len(etf["strong"]) == 3
    strong_names = {s["name"] for s in etf["strong"]}
    assert {"KODEX 반도체", "TIGER 2차전지테마", "KODEX 2차전지산업"} <= strong_names
    assert len(etf["neutral"]) == 5
    assert len(etf["weak"]) == 6
    weak_names = {w["name"] for w in etf["weak"]}
    assert "TIGER 반도체TOP10" in weak_names
    assert "KODEX K-방산" in weak_names


def test_sector_etf_weekly_changes(data):
    changes = data["sector_etf"]["weekly_changes"]
    assert len(changes) == 5
    by_name = {c["name"]: c["delta"] for c in changes}
    assert by_name["KODEX 2차전지산업"] == 6.0
    assert by_name["KODEX 보험"] == -6.0


def test_holdings(data):
    assert len(data["holdings"]) == 1
    h = data["holdings"][0]
    assert h["name"] == "두산에너빌리티"
    assert h["code"] == "034020"
    assert h["grade"] == "B"
    assert h["buy_price"] == 109000
    assert h["current_price"] == 111000
    assert h["change_pct"] == 1.83
    assert h["stop_price"] == 101000
    assert h["core"] == 8
    assert h["align"] is True
    assert h["pct_from_52w_high"] == 0.0


def test_macro_calendar(data):
    cal = data["macro_calendar"]
    fomc = next(e for e in cal if e["event"] == "FOMC")
    assert fomc["dday"] == 15
    assert fomc["date"] == "2026-05-06"
    assert fomc["impact"] == "high"
    cpi = next(e for e in cal if e["event"].startswith("CPI"))
    assert cpi["date"] == "2026-05-13"
    earnings = next(e for e in cal if "어닝" in e["event"])
    assert earnings["dday"] is None
