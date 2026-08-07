"""Morgan Stanley at Work — ESPP.

Platform note: Morgan Stanley acquired E*TRADE in 2020 and migrated most
StockPlan Connect participants onto the E*TRADE platform between 2023 and 2025.
Check which platform your account actually lives on before building against
StockPlan Connect's older report exports — the E*TRADE exports are cleaner:

  * At Work -> My Account -> Benefit History -> Download -> "Download Expanded"
    produces BenefitHistory.xlsx (purchases, vests, releases).
  * Stock Plan -> My Account -> Gains & Losses -> Download -> "Download Collapsed"
    produces G&L_Collapsed.xlsx (per-lot cost basis and gain/loss).

Between the two, Benefit History gives the acquisition events and Gains & Losses
gives the cost basis — a full ESPP holdings picture needs both, which is the
real content behind the plan's "no holdings/gains export natively" note.
"""

from pathlib import Path

from app.ingestion.base import BaseParser, ParseResult


class MorganStanleyReleasesParser(BaseParser):
    institution = "Morgan Stanley"
    account_type = "espp"
    extensions = (".xlsx", ".xls", ".csv")

    def parse(self, path: Path) -> ParseResult:
        raise NotImplementedError(
            "Read with pandas.read_excel(). Expect a title/metadata block above the "
            "real header — find the header row by looking for the row containing "
            "'Symbol' or 'Grant Date' rather than assuming header=0. Map purchase "
            "lots to holdings with vested=True and cost_basis from the purchase price."
        )
