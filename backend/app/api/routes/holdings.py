from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Holding
from app.schemas import HoldingOut

router = APIRouter(tags=["holdings"])


@router.get("/holdings", response_model=list[HoldingOut])
def list_holdings(
    institution_id: int | None = None,
    ticker: str | None = None,
    as_of: date | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    query = select(Holding)
    if institution_id is not None:
        query = query.where(Holding.institution_id == institution_id)
    if ticker is not None:
        query = query.where(Holding.ticker == ticker.upper())
    if as_of is not None:
        query = query.where(Holding.as_of_date == as_of)
    query = query.order_by(desc(Holding.as_of_date), Holding.ticker).limit(limit)
    return db.scalars(query).all()
