"""DCU checking/savings.

Correction to the original design plan: DCU Digital Banking *does* export
transactions directly — Account -> transaction list -> download, in CSV (and
historically OFX/QFX/QBO, though the post-2022 web interface reportedly dropped
QFX in favor of CSV). Prefer the CSV path; the PDF eStatement parser is only
needed for history older than what Digital Banking will export.

See docs/DATA-SOURCES.md for the validation notes and the First Tech merger
caveat (Jan 2026) that may change this UI.
"""

from pathlib import Path

from app.ingestion.base import BaseParser, ParseResult


class DCUCSVParser(BaseParser):
    institution = "DCU"
    account_type = "checking"
    extensions = (".csv",)

    def parse(self, path: Path) -> ParseResult:
        raise NotImplementedError(
            "Export one month from DCU Digital Banking, put the real header row in "
            "this docstring, then implement against it. Expect date / description / "
            "amount-or-debit-credit-pair / balance."
        )


class DCUPDFParser(BaseParser):
    """PDF eStatement fallback (7-year archive, PDF and HTML only)."""

    institution = "DCU"
    account_type = "checking"
    extensions = (".pdf",)

    def parse(self, path: Path) -> ParseResult:
        raise NotImplementedError(
            "DCU eStatements are multi-section (checking, savings, and any loan on "
            "one statement). Split by section header before extracting tables, or "
            "savings interest will land in the checking account's transactions."
        )
