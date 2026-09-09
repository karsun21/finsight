from collections import Counter
from datetime import date
from decimal import Decimal

import pytest

from app.ingestion.dedup import (
    file_hash,
    normalize_description,
    occurrence_hash,
    transaction_hash,
)
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
    a = transaction_hash("Test Bank", date(2026, 3, 4), Decimal("-10.00"), "COFFEE")
    b = transaction_hash("Test Bank", date(2026, 3, 4), Decimal("-10.01"), "COFFEE")
    assert a != b


def test_normalize_strips_reference_numbers():
    assert normalize_description("SHELL OIL #12345678") == "SHELL OIL"


# --- identical charges within one file ---------------------------------------


def _digests_for(descriptions):
    """Mirror the digest sequence _persist() builds for one file's transactions."""
    occurrences: Counter[str] = Counter()
    digests = []
    for description in descriptions:
        base = transaction_hash("Capital One", date(2026, 3, 4), Decimal("-3.50"), description)
        digests.append(occurrence_hash(base, occurrences[base]))
        occurrences[base] += 1
    return digests


def test_occurrence_zero_is_the_base_digest_unchanged():
    """The overwhelmingly common case must hash exactly as it did before
    occurrence indexing existed."""
    base = transaction_hash("Test Bank", date(2026, 3, 4), Decimal("-10.00"), "COFFEE")
    assert occurrence_hash(base, 0) == base


def test_two_identical_charges_get_distinct_digests():
    """Two $3.50 coffees at the same shop on the same day are both real. Before
    this they produced one digest, the unique constraint rejected the batch, and
    the whole ingest 500'd."""
    first, second = _digests_for(["BLUE BOTTLE COFFEE", "BLUE BOTTLE COFFEE"])
    assert first != second


def test_reingesting_the_same_file_reproduces_the_same_digests():
    """Idempotence: the occurrence index is per-file, so a second run generates
    the identical sequence and every row is recognized as already present. If it
    were derived from the database instead, run two would insert duplicates."""
    rows = ["BLUE BOTTLE COFFEE", "BLUE BOTTLE COFFEE", "CHIPOTLE"]
    assert _digests_for(rows) == _digests_for(rows)


def test_three_identical_charges_all_stay_distinct():
    assert len(set(_digests_for(["COFFEE"] * 3))) == 3


# --- file-level fingerprinting -----------------------------------------------


def test_renamed_copy_of_a_file_hashes_identically(tmp_path):
    """Capital One names every export the same thing, and the old check was on
    filename — so month two looked like month one and was silently skipped.
    Contents are what actually decide."""
    original = tmp_path / "transactions.csv"
    renamed = tmp_path / "capital_one_2026-07.csv"
    body = "Transaction Date,Description\n2026-07-01,CHIPOTLE\n"
    original.write_text(body)
    renamed.write_text(body)
    assert file_hash(original) == file_hash(renamed)


def test_same_name_different_contents_hashes_differently(tmp_path):
    """The case that was actually broken: two months of exports, same filename,
    different rows. These must not collide or the second month is lost."""
    march = tmp_path / "march" / "transactions.csv"
    april = tmp_path / "april" / "transactions.csv"
    for path in (march, april):
        path.parent.mkdir()
    march.write_text("Transaction Date,Description\n2026-03-01,CHIPOTLE\n")
    april.write_text("Transaction Date,Description\n2026-04-01,KROGER\n")
    assert march.name == april.name
    assert file_hash(march) != file_hash(april)


@pytest.mark.parametrize(
    "question",
    [
        "What's my net worth right now?",
        "Total dining spend",
        "Show my asset allocation",
        # Periodicity phrasings. "month to month" was a real misroute: it matched
        # none of the original patterns, fell through to vector search, and the
        # model was handed 20 raw transactions for a question that needs a sum.
        # These four are the family, not the one string that failed — if a
        # phrasing outside them misroutes, add the Haiku classifier instead of a
        # fifth pattern.
        "How has my spending changed month to month?",
        "What do I spend each month?",
        "Show me my spending by month",
        "Is my dining spend trending up?",
    ],
)
def test_aggregate_questions_route_to_sql(question):
    assert route(question) == "aggregate"


@pytest.mark.parametrize(
    "question",
    [
        "Did I pay for parking at the airport?",
        "What was that charge from Chipotle?",
        # Guards the periodicity patterns above against over-triggering: a date
        # in the question is not a request to roll anything up.
        "Where did I eat on June 3rd?",
    ],
)
def test_lookup_questions_route_to_vector_search(question):
    assert route(question) == "semantic"
