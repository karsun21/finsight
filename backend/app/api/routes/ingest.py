from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.ingestion.pipeline import ingest_inbox
from app.models import IngestionLog
from app.schemas import IngestionLogOut, IngestResult

router = APIRouter(tags=["ingestion"])


@router.post("/ingest", response_model=IngestResult)
def trigger_ingest(db: Session = Depends(get_db)) -> IngestResult:
    """Scan /inbox and ingest anything not already logged as successful."""
    return ingest_inbox(db)


@router.get("/ingestion-log", response_model=list[IngestionLogOut])
def ingestion_log(limit: int = 50, db: Session = Depends(get_db)):
    return db.scalars(
        select(IngestionLog).order_by(desc(IngestionLog.ingested_at)).limit(limit)
    ).all()
