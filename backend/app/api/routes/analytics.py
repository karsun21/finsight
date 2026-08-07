from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Holding
from app.rag.retrieval import latest_holdings_snapshot

router = APIRouter(tags=["analytics"])


@router.get("/net-worth")
def net_worth(db: Session = Depends(get_db)) -> dict:
    """Investment market value over time, plus the current total.

    Cash balances are not included yet — that needs a running balance from the
    DCU parser, which does not exist. The response says so rather than silently
    reporting a partial number as "net worth".
    """
    series = db.execute(
        select(Holding.as_of_date, func.sum(Holding.market_value))
        .group_by(Holding.as_of_date)
        .order_by(Holding.as_of_date)
    ).all()

    snapshot = latest_holdings_snapshot(db)
    current = sum((value for _, _, value in snapshot if value is not None), Decimal(0))

    return {
        "current_investment_value": current,
        "includes_cash": False,
        "series": [{"as_of_date": d, "market_value": v} for d, v in series],
    }


@router.get("/allocation")
def allocation(db: Session = Depends(get_db)) -> dict:
    snapshot = latest_holdings_snapshot(db)
    total = sum((value for _, _, value in snapshot if value is not None), Decimal(0))
    positions = [
        {
            "institution": name,
            "ticker": ticker,
            "market_value": value,
            "weight_pct": float(value / total * 100) if total and value else 0.0,
        }
        for name, ticker, value in snapshot
        if value is not None
    ]
    return {
        "total": total,
        "positions": sorted(positions, key=lambda p: -p["market_value"]),
    }
