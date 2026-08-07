from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Transaction
from app.schemas import TransactionOut

router = APIRouter(tags=["transactions"])


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    institution_id: int | None = None,
    category: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    query = select(Transaction)
    if institution_id is not None:
        query = query.where(Transaction.institution_id == institution_id)
    if category is not None:
        query = query.where(Transaction.category == category)
    if start is not None:
        query = query.where(Transaction.txn_date >= start)
    if end is not None:
        query = query.where(Transaction.txn_date <= end)
    query = query.order_by(desc(Transaction.txn_date)).limit(limit).offset(offset)
    return db.scalars(query).all()
