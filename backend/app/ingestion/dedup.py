import hashlib
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

_READ_CHUNK = 64 * 1024

_WHITESPACE = re.compile(r"\s+")
# Trailing reference/auth numbers vary between the CSV and the PDF of the same
# transaction, so they are stripped before hashing — otherwise backfilling from
# PDF would duplicate rows already ingested from CSV.
_TRAILING_REF = re.compile(r"\s+#?\d{6,}$")


def normalize_description(description: str) -> str:
    text = description.upper().strip()
    text = _TRAILING_REF.sub("", text)
    return _WHITESPACE.sub(" ", text)


def transaction_hash(
    institution: str, txn_date: date, amount: Decimal, description: str
) -> str:
    key = f"{institution}|{txn_date.isoformat()}|{amount:.2f}|{normalize_description(description)}"
    return hashlib.sha256(key.encode()).hexdigest()


def occurrence_hash(base_digest: str, occurrence: int) -> str:
    """Disambiguate the Nth *genuinely identical* transaction within one file.

    Two $3.50 coffees at the same shop on the same day are indistinguishable
    under `transaction_hash` — same institution, date, amount, description — so
    both rows produce one digest and the unique constraint rejects the batch.
    Dropping the second would be wrong too: it's a real charge, and silently
    discarding it understates spending.

    So the occurrence index within the source file becomes part of the key.
    Occurrence 0 deliberately hashes to the base digest unchanged, which keeps
    the common case byte-identical to what it was before this existed.

    Computing the index **per file** rather than per database is what keeps
    re-ingestion idempotent. Re-dropping the same file regenerates the same
    sequence (0, 1, ...), so both digests are found and both rows skip. If the
    index were derived from what's already stored, the second ingest would see
    occurrence 0 taken, insert at 1, and duplicate the row it was meant to
    recognize.
    """
    if occurrence == 0:
        return base_digest
    return hashlib.sha256(f"{base_digest}#{occurrence}".encode()).hexdigest()


def holding_hash(institution: str, as_of_date: date, ticker: str) -> str:
    """One row per (institution, snapshot date, ticker) — re-ingesting the same
    statement overwrites nothing and inserts nothing."""
    key = f"{institution}|{as_of_date.isoformat()}|{ticker.upper()}"
    return hashlib.sha256(key.encode()).hexdigest()


def file_hash(path: Path) -> str:
    """Fingerprint a file's *contents*, for deciding whether it was already run.

    Skipping by filename is not enough: Capital One names every export
    identically, so the second month's file looks like one already processed.
    Contents are the thing that actually determines whether there's new data.

    Streamed in chunks so a large PDF backfill doesn't get read into memory
    whole.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()
