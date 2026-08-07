"""Parser contract.

Every institution parser turns one file into a list of NormalizedTransaction or
NormalizedHolding records. Parsers do not touch the database and do not compute
dedup hashes — that is the pipeline's job. This keeps each parser testable with
a single fixture file and no Postgres.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path


@dataclass
class NormalizedTransaction:
    txn_date: date
    description: str
    amount: Decimal  # negative = money out, positive = money in
    posted_date: date | None = None
    category: str | None = None


@dataclass
class NormalizedHolding:
    as_of_date: date
    ticker: str
    quantity: Decimal
    asset_class: str | None = None
    cost_basis: Decimal | None = None
    market_value: Decimal | None = None
    vested: bool | None = None


@dataclass
class ParseResult:
    transactions: list[NormalizedTransaction] = field(default_factory=list)
    holdings: list[NormalizedHolding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BaseParser(ABC):
    """One parser per (institution, export format)."""

    institution: str  # must match a row in the `institutions` table
    account_type: str
    #: File extensions this parser handles, lowercase and dot-prefixed.
    extensions: tuple[str, ...] = ()

    @classmethod
    def handles(cls, path: Path) -> bool:
        return path.suffix.lower() in cls.extensions

    @abstractmethod
    def parse(self, path: Path) -> ParseResult: ...
