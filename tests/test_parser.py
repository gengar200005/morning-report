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
    assert len(sectors) == 7  # 구 fixture (2026-04-21) 기준. 신 포맷은 별도 테스트
    soxx = next(s for s in sectors if s["ticker"] == "SOXX")
    assert soxx["name"] == "반도체"
    assert soxx["change_pct"] == 0.44
    assert soxx["leaders"] == "NVDA·AVGO·AMD"
    assert soxx["super_sector"] == "sensitive"
    xlv = next(s for s in sectors if s["ticker"] == "XLV")
    assert xlv["change_pct"] == -0.93
    assert xlv["ma60"] is False
    assert xlv["ma120"] is False
    assert xlv["leaders"] == "LLY·UNH·JNJ"
    assert xlv["super_sector"] == "defensive"


def test_us_sectors_multi_arrow():
    """morning_report.py 가 pct 크기에 따라 ▲/▼ 를 최대 10개까지 찍는 것에 대응.

    회귀: 2026-04-24 세션에서 regex `[▲▼]?` 가 ±1% 이상 등락 섹터를 놓쳐
    7섹터 중 3섹터만 파싱되던 버그 (jvYaw `13d91a7` fix 재반영).
    """
    from reports.parsers.morning_data_parser import _parse_us_sectors

    body = (
        "  IT(XLK)              +2.50%  ▲▲▲▲▲  MA20✓/MA60✓/MA120✓\n"
        "  에너지(XLE)           -2.10%  ▼▼▼▼  MA20✗/MA60✗/MA120✓\n"
        "  부동산(XLRE)          -0.70%  ▼  MA20✗/MA60✓/MA120✓\n"
        "  금융(XLF)             +0.20%    MA20✓/MA60✓/MA120✓\n"
    )
    sectors = _parse_us_sectors(body)
    tickers = {s["ticker"]: s for s in sectors}
    assert len(sectors) == 4, "multi-arrow 섹터가 regex 미스매치로 드롭됨"
    assert tickers["XLK"]["change_pct"] == 2.50
    assert tickers["XLE"]["change_pct"] == -2.10
    assert tickers["XLRE"]["change_pct"] == -0.70
    assert tickers["XLF"]["change_pct"] == 0.20


def test_us_sectors_12_etf_extended():
    """GICS 11 + SOXX 확장 포맷 파싱 — 한국 증권가 표준 명칭 전부 매칭."""
    from reports.parsers.morning_data_parser import _parse_us_sectors

    body = (
        "  반도체(SOXX)         +2.10%  ▲▲▲▲  MA20✓/MA60✓/MA120✓\n"
        "  IT(XLK)              +1.20%  ▲▲  MA20✓/MA60✓/MA120✓\n"
        "  커뮤니케이션(XLC)     +0.80%  ▲  MA20✓/MA60✓/MA120✓\n"
        "  경기소비재(XLY)       -0.40%    MA20✓/MA60✓/MA120✗\n"
        "  필수소비재(XLP)       +0.30%    MA20✓/MA60✓/MA120✓\n"
        "  에너지(XLE)          -0.50%  ▼  MA20✗/MA60✗/MA120✗\n"
        "  금융(XLF)            +0.60%  ▲  MA20✓/MA60✓/MA120✓\n"
        "  헬스케어(XLV)         +0.10%    MA20✓/MA60✓/MA120✓\n"
        "  산업재(XLI)          +0.40%    MA20✓/MA60✓/MA120✓\n"
        "  소재(XLB)            +0.20%    MA20✓/MA60✓/MA120✗\n"
        "  부동산(XLRE)         -0.70%  ▼  MA20✗/MA60✓/MA120✓\n"
        "  유틸리티(XLU)         -0.20%    MA20✗/MA60✓/MA120✓\n"
    )
    sectors = _parse_us_sectors(body)
    assert len(sectors) == 12
    tickers = {s["ticker"] for s in sectors}
    assert tickers == {"SOXX", "XLK", "XLC", "XLY", "XLP", "XLE",
                       "XLF", "XLV", "XLI", "XLB", "XLRE", "XLU"}
    xlc = next(s for s in sectors if s["ticker"] == "XLC")
    assert xlc["name"] == "커뮤니케이션"
    assert xlc["leaders"] == "META·GOOGL·NFLX"
    assert xlc["super_sector"] == "sensitive"


def test_us_sector_summary_regime():
    """super-sector 3분류 평균 + regime 판정."""
    from reports.parsers.morning_data_parser import _build_us_sector_summary

    # 민감 주도 → Risk-on
    sectors_on = [
        {"ticker": "XLK", "change_pct": 1.2, "super_sector": "sensitive"},
        {"ticker": "XLC", "change_pct": 0.8, "super_sector": "sensitive"},
        {"ticker": "XLP", "change_pct": 0.1, "super_sector": "defensive"},
        {"ticker": "XLV", "change_pct": 0.0, "super_sector": "defensive"},
        {"ticker": "XLF", "change_pct": 0.4, "super_sector": "cyclical"},
    ]
    summary = _build_us_sector_summary(sectors_on)
    assert summary["sensitive_avg"] == 1.0
    assert summary["defensive_avg"] == 0.05
    assert summary["cyclical_avg"] == 0.4
    assert "Risk-on" in summary["regime"]

    # 방어 주도 → Risk-off
    sectors_off = [
        {"ticker": "XLK", "change_pct": -1.0, "super_sector": "sensitive"},
        {"ticker": "XLP", "change_pct": 0.5, "super_sector": "defensive"},
        {"ticker": "XLV", "change_pct": 0.3, "super_sector": "defensive"},
    ]
    assert "Risk-off" in _build_us_sector_summary(sectors_off)["regime"]


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


