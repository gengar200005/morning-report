"""screening_history.json 쿨다운 추적 회귀 테스트 (ADR-015).

발현 패턴:
- 어제 보유였던 종목이 오늘 매도/손절됨
- 단 A/B 등급은 유지 중 → 등급 이탈 fallback 분기 미작동
- 따라서 last_exit_date 는 _held_tickers 비교 분기로만 잡힘

두 layer 검증:
- Layer 1 (morning.yml step 순서, ADR-015 §결정 1):
  fresh holdings 가 입력되어야 함. stale holdings 는 청산 감지 실패.
- Layer 2 (cooldown 계산 시점, ADR-015 §결정 2):
  holdings 기반 청산 감지가 cooldown 계산 **전**에 일어나야 same-day 표시.
  update_screening_state_holdings → compute_cooldown_remaining 순.

morning.yml 의 step 순서가 잘못되면 Layer 1 위반,
screen_stocks 흐름이 잘못되면 Layer 2 위반 — 본 테스트가 그 실패를
명시적으로 표현해 운영자에게 두 layer 의존을 알린다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# kr_report.py 는 import 시점에 KIS_APP_KEY 환경변수를 읽음 (라이브 실행 의존).
# 테스트는 update_screening_state 의 순수 logic 만 검증하므로 dummy 값 주입.
os.environ.setdefault("KIS_APP_KEY", "test_dummy")
os.environ.setdefault("KIS_APP_SECRET", "test_dummy")
os.environ.setdefault("MORNINGREPOT", "test_dummy")

from kr_report import (
    compute_cooldown_remaining,
    update_screening_state,
    update_screening_state_grades,
    update_screening_state_holdings,
)


def _state_yesterday() -> dict:
    """5/4 cron 직후 state — 보유 4종목, 047040 정상."""
    return {
        "_held_tickers": ["000660", "009150", "034020", "047040"],
        "000660": {"last_high_grade_date": "2026-05-04"},
        "009150": {"last_high_grade_date": "2026-05-04"},
        "034020": {"last_high_grade_date": "2026-05-04"},
        "047040": {"last_high_grade_date": "2026-05-04"},
    }


# 오늘 (5/5) high_grade list — 047040 도 A 등급 유지 (등급 이탈 분기 미작동 조건)
HIGH_GRADE_TODAY = {"000660", "009150", "034020", "047040"}


def test_fresh_holdings_detects_exit():
    """오늘 holdings_data.txt 가 갱신된 상태에서 호출 (정상 step 순서)."""
    state = _state_yesterday()
    fresh_holdings = {"000660", "009150", "034020"}  # 047040 빠짐

    update_screening_state(
        state, HIGH_GRADE_TODAY, "2026-05-05",
        held_tickers=fresh_holdings,
    )

    assert state["047040"]["last_exit_date"] == "2026-05-05", (
        "A 등급 유지된 채 보유 빠진 종목의 last_exit_date 가 기록돼야 함"
    )
    assert state["_held_tickers"] == ["000660", "009150", "034020"], (
        "_held_tickers 가 오늘 실제 보유로 갱신돼야 함"
    )


def test_fresh_holdings_preserves_held_tickers_for_unchanged():
    """보유 변동 없는 종목은 last_exit_date 기록 안 됨."""
    state = _state_yesterday()
    fresh_holdings = {"000660", "009150", "034020"}

    update_screening_state(
        state, HIGH_GRADE_TODAY, "2026-05-05",
        held_tickers=fresh_holdings,
    )

    for tk in ("000660", "009150", "034020"):
        assert "last_exit_date" not in state[tk], (
            f"{tk} 는 오늘도 보유 중이라 last_exit_date 가 없어야 함"
        )


def test_stale_holdings_misses_exit_documented_failure():
    """⚠️ ADR-015 위반 패턴 — morning.yml step 순서가 잘못되면 발생.

    kr_report.py 가 holdings_report.py 보다 먼저 실행되면 read_current_holdings()
    가 어제 파일을 읽음. 이 시뮬레이션에서는 "어제 보유" 가 그대로 입력되어
    청산 감지가 실패함을 명시적으로 검증한다.

    이 테스트가 통과하면 = 본 ADR 이 막으려는 패턴 정확히 재현.
    morning.yml 의 step 순서 변경 시 본 동작은 변하지 않음 (logic 자체는 stale
    입력에서 청산 감지 못 함). 운영 안전성은 step 순서로 보장.
    """
    state = _state_yesterday()
    stale_holdings = {"000660", "009150", "034020", "047040"}  # 어제 파일

    update_screening_state(
        state, HIGH_GRADE_TODAY, "2026-05-05",
        held_tickers=stale_holdings,
    )

    assert "last_exit_date" not in state["047040"], (
        "stale 입력에서는 청산 감지 실패 — ADR-015 가 막으려는 패턴"
    )


def test_held_tickers_none_skips_position_diff():
    """held_tickers=None (read_current_holdings() 가 빈 set 반환 + `or None` 패턴)
    이면 청산 감지 분기 자체를 스킵."""
    state = _state_yesterday()

    update_screening_state(
        state, HIGH_GRADE_TODAY, "2026-05-05",
        held_tickers=None,
    )

    assert state["_held_tickers"] == ["000660", "009150", "034020", "047040"], (
        "held_tickers=None 이면 _held_tickers 갱신 안 됨"
    )
    assert "last_exit_date" not in state["047040"]


def test_grade_dropout_fallback_still_works():
    """A/B 에서 빠진 종목은 fallback 분기로 last_exit_date 기록 (회귀 방지)."""
    state = _state_yesterday()
    high_grade_dropout = {"000660", "009150", "034020"}  # 047040 등급 이탈
    fresh_holdings = {"000660", "009150", "034020", "047040"}  # 보유는 유지 (이론적)

    update_screening_state(
        state, high_grade_dropout, "2026-05-05",
        held_tickers=fresh_holdings,
    )

    assert state["047040"].get("last_exit_date") == "2026-05-05", (
        "A/B → C/D 이탈 시 fallback 으로 last_exit_date 기록"
    )


# ─── ADR-015 Layer 2: cooldown 계산 시점 ────────────────────────────────────
#
# screen_stocks 흐름이 다음 순서를 보장해야 same-day 쿨다운 표시:
#   1. update_screening_state_holdings(state, today, fresh_holdings)
#   2. compute_cooldown_remaining(state, ticker, today_date)
#   3. update_screening_state_grades(state, high_grade_today, today)
#
# 만약 (3) 을 (2) 보다 먼저 실행하거나, (1) 을 (2) 다음에 실행하면 1일 lag.


from datetime import date


def test_layer2_holdings_update_before_cooldown_yields_correct_remaining():
    """Layer 2 정상 흐름 — holdings update 후 cooldown 계산 시 잔여 표시."""
    state = {
        "_held_tickers": ["000660", "009150", "034020", "047040"],
        "047040": {"last_high_grade_date": "2026-05-04"},  # exit_date 미기록
    }
    today_str = "2026-05-05"
    today_date = date(2026, 5, 5)

    # Step 1: holdings 기반 청산 감지 (047040 빠짐)
    update_screening_state_holdings(
        state, today_str, {"000660", "009150", "034020"},
    )

    # Step 2: cooldown 계산 — Step 1 결과가 반영된 state 사용
    rem = compute_cooldown_remaining(state, "047040", today_date)

    assert rem is not None and rem > 0, (
        "holdings update 후 cooldown 계산이면 047040 잔여 거래일이 표시돼야 함"
    )
    assert rem >= 55, (
        f"60거래일 쿨다운이 today=exit_date 시 거의 만기 전 잔여 표시, got {rem}"
    )


def test_layer2_cooldown_before_holdings_update_misses_remaining():
    """Layer 2 위반 — cooldown 계산이 holdings update 전이면 잔여 안 잡힘."""
    state = {
        "_held_tickers": ["000660", "009150", "034020", "047040"],
        "047040": {"last_high_grade_date": "2026-05-04"},
    }
    today_str = "2026-05-05"
    today_date = date(2026, 5, 5)

    # ⚠️ Step 1 을 건너뛴 채 cooldown 계산 — same-day 표시 누락 시뮬레이션
    rem = compute_cooldown_remaining(state, "047040", today_date)

    assert rem is None, (
        "holdings update 없이 cooldown 계산이면 last_exit_date 없어 None 반환 — "
        "Layer 2 가 막으려는 1일 lag 패턴"
    )


def test_layer2_split_function_yields_same_result_as_legacy_wrapper():
    """분리된 두 함수와 레거시 wrapper 결과 동치성 (회귀 방지)."""
    state_split = {
        "_held_tickers": ["000660", "009150", "034020", "047040"],
        "047040": {"last_high_grade_date": "2026-05-04"},
    }
    state_legacy = {
        "_held_tickers": ["000660", "009150", "034020", "047040"],
        "047040": {"last_high_grade_date": "2026-05-04"},
    }
    fresh_holdings = {"000660", "009150", "034020"}
    high_grade = {"000660", "009150", "034020", "047040"}

    update_screening_state_holdings(state_split, "2026-05-05", fresh_holdings)
    update_screening_state_grades(state_split, high_grade, "2026-05-05")
    update_screening_state(
        state_legacy, high_grade, "2026-05-05",
        held_tickers=fresh_holdings,
    )

    assert state_split == state_legacy, (
        "분리 호출과 레거시 wrapper 가 동일 결과를 내야 함"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
