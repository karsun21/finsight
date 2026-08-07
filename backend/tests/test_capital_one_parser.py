from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.ingestion.parsers.capital_one import CapitalOneCSVParser

FIXTURE = Path(__file__).parent / "fixtures" / "capital_one_sample.csv"


@pytest.fixture
def parsed():
    return CapitalOneCSVParser().parse(FIXTURE)


def test_parses_every_row(parsed):
    assert len(parsed.transactions) == 4
    assert not parsed.warnings


def test_debits_are_negative_and_credits_positive(parsed):
    by_description = {t.description: t.amount for t in parsed.transactions}
    assert by_description["CHIPOTLE MEXICAN GRILL"] == Decimal("-42.10")
    assert by_description["CAPITAL ONE MOBILE PYMTAuthDate 11-Mar"] == Decimal("250.00")


def test_dates_and_issuer_category(parsed):
    first = parsed.transactions[0]
    assert first.txn_date == date(2026, 3, 4)
    assert first.posted_date == date(2026, 3, 5)
    assert first.category == "dining"


def test_rejects_unknown_layout(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Date,Amount\n2026-01-01,5.00\n")
    with pytest.raises(ValueError, match="unexpected Capital One CSV layout"):
        CapitalOneCSVParser().parse(bad)
