"""Answer generation via the Claude API."""

from functools import lru_cache

import anthropic

from app.config import get_settings

SYSTEM_PROMPT = """You are FinSight, a personal finance assistant answering questions about \
one person's own financial data.

You will be given a set of data rows retrieved from their database. Rules:

- Answer only from the provided rows. If the rows do not contain enough information \
to answer, say so plainly and name what is missing.
- Cite specific numbers and dates from the rows. Never estimate or extrapolate.
- Any figure labeled as a total or aggregate was already computed in SQL. Use it as \
given; do not recompute or re-add the underlying rows.
- Amounts are signed: negative is money out, positive is money in.
- Be concise. Lead with the answer, then the supporting figures."""


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — copy .env.example to .env")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def answer(question: str, rows: list[str]) -> str:
    settings = get_settings()
    context = "\n".join(rows) if rows else "(no matching rows)"

    response = _client().messages.create(
        model=settings.chat_model,
        max_tokens=1500,
        # cache_control pays off once the system prompt grows past the model's
        # minimum cacheable prefix (1024 tokens on Sonnet 5). It is a no-op below
        # that — harmless, and already wired for when few-shot examples are added.
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[
            {
                "role": "user",
                "content": f"<data>\n{context}\n</data>\n\nQuestion: {question}",
            }
        ],
    )
    return "".join(block.text for block in response.content if block.type == "text")
