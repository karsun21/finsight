import hashlib
import re
from datetime import date
from decimal import Decimal

_WHITESPACE = re.compile(r"\s+")
# Trailing reference/auth numbers vary between the CSV and the PDF of the same
# transaction, so they are stripped before hashing — otherwise backfilling from
# PDF would duplicate rows already ingested from CSV.
_TRAILING_REF = re.compile(r"\s+#?\d{6,}$")


def normalize_description(description: str) -> str:
    text = description.upper().strip()
    text = _TRAILING_REF.sub("", text)
    return _WHITESPACE.sub(" ", text)


def transaction_hash(
    institution: str, txn_date: date, amount: Decimal, description: str
) -> str:
    key = f"{institution}|{txn_date.isoformat()}|{amount:.2f}|{normalize_description(description)}"
    return hashlib.sha256(key.encode()).hexdigest()


def holding_hash(institution: str, as_of_date: date, ticker: str) -> str:
    """One row per (institution, snapshot date, ticker) — re-ingesting the same
    statement overwrites nothing and inserts nothing."""
    key = f"{institution}|{as_of_date.isoformat()}|{ticker.upper()}"
    return hashlib.sha256(key.encode()).hexdigest()
