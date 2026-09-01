"""Transaction categorization.

Coarse buckets only — "dining", not "coffee specifically". See
docs/HOW-IT-WORKS.md §1.1 for why this stays a regex list rather than becoming a
trained classifier.

Two things can suggest a category for a row: the merchant description, and
whatever label the issuer shipped in its own export. Descriptions win — see
`resolve_category()` for why.
"""

import logging
import re

log = logging.getLogger(__name__)

#: The project taxonomy — every category anything in this module can return.
#: Aggregate spending questions are a `GROUP BY category` over this set, so this
#: is the vocabulary the whole product reports in. Adding a bucket here means
#: adding it to the rules or the issuer map too; `_validate_taxonomy()` enforces
#: the reverse direction.
CATEGORIES: frozenset[str] = frozenset(
    {
        "dining",
        "groceries",
        "travel",
        "transport",
        "shopping",
        "housing",
        "utilities",
        "health",
        "insurance",
        "entertainment",
        "donations",
        "subscriptions",
        "fees",
        "cash",
        "transfer",
        "card_payment",
        "income",
        "investment_income",
    }
)

#: Categories that move money without being spending. Monthly rollups must
#: exclude these: a credit card statement carries one payment per cycle, and
#: netting it against the charges inverts the answer — May→June once read as
#: cash flow *rising* $135.77 while spending actually *fell* $399.
#: `cash` is deliberately absent — an ATM withdrawal is money going out.
NON_SPEND_CATEGORIES: frozenset[str] = frozenset(
    {
        "card_payment",
        "transfer",
        "income",
        "investment_income",
    }
)

assert NON_SPEND_CATEGORIES <= CATEGORIES, "NON_SPEND_CATEGORIES must be a subset of CATEGORIES"

