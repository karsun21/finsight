"""Inbox scan -> parse -> normalize -> dedup -> classify -> embed -> insert."""

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classification.rules import categorize
from app.config import get_settings
from app.ingestion.dedup import holding_hash, transaction_hash
from app.ingestion.registry import FOLDER_TO_INSTITUTION, INSTITUTIONS, resolve
from app.models import Holding, IngestionLog, Institution, Transaction
from app.rag.embeddings import embed_texts, holding_to_text, transaction_to_text
from app.schemas import IngestResult

log = logging.getLogger(__name__)


def ensure_institutions(db: Session) -> dict[str, int]:
    """Idempotently seed the institutions table; return name -> id."""
    existing = {i.name: i.id for i in db.scalars(select(Institution)).all()}
    for name, account_type in INSTITUTIONS:
        if name not in existing:
            row = Institution(name=name, account_type=account_type)
            db.add(row)
            db.flush()
            existing[name] = row.id
    db.commit()
    return existing


def ingest_inbox(db: Session, inbox: Path | None = None) -> IngestResult:
    inbox = inbox or get_settings().inbox_dir
    institutions = ensure_institutions(db)
    result = IngestResult(files_seen=0, files_ingested=0, rows_ingested=0, rows_duplicate=0)

    for folder, institution_name in FOLDER_TO_INSTITUTION.items():
        folder_path = inbox / folder
        if not folder_path.is_dir():
            continue

        for path in sorted(folder_path.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            result.files_seen += 1

            if _already_ingested(db, path.name):
                continue

            parser = resolve(folder, path)
            if parser is None:
                _log_file(db, path.name, None, None, "skipped", 0, 0, "no parser for this format")
                result.failures.append(f"{path.name}: no parser")
                continue

            institution_id = institutions[institution_name]
            try:
                parsed = parser.parse(path)
            except Exception as exc:  # noqa: BLE001 — one bad file must not stop the run
                log.exception("parse failed for %s", path)
                _log_file(
                    db, path.name, institution_id, type(parser).__name__, "failed", 0, 0, str(exc)
                )
                result.failures.append(f"{path.name}: {exc}")
                continue

            inserted, duplicate = _persist(
                db, parsed, institution_id, institution_name, path.name
            )
            status = "partial" if parsed.warnings else "success"
            _log_file(
                db,
                path.name,
                institution_id,
                type(parser).__name__,
                status,
                inserted,
                duplicate,
                "; ".join(parsed.warnings) or None,
            )
            result.files_ingested += 1
            result.rows_ingested += inserted
            result.rows_duplicate += duplicate

    return result


def _already_ingested(db: Session, file_name: str) -> bool:
    return (
        db.scalar(
            select(IngestionLog.id)
            .where(IngestionLog.file_name == file_name)
            .where(IngestionLog.status.in_(("success", "partial")))
            .limit(1)
        )
        is not None
    )


def _persist(db, parsed, institution_id: int, institution_name: str, file_name: str):
    """Insert rows whose dedup hash is new. Returns (inserted, duplicate)."""
    inserted = duplicate = 0

    txn_rows: list[Transaction] = []
    for txn in parsed.transactions:
        digest = transaction_hash(institution_name, txn.txn_date, txn.amount, txn.description)
        if db.scalar(select(Transaction.id).where(Transaction.dedup_hash == digest)):
            duplicate += 1
            continue
        txn_rows.append(
            Transaction(
                institution_id=institution_id,
                txn_date=txn.txn_date,
                posted_date=txn.posted_date,
                description=txn.description,
                amount=txn.amount,
                category=txn.category or categorize(txn.description),
                source_file=file_name,
                dedup_hash=digest,
            )
        )

    hold_rows: list[Holding] = []
    for holding in parsed.holdings:
        digest = holding_hash(institution_name, holding.as_of_date, holding.ticker)
        if db.scalar(select(Holding.id).where(Holding.dedup_hash == digest)):
            duplicate += 1
            continue
        hold_rows.append(
            Holding(
                institution_id=institution_id,
                as_of_date=holding.as_of_date,
                ticker=holding.ticker,
                asset_class=holding.asset_class,
                quantity=holding.quantity,
                cost_basis=holding.cost_basis,
                market_value=holding.market_value,
                vested=holding.vested,
                source_file=file_name,
                dedup_hash=digest,
            )
        )

    # Embed in one batch per file — the model has meaningful per-call overhead.
    if txn_rows:
        for row, vector in zip(
            txn_rows,
            embed_texts([transaction_to_text(r, institution_name) for r in txn_rows]),
            strict=True,
        ):
            row.embedding = vector
    if hold_rows:
        for row, vector in zip(
            hold_rows,
            embed_texts([holding_to_text(r, institution_name) for r in hold_rows]),
            strict=True,
        ):
            row.embedding = vector

    db.add_all(txn_rows + hold_rows)
    db.commit()
    inserted = len(txn_rows) + len(hold_rows)
    return inserted, duplicate


def _log_file(db, file_name, institution_id, parser, status, rows, dupes, error):
    db.add(
        IngestionLog(
            file_name=file_name,
            institution_id=institution_id,
            parser=parser,
            status=status,
            rows_ingested=rows,
            rows_duplicate=dupes,
            error=error,
        )
    )
    db.commit()
