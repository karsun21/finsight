from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    institution_id: int
    txn_date: date
    posted_date: date | None
    description: str
    amount: Decimal
    category: str | None
    is_recurring: bool
    source_file: str


class HoldingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    institution_id: int
    as_of_date: date
    ticker: str
    asset_class: str | None
    quantity: Decimal
    cost_basis: Decimal | None
    market_value: Decimal | None
    vested: bool | None


class IngestionLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    parser: str | None
    status: str
    rows_ingested: int
    rows_duplicate: int
    error: str | None
    ingested_at: datetime


class IngestResult(BaseModel):
    files_seen: int
    files_ingested: int
    rows_ingested: int
    rows_duplicate: int
    failures: list[str] = []


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    route: str  # "aggregate" | "semantic"
    rows_used: int
