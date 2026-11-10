"""Ботсыз тексеру: python analyze_pdf.py есеп.pdf

Мәтіндік есепті экранға шығарады және PDF-тің жанына HTML есеп сақтайды.
"""
import re
import sys
from pathlib import Path

from salesreport import ReportParseError, run


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows консолі үшін
    except (AttributeError, ValueError):
        pass
    if len(sys.argv) < 2:
        print("Қолданылуы: python analyze_pdf.py есеп.pdf")
        return 1
    path = Path(sys.argv[1])
    try:
        A, messages, html = run(str(path))
    except ReportParseError as exc:
        print(f"Қате: {exc}")
        return 2
    for i, msg in enumerate(messages, 1):
        plain = re.sub(r"<[^>]+>", "", msg).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        print(f"----- хабарлама {i} ({len(msg)} таңба) -----")
        print(plain)
    out = path.with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    print(f"\nHTML есеп сақталды: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
