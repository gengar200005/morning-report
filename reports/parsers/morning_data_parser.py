"""morning_data_YYYYMMDD.txt → dict 파서.

v6.2 HTML 템플릿 렌더링을 위한 원천 데이터 추출.
서사 텍스트(Executive Summary, Catalysts 등)는 파서 책임이 아니며
렌더러 계층에서 dict를 조립해 생성한다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

NUM_RE = r"-?[\d,]+(?:\.\d+)?"
PCT_RE = r"[+\-−▲▼]\s*[\d.]+"


def _to_float(text: str) -> float:
    """'1,166,000' / '−0.24' / '▲ +0.58%' → float."""
    cleaned = text.replace(",", "").replace("−", "-").replace("▲", "").replace("▼", "")
    cleaned = cleaned.replace("%", "").replace("+", "").strip()
    return float(cleaned)


def _to_int(text: str) -> int:
    return int(_to_float(text))


def _parse_change_pct(text: str) -> float:
    """'▲ +0.58%' / '▼ -0.24%' → 0.58 / -0.24."""
    match = re.search(r"([▲▼])?\s*([+\-−]?\s*[\d.]+)", text)
    if not match:
        raise ValueError(f"change_pct 파싱 실패: {text!r}")
    sign_marker, number = match.groups()
    value = float(number.replace("−", "-").replace(" ", ""))
    if sign_marker == "▼" and value > 0:
        value = -value
    return value


def _extract_section(text: str, header: str, next_header_pattern: str = r"\n【") -> str | None:
    """【 ... 】 섹션 본문만 추출."""
    pattern = rf"【\s*{re.escape(header)}[^】]*】(.*?)(?={next_header_pattern}|={{10,}}|\Z)"
    match = re.search(pattern, text, flags=re.DOTALL)
    return match.group(1) if match else None


def _parse_date(text: str) -> tuple[str, str]:
    """'2026년 04월 21일 (Tue)' → ('2026-04-21', 'Tue')."""
    match = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*\(([^)]+)\)", text)
    if not match:
        raise ValueError("날짜 파싱 실패")
    year, month, day, weekday = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}", weekday


def _parse_ma_flags(text: str) -> dict[str, bool]:
    """'MA20✓위 / MA60✓위 / MA120✓위' → {'ma20': True, 'ma60': True, 'ma120': True}.
    '✗' 또는 '아래' 패턴은 False."""
    result = {}
    for ma in ("MA20", "MA60", "MA120"):
        pattern = rf"{ma}\s*([✓✗])"
        match = re.search(pattern, text)
        if match:
            result[ma.lower()] = match.group(1) == "✓"
    return result


def _parse_us_indices(body: str) -> list[dict[str, Any]]:
    """'S&P500  7,109.14  ▼ -0.24%  |  MA20✓위 / MA60✓위 / MA120✓위'."""
    name_map = {
        "S&P500": "S&P 500",
        "나스닥": "Nasdaq",
        "다우": "Dow Jones",
        "러셀2000": "Russell 2000",
    }
    pattern = re.compile(
        r"^\s*(S&P500|나스닥|다우|러셀2000)\s+([\d,]+\.\d+)\s+([▲▼])\s*([+\-−]?[\d.]+%)"
        r"\s*\|\s*(MA20[^/]+/\s*MA60[^/]+/\s*MA120\S+)",
        re.MULTILINE,
    )
    indices = []
    for match in pattern.finditer(body):
        raw_name, value, arrow, pct, ma_text = match.groups()
        change = _parse_change_pct(f"{arrow} {pct}")
        indices.append(
            {
                "name": name_map[raw_name],
                "value": _to_float(value),
                "change_pct": change,
                **_parse_ma_flags(ma_text),
            }
        )
    return indices


def _parse_vix(body: str) -> dict[str, Any]:
    match = re.search(r"([\d.]+)\s*\[([^\]]+)\]", body)
    if not match:
        return {"value": None, "status": None}
    return {"value": float(match.group(1)), "status": match.group(2).strip()}


def _parse_rates_fx(body: str) -> dict[str, Any]:
    labels = {
        "미국채10년": "us10y",
        "미국채2년": "us2y",
        "달러인덱스": "dxy",
        "달러/원": "usd_krw",
        "달러/엔": "usd_jpy",
    }
    result: dict[str, Any] = {}
    for label, key in labels.items():
        pattern = rf"{re.escape(label)}\s+([\d,]+\.\d+)\s+([▲▼])\s*([+\-−]?[\d.]+%)"
        match = re.search(pattern, body)
        if match:
            value, arrow, pct = match.groups()
            result[key] = {
                "value": _to_float(value),
                "change_pct": _parse_change_pct(f"{arrow} {pct}"),
            }
    spread_match = re.search(r"장단기 금리차[^:]*:\s*([+\-−]?[\d.]+)%", body)
    if spread_match:
        result["yield_spread"] = _to_float(spread_match.group(1))
    return result


def _parse_commodities(body: str) -> dict[str, Any]:
    labels = {"WTI": "wti", "브렌트": "brent", "금": "gold", "은": "silver"}
    result = {}
    for label, key in labels.items():
        pattern = rf"^\s*{re.escape(label)}\s+([\d,]+\.\d+)\s+([▲▼])\s*([+\-−]?[\d.]+%)"
        match = re.search(pattern, body, re.MULTILINE)
        if match:
            value, arrow, pct = match.groups()
            result[key] = {
                "value": _to_float(value),
                "change_pct": _parse_change_pct(f"{arrow} {pct}"),
            }
    return result


# GICS 11 Select Sector SPDR + SOXX. leaders = ETF 상위 비중 상위 3개 (연 1회 리밸런싱),
# super_sector = Morningstar 3분류 (cyclical/defensive/sensitive). SOXX는 Tech 하위
# industry ETF 이므로 sensitive 로 분류.
US_SECTOR_META: dict[str, dict[str, str]] = {
    "SOXX": {"leaders": "NVDA·AVGO·AMD",   "super_sector": "sensitive"},
    "XLK":  {"leaders": "AAPL·MSFT·NVDA",  "super_sector": "sensitive"},
    "XLC":  {"leaders": "META·GOOGL·NFLX", "super_sector": "sensitive"},
    "XLE":  {"leaders": "XOM·CVX·COP",     "super_sector": "sensitive"},
    "XLI":  {"leaders": "GE·RTX·CAT",      "super_sector": "sensitive"},
    "XLY":  {"leaders": "AMZN·TSLA·HD",    "super_sector": "cyclical"},
    "XLF":  {"leaders": "BRK.B·JPM·V",     "super_sector": "cyclical"},
    "XLB":  {"leaders": "LIN·SHW·FCX",     "super_sector": "cyclical"},
    "XLRE": {"leaders": "PLD·AMT·WELL",    "super_sector": "cyclical"},
    "XLP":  {"leaders": "COST·WMT·PG",     "super_sector": "defensive"},
    "XLV":  {"leaders": "LLY·UNH·JNJ",     "super_sector": "defensive"},
    "XLU":  {"leaders": "NEE·SO·DUK",      "super_sector": "defensive"},
}


def _parse_us_sectors(body: str) -> list[dict[str, Any]]:
    """'반도체(SOXX)  +0.44%  MA20✓/MA60✓/MA120✓'.

    morning_report.py 는 `|pct| × 2` 만큼 ▲/▼ 를 찍어 최대 10개까지 생성하므로
    arrow 그룹은 `*` (0-N개) 여야 한다. `?` (0-1개) 였을 때 ±1% 이상 등락 섹터가
    탈락하는 버그가 있었음 (회귀 방지 테스트: test_us_sectors_multi_arrow).
    """
    pattern = re.compile(
        r"^\s*([가-힣A-Z]+)\(([A-Z]+)\)\s+([+\-−]?[\d.]+%)\s*[▲▼]*\s*(MA20[^/]+/\s*MA60[^/]+/\s*MA120\S+)",
        re.MULTILINE,
    )
    sectors = []
    for match in pattern.finditer(body):
        name, ticker, pct, ma_text = match.groups()
        meta = US_SECTOR_META.get(ticker, {"leaders": "", "super_sector": "unknown"})
        sectors.append(
            {
                "name": name,
                "ticker": ticker,
                "change_pct": _parse_change_pct(pct),
                **_parse_ma_flags(ma_text),
                "leaders": meta["leaders"],
                "super_sector": meta["super_sector"],
            }
        )
    return sectors


def _build_us_sector_summary(sectors: list[dict[str, Any]]) -> dict[str, Any]:
    """Morningstar 3분류 (cyclical/defensive/sensitive) 단순평균 + regime 판정."""
    def avg(group: str) -> float | None:
        vals = [s["change_pct"] for s in sectors if s.get("super_sector") == group]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 2)

    defensive = avg("defensive")
    sensitive = avg("sensitive")
    cyclical = avg("cyclical")

    regime: str | None = None
    if defensive is not None and sensitive is not None:
        diff = sensitive - defensive
        if diff >= 0.3:
            regime = "Risk-on · 민감재 주도"
        elif diff <= -0.3:
            regime = "Risk-off · 방어주 선호"
        else:
            regime = "혼조 · 뚜렷한 주도 없음"

    return {
        "defensive_avg": defensive,
        "sensitive_avg": sensitive,
        "cyclical_avg": cyclical,
        "regime": regime,
    }


def _parse_simple_quotes(body: str) -> list[dict[str, Any]]:
    """'엔비디아  202.06  ▲ +0.19%' 같은 단순 종목 시세 라인."""
    pattern = re.compile(
        r"^\s*([가-힣A-Z0-9&]+(?:ADR)?)\s+([\d,]+\.\d+)\s+([▲▼])\s*([+\-−]?[\d.]+%)",
        re.MULTILINE,
    )
    result = []
    for match in pattern.finditer(body):
        name, value, arrow, pct = match.groups()
        result.append(
            {
                "name": name,
                "value": _to_float(value),
                "change_pct": _parse_change_pct(f"{arrow} {pct}"),
            }
        )
    return result


def _parse_kr_indices(body: str, trend_body: str) -> list[dict[str, Any]]:
    """코스피/코스닥 지수 + 추세 분석 결합."""
    idx_pattern = re.compile(
        r"^\s*(코스피|코스닥)\s+([\d,]+\.\d+)\s+([▲▼])\s*([+\-−]?[\d.]+%)",
        re.MULTILINE,
    )
    indices = []
    for match in idx_pattern.finditer(body):
        name, value, arrow, pct = match.groups()
        indices.append(
            {
                "name": "KOSPI" if name == "코스피" else "KOSDAQ",
                "value": _to_float(value),
                "change_pct": _parse_change_pct(f"{arrow} {pct}"),
            }
        )
    for idx in indices:
        kr_name = "코스피" if idx["name"] == "KOSPI" else "코스닥"
        trend_pattern = rf"{kr_name}\s*\|\s*5일\s*([+\-−]?[\d.]+)%\s*/\s*20일\s*([+\-−]?[\d.]+)%(.*?)(?=\n\s*(?:코스피|코스닥|\Z))"
        match = re.search(trend_pattern, trend_body, re.DOTALL)
        if match:
            trend_5d, trend_20d, rest = match.groups()
            idx["trend_5d"] = _to_float(trend_5d)
            idx["trend_20d"] = _to_float(trend_20d)
            idx["is_20d_new_high"] = "20일 신고가" in rest
            high_match = re.search(r"52주 고점\s*[\d,]+\s*대비\s*([+\-−]?[\d.]+)%", rest)
            low_match = re.search(r"52주 저점\s*[\d,]+\s*대비\s*([+\-−]?[\d.]+)%", rest)
            if high_match:
                idx["pct_from_52w_high"] = _to_float(high_match.group(1))
            if low_match:
                idx["pct_from_52w_low"] = _to_float(low_match.group(1))
    return indices


def _parse_kospi_flow(body: str, header: str = "") -> dict[str, Any]:
    """수급 (코스피) — 외국인/기관/개인 (억원)."""
    result: dict[str, Any] = {}
    for label, key in (("외국인", "foreign"), ("기관", "institution"), ("개인", "retail")):
        match = re.search(rf"{label}\s+([+\-−]?[\d,]+)억원", body)
        if match:
            result[key] = _to_int(match.group(1))
    # 헤더에서 기준일(YYYY.MM.DD) 추출
    date_match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", header)
    if date_match:
        result["basis_date"] = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
        result["basis_md"] = f"{date_match.group(2)}/{date_match.group(3)}"
    return result


def _parse_market_context(body: str) -> dict[str, Any]:
    """코스피·코스닥 MA 상태."""
    ctx: dict[str, Any] = {}
    vix_match = re.search(r"VIX\s+([\d.]+)\s+([✓✗])", body)
    if vix_match:
        ctx["vix"] = float(vix_match.group(1))
        ctx["vix_ok"] = vix_match.group(2) == "✓"
    for idx_name, prefix in (("코스피", "kospi"), ("코스닥", "kosdaq")):
        for ma in ("MA20", "MA60", "MA120"):
            pattern = rf"{idx_name}\s+{ma}\s+([\d,]+(?:\.\d+)?)\s+([✓✗])"
            match = re.search(pattern, body)
            if match:
                ctx[f"{prefix}_{ma.lower()}"] = _to_float(match.group(1))
                ctx[f"{prefix}_{ma.lower()}_ok"] = match.group(2) == "✓"
    return ctx


@dataclass
class StockA:
    name: str
    code: str
    grade: str
    core: int
    core_max: int
    signal_days: int
    price: int
    ma50: int
    ma150: int
    ma200: int
    rs: int
    supply_ok: bool
    supply_20d: int
    pct_from_52w_high: float
    per: float
    pbr: float
    roe: float
    stop_price: int


def _parse_grade_a(body: str) -> list[dict[str, Any]]:
    """▶ 종목명 (코드) [A 12/12] N일 블록 파싱."""
    # A등급 블록만 추출
    section = re.search(r"── A등급[^─]*──(.*?)── B등급", body, re.DOTALL)
    if not section:
        return []
    a_body = section.group(1)

    stock_pattern = re.compile(
        r"▶\s*(\S[^(]*?)\s*\((\d{6})\)\s*\[([A-D])\s+(\d+)/(\d+)\]\s*(\d+일|🆕)\s*\n"
        r"\s*([\d,]+)원\s*\|\s*MA50\s+([\d,]+)\s*/\s*MA150\s+([\d,]+)\s*/\s*MA200\s+([\d,]+)\s*\n"
        r"\s*RS\s+(\d+)%\s*\|\s*수급\s+([✓✗])\(([+\-−]?[\d,]+)주\)\s*\|\s*52주고점\s+([+\-−]?[\d.]+)%\s*\n"
        r"\s*PER\s+(-?[\d.]+)x\s+PBR\s+(-?[\d.]+)x\s+ROE\s+(-?[\d.]+)%\s*\n"
        r"\s*손절\s+([\d,]+)원",
        re.MULTILINE,
    )
    stocks = []
    for match in stock_pattern.finditer(a_body):
        (
            name,
            code,
            grade,
            core,
            core_max,
            signal,
            price,
            ma50,
            ma150,
            ma200,
            rs,
            supply_mark,
            supply_20d,
            high_pct,
            per,
            pbr,
            roe,
            stop_price,
        ) = match.groups()
        is_new = signal == "🆕"
        signal_days = 0 if is_new else int(signal[:-1])
        stocks.append(
            {
                "name": name.strip(),
                "code": code,
                "grade": grade,
                "core": int(core),
                "core_max": int(core_max),
                "signal_days": signal_days,
                "is_new": is_new,
                "price": _to_int(price),
                "ma50": _to_int(ma50),
                "ma150": _to_int(ma150),
                "ma200": _to_int(ma200),
                "rs": int(rs),
                "supply_ok": supply_mark == "✓",
                "supply_20d": _to_int(supply_20d),
                "pct_from_52w_high": _to_float(high_pct),
                "per": _to_float(per),
                "pbr": _to_float(pbr),
                "roe": _to_float(roe),
                "stop_price": _to_int(stop_price),
            }
        )
    return stocks


def _parse_grade_b(body: str) -> list[dict[str, Any]]:
    """B등급 단순 표: 종목명 / 현재가 / RS / 수급 / 신호일."""
    section = re.search(r"── B등급[^─]*──(.*?)(?:\n\n\s*C등급|$)", body, re.DOTALL)
    if not section:
        return []
    b_body = section.group(1)
    pattern = re.compile(
        r"^\s*(\S[^\s]*(?:\s\S+)*?)\s+([\d,]+)원\s+(\d+)%\s+([✓✗])\s+(\S+)",
        re.MULTILINE,
    )
    stocks = []
    for match in pattern.finditer(b_body):
        name, price, rs, supply, signal = match.groups()
        if name in ("종목명",):  # 헤더 스킵
            continue
        signal_days: int | None
        if signal == "🆕":
            signal_days = 0
        else:
            m = re.search(r"(\d+)", signal)
            signal_days = int(m.group(1)) if m else None
        stocks.append(
            {
                "name": name.strip(),
                "price": _to_int(price),
                "rs": int(rs),
                "supply_ok": supply == "✓",
                "signal_days": signal_days,
                "is_new": signal == "🆕",
            }
        )
    return stocks


def _parse_grade_c(body: str) -> list[str]:
    match = re.search(r"C등급\s*\d+개[^:]*:\s*(.+)", body)
    if not match:
        return []
    raw = match.group(1)
    separator = "," if "," in raw else "·"
    return [name.strip() for name in raw.split(separator) if name.strip()]


def _parse_minervini(body: str) -> dict[str, Any]:
    counts_match = re.search(r"전체\s+(\d+)종목\s*—\s*A:(\d+)\s*B:(\d+)\s*C:(\d+)\s*D:(\d+)", body)
    counts: dict[str, int] = {}
    total = 0
    if counts_match:
        total = int(counts_match.group(1))
        counts = {
            "A": int(counts_match.group(2)),
            "B": int(counts_match.group(3)),
            "C": int(counts_match.group(4)),
            "D": int(counts_match.group(5)),
        }
    return {
        "total": total,
        "counts": counts,
        "grade_a": _parse_grade_a(body),
        "grade_b": _parse_grade_b(body),
        "grade_c": _parse_grade_c(body),
    }


def _parse_sector_etf(text: str) -> dict[str, Any]:
    """📊 주도 섹터 ETF 현황 블록."""
    section_match = re.search(
        r"주도 섹터 ETF 현황[^━]*━+\s*\n(.*?)━━━━",
        text,
        re.DOTALL,
    )
    if not section_match:
        return {"leaders": [], "strong": [], "neutral": [], "weak": [], "weekly_changes": []}
    body = section_match.group(1)

    def _extract_tier(tier_header: str, next_tier_header: str | None) -> list[dict[str, Any]]:
        if next_tier_header:
            pattern = rf"{re.escape(tier_header)}.*?\n(.*?)(?={re.escape(next_tier_header)})"
        else:
            pattern = rf"{re.escape(tier_header)}.*?\n(.*?)(?=⚡|$)"
        match = re.search(pattern, body, re.DOTALL)
        if not match:
            return []
        tier_body = match.group(1)
        items = []
        # Leader/Strong 포맷: '1. KODEX IT  99.0점  ▲0.00%  (RS 49 / 추세 30 / 자금 20)'
        # Neutral/Weak 포맷:  '• TIGER 미디어컨텐츠  62.0점  ▲0.00%  (RS 32 / 추세 30 / 자금 0)'
        item_pattern = re.compile(
            r"(?:^\s*\d+\.|^\s*•)\s+(.+?)\s+([\d.]+)점\s+([▲▼])([\d.]+)%"
            r"(?:\s+\(RS\s+(\d+)\s*/\s*추세\s+(\d+)\s*/\s*자금\s+(\d+)\))?",
            re.MULTILINE,
        )
        perf_pattern = re.compile(
            r"└\s*1M\s+([+\-−]?[\d.]+)%.*?3M\s+([+\-−]?[\d.]+)%.*?6M\s+([+\-−]?[\d.]+)%",
            re.DOTALL,
        )
        ma_pattern = re.compile(r"MA20\s*([✓✗])\s*MA60\s*([✓✗])\s*MA120\s*([✓✗])")
        weekly_pattern = re.compile(r"└\s*주간\s+([+\-−]?[\d.]+)")

        matches = list(item_pattern.finditer(tier_body))
        for i, m in enumerate(matches):
            name, score, arrow, pct, rs_s, trend_s, flow_s = m.groups()
            # 해당 아이템의 └ 줄(있으면) 추출
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(tier_body)
            tail = tier_body[start:end]
            item: dict[str, Any] = {
                "name": name.strip(),
                "score": _to_float(score),
                "change_pct": _parse_change_pct(f"{arrow}{pct}"),
            }
            if rs_s:
                item["rs_score"] = int(rs_s)
                item["trend_score"] = int(trend_s)
                item["flow_score"] = int(flow_s)
            perf_m = perf_pattern.search(tail)
            if perf_m:
                item["perf_1m"] = _to_float(perf_m.group(1))
                item["perf_3m"] = _to_float(perf_m.group(2))
                item["perf_6m"] = _to_float(perf_m.group(3))
            ma_m = ma_pattern.search(tail)
            if ma_m:
                item["ma20"] = ma_m.group(1) == "✓"
                item["ma60"] = ma_m.group(2) == "✓"
                item["ma120"] = ma_m.group(3) == "✓"
            weekly_m = weekly_pattern.search(tail)
            if weekly_m:
                item["weekly_change"] = _to_float(weekly_m.group(1))
            items.append(item)
        return items

    leaders = _extract_tier("🔥 주도", "📈 강세")
    strong = _extract_tier("📈 강세", "〰️ 중립")
    neutral = _extract_tier("〰️ 중립", "📉 약세")
    weak = _extract_tier("📉 약세", None)

    weekly_changes: list[dict[str, Any]] = []
    weekly_match = re.search(r"점수 급변:\s*(.+)", body)
    if weekly_match:
        for chunk in weekly_match.group(1).split(","):
            chunk = chunk.strip()
            m = re.match(r"(.+?)\s*\(([+\-−]?[\d.]+)점\)", chunk)
            if m:
                weekly_changes.append({"name": m.group(1).strip(), "delta": _to_float(m.group(2))})

    return {
        "leaders": leaders,
        "strong": strong,
        "neutral": neutral,
        "weak": weak,
        "weekly_changes": weekly_changes,
    }


def _parse_sector_adr003(text: str) -> dict[str, Any]:
    """📊 주도 섹터 현황 블록 (ADR-003 Amendment 3, KOSPI200 11섹터).

    sector_report.py::build_text 의 출력을 파싱. 구 18 ETF 포맷과 공존하려면
    헤더를 '주도 섹터 현황' 로 좁혀 'ETF' 단어가 없는 경우만 매칭한다.
    """
    empty = {
        "leaders": [],
        "strong": [],
        "neutral": [],
        "weak": [],
        "na": [],
        "new_leaders": [],
        "demoted": [],
        "score_jumps": [],
        "transition": False,
        "ref_date": None,
    }

    section_match = re.search(
        r"📊\s*주도 섹터 현황(?!\s*ETF)[^━]*━+\s*\n(.*?)━━━━",
        text,
        re.DOTALL,
    )
    if not section_match:
        return empty
    body = section_match.group(1)

    ref_date_match = re.search(r"기준일\s*(\d{4}-\d{2}-\d{2})", text)
    ref_date = ref_date_match.group(1) if ref_date_match else None

    item_pattern = re.compile(
        r"^\s*•\s+(.+?)\s+([\d.]+)점\s+\(\s*(\d+)종목,\s+breadth\s+(\S+?)\s*\)",
        re.MULTILINE,
    )

    def _extract_tier(tier_header: str, next_tier_header: str | None) -> list[dict[str, Any]]:
        end_lookahead = re.escape(next_tier_header) if next_tier_header else r"⚠\s*표본부족|⚡"
        pattern = rf"{re.escape(tier_header)}.*?\n(.*?)(?={end_lookahead}|\Z)"
        match = re.search(pattern, body, re.DOTALL)
        if not match:
            return []
        items: list[dict[str, Any]] = []
        for m in item_pattern.finditer(match.group(1)):
            name, score, n_stocks, breadth_raw = m.groups()
            breadth = None
            if breadth_raw and breadth_raw != "N/A":
                breadth = _to_float(breadth_raw) / 100.0
            items.append({
                "name": name.strip(),
                "score": _to_float(score),
                "n_stocks": int(n_stocks),
                "breadth_pct": breadth,
            })
        return items

    leaders = _extract_tier("🔥 주도", "📈 강세")
    strong = _extract_tier("📈 강세", "〰️ 중립")
    neutral = _extract_tier("〰️ 중립", "📉 약세")
    weak = _extract_tier("📉 약세", None)

    na: list[dict[str, Any]] = []
    na_match = re.search(r"⚠\s*표본부족\s*\(\d+섹터\):\s*(.+?)(?=\n|$)", body)
    if na_match:
        for chunk in na_match.group(1).split(","):
            m = re.match(r"\s*(.+?)\s*\(\s*(\d+)종목\s*\)", chunk)
            if m:
                na.append({"name": m.group(1).strip(), "n_stocks": int(m.group(2))})

    transition = bool(re.search(r"산식 전환 후 첫 런", body))

    new_leaders: list[str] = []
    nl_match = re.search(r"🆕\s*신규 주도 진입:\s*(.+?)(?=\n|$)", body)
    if nl_match:
        new_leaders = [s.strip() for s in nl_match.group(1).split(",") if s.strip()]

    demoted: list[str] = []
    dm_match = re.search(r"⬇️\s*주도 이탈:\s*(.+?)(?=\n|$)", body)
    if dm_match:
        demoted = [s.strip() for s in dm_match.group(1).split(",") if s.strip()]

    score_jumps: list[dict[str, Any]] = []
    sj_match = re.search(r"📊\s*점수 급변:\s*(.+?)(?=\n|$)", body)
    if sj_match:
        for chunk in sj_match.group(1).split(","):
            m = re.match(r"\s*(.+?)\s*\(([+\-−]?[\d.]+)점\)", chunk)
            if m:
                score_jumps.append({
                    "name": m.group(1).strip(),
                    "delta": _to_float(m.group(2)),
                })

    return {
        "leaders": leaders,
        "strong": strong,
        "neutral": neutral,
        "weak": weak,
        "na": na,
        "new_leaders": new_leaders,
        "demoted": demoted,
        "score_jumps": score_jumps,
        "transition": transition,
        "ref_date": ref_date,
    }


def _parse_holdings(text: str) -> list[dict[str, Any]]:
    section_match = re.search(
        r"보유 종목 현황.*?={10,}\s*\n(.*?)(?=={10,}|\Z)",
        text,
        re.DOTALL,
    )
    if not section_match:
        return []
    body = section_match.group(1)

    stock_pattern = re.compile(
        r"▶\s*(\S[^(]*?)\s*\((\d{6})\)\s*\[([A-D])등급\]\s*\n"
        r"\s*매수가\s+([\d,]+)\s*→\s*현재\s+([\d,]+)\s*\(([+\-−]?[\d.]+)%\)\s*\n"
        r"\s*MA50\s+([\d,]+)\s*/\s*MA150\s+([\d,]+)\s*/\s*MA200\s+([\d,]+)\s*\n"
        r"\s*정배열:([✓✗])\s*MA200상승:([✓✗])\s*코어\s+(\d+)/(\d+)\s*\n"
        r"\s*52주고점\s+([\d,]+)\s*\(대비\s+([+\-−]?[\d.]+)%\)\s*\n"
        r"\s*손절가\s+([\d,]+)\s*\|\s*수급20일\s+([+\-−]?[\d,]+)주\s*\n"
        r"\s*⇒\s*(.+?)(?=\n|$)",
        re.MULTILINE,
    )
    holdings = []
    for match in stock_pattern.finditer(body):
        (
            name,
            code,
            grade,
            buy_price,
            current_price,
            change_pct,
            ma50,
            ma150,
            ma200,
            align,
            ma200_up,
            core,
            core_max,
            high_52w,
            high_pct,
            stop_price,
            supply_20d,
            verdict,
        ) = match.groups()
        holdings.append(
            {
                "name": name.strip(),
                "code": code,
                "grade": grade,
                "buy_price": _to_int(buy_price),
                "current_price": _to_int(current_price),
                "change_pct": _to_float(change_pct),
                "ma50": _to_int(ma50),
                "ma150": _to_int(ma150),
                "ma200": _to_int(ma200),
                "align": align == "✓",
                "ma200_up": ma200_up == "✓",
                "core": int(core),
                "core_max": int(core_max),
                "high_52w": _to_int(high_52w),
                "pct_from_52w_high": _to_float(high_pct),
                "stop_price": _to_int(stop_price),
                "supply_20d": _to_int(supply_20d),
                "verdict": verdict.strip(),
            }
        )
    return holdings


IMPACT_KEYWORDS = {
    "FOMC": "high",
    "CPI": "high",
    "NFP": "high",
    "PCE": "high",
    "어닝": "medium",
}


def _parse_macro_calendar(body: str) -> list[dict[str, Any]]:
    """'FOMC       05/06  D-15' 형식 + '어닝시즌   진행 중 ⚠️'."""
    events = []
    line_pattern = re.compile(
        r"^\s*(\S[^\d]*?)\s+(\d{2})/(\d{2})\s+D-(\d+)",
        re.MULTILINE,
    )
    for match in line_pattern.finditer(body):
        name, month, day, dday = match.groups()
        name = name.strip()
        # 연도는 당해 연도 가정 (파서에 연도 전달 시 보정 가능)
        events.append(
            {
                "event": name,
                "month": int(month),
                "day": int(day),
                "dday": int(dday),
                "impact": next(
                    (level for kw, level in IMPACT_KEYWORDS.items() if kw in name),
                    "medium",
                ),
            }
        )
    # 어닝시즌 같은 특수 라인
    if re.search(r"어닝시즌\s+진행 중", body):
        events.append({"event": "어닝시즌 진행 중", "dday": None, "impact": "medium"})
    # dday 오름차순 정렬 (None은 뒤로)
    events.sort(key=lambda e: (e["dday"] is None, e.get("dday") or 9999))
    return events


def _resolve_calendar_dates(events: list[dict[str, Any]], base_date: str) -> None:
    """dday 기반으로 full date(YYYY-MM-DD) 산출.

    base_date: 리포트 기준일 (YYYY-MM-DD). D-N일 이벤트 → base + N일.
    month/day 필드와 충돌 시 dday 기반 결과가 우선한다.
    """
    from datetime import date, timedelta

    y, m, d = (int(x) for x in base_date.split("-"))
    base = date(y, m, d)
    for event in events:
        if event.get("dday") is None:
            continue
        event_date = base + timedelta(days=event["dday"])
        event["date"] = event_date.isoformat()
        weekday = event_date.strftime("%a").upper()
        event["weekday"] = weekday


def parse_morning_data(path: str | Path) -> dict[str, Any]:
    """morning_data_YYYYMMDD.txt 전체 파싱."""
    text = Path(path).read_text(encoding="utf-8")
    date_str, weekday = _parse_date(text)

    us_idx_body = _extract_section(text, "주요 지수") or ""
    vix_body = _extract_section(text, "VIX") or ""
    rates_body = _extract_section(text, "금리·달러") or ""
    commodities_body = _extract_section(text, "원자재") or ""
    us_sectors_body = _extract_section(text, "섹터별 등락") or ""
    semis_body = _extract_section(text, "반도체 개별주") or ""
    bigtech_body = _extract_section(text, "빅테크 M7") or ""

    # 국장 섹션의 '주요 지수'는 두 번째 매칭이 필요. 전체 텍스트를 잘라 처리.
    kr_split = text.split("국장 데이터 브리핑")
    kr_text = kr_split[1] if len(kr_split) > 1 else ""
    kr_idx_body = _extract_section(kr_text, "주요 지수") or ""
    kospi_flow_body = _extract_section(kr_text, "수급 (코스피)") or ""
    # 헤더(【 수급 (코스피) — YYYY.MM.DD 기준 ... 】) 별도 추출
    flow_header_match = re.search(r"【\s*수급\s*\(코스피\)[^】]*】", kr_text)
    kospi_flow_header = flow_header_match.group(0) if flow_header_match else ""
    context_body = _extract_section(kr_text, "시장 컨텍스트") or ""
    trend_body = _extract_section(kr_text, "지수 추세 분석") or ""
    minervini_body = _extract_section(kr_text, "Minervini 스크리닝 결과") or ""
    calendar_body = _extract_section(text, "매크로 캘린더") or ""

    us_sectors = _parse_us_sectors(us_sectors_body)
    data: dict[str, Any] = {
        "date": date_str,
        "weekday": weekday,
        "us_indices": _parse_us_indices(us_idx_body),
        "vix": _parse_vix(vix_body),
        "rates_fx": _parse_rates_fx(rates_body),
        "commodities": _parse_commodities(commodities_body),
        "us_sectors": us_sectors,
        "us_sector_summary": _build_us_sector_summary(us_sectors),
        "us_semis": _parse_simple_quotes(semis_body),
        "big_tech": _parse_simple_quotes(bigtech_body),
        "kr_indices": _parse_kr_indices(kr_idx_body, trend_body),
        "kospi_flow": _parse_kospi_flow(kospi_flow_body, kospi_flow_header),
        "market_context": _parse_market_context(context_body),
        "minervini": _parse_minervini(minervini_body),
        "sector_etf": _parse_sector_etf(text),
        "sector_adr003": _parse_sector_adr003(text),
        "holdings": _parse_holdings(text),
        "macro_calendar": _parse_macro_calendar(calendar_body),
    }
    _resolve_calendar_dates(data["macro_calendar"], date_str)
    return data


if __name__ == "__main__":
    import json
    import sys

    source = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/morning_data_20260421.txt"
    parsed = parse_morning_data(source)
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
