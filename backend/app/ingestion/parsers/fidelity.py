"""Fidelity NetBenefits 401(k).

CSV export: fidelity.com -> Activity & Orders -> pick date range and account ->
download icon -> CSV. This covers recent activity only; it is not the statement.

Known quirk (the design plan's "CSV occasionally drops rows"): the Activity &
Orders export reflects the current account *view*, not the full statement, and
omits running balances. For a 401(k) the authoritative record of contributions,
employer match, and per-fund balances is the quarterly PDF statement — so treat
the CSV as the incremental feed and the PDF as the source of truth for balances.

Fidelity CSVs also carry disclaimer text after the data rows; skip trailing rows
that fail date parsing rather than letting them become garbage transactions.
"""

from pathlib import Path

from app.ingestion.base import BaseParser, ParseResult


class FidelityCSVParser(BaseParser):
    institution = "Fidelity"
    account_type = "401k"
    extensions = (".csv",)

    def parse(self, path: Path) -> ParseResult:
        raise NotImplementedError(
            "Handle the trailing disclaimer block: parse rows until the date column "
            "stops parsing, then stop. Do not use skipfooter with a fixed count — the "
            "disclaimer length changes."
        )


class FidelityPDFParser(BaseParser):
    """Quarterly statement — source of truth for holdings/balances."""

    institution = "Fidelity"
    account_type = "401k"
    extensions = (".pdf",)

    def parse(self, path: Path) -> ParseResult:
        raise NotImplementedError(
            "Extract the 'Your Account Holdings' table into holdings rows keyed on the "
            "statement's period-end date."
        )
