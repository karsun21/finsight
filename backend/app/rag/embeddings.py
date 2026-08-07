"""Local embeddings via sentence-transformers. No API cost, no data leaves the box."""

from functools import lru_cache

from app.config import get_settings


@lru_cache(maxsize=1)
def _model():
    # Imported lazily so that importing this module (e.g. in tests that never
    # embed) does not pull in torch and pay a multi-second import.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(get_settings().embedding_model)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return _model().encode(texts, normalize_embeddings=True).tolist()


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def transaction_to_text(txn, institution: str) -> str:
    """The row's text representation — this is what gets embedded and what the
    LLM sees at answer time, so keep it readable and self-describing."""
    category = txn.category or "uncategorized"
    return (
        f"{txn.txn_date.isoformat()} | {institution} | {category} | "
        f"${txn.amount:,.2f} | {txn.description}"
    )


def holding_to_text(holding, institution: str) -> str:
    value = f"${holding.market_value:,.2f}" if holding.market_value is not None else "unknown value"
    return (
        f"{holding.as_of_date.isoformat()} | {institution} | holding | "
        f"{holding.ticker} | {holding.quantity} shares | {value}"
    )
