from datetime import date
from decimal import Decimal

import pytest

from app.ingestion.dedup import normalize_description, transaction_hash
from app.rag.router import route


def test_same_transaction_from_csv_and_pdf_hashes_identically():
    """The CSV carries a trailing auth reference the PDF omits. Both must collapse
    to one row, otherwise PDF backfill duplicates everything already ingested."""
    from_csv = transaction_hash(
        "Capital One", date(2026, 3, 4), Decimal("-42.10"), "CHIPOTLE MEXICAN GRILL 887766554"
    )
    from_pdf = transaction_hash(
        "Capital One", date(2026, 3, 4), Decimal("-42.10"), "Chipotle  Mexican Grill"
    )
    assert from_csv == from_pdf


def test_different_amounts_do_not_collide():
    a = transaction_hash("DCU", date(2026, 3, 4), Decimal("-10.00"), "COFFEE")
    b = transaction_hash("DCU", date(2026, 3, 4), Decimal("-10.01"), "COFFEE")
    assert a != b


def test_normalize_strips_reference_numbers():
    assert normalize_description("SHELL OIL #12345678") == "SHELL OIL"


@pytest.mark.parametrize(
    "question",
    ["What's my net worth right now?", "Total dining spend", "Show my asset allocation"],
)
def test_aggregate_questions_route_to_sql(question):
    assert route(question) == "aggregate"


@pytest.mark.parametrize(
    "question",
    ["Did I pay for parking at the airport?", "What was that charge from Chipotle?"],
)
def test_lookup_questions_route_to_vector_search(question):
    assert route(question) == "semantic"
