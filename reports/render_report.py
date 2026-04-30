"""Morning Report v6.2 렌더러.

CLI:
    python -m reports.render_report \\
        --input morning_data.txt \\
        --output-dir docs \\
        [--claude-analysis docs/claude_analysis/YYYYMMDD.json]

플로우:
  1) parser → dict
  2) derive (Top 5, leading sector 매칭, Exec Summary 자동 조립)
  3) Jinja2 → HTML (claude_analysis 주어지면 8키 주입, 아니면 fallback)
  4) 두 파일 저장: archive/report_YYYYMMDD.html + latest.html
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from reports.parsers.morning_data_parser import parse_morning_data
from reports.sector_mapping import resolve_sector

logger = logging.getLogger(__name__)

ROMAN = ["I", "II", "III", "IV", "V"]

def _normalize_claude_macro_events(events: list[dict], base_date: str) -> list[dict]:
    """claude_analysis.macro_events → parser 호환 macro_calendar 리스트.

    입력: [{"event": "FOMC", "date": "2026-06-17", "impact": "high"}, ...]
    출력: 파서 dict 형식 (dday / weekday / month / day 자동 산출).
    """
    from datetime import timedelta

    y, m, d = (int(x) for x in base_date.split("-"))
    base = date(y, m, d)
    result = []
    for ev in events:
        event_date = date.fromisoformat(ev["date"])
        dday = (event_date - base).days
        result.append(
            {
                "event": ev["event"],
                "month": event_date.month,
                "day": event_date.day,
                "dday": dday,
                "impact": ev.get("impact", "medium"),
                "date": ev["date"],
                "weekday": event_date.strftime("%a").upper(),
            }
        )
    result.sort(key=lambda e: e["dday"])
    return result


MACRO_EVENT_FULLNAME = {
    # 중앙은행
    "FOMC": "FOMC · Federal Reserve 금리 결정",
    "ECB": "ECB · 유럽중앙은행 금리 결정",
    "BOJ": "BOJ · 일본은행 금리 결정",
    "BOK 금통위": "BOK 금통위 · 한국은행 기준금리 결정",
    "FOMC 의사록": "FOMC Minutes · 연준 의사록 공개",
    # 고용
    "NFP": "NFP · 미국 고용 지표",
    "NFP(고용)": "NFP · 미국 고용 지표",
    "JOLTS": "JOLTS · 미국 구인·이직 보고서",
    "실업수당": "실업수당청구건수 · 미국 주간 고용",
    # 물가
    "CPI": "CPI · 미국 소비자물가지수",
    "CPI(미)": "CPI · 미국 소비자물가지수",
    "PPI": "PPI · 미국 생산자물가지수",
    "PCE": "PCE · 미국 개인소비지출",
    # 성장
    "GDP": "GDP · 미국 국내총생산",
    "ISM 제조업": "ISM 제조업 PMI · 미국 제조업 경기",
    "ISM 서비스업": "ISM 서비스업 PMI · 미국 서비스업 경기",
    "소매판매": "소매판매 · 미국 소비 동향",
}


# ──────────────── Filters ────────────────


def format_number(value: float | int | None, digits: int = 0) -> str:
    if value is None:
        return "—"
    if digits == 0:
        return f"{value:,.0f}" if isinstance(value, float) else f"{value:,}"
    return f"{value:,.{digits}f}"


def format_pct_signed(value: float | None, digits: int = 2) -> str:
    """'+1.83%' / '−0.24%' (U+2212 minus sign). 0은 '+0.00%'로 표시."""
    if value is None:
        return "—"
    sign = "−" if value < 0 else "+"
    return f"{sign}{abs(value):.{digits}f}%"


def format_pct_unsigned(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}%"


def format_change_arrow(value: float | None) -> str:
    """'▲' / '▼' / '·'."""
    if value is None or value == 0:
        return "·"
    return "▲" if value > 0 else "▼"


def format_signed_int(value: int | None) -> str:
    """'+2,937' / '−2,338'."""
    if value is None:
        return "—"
    sign = "+" if value > 0 else ("−" if value < 0 else "")
    return f"{sign}{abs(value):,}"


def format_weekday_en(date_str: str) -> str:
    """'2026-04-21' → 'Tue'."""
    return datetime.fromisoformat(date_str).strftime("%a")


def format_date_long(date_str: str) -> str:
    """'2026-04-21' → '21 April 2026 · Tue'."""
    dt = datetime.fromisoformat(date_str)
    return dt.strftime("%d %B %Y · %a")


# ──────────────── Derivation ────────────────


def _label_kospi_state(idx: dict) -> str:
    if idx.get("is_20d_new_high"):
        return "신고가"
    chg = idx["change_pct"]
    if chg >= 0.3:
        return "상승"
    if chg <= -0.3:
        return "조정"
    return "보합"


def _label_kosdaq_state(idx: dict) -> str:
    if idx.get("is_20d_new_high"):
        return "신고가"
    chg = idx["change_pct"]
    if chg >= 0.3:
        return "상승"
    if chg <= -0.3:
        return "하락"
    return "보합"


def _label_us_overall(us_indices: list[dict]) -> str:
    core = [i for i in us_indices if i["name"] in ("S&P 500", "Nasdaq", "Dow Jones")]
    if not core:
        return "혼조"
    avg = sum(i["change_pct"] for i in core) / len(core)
    if avg <= -0.15:
        return "소폭 하락"
    if avg >= 0.15:
        return "상승"
    return "혼조"


def _rs_bar_class(rs: int) -> str:
    if rs >= 90:
        return "rs-90"
    if rs >= 80:
        return "rs-80"
    return "rs-70"


def _format_roe(value: float) -> str:
    """'+26.8%' / '−15.3%' (U+2212)."""
    sign = "−" if value < 0 else ""
    return f"{sign}{abs(value):.1f}%"


def _top5_verdict(stock: dict, leading: dict, holdings: list[dict]) -> tuple[str, str, str]:
    """Returns (verdict_tag, trigger_label, verdict_text)."""
    if stock.get("is_held"):
        held = next((h for h in holdings if h["code"] == stock["code"]), None)
        if held:
            add = held["add_threshold"]
            stop = held["stop_price"]
        else:
            add = int(stock["price"] * 1.05)
            stop = stock["stop_price"]
        return (
            "ACTION",
            "Add-On Trigger",
            f"보유 종목 · <strong>HOLD 유지</strong>. {add:,}원 도달 + 거래량 확장 동반 시 1차 추매 검토. "
            f"{stop:,}원 이탈 시 전량 손절.",
        )
    if leading.get("tier") == "weak":
        short = leading["sector"]
        return (
            "CAUTION",
            "Entry Trigger",
            f"스크리너 통과 · <strong>섹터({short}) 약세</strong>라 Minervini 기준 미달 구간. "
            f"52W 고점 대비 {format_pct_signed(stock['pct_from_52w_high'], 1)}로 재돌파 여부 관찰 필요.",
        )
    if stock["roe"] < 0 or stock["pbr"] > 15:
        return (
            "READINESS",
            "Entry Trigger",
            f"스크리너 통과 · <strong>PBR {stock['pbr']:.1f}·ROE {_format_roe(stock['roe'])} 펀더멘털 취약</strong>. "
            "차트 확인 + 포지션 사이즈 보수적 관리 권장.",
        )
    return (
        "READINESS",
        "Entry Trigger",
        "스크리너 통과 · <strong>일봉 차트에서 VCP + 피벗 가격 + 거래량 배수 수동 확인 필요</strong>. R:R 목표 2~3R.",
    )


def _enrich_grade_a(data: dict) -> None:
    """Top 5 + Remaining을 grade_a에서 파생."""
    grade_a_sorted = sorted(data["minervini"]["grade_a"], key=lambda s: s["rs"], reverse=True)
    held_codes = {h["code"] for h in data["holdings"]}

    for i, stock in enumerate(grade_a_sorted):
        stock["is_held"] = stock["code"] in held_codes
        leading = resolve_sector(stock["name"], data["sector_adr003"], code=stock.get("code"))
        stock["leading_sector"] = leading

        # check mark for AUTO column '주도 섹터 소속'
        if leading["in_leading"]:
            stock["leading_check"] = "✓"
            score_str = f"{leading['score']:.0f}" if leading.get("score") is not None else "—"
            stock["leading_detail"] = f"{leading['sector']} {score_str}점"
        elif leading["sector"] and leading["tier"] == "weak":
            stock["leading_check"] = "✗"
            stock["leading_detail"] = f"{leading['sector']} {leading['score']:.0f}점"
        elif leading["sector"] and leading["tier"] in ("neutral", "na"):
            stock["leading_check"] = "⚠"
            score_part = (
                f" {leading['score']:.0f}점" if leading.get("score") is not None else ""
            )
            label = "표본부족" if leading["tier"] == "na" else "중립"
            stock["leading_detail"] = f"{leading['sector']} {label}{score_part}"
        else:
            stock["leading_check"] = "⚠"
            stock["leading_detail"] = "섹터 미매핑"

        stock["rs_bar_class"] = _rs_bar_class(stock["rs"])

    top5 = grade_a_sorted[:5]
    for i, stock in enumerate(top5):
        stock["rank_roman"] = ROMAN[i]
        tag, trigger_label, text = _top5_verdict(stock, stock["leading_sector"], data["holdings"])
        stock["verdict_tag"] = tag
        stock["trigger_label"] = trigger_label
        stock["verdict_text"] = text

    remaining = grade_a_sorted[5:]
    for i, stock in enumerate(remaining):
        stock["rank_num"] = 6 + i  # 6~24

    data["top5"] = top5
    data["remaining_a"] = remaining


def _enrich_exec_summary(data: dict) -> None:
    kospi = next(i for i in data["kr_indices"] if i["name"] == "KOSPI")
    kosdaq = next(i for i in data["kr_indices"] if i["name"] == "KOSDAQ")
    data["kospi_state"] = _label_kospi_state(kospi)
    data["kosdaq_state"] = _label_kosdaq_state(kosdaq)
    data["us_state"] = _label_us_overall(data["us_indices"])

    # Kospi above MA60 pct
    ctx = data["market_context"]
    if "kospi_ma60" in ctx and ctx["kospi_ma60"]:
        kospi_price = kospi["value"]
        data["kospi_above_ma60_pct"] = (kospi_price / ctx["kospi_ma60"] - 1) * 100

    # Exec summary strings
    bcd = sum(v for k, v in data["minervini"]["counts"].items() if k != "A")
    data["minervini"]["bcd_total"] = bcd

    leaders = data["sector_adr003"].get("leaders") or []
    data["top_leader"] = leaders[0] if leaders else None

    # Next high-impact event
    calendar_events = [
        e for e in data["macro_calendar"] if e.get("dday") is not None and e.get("impact") == "high"
    ]
    data["next_high_impact"] = min(calendar_events, key=lambda e: e["dday"]) if calendar_events else None

    # 52W new-high cluster (A-grade at high)
    at_high = sum(1 for s in data["minervini"]["grade_a"] if s["pct_from_52w_high"] >= -0.5)
    data["grade_a_at_high"] = at_high


def _enrich_macro_calendar(data: dict) -> None:
    for ev in data["macro_calendar"]:
        key = ev["event"]
        ev["event_full"] = MACRO_EVENT_FULLNAME.get(key, key)


def _enrich_holdings(data: dict) -> None:
    """보유 종목에 추매 기준가 + verdict parsing."""
    for h in data["holdings"]:
        h["add_threshold"] = int(h["buy_price"] * 1.05)
        # verdict 문자열에서 마크/라벨 추출
        verdict = h["verdict"]
        if "금지" in verdict:
            h["action_label"] = "추매 금지 · HOLD"
        elif "가능" in verdict:
            h["action_label"] = "추매 가능"
        elif "손절" in verdict:
            h["action_label"] = "손절 검토"
        else:
            h["action_label"] = "HOLD"


def _enrich_sector_flags(data: dict) -> None:
    """US sector / semi / big_tech 이름을 HTML 디스플레이 이름으로 치환 + 정렬 유지."""
    # Big tech: Microsoft -> MS로 줄이기 (HTML 표준 사용)
    name_short = {"마이크로소프트": "MS", "알파벳": "알파벳"}
    for item in data["big_tech"]:
        if item["name"] in name_short:
            item["display_name"] = name_short[item["name"]]
        else:
            item["display_name"] = item["name"]
    # US semi: 그대로
    for item in data["us_semis"]:
        item["display_name"] = item["name"]
    # 빅테크+반도체 통합 (HTML에서 한 테이블로 8개 표시)
    merged = []
    seen = set()
    for item in data["big_tech"] + data["us_semis"]:
        if item["name"] in seen:
            continue
        seen.add(item["name"])
        merged.append(item)
    # HTML 기준: 애플, 엔비디아, ASML, MS, AMD, 테슬라, 메타, 인텔 순서
    order = ["애플", "엔비디아", "ASML", "마이크로소프트", "AMD", "테슬라", "메타", "인텔"]
    merged_sorted = sorted(merged, key=lambda x: order.index(x["name"]) if x["name"] in order else 999)
    data["tech_merged"] = merged_sorted[:8]


def derive(data: dict) -> dict:
    """파서 결과에 렌더링용 파생 필드 추가."""
    _enrich_holdings(data)  # add_threshold 먼저 계산 (grade_a verdict 생성 시 참조)
    _enrich_grade_a(data)
    _enrich_exec_summary(data)
    _enrich_sector_flags(data)
    _enrich_macro_calendar(data)
    return data


# ──────────────── Render ────────────────


def _build_env(template_dir: Path) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=False,  # HTML 템플릿이 이미 처리된 서사 문구 포함
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
    )
    env.filters.update(
        {
            "format_number": format_number,
            "format_pct_signed": format_pct_signed,
            "format_pct_unsigned": format_pct_unsigned,
            "format_change_arrow": format_change_arrow,
            "format_signed_int": format_signed_int,
            "format_weekday_en": format_weekday_en,
            "format_date_long": format_date_long,
            "abs": abs,
        }
    )
    return env


def render_html(
    data: dict,
    template_dir: Path,
    template_name: str = "v6.2_template.html.j2",
    claude_analysis: dict | None = None,
) -> str:
    env = _build_env(template_dir)
    template = env.get_template(template_name)
    return template.render(data=data, claude_analysis=claude_analysis or {})


def save_outputs(html: str, date_str: str, output_dir: Path) -> tuple[Path, Path]:
    """archive/report_YYYYMMDD.html + latest.html 둘 다 저장."""
    archive_dir = output_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"report_{date_str.replace('-', '')}.html"
    archive_path.write_text(html, encoding="utf-8")
    latest_path = output_dir / "latest.html"
    latest_path.write_text(html, encoding="utf-8")
    return archive_path, latest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("morning_data.txt"),
        help="morning_data_YYYYMMDD.txt 경로",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/generated"),
        help="HTML 출력 디렉토리",
    )
    parser.add_argument(
        "--template-dir",
        type=Path,
        default=Path("reports/templates"),
        help="Jinja2 템플릿 디렉토리",
    )
    parser.add_argument(
        "--template",
        default="v6.2_template.html.j2",
        help="템플릿 파일명",
    )
    parser.add_argument(
        "--claude-analysis",
        type=Path,
        default=None,
        help="Claude 분석 JSON (7키: alert/gate_flow/sector/entry/agrade/portfolio/macro). "
        "미지정/파일없음 시 fallback 렌더 (해당 카드 div 생략).",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    logger.info("Parsing %s", args.input)
    data = parse_morning_data(args.input)
    logger.info("Report date: %s (%s)", data["date"], data["weekday"])

    claude_analysis: dict = {}
    if args.claude_analysis:
        if args.claude_analysis.exists():
            claude_analysis = json.loads(args.claude_analysis.read_text(encoding="utf-8"))
            logger.info(
                "Loaded claude_analysis (%d keys): %s",
                len(claude_analysis),
                sorted(claude_analysis.keys()),
            )
            if "macro_events" in claude_analysis:
                data["macro_calendar"] = _normalize_claude_macro_events(
                    claude_analysis["macro_events"], data["date"]
                )
                logger.info(
                    "macro_calendar overridden from claude_analysis.macro_events (%d events)",
                    len(data["macro_calendar"]),
                )
        else:
            logger.warning(
                "claude_analysis 파일 없음: %s — fallback 렌더 진행", args.claude_analysis
            )

    logger.info("Deriving render-time fields")
    data = derive(data)

    logger.info("Rendering template %s", args.template)
    html = render_html(data, args.template_dir, args.template, claude_analysis=claude_analysis)

    archive_path, latest_path = save_outputs(html, data["date"], args.output_dir)
    logger.info("Wrote %s (%.1f KB)", archive_path, archive_path.stat().st_size / 1024)
    logger.info("Wrote %s", latest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
