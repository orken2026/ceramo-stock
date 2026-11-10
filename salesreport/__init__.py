"""1С «Валовая прибыль по клиентам» PDF есебін талдау.

Ауыр кітапханалар (pdfplumber) тек керек кезде жүктеледі — бот тезірек оянады.
"""

__all__ = ["analyze", "build_html", "build_messages", "split_message", "parse_report", "ReportParseError", "run"]


def __getattr__(name):
    if name in ("parse_report", "ReportParseError"):
        from . import parser
        return getattr(parser, name)
    if name == "analyze":
        from .analysis import analyze
        return analyze
    if name == "build_html":
        from .html_report import build_html
        return build_html
    if name in ("build_messages", "split_message"):
        from . import text_report
        return getattr(text_report, name)
    raise AttributeError(name)


def run(path: str):
    """PDF → (талдау, Telegram хабарламалары, HTML есеп)."""
    from .analysis import analyze
    from .html_report import build_html
    from .parser import parse_report
    from .text_report import build_messages

    A = analyze(parse_report(path))
    return A, build_messages(A), build_html(A)
