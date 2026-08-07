"""Query router: aggregate vs semantic.

"What's my net worth" needs *every* holding row, and vector search over the top-k
most similar rows will confidently answer it wrong. So aggregate-shaped questions
bypass retrieval and run SQL instead; the LLM only phrases the result.

Rules first because they are free and cover the common cases. Escalate the
ambiguous remainder to Haiku (see classify_with_llm) once you have real questions
that the rules get wrong — don't add the API call before then.
"""

import re

AGGREGATE_PATTERNS = [
    r"\bnet worth\b",
    r"\btotal\b",
    r"\bhow much (did|do|have) i\b",
    r"\ballocation\b",
    r"\bbreakdown\b",
    r"\baverage\b",
    r"\bsum\b",
    r"\bbalance\b",
    r"\bconcentration\b",
    r"\bper month\b|\bmonthly\b",
    r"\bcompared? to\b|\bvs\.?\b",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in AGGREGATE_PATTERNS]


def route(question: str) -> str:
    """Return "aggregate" or "semantic"."""
    return "aggregate" if any(p.search(question) for p in _COMPILED) else "semantic"
