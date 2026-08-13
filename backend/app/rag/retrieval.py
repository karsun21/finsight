import calendar
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Holding, Institution, Transaction
from app.rag.embeddings import embed_query, holding_to_text, transaction_to_text


def semantic_search(db: Session, question: str, k: int | None = None) -> list[str]:
    """Top-k rows by cosine distance, as text lines ready to drop into a prompt."""
    k = k or get_settings().retrieval_top_k
    vector = embed_query(question)

    txns = db.execute(
        select(Transaction, Institution.name)
        .join(Institution)
        .where(Transaction.embedding.is_not(None))
        .order_by(Transaction.embedding.cosine_distance(vector))
        .limit(k)
    ).all()

    holdings = db.execute(
        select(Holding, Institution.name)
        .join(Institution)
        .where(Holding.embedding.is_not(None))
        .order_by(Holding.embedding.cosine_distance(vector))
        .limit(k // 2 or 1)
    ).all()

    return [transaction_to_text(t, name) for t, name in txns] + [
        holding_to_text(h, name) for h, name in holdings
    ]


def latest_holdings_snapshot(db: Session) -> list[tuple[str, str, Decimal | None]]:
    """Most recent holding row per (institution, ticker) — the basis for net worth."""
    newest = (
        select(
            Holding.institution_id,
            Holding.ticker,
            func.max(Holding.as_of_date).label("as_of_date"),
        )
        .group_by(Holding.institution_id, Holding.ticker)
        .subquery()
    )
    rows = db.execute(
        select(Institution.name, Holding.ticker, Holding.market_value)
        .join(Institution, Institution.id == Holding.institution_id)
        .join(
            newest,
            (Holding.institution_id == newest.c.institution_id)
            & (Holding.ticker == newest.c.ticker)
            & (Holding.as_of_date == newest.c.as_of_date),
        )
    ).all()
    return [(name, ticker, value) for name, ticker, value in rows]


def _coverage_facts(db: Session) -> list[str]:
    """State the window the data actually spans, and flag partial months.

    Without this the rollups are correct and the conclusions drawn from them are
    not. Statement exports open and close mid-cycle, so the first and last
    calendar months hold a fraction of a month's spending. Handed a bare "July =
    $364.58" next to "June = $1,017.04", the model reports a 65% collapse in
    spending, confidently and wrongly. Nothing in the numbers reveals that July
    is eleven days long — so the fact has to be said out loud.
    """
    first, last, count = db.execute(
        select(
            func.min(Transaction.txn_date),
            func.max(Transaction.txn_date),
            func.count(Transaction.id),
        )
    ).one()

    if first is None:
        return ["Transaction data: none ingested yet."]

    facts = [
        f"Transaction data covers {first.isoformat()} to {last.isoformat()} "
        f"({count} transactions). Nothing outside that window is known."
    ]

    partial = []
    if first.day != 1:
        partial.append(first.strftime("%Y-%m"))
    if last.day != calendar.monthrange(last.year, last.month)[1]:
        partial.append(last.strftime("%Y-%m"))
    # dict.fromkeys dedupes while keeping order, for the single-partial-month case.
    partial = list(dict.fromkeys(partial))

    if partial:
        facts.append(
            f"Partial months, covering only part of the month: {', '.join(partial)}. "
            "Their totals are not comparable to full months and must not be described "
            "as a rise or fall in spending."
        )
    return facts


def aggregate_facts(db: Session) -> list[str]:
    """Deterministic SQL rollups for aggregate-shaped questions.

    Everything here is computed in Postgres. The LLM never does arithmetic — it
    only turns these lines into a sentence.
    """
    facts: list[str] = []

    snapshot = latest_holdings_snapshot(db)
    total = sum((v for _, _, v in snapshot if v is not None), Decimal(0))
    facts.append(f"Total investment market value (latest snapshot per position): ${total:,.2f}")
    for name, ticker, value in sorted(snapshot, key=lambda r: -(r[2] or 0)):
        if value is not None:
            share = (value / total * 100) if total else Decimal(0)
            facts.append(f"Holding: {name} {ticker} = ${value:,.2f} ({share:.1f}% of investments)")

    facts.extend(_coverage_facts(db))

    by_category = db.execute(
        select(Transaction.category, func.sum(Transaction.amount), func.count())
        .group_by(Transaction.category)
        .order_by(func.sum(Transaction.amount))
    ).all()
    for category, amount, count in by_category:
        facts.append(f"Spend by category: {category or 'uncategorized'} = ${amount:,.2f} ({count} txns)")

    # Build the month expression once and reuse the object. Constructing
    # to_char() separately for SELECT, GROUP BY, and ORDER BY gives each call its
    # own bind parameter, and Postgres then rejects the query because the grouped
    # expression is not syntactically identical to the selected one.
    month = func.to_char(Transaction.txn_date, "YYYY-MM")
    monthly = db.execute(
        select(month, func.sum(Transaction.amount))
        .group_by(month)
        .order_by(month.desc())
        .limit(12)
    ).all()
    for month, amount in monthly:
        facts.append(f"Net cash flow {month}: ${amount:,.2f}")

    return facts
