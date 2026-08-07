"""Capital One credit card.

CSV export: Account page -> "Download Transactions" (desktop web only; the mobile
app does not expose it). Capped at ~90 days per export, so recent history comes
from repeated CSV pulls and anything older comes from the 7-year PDF archive.

Observed header (verify against your own export before trusting it):
    Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit

Debit and Credit are separate columns and mutually exclusive per row. Debit is a
purchase (money out) and is normalized to a negative amount; Credit is a payment
or refund (money in) and stays positive.
"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from app.ingestion.base import BaseParser, NormalizedTransaction, ParseResult

REQUIRED_COLUMNS = {"transaction date", "description"}


def _to_decimal(value: object) -> Decimal | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
        return None
    return Decimal(str(value).replace("$", "").replace(",", "").strip())


class CapitalOneCSVParser(BaseParser):
    institution = "Capital One"
    account_type = "credit"
    extensions = (".csv",)

    def parse(self, path: Path) -> ParseResult:
        result = ParseResult()
        frame = pd.read_csv(path, dtype=str).rename(columns=lambda c: c.strip().lower())

        missing = REQUIRED_COLUMNS - set(frame.columns)
        if missing:
            raise ValueError(
                f"{path.name}: unexpected Capital One CSV layout, missing {sorted(missing)}. "
                f"Found columns: {list(frame.columns)}"
            )

        for _, row in frame.iterrows():
            debit = _to_decimal(row.get("debit"))
            credit = _to_decimal(row.get("credit"))
            if debit is None and credit is None:
                result.warnings.append(f"row with no debit/credit: {row.get('description')!r}")
                continue

            amount = -debit if debit is not None else credit

            result.transactions.append(
                NormalizedTransaction(
                    txn_date=datetime.strptime(row["transaction date"], "%Y-%m-%d").date(),
                    posted_date=(
                        datetime.strptime(row["posted date"], "%Y-%m-%d").date()
                        if row.get("posted date")
                        else None
                    ),
                    description=str(row["description"]).strip(),
                    amount=amount,
                    # Capital One ships its own merchant category; keep it as the
                    # starting label rather than re-deriving it from the description.
                    category=(str(row["category"]).strip().lower() or None)
                    if row.get("category")
                    else None,
                )
            )

        return result


class CapitalOnePDFParser(BaseParser):
    """PDF statement backfill for anything older than the 90-day CSV window.

    Statements & Documents holds ~7 years. Extract the transaction table with
    pdfplumber first; fall back to camelot only if the ruling lines confuse it.
    """

    institution = "Capital One"
    account_type = "credit"
    extensions = (".pdf",)

    def parse(self, path: Path) -> ParseResult:
        raise NotImplementedError(
            "Capital One PDF parser not implemented yet — start by running "
            "`pdfplumber.open(path).pages[1].extract_table()` on a real statement "
            "and building the column map from what comes back."
        )
