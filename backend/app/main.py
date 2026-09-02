import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.routes import analytics, chat, health, holdings, ingest, transactions
from app.db import SessionLocal
from app.ingestion.pipeline import ensure_institutions

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="FinSight",
    description="Personal finance assistant over your own statement exports. Ask a "
    "question in plain English; aggregate questions are answered from SQL rollups "
    "and specific lookups from vector search over transaction descriptions. "
    "Automated ingestion currently covers Capital One credit statements.",
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
    # Schema is owned by Alembic, applied by `alembic upgrade head` in the
    # container command before uvicorn starts — not here. create_all() used to
    # run at this point, which created missing tables but silently ignored
    # changes to existing ones; adding file_hash to ingestion_log appeared to
    # work and then failed at query time.
    #
    # Seeding institutions is data, not schema, so it stays. It is idempotent.
    with SessionLocal() as db:
        ensure_institutions(db)


app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(transactions.router)
app.include_router(holdings.router)
app.include_router(analytics.router)
app.include_router(chat.router)

# The chat client is a single self-contained HTML file served by this API rather
# than a separate build: it is one input, one message list, and one fetch, so a
# framework and a build step would cost more than they return. Same-origin, so
# the CORS middleware above is not involved. Registered last, and at a path no
# router claims, so it cannot shadow an endpoint.
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def chat_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
