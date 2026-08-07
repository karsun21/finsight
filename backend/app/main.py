import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import analytics, chat, health, holdings, ingest, transactions
from app.db import SessionLocal, engine
from app.ingestion.pipeline import ensure_institutions
from app.models import Base

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="FinSight",
    description="Personal finance RAG assistant across DCU, Capital One, Vanguard, "
    "Fidelity, and Morgan Stanley.",
    version="0.1.0",
)

# Local-only frontend during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    # create_all is fine while the schema is still moving. Switch to Alembic
    # migrations before there is data in the database you care about keeping.
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_institutions(db)


app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(transactions.router)
app.include_router(holdings.router)
app.include_router(analytics.router)
app.include_router(chat.router)