# Ordered: first match wins, so put specific patterns above general ones.
# Matched against the uppercased description.
RULES: list[tuple[str, str]] = [
    # GOOGLE ONE is cloud storage, but Capital One labels it "Internet", which the
    # issuer map sends to utilities. Rules run first, so naming it here wins.
    # Deliberately not a bare GOOGLE — that would swallow Play, Ads, and Domains.
    (
        r"NETFLIX|SPOTIFY|HULU|DISNEY|PRIME VIDEO|YOUTUBE PREMIUM|ICLOUD|DROPBOX"
        r"|GOOGLE ONE",
        "subscriptions",
    ),
    # COFFEE belongs here: at coarse granularity a coffee run *is* dining. That's
    # the scope decision, not an oversight — see docs/HOW-IT-WORKS.md §1.1.
    (
        r"CHIPOTLE|STARBUCKS|DOORDASH|UBER EATS|GRUBHUB|MCDONALD"
        r"|RESTAURANT|CAFE|COFFEE|PIZZA|\bBAR\b|BREWING|TAQUERIA|\bDELI\b",
        "dining",
    ),
    (r"KROGER|PUBLIX|TRADER JOE|WHOLE FOODS|ALDI|SAFEWAY|WEGMANS|GROCER", "groceries"),
    # Travel sits above transport deliberately. Airport *parking* is transport;
    # the flight is not. Carrier names are qualified (DELTA AIR, not DELTA) so
    # they cannot swallow DELTA DENTAL or FRONTIER COMMUNICATIONS — a bare
    # airline name is one of the easiest ways to poison this bucket.
    # Starting list; extend it once real card data shows what actually appears.
    (
        r"DELTA AIR|UNITED AIR|AMERICAN AIR|SOUTHWEST AIR|ALASKA AIR|SPIRIT AIR"
        r"|FRONTIER AIR|JETBLUE|\bAIRLINE|AMTRAK"
        r"|AIRBNB|VRBO|MARRIOTT|HILTON|HYATT|\bIHG\b|WESTIN|SHERATON|RITZ.CARLTON"
        r"|BOOKING\.COM|HOTELS\.COM|EXPEDIA|PRICELINE|ORBITZ|TRIP\.COM"
        r"|\bAVIS\b|HERTZ|ENTERPRISE RENT|BUDGET RENT|NATIONAL CAR|ALAMO RENT",
        "travel",
    ),
    # \b on the short tokens is load-bearing, not tidiness. Unanchored, MTA
    # matches "PYMTAUTHDATE" (a card payment filed as transport), ATM matches
    # "TREATMENT", ACH matches "COACH"/"BEACH", FEE matches "COFFEE", and RENT
    # matches "AVIS RENT A CAR". Each one silently moves money into the wrong
    # bucket, which at coarse granularity is the only thing this project reports.
    # Utilities sits ABOVE transport so the phone carriers win the word "METRO".
    # METRO PCS / METRO BY T-MOBILE are not subway rides.
    (
        r"ELECTRIC|WATER UTIL|GAS COMPANY|COMCAST|XFINITY|VERIZON|T-MOBILE|AT&T"
        r"|METRO ?PCS|METRO BY T",
        "utilities",
    ),
    # Local transit belongs here, not in travel. Capital One files transit fares
    # under a travel-ish label (MCC 4111 sits in the 4000-4799 transportation
    # block alongside airlines), so without these rules every $2.25 subway tap
    # falls through to the issuer map and inflates "travel".
    (
        r"UBER|LYFT|SHELL|EXXON|CHEVRON|BP #|MARATHON|PARKING"
        r"|\bMTA\b|TRANSIT|\bMETRO\b|METROCARD|SMARTRIP|WMATA|\bMARTA\b"
        r"|\bSEPTA\b|\bBART\b|\bMUNI\b|CLIPPER CARD|ORCA CARD|CHARLIECARD|TRIMET"
        r"|\bVENTRA\b",
        "transport",
    ),
    (r"AMAZON|TARGET|WALMART|COSTCO|BEST BUY|FABLETICS", "shopping"),
    # Capital One's "Entertainment" label was the only thing populating this
    # bucket. These are the merchants its label missed — REGALTICKETS arrives
    # through a benefits portal as *PERKSATWORK*REGALTICKETS with no issuer
    # category at all, so only a rule catches it.
    (
        r"REGAL CINEMA|REGALTICKETS|AMC THEATRE|AMC CLASSIC|CINEMARK|ALAMO DRAFTHOUSE"
        r"|FANDANGO|TICKETMASTER|DICE\.FM|STUBHUB|EVENTBRITE|AXS\.COM",
        "entertainment",
    ),
    # Self-storage is a recurring housing-adjacent cost. Named brands rather than
    # a bare STORAGE, which would swallow "GOOGLE ONE STORAGE" and similar.
    (
        r"\bRENT\b|LANDLORD|PROPERTY MGMT|APARTMENT"
        r"|SELF STORAGE|PUBLIC STORAGE|EXTRA SPACE STOR|CUBESMART|LIFE STORAGE",
        "housing",
    ),
    # Fitness folds into health rather than getting its own bucket, and rather
    # than staying where Capital One puts it. Its "Entertainment" label covered
    # both a gym membership and a concert ticket, which made "how much do I spend
    # on entertainment" answer with the gym included. Owner's call, 2026-08-12:
    # keep the bucket count down, and treat a gym as closer to healthcare than to
    # a night out.
    (
        r"CVS|WALGREENS|PHARMACY|DENTAL|MEDICAL|CLINIC|HOSPITAL"
        r"|GLOBALFIT|PICKLR|PICKLEBALL|\bGYM\b|GOLD.?S GYM|PLANET FITNESS"
        r"|LA FITNESS|LIFE ?TIME FITNESS|ANYTIME FITNESS|CRUNCH FITNESS"
        r"|EQUINOX|ORANGETHEORY|SOULCYCLE|CROSSFIT|CLASSPASS|PELOTON|\bF45\b|\bYMCA\b",
        "health",
    ),
    (r"GOFUNDME|\bDONATION\b|\bDONATE\b|RED CROSS|UNICEF|\bNPR\b", "donations"),
    (r"PAYROLL|DIRECT DEP|SALARY|EMPLOYER", "income"),
    (r"TRANSFER|XFER|ZELLE|VENMO|CASH APP|\bACH\b", "transfer"),
    (r"PAYMENT.*THANK YOU|AUTOPAY|CARD PAYMENT|\bPYMT\b", "card_payment"),
    (r"INTEREST|DIVIDEND", "investment_income"),
    (r"\bATM\b|WITHDRAWAL", "cash"),
    (r"\bFEES?\b|SERVICE CHARGE|OVERDRAFT", "fees"),
]

