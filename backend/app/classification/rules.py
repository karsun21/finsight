"""Rule-based transaction categorization.

Phase 1 baseline. Once a few thousand rows are categorized and hand-corrected,
this becomes the labeled training set for the scikit-learn classifier, with these
rules kept as the fallback for low-confidence predictions.
"""

import re

# Ordered: first match wins, so put specific patterns above general ones.
RULES: list[tuple[str, str]] = [
    (r"NETFLIX|SPOTIFY|HULU|DISNEY|PRIME VIDEO|YOUTUBE PREMIUM|ICLOUD|DROPBOX", "subscriptions"),
    (r"CHIPOTLE|STARBUCKS|DOORDASH|UBER EATS|GRUBHUB|MCDONALD|RESTAURANT|CAFE|PIZZA", "dining"),
    (r"KROGER|PUBLIX|TRADER JOE|WHOLE FOODS|ALDI|SAFEWAY|WEGMANS|GROCER", "groceries"),
    (r"UBER|LYFT|SHELL|EXXON|CHEVRON|BP #|MARATHON|PARKING|MTA|TRANSIT", "transport"),
    (r"AMAZON|TARGET|WALMART|COSTCO|BEST BUY", "shopping"),
    (r"RENT|LANDLORD|PROPERTY MGMT|APARTMENT", "housing"),
    (r"ELECTRIC|WATER UTIL|GAS COMPANY|COMCAST|XFINITY|VERIZON|T-MOBILE|AT&T", "utilities"),
    (r"CVS|WALGREENS|PHARMACY|DENTAL|MEDICAL|CLINIC|HOSPITAL", "health"),
    (r"PAYROLL|DIRECT DEP|SALARY|EMPLOYER", "income"),
    (r"TRANSFER|XFER|ZELLE|VENMO|CASH APP|ACH", "transfer"),
    (r"PAYMENT.*THANK YOU|AUTOPAY|CARD PAYMENT", "card_payment"),
    (r"INTEREST|DIVIDEND", "investment_income"),
    (r"ATM|WITHDRAWAL", "cash"),
    (r"FEE|SERVICE CHARGE|OVERDRAFT", "fees"),
]

_COMPILED = [(re.compile(pattern), category) for pattern, category in RULES]


def categorize(description: str) -> str | None:
    """Return a category, or None when no rule matches (left for the ML model)."""
    text = description.upper()
    for pattern, category in _COMPILED:
        if pattern.search(text):
            return category
    return None
