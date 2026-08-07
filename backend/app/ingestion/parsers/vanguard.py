"""Vanguard brokerage.

CSV export: My Accounts -> Download Center. Limited to the trailing 18 months.

Format gotcha: the Vanguard download (often saved as OfxDownload.csv) is a
*multi-section* file — a positions block and a transactions block concatenated
into one CSV, with different column counts and a blank line between them. A
plain `pd.read_csv()` raises a tokenizing error on it. Split on the blank line
and parse each block separately, which is why this parser produces both
holdings and transactions from a single file.
"""

from pathlib import Path

from app.ingestion.base import BaseParser, ParseResult


class VanguardCSVParser(BaseParser):
    institution = "Vanguard"
    account_type = "brokerage"
    extensions = (".csv",)

    def parse(self, path: Path) -> ParseResult:
        raise NotImplementedError(
            "Implement the two-section split first: read the file as text, break on "
            "blank lines into blocks, then feed each block to pd.read_csv(io.StringIO(...)). "
            "The positions block becomes holdings; the transactions block becomes transactions."
        )


class VanguardPDFParser(BaseParser):
    """Statement backfill for anything beyond the 18-month CSV window."""

    institution = "Vanguard"
    account_type = "brokerage"
    extensions = (".pdf",)

    def parse(self, path: Path) -> ParseResult:
        raise NotImplementedError(
            "Vanguard PDF backfill. Note the browser-visible transaction history goes "
            "back much further than 18 months — screen-scraping that table may be less "
            "work than parsing statement PDFs."
        )