#: Issuer-supplied categories mapped onto the project taxonomy, keyed by the
#: label lowercased. Currently Capital One's set — the only issuer that ships
#: categories at all right now.
#:
#: An explicit `None` means "seen, deliberately not mapped": these are grab-bag
#: labels that carry no real signal, and inventing a bucket for them would put
#: wrong numbers in a spending breakdown. Leaving the row uncategorized is the
#: honest outcome. A label *missing* from this dict is different — that's one we
#: have never seen, and it gets logged.
ISSUER_CATEGORIES: dict[str, str | None] = {
    "airfare": "travel",
    "car rental": "travel",
    "hotels": "travel",
    "lodging": "travel",
    # NOT travel. Observed on real data: Capital One files subway fares
    # (transit-card reloads and fare taps) and self-storage under this label, by
    # MCC range — 4111 local transit and 4225 storage both sit in the 4000-4799
    # transportation block with the airlines. It behaves like "other services":
    # a grab bag with no reliable meaning. Genuine travel arrives labelled
    # airfare / hotels / lodging, which stay mapped above.
    "other travel": None,
    "dining": "dining",
    "grocery": "groceries",
    "entertainment": "entertainment",
    "gas/automotive": "transport",
    "health care": "health",
    "insurance": "insurance",
    "internet": "utilities",
    "phone/cable": "utilities",
    "utilities": "utilities",
    "merchandise": "shopping",
    "payment/credit": "card_payment",
    "fee/interest charge": "fees",
    "other": None,
    "other services": None,
    "professional services": None,
}

_COMPILED = [(re.compile(pattern), category) for pattern, category in RULES]

#: Issuer labels already reported, so a 200-row file logs each novelty once.
_unmapped_seen: set[str] = set()


def categorize(description: str) -> str | None:
    """Return a category based on the description alone, or None if no rule matches."""
    text = description.upper()
    for pattern, category in _COMPILED:
        if pattern.search(text):
            return category
    return None


def resolve_category(description: str, issuer_category: str | None = None) -> str | None:
    """Return a project-taxonomy category for one transaction, or None.

    **Description rules win over the issuer's label.** Issuer taxonomies are
    inconsistent between institutions and coarse in the wrong places — Capital
    One files KROGER under "merchandise" and NETFLIX under "other services" —
    so the issuer label is a fallback for rows our own rules don't recognize,
    not a starting point. Getting this backwards was the original bug: a plain
    `issuer or rules` short-circuit meant the rules never ran for card
    transactions at all.

    Returning None is a real answer. An uncategorized row is recoverable; a
    confidently wrong bucket silently corrupts every spending total.
    """
    matched = categorize(description)
    if matched is not None:
        return matched

    if not issuer_category:
        return None

    label = issuer_category.strip().lower()
    if label not in ISSUER_CATEGORIES:
        if label not in _unmapped_seen:
            _unmapped_seen.add(label)
            log.warning(
                "unmapped issuer category %r — add it to ISSUER_CATEGORIES in "
                "classification/rules.py; rows land uncategorized until then",
                label,
            )
        return None

    return ISSUER_CATEGORIES[label]


def _validate_taxonomy() -> None:
    """Fail at import if a rule or mapping invents a category.

    Without this a typo ("grocerys") silently creates a phantom bucket that
    shows up in spending breakdowns and matches nothing anyone filters on.
    """
    stray = {category for _, category in RULES} - CATEGORIES
    stray |= {c for c in ISSUER_CATEGORIES.values() if c is not None} - CATEGORIES
    if stray:
        raise ValueError(f"categories outside the project taxonomy: {sorted(stray)}")


_validate_taxonomy()
