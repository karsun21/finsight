from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Holding, Transaction

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    has_pgvector = db.scalar(
        text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
    )
    return {
        "status": "ok",
        "pgvector": bool(has_pgvector),
        "transactions": db.scalar(select(func.count()).select_from(Transaction)),
        "holdings": db.scalar(select(func.count()).select_from(Holding)),
    }