def test_minervini_grade_a_new_badge_regression():
    """🆕 가 붙은 A등급 신규 편입 종목이 드롭되지 않는지 보장 (2026-04-24 LIG넥스원 사례)."""
    from reports.parsers.morning_data_parser import _parse_grade_a

    body = (
        "  ── A등급 (2개) — 진입 검토 ──\n\n"
        "  ▶ LIG넥스원 (079550) [A 12/12] 🆕\n"
        "    966,000원 | MA50 714,820 / MA150 545,863 / MA200 545,792\n"
        "    RS 92% | 수급 ✓(+181,822주) | 52주고점 -5.3%\n"
        "    PER 83.9x PBR 14.76x ROE 17.6%\n"
        "    손절 898,380원(-7%) | 트레일링(고점-15%)\n\n"
        "  ▶ SK하이닉스 (000660) [A 12/12] 14일\n"
        "    1,225,000원 | MA50 978,360 / MA150 711,486 / MA200 589,322\n"
        "    RS 99% | 수급 ✓(+231,723주) | 52주고점 +0.0%\n"
        "    PER 20.8x PBR 5.04x ROE 33.8%\n"
        "    손절 1,139,250원(-7%) | 트레일링(고점-15%)\n\n"
        "  ── B등급 (0개) ──\n"
    )
    stocks = _parse_grade_a(body)
    assert len(stocks) == 2, "🆕 종목이 regex 미스매치로 드롭됨"
    new_stock = next(s for s in stocks if s["code"] == "079550")
    assert new_stock["name"] == "LIG넥스원"
    assert new_stock["is_new"] is True
    assert new_stock["signal_days"] == 0
    old_stock = next(s for s in stocks if s["code"] == "000660")
    assert old_stock["is_new"] is False
    assert old_stock["signal_days"] == 14


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


def test_sector_adr003_key_always_present(data):
    """구 fixture 는 ADR-003 포맷 없으므로 빈 dict 반환 (KeyError 없이)."""
    adr = data["sector_adr003"]
    assert adr["leaders"] == []
    assert adr["strong"] == []
    assert adr["weak"] == []
    assert adr["transition"] is False


ADR003_FIXTURE = """\
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📊 주도 섹터 현황 — 2026년 04월 23일 (수)
  산식: ADR-003 Amendment 2 (IBD 6M + Breadth MA50)
  기준: universe 164종목 · 11섹터 · 기준일 2026-04-23
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔥 주도 (≥75점)
  • 반도체       100.0점  ( 5종목, breadth 100%)
  • 건설          89.8점  ( 8종목, breadth  88%)

📈 강세 (60~74점)
  • 2차전지       64.2점  (10종목, breadth  80%)

〰️ 중립 (40~59점)
  • 금융          57.9점  (24종목, breadth  46%)
  • 소재·유통     44.3점  (66종목, breadth  41%)

📉 약세 (<40점)
  • 바이오        10.8점  ( 7종목, breadth  14%)

⚠ 표본부족 (1섹터): 레어섹터(2종목)

⚡ 주간 변동 (전주 대비)
  🆕 신규 주도 진입: 반도체, 건설
  ⬇️  주도 이탈: 플랫폼
  📊 점수 급변: 반도체 (+12점), 바이오 (-8.5점)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""


def test_sector_adr003_parses_new_format():
    from reports.parsers.morning_data_parser import _parse_sector_adr003
    adr = _parse_sector_adr003(ADR003_FIXTURE)

    assert adr["ref_date"] == "2026-04-23"
    assert len(adr["leaders"]) == 2
    assert adr["leaders"][0] == {
        "name": "반도체", "score": 100.0, "n_stocks": 5, "breadth_pct": 1.0,
    }
    assert adr["leaders"][1]["name"] == "건설"
    assert adr["leaders"][1]["n_stocks"] == 8
    assert adr["leaders"][1]["breadth_pct"] == 0.88

    assert len(adr["strong"]) == 1
    assert adr["strong"][0]["name"] == "2차전지"

    neutral_names = {x["name"] for x in adr["neutral"]}
    assert "소재·유통" in neutral_names  # 중점(·) 포함 섹터명 파싱

    assert adr["weak"][0]["name"] == "바이오"

    assert adr["na"] == [{"name": "레어섹터", "n_stocks": 2}]

    assert adr["new_leaders"] == ["반도체", "건설"]
    assert adr["demoted"] == ["플랫폼"]
    jumps = {j["name"]: j["delta"] for j in adr["score_jumps"]}
    assert jumps["반도체"] == 12.0
    assert jumps["바이오"] == -8.5
    assert adr["transition"] is False


def test_sector_adr003_transition_flag():
    from reports.parsers.morning_data_parser import _parse_sector_adr003
    text = ADR003_FIXTURE.replace(
        "  🆕 신규 주도 진입: 반도체, 건설\n"
        "  ⬇️  주도 이탈: 플랫폼\n"
        "  📊 점수 급변: 반도체 (+12점), 바이오 (-8.5점)",
        "  ℹ 산식 전환 후 첫 런 — 비교 생략 (다음 주부터 정상 감지)",
    )
    adr = _parse_sector_adr003(text)
    assert adr["transition"] is True
    assert adr["new_leaders"] == []
    assert adr["score_jumps"] == []


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
