"""HTML → PDF 변환 (Chrome headless 사용).

GitHub Actions에서 HTML 리포트를 PDF로 변환하는 유틸.
Chrome/Chromium 의 `--headless=new --print-to-pdf` 모드를 subprocess로 호출.
외부 Python 의존성 없음 (브라우저 바이너리만 필요).

Usage:
    python -m reports.render_pdf --html docs/archive/report_20260422.html \\
                                 --pdf  docs/archive/report_20260422.pdf
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


CHROME_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chrome",
    "chromium",
    "chromium-browser",
)


def find_chrome() -> str:
    override = os.environ.get("CHROME_BIN")
    if override and Path(override).is_file():
        return override
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError(
        f"Chrome/Chromium 실행 파일을 찾을 수 없습니다 "
        f"(후보: {', '.join(CHROME_CANDIDATES)}, CHROME_BIN env 로 override 가능)"
    )


def render(html_path: Path, pdf_path: Path, timeout: int = 120) -> None:
    chrome = find_chrome()
    html_abs = html_path.resolve()
    pdf_abs = pdf_path.resolve()
    pdf_abs.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        "--no-pdf-header-footer",
        "--virtual-time-budget=10000",
        f"--print-to-pdf={pdf_abs}",
        f"file://{html_abs}",
    ]
    print(f"▶ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0 or not pdf_abs.exists():
        sys.stderr.write(f"STDOUT:\n{result.stdout}\n")
        sys.stderr.write(f"STDERR:\n{result.stderr}\n")
        raise RuntimeError(f"Chrome PDF 변환 실패 (rc={result.returncode})")

    size = pdf_abs.stat().st_size
    print(f"✅ PDF 생성 완료: {pdf_abs} ({size:,} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description="HTML → PDF (Chrome headless)")
    parser.add_argument("--html", required=True, type=Path, help="입력 HTML 경로")
    parser.add_argument("--pdf", required=True, type=Path, help="출력 PDF 경로")
    args = parser.parse_args()

    if not args.html.exists():
        sys.stderr.write(f"⚠️ HTML 파일 없음: {args.html}\n")
        return 1

    render(args.html, args.pdf)
    return 0


if __name__ == "__main__":
    sys.exit(main())
