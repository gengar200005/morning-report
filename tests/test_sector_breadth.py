"""sector_breadth 단위 테스트.

실데이터 (Colab 산출 parquet) 검증은 scripts/validate_sector_breadth.py 로 분리.
여기서는 mock 데이터 기반 산식 정확성만 검증한다.

ADR-003 Amendment 2026-04-23 기준.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import sector_breadth as sb


# ═══════════════════════════════════════════════════════════════════
#  _cap_weights
# ═══════════════════════════════════════════════════════════════════
class TestCapWeights:
    def test_empty(self):
        w = sb._cap_weights(np.array([]))
        assert len(w) == 0

    def test_single_stock_is_100pct(self):
        w = sb._cap_weights(np.array([100.0]))
        assert w.tolist() == [1.0]

    def test_no_cap_needed(self):
        # 4종목 균등 → 각 25% (cap과 같음)
        w = sb._cap_weights(np.array([100.0, 100.0, 100.0, 100.0]))
        np.testing.assert_allclose(w, [0.25, 0.25, 0.25, 0.25])

    def test_samsung_case_cap_at_25pct(self):
        # 삼성전자 비중 80% 같은 극단 케이스 → 25%로 제한
        w = sb._cap_weights(np.array([800.0, 50.0, 50.0, 50.0, 50.0]))
        assert w[0] == pytest.approx(0.25, abs=1e-9)
        # 나머지 4종목은 (0.75 / 200) × 50 = 0.1875 씩
        np.testing.assert_allclose(w[1:], 0.1875)
        assert w.sum() == pytest.approx(1.0)

    def test_multiple_over_cap_iterative(self):
        # 2종목이 초기에 cap 초과 → 둘 다 25%로 고정 후 나머지 분배
        w = sb._cap_weights(np.array([400.0, 400.0, 100.0, 100.0]))
        assert w[0] == pytest.approx(0.25)
        assert w[1] == pytest.approx(0.25)
        np.testing.assert_allclose(w[2:], 0.25)  # 나머지도 25%씩
        assert w.sum() == pytest.approx(1.0)

    def test_extreme_case_cap_exceeds_full(self):
        # cap × 종목수 < 1 이면 재분배 불가 → 동등 가중 (방어)
        # cap=0.25 × 3종목 = 0.75 < 1 → 극단 케이스
        w = sb._cap_weights(np.array([1000.0, 1.0, 1.0]))
        # cap 적용 후 나머지 0.75 / 2 = 0.375 → 두 번째 반복에서 cap 초과 없음
        assert w.sum() == pytest.approx(1.0)
        assert w.max() <= sb.SINGLE_STOCK_CAP + 1e-9


# ═══════════════════════════════════════════════════════════════════
#  classify_grade
# ═══════════════════════════════════════════════════════════════════
class TestClassifyGrade:
    @pytest.mark.parametrize("score,expected", [
        (100.0, "주도"),
        (75.0, "주도"),
        (74.99, "강세"),
        (60.0, "강세"),
        (59.99, "중립"),
        (40.0, "중립"),
        (39.99, "약세"),
        (0.0, "약세"),
    ])
    def test_thresholds(self, score, expected):
        assert sb.classify_grade(score) == expected

    def test_nan(self):
        assert sb.classify_grade(float("nan")) == "N/A"

    def test_inf(self):
        # inf 는 유효하지 않은 점수로 취급
        assert sb.classify_grade(float("inf")) == "주도"  # inf ≥ 75 이므로 주도. 방어 필요 없음.


# ═══════════════════════════════════════════════════════════════════
#  compute_stock_6m_returns (mock)
# ═══════════════════════════════════════════════════════════════════
def _make_stocks_daily(tickers_and_prices: dict[str, list[float]], start="2025-01-01") -> pd.DataFrame:
    """각 ticker 별 종가 리스트 → 일봉 DataFrame (평일만, 시고저=종가)."""
    dates = pd.bdate_range(start, periods=max(len(v) for v in tickers_and_prices.values()))
    rows = []
    for ticker, prices in tickers_and_prices.items():
        for d, p in zip(dates, prices):
            rows.append({
                "날짜": d, "ticker": ticker, "name": f"Stock{ticker}",
                "시가": p, "고가": p, "저가": p, "종가": p,
                "거래량": 1000, "거래대금": 1000 * p,
            })
    return pd.DataFrame(rows)


class TestStock6mReturns:
    def test_exact_126_days_return(self):
        # 127일 (126일 lookback + 기준일), 첫날 100 → 마지막 150 → +50%
        prices = [100.0] + [110.0] * 125 + [150.0]
        df = _make_stocks_daily({"A": prices})
        end = df["날짜"].max()
        r = sb.compute_stock_6m_returns(df, end)
        assert r["A"] == pytest.approx(0.5)

    def test_insufficient_data_excluded(self):
        prices = [100.0] * 50  # 126일 미달
        df = _make_stocks_daily({"A": prices})
        end = df["날짜"].max()
        r = sb.compute_stock_6m_returns(df, end)
        assert "A" not in r.index

    def test_end_date_respected(self):
        # 300일치 데이터, 기준일을 중간으로 → 그 시점 기준 6M 수익률
        prices = list(range(100, 400))  # 100→399
        df = _make_stocks_daily({"A": prices})
        end = df["날짜"].iloc[200]
        r = sb.compute_stock_6m_returns(df, end)
        # end_idx 포함 마지막 127개 → prices[200-126 .. 200] = [174 .. 300]
        expected = 300 / 174 - 1
        assert r["A"] == pytest.approx(expected, rel=1e-6)


# ═══════════════════════════════════════════════════════════════════
#  compute_sector_ibd_return
# ═══════════════════════════════════════════════════════════════════
class TestSectorIbdReturn:
    def test_single_sector_single_stock(self):
        sm = pd.DataFrame([
            {"ticker": "A", "name": "A", "sector": "전기전자", "marcap": 1000},
        ])
        rets = pd.Series({"A": 0.10})
        out = sb.compute_sector_ibd_return(sm, rets)
        assert out.loc["전기전자", "ibd_return"] == pytest.approx(0.10)
        assert out.loc["전기전자", "n_stocks"] == 1
        assert out.loc["전기전자", "n_priced"] == 1

    def test_cap_applies(self):
        # 삼성전자 시총 80%, 수익률 -10%. 나머지 4종목 각 +10%.
        # 순수 시총: 0.8×(-10%) + 0.2×10% = -6%
        # cap 25%: 0.25×(-10%) + 0.75×10% = +5%
        sm = pd.DataFrame([
            {"ticker": "A", "name": "A", "sector": "전기전자", "marcap": 800},
            {"ticker": "B", "name": "B", "sector": "전기전자", "marcap": 50},
            {"ticker": "C", "name": "C", "sector": "전기전자", "marcap": 50},
            {"ticker": "D", "name": "D", "sector": "전기전자", "marcap": 50},
            {"ticker": "E", "name": "E", "sector": "전기전자", "marcap": 50},
        ])
        rets = pd.Series({"A": -0.10, "B": 0.10, "C": 0.10, "D": 0.10, "E": 0.10})
        out = sb.compute_sector_ibd_return(sm, rets)
        assert out.loc["전기전자", "ibd_return"] == pytest.approx(0.05)

    def test_missing_prices_skipped(self):
        sm = pd.DataFrame([
            {"ticker": "A", "name": "A", "sector": "X", "marcap": 100},
            {"ticker": "B", "name": "B", "sector": "X", "marcap": 100},  # 가격 없음
        ])
        rets = pd.Series({"A": 0.20})
        out = sb.compute_sector_ibd_return(sm, rets)
        assert out.loc["X", "n_stocks"] == 2
        assert out.loc["X", "n_priced"] == 1
        assert out.loc["X", "ibd_return"] == pytest.approx(0.20)


# ═══════════════════════════════════════════════════════════════════
#  compute_ibd_points (percentile)
# ═══════════════════════════════════════════════════════════════════
class TestIbdPoints:
    def test_percentile_rank(self):
        sr = pd.DataFrame({
            "n_stocks": [5, 5, 5, 5],
            "n_priced": [5, 5, 5, 5],
            "ibd_return": [0.0, 0.1, 0.2, 0.3],
        }, index=["W", "X", "Y", "Z"])
        p = sb.compute_ibd_points(sr)
        # rank pct: W=0.25, X=0.5, Y=0.75, Z=1.0
        assert p["Z"] == pytest.approx(50.0)
        assert p["Y"] == pytest.approx(37.5)
        assert p["X"] == pytest.approx(25.0)
        assert p["W"] == pytest.approx(12.5)

    def test_nan_excluded_from_rank(self):
        sr = pd.DataFrame({
            "n_stocks": [5, 5, 5],
            "n_priced": [5, 0, 5],
            "ibd_return": [0.0, np.nan, 0.2],
        }, index=["A", "B", "C"])
        p = sb.compute_ibd_points(sr)
        # Only A, C ranked. A=0.5, C=1.0 → points 25, 50. B=NaN
        assert np.isnan(p["B"])
        assert p["C"] == pytest.approx(50.0)
        assert p["A"] == pytest.approx(25.0)


# ═══════════════════════════════════════════════════════════════════
#  compute_breadth
# ═══════════════════════════════════════════════════════════════════
class TestBreadth:
    def test_above_and_below_ma50(self):
        # A: 마지막이 MA50 위, B: 아래
        prices_A = [100.0] * 49 + [110.0]  # 50일, 마지막이 평균보다 위
        prices_B = [100.0] * 49 + [90.0]
        df = _make_stocks_daily({"A": prices_A, "B": prices_B})
        sm = pd.DataFrame([
            {"ticker": "A", "name": "A", "sector": "X", "marcap": 100},
            {"ticker": "B", "name": "B", "sector": "X", "marcap": 100},
        ])
        end = df["날짜"].max()
        out = sb.compute_breadth(sm, df, end)
        assert out.loc["X", "n_above"] == 1
        assert out.loc["X", "n_ma50_eligible"] == 2
        assert out.loc["X", "breadth_pct"] == pytest.approx(0.5)

    def test_insufficient_data_excluded(self):
        # 49일만 있으면 MA50 계산 불가
        prices = [100.0] * 49
        df = _make_stocks_daily({"A": prices})
        sm = pd.DataFrame([{"ticker": "A", "name": "A", "sector": "X", "marcap": 100}])
        end = df["날짜"].max()
        out = sb.compute_breadth(sm, df, end)
        assert out.loc["X", "n_ma50_eligible"] == 0
        assert pd.isna(out.loc["X", "breadth_pct"])


# ═══════════════════════════════════════════════════════════════════
#  compute_breadth_points (표본 단계화)
# ═══════════════════════════════════════════════════════════════════
class TestBreadthPoints:
    def test_full_sample_uses_breadth(self):
        breadth = pd.DataFrame({"breadth_pct": [0.8]}, index=["X"])
        sizes = pd.Series({"X": 10})
        p = sb.compute_breadth_points(breadth, sizes)
        assert p["X"] == pytest.approx(20.0)  # 25 × 0.8

    def test_partial_sample_zero(self):
        # 3-4 종목: breadth 무시 (0점)
        breadth = pd.DataFrame({"breadth_pct": [0.8]}, index=["X"])
        sizes = pd.Series({"X": 4})
        p = sb.compute_breadth_points(breadth, sizes)
        assert p["X"] == 0.0

    def test_boundary_at_5(self):
        breadth = pd.DataFrame({"breadth_pct": [1.0]}, index=["X"])
        assert sb.compute_breadth_points(breadth, pd.Series({"X": 5}))["X"] == pytest.approx(25.0)
        assert sb.compute_breadth_points(breadth, pd.Series({"X": 4}))["X"] == 0.0


# ═══════════════════════════════════════════════════════════════════
#  compute_sector_scores (end-to-end)
# ═══════════════════════════════════════════════════════════════════
class TestSectorScoresEndToEnd:
    def _build(self):
        # 섹터 3개: Big(5종), Mid(3종), Small(2종)
        sm_rows = []
        for i in range(5):
            sm_rows.append({"ticker": f"B{i}", "name": f"B{i}", "sector": "Big", "marcap": 200})
        for i in range(3):
            sm_rows.append({"ticker": f"M{i}", "name": f"M{i}", "sector": "Mid", "marcap": 100})
        for i in range(2):
            sm_rows.append({"ticker": f"S{i}", "name": f"S{i}", "sector": "Small", "marcap": 50})
        sm = pd.DataFrame(sm_rows)

        # 가격: Big 상승 (모두 MA50 위), Mid 정체, Small 하락
        tickers = {}
        n = 140  # 126+ 확보
        for i in range(5):
            tickers[f"B{i}"] = [100.0] * (n - 1) + [150.0]  # 마지막에 크게 상승
        for i in range(3):
            tickers[f"M{i}"] = [100.0] * n
        for i in range(2):
            tickers[f"S{i}"] = list(np.linspace(100, 80, n))  # 하락 추세

        stocks = _make_stocks_daily(tickers)
        return sm, stocks

    def test_big_sector_leads(self):
        sm, stocks = self._build()
        out = sb.compute_sector_scores(sector_map=sm, stocks_daily=stocks)
        # Big 이 가장 높고 Small 은 N/A (n=2 < 3)
        assert out.loc["Big", "grade"] in ("주도", "강세")
        assert out.loc["Small", "grade"] == "N/A"
        assert pd.isna(out.loc["Small", "score"])

    def test_breadth_disabled_for_mid_sample(self):
        sm, stocks = self._build()
        out = sb.compute_sector_scores(sector_map=sm, stocks_daily=stocks)
        # Mid (3종목) 는 breadth_points=0 (표본 단계화)
        assert out.loc["Mid", "breadth_points"] == 0.0

    def test_score_scale_100(self):
        sm, stocks = self._build()
        out = sb.compute_sector_scores(sector_map=sm, stocks_daily=stocks)
        # rescale 적용: score = raw_score × 100/75
        valid = out.dropna(subset=["score"])
        np.testing.assert_allclose(
            valid["score"], valid["raw_score"] * (100 / 75),
        )
