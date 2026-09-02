"""Tests for the SQL fact layer behind aggregate-shaped questions.

`aggregate_facts()` produces every number the model is allowed to state. It had
no coverage at all until now, which is how a monthly rollup that netted card
payments into spending — and so reported a fall as a rise — survived from the day
it was written. These tests exist mostly to make that class of bug loud.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models import Institution, Transaction
from app.rag.retrieval import aggregate_facts


def _txn(institution_id: int, day: date, amount: str, category: str | None, note: str):
    return Transaction(
        institution_id=institution_id,
        txn_date=day,
        description=note,
        amount=Decimal(amount),
        category=category,
        source_file="test.csv",
        # Unique per row; the real hash is exercised in test_dedup_and_routing.
        dedup_hash=f"{day.isoformat()}-{amount}-{note}",
    )


@pytest.fixture
def seeded(db):
    """A statement-shaped month range: May partial, June whole, July partial.

    Mirrors the real data's shape — statements run mid-month to mid-month, so the
    first and last calendar months are always fractions of a month.
    """
    inst = Institution(name="Test Card", account_type="credit")
    db.add(inst)
    db.flush()

    db.add_all(
        [
            _txn(inst.id, date(2026, 5, 10), "-100.00", "dining", "RESTAURANT"),
            _txn(inst.id, date(2026, 5, 15), "500.00", "card_payment", "PAYMENT"),
            _txn(inst.id, date(2026, 6, 1), "-30.00", "dining", "CAFE"),
            _txn(inst.id, date(2026, 6, 30), "-70.00", "shopping", "STORE"),
            _txn(inst.id, date(2026, 7, 11), "-25.00", "dining", "DINER"),
        ]
    )
    db.commit()
    return db


def _fact_starting(facts: list[str], prefix: str) -> str:
    matches = [f for f in facts if f.startswith(prefix)]
    assert len(matches) == 1, f"expected exactly one {prefix!r} fact, got {matches}"
    return matches[0]


def test_card_payments_are_not_netted_into_spending(seeded):
    """The regression that motivated this file.

    May holds a -100 charge and a +500 payment. Summing both gives +400, which
    reads as income; the model handed that figure reported spending rising when
    it had fallen. Spending must be reported alone.
    """
    facts = aggregate_facts(seeded)

    may_spending = _fact_starting(facts, "Spending 2026-05:")
    assert "-100.00" in may_spending
    assert "400" not in may_spending, "payment was netted into the spending figure"

    may_payments = _fact_starting(facts, "Payments and transfers 2026-05:")
    assert "500.00" in may_payments


def test_a_month_without_payments_reports_no_payments_fact(seeded):
    """June has only spending, so a payments line would be noise."""
    facts = aggregate_facts(seeded)

    assert _fact_starting(facts, "Spending 2026-06:")
    assert not [f for f in facts if f.startswith("Payments and transfers 2026-06:")]


def test_spending_excludes_payments_in_every_month(seeded):
    """No monthly spending figure may be positive for a spend-only dataset."""
    spending = [f for f in aggregate_facts(seeded) if f.startswith("Spending ")]
    assert len(spending) == 3
    for fact in spending:
        assert "$-" in fact, f"a spending figure came out positive: {fact}"


def test_partial_months_are_flagged_and_whole_months_are_not(seeded):
    """The guard that stops an 11-day month being read as a collapse in spending."""
    facts = aggregate_facts(seeded)

    partial = _fact_starting(facts, "Partial months")
    assert "2026-05" in partial
    assert "2026-07" in partial
    assert "2026-06" not in partial, "a complete month was flagged as partial"


def test_coverage_states_the_window_and_the_row_count(seeded):
    facts = aggregate_facts(seeded)

    coverage = _fact_starting(facts, "Transaction data covers")
    assert "2026-05-10" in coverage
    assert "2026-07-11" in coverage
    assert "5 transactions" in coverage


def test_category_totals_are_grouped(seeded):
    """Dining spans all three months and must arrive summed, not per-row."""
    dining = _fact_starting(aggregate_facts(seeded), "Spend by category: dining")
    assert "-155.00" in dining
    assert "3 txns" in dining


def test_empty_database_says_so_rather_than_inventing_a_window(db):
    """No rows must not produce a coverage window over nothing."""
    facts = aggregate_facts(db)
    assert any("none ingested yet" in f for f in facts)
    assert not [f for f in facts if f.startswith("Partial months")]
