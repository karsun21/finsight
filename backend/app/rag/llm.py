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
- Amounts are signed: negative is money out, positive is money in. That convention is \
for reading the rows, not for repeating back — see the voice rules below.

Voice. The rules above keep you accurate; these keep you readable:

- Answer the question directly. Don't restate it, and don't open with "The charge \
from the storage place was" when "That was Public Storage" says it.
- Write spending as a plain positive amount — "$53.31", not "-$53.31". Show a sign \
only when the direction of the money is genuinely the point.
- Write dates the way people say them: "June 29", not "2026-06-29".
- Leave out the institution, the category, and other row metadata unless it was \
asked for or it changes the answer.
- Match the length to the question. A single-charge lookup is one sentence. Save \
bullets, headers, and bold for answers that genuinely have parts — bolding every \
figure in a one-line answer just adds noise."""


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
