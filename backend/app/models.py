from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings

EMBEDDING_DIM = get_settings().embedding_dim


class Base(DeclarativeBase):
    pass


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    # checking | savings | credit | brokerage | 401k | espp
    account_type: Mapped[str] = mapped_column(String(32))

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="institution")
    holdings: Mapped[list["Holding"]] = relationship(back_populates="institution")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    txn_date: Mapped[date] = mapped_column(Date, index=True)
    posted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str] = mapped_column(Text)
    # Sign convention: negative = money out, positive = money in. Normalizers are
    # responsible for flipping institution-specific conventions to match.
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # The issuer's own label, kept verbatim alongside our resolved category so
    # "why is this row in this bucket?" is answerable in SQL. Diagnosing the
    # travel-vs-transport problem meant re-running the rules by hand because
    # this was discarded. Not indexed: it is for inspection, not filtering.
    issuer_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    source_file: Mapped[str] = mapped_column(Text)
    # sha256 over (institution, txn_date, amount, normalized description) — the
    # unique constraint is what makes re-dropping the same statement a no-op.
    dedup_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    institution: Mapped[Institution] = relationship(back_populates="transactions")


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    # Holdings are a point-in-time snapshot, so (institution, as_of_date, ticker)
    # is the natural key — net worth over time is a series of these snapshots.
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    asset_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    cost_basis: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    market_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    vested: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_file: Mapped[str] = mapped_column(Text)
    dedup_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    institution: Mapped[Institution] = relationship(back_populates="holdings")


class IngestionLog(Base):
    __tablename__ = "ingestion_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(Text)
    # sha256 of the file's contents. This, not file_name, is what decides whether
    # a file has already been ingested — Capital One names every export the same
    # thing, so a name-based check silently swallows every month after the first.
    # Nullable because a file we cannot read still deserves a log row.
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id"), nullable=True
    )
    parser: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # success | partial | failed | skipped
    status: Mapped[str] = mapped_column(String(16))
    rows_ingested: Mapped[int] = mapped_column(Integer, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
