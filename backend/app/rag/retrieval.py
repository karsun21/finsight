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

    by_category = db.execute(
        select(Transaction.category, func.sum(Transaction.amount), func.count())
        .group_by(Transaction.category)
        .order_by(func.sum(Transaction.amount))
    ).all()
    for category, amount, count in by_category:
        facts.append(f"Spend by category: {category or 'uncategorized'} = ${amount:,.2f} ({count} txns)")

    monthly = db.execute(
        select(
            func.to_char(Transaction.txn_date, "YYYY-MM"),
            func.sum(Transaction.amount),
        )
        .group_by(func.to_char(Transaction.txn_date, "YYYY-MM"))
        .order_by(func.to_char(Transaction.txn_date, "YYYY-MM").desc())
        .limit(12)
    ).all()
    for month, amount in monthly:
        facts.append(f"Net cash flow {month}: ${amount:,.2f}")

    return facts
