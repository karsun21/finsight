"""Categorization: the coarse buckets are the product, so they get pinned hard.

The bug these exist to prevent: the pipeline used to do
`txn.category or categorize(...)`, which short-circuited on any issuer-supplied
label and meant the rules never ran for Capital One rows at all.
"""

from pathlib import Path

import pytest

from app.classification.rules import (
    CATEGORIES,
    ISSUER_CATEGORIES,
    RULES,
    categorize,
    resolve_category,
)
from app.ingestion.parsers.capital_one import CapitalOneCSVParser

FIXTURE = Path(__file__).parent / "fixtures" / "capital_one_sample.csv"


# --- rules beat issuer labels -------------------------------------------------


@pytest.mark.parametrize(
    ("description", "issuer_category", "expected"),
    [
        # The two mis-categorizations observed live on the fixture.
        ("KROGER #421", "merchandise", "groceries"),
        ("NETFLIX.COM", "other services", "subscriptions"),
        # Issuer and rules agree here; result must be stable either way.
        ("CHIPOTLE MEXICAN GRILL", "dining", "dining"),
    ],
)
def test_description_rules_override_issuer_label(description, issuer_category, expected):
    assert resolve_category(description, issuer_category) == expected


def test_issuer_label_is_used_when_no_rule_matches():
    """The fallback still has to work — that's the whole reason to keep the map."""
    assert resolve_category("SUNSET SHUTTLE SVC", "car rental") == "travel"
    assert resolve_category("PORTOLA CO 8871", "merchandise") == "shopping"


def test_unrecognized_issuer_label_yields_none():
    assert resolve_category("SOMETHING UNRECOGNIZABLE", "artisanal widgets") is None


def test_deliberately_unmapped_issuer_labels_yield_none():
    """Grab-bag labels carry no signal; a wrong bucket is worse than no bucket."""
    for label in ("other", "other services", "professional services"):
        assert ISSUER_CATEGORIES[label] is None
        assert resolve_category("UNKNOWN MERCHANT LLC", label) is None


def test_no_rule_and_no_issuer_label_yields_none():
    assert resolve_category("UNKNOWN MERCHANT LLC") is None
    assert resolve_category("UNKNOWN MERCHANT LLC", None) is None
    assert resolve_category("UNKNOWN MERCHANT LLC", "") is None


# --- the travel bucket --------------------------------------------------------


@pytest.mark.parametrize(
    "description",
    [
        "DELTA AIR LINES 0062",
        "SOUTHWEST AIRLINES",
        "JETBLUE 2795512",
        "AIRBNB * HMQRST",
        "MARRIOTT BONVOY DENVER",
        "EXPEDIA 72998811",
        "BOOKING.COM AMSTERDAM",
    ],
)
def test_travel_matches_airlines_hotels_and_booking_sites(description):
    assert categorize(description) == "travel"


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        # Bare carrier names would swallow all of these. They're qualified for
        # exactly this reason — regressions here are silent and expensive.
        ("DELTA DENTAL OF MA", "health"),
        ("FRONTIER COMMUNICATIONS", None),
        ("AIRPORT PARKING LOT C", "transport"),
        ("UNITED WAY DONATION", "donations"),
    ],
)
def test_travel_patterns_do_not_swallow_lookalikes(description, expected):
    assert categorize(description) == expected


# --- transit is transport, not travel ----------------------------------------
# Found on the first real Capital One file: 18 of 19 "travel" rows were subway
# fares and a storage unit, all arriving via the issuer's own label.


@pytest.mark.parametrize(
    "description",
    [
        "METRO",
        "SMARTRIP RELOAD",
        "MARTA TAP AND GO",
        "WMATA RAIL",
        "METROCARD VENDING",
    ],
)
def test_local_transit_is_transport(description):
    assert categorize(description) == "transport"


def test_metro_pcs_is_utilities_not_a_subway_ride():
    """`METRO` is a transit pattern, so the phone carriers have to win it. They
    do by rule order, not by cleverness — utilities sits above transport."""
    assert categorize("METRO PCS PAYMENT") == "utilities"
    assert categorize("METRO BY T-MOBILE") == "utilities"


def test_other_travel_is_not_mapped_to_travel():
    """Capital One's "Other Travel" carried transit fares and a storage unit on
    real data. It's a grab bag, so it maps to nothing."""
    assert ISSUER_CATEGORIES["other travel"] is None
    assert resolve_category("SOME LOCAL BUS CO", "other travel") is None


def test_self_storage_is_housing():
    assert categorize("PUBLIC STORAGE 00000") == "housing"
    assert categorize("CUBESMART #4412") == "housing"


def test_storage_pattern_does_not_swallow_cloud_storage():
    """A bare STORAGE pattern would put iCloud in the housing bucket."""
    assert categorize("APPLE ICLOUD STORAGE 50GB") == "subscriptions"


def test_donations_bucket():
    assert categorize("GoFundMe Support for a friend") == "donations"


# --- merchants found in three months of real data ----------------------------


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("IBI*FABLETICS.COM", "shopping"),
        ("*PERKSATWORK*REGALTICKETS", "entertainment"),
        ("VENTRA ACCOUNT", "transport"),
        ("DICE.FM", "entertainment"),
        ("REGAL CINEMAS INC", "entertainment"),
    ],
)
def test_real_merchants_that_arrived_uncategorized(description, expected):
    """These four had no issuer label and no rule, so they landed as NULL. The
    payment-processor prefixes (IBI*, *PERKSATWORK*, SQ*, TST*) are why: they
    push the merchant name away from the start of the description."""
    assert categorize(description) == expected


def test_google_one_is_a_subscription_not_a_utility():
    """Capital One labels Google One as "Internet", which the issuer map sends to
    utilities. It's cloud storage. Rules run first, so naming it wins."""
    assert resolve_category("GOOGLE *Google One", "internet") == "subscriptions"


def test_google_one_pattern_does_not_swallow_other_google_charges():
    assert categorize("GOOGLE PLAY 1234") is None
    assert categorize("GOOGLE ADS 887766") is None


@pytest.mark.parametrize(
    "description",
    ["GLOBALFIT", "THE PICKLR", "PLANET FITNESS 4471", "EQUINOX FITNESS"],
)
def test_fitness_folds_into_health_not_entertainment(description):
    """Capital One labels gyms "Entertainment", which put a monthly gym
    membership into the same bucket as concert tickets. Owner chose health over
    a separate fitness bucket — see the comment on the health rule."""
    assert resolve_category(description, "entertainment") == "health"


@pytest.mark.parametrize("description", ["DICE.FM", "REGAL CINEMAS INC"])
def test_real_entertainment_stays_entertainment(description):
    assert resolve_category(description, "entertainment") == "entertainment"


def test_travel_is_reachable_from_issuer_labels_too():
    # "other travel" is deliberately absent — it carried transit and storage on
    # real data and now maps to None. See test_other_travel_is_not_mapped_to_travel.
    for label in ("airfare", "hotels", "lodging", "car rental"):
        assert ISSUER_CATEGORIES[label] == "travel"


def test_car_rental_brands_are_travel_not_housing():
    """`RENT` is a housing pattern; "AVIS RENT A CAR" must not land in housing."""
    assert categorize("AVIS RENT A CAR SFO") == "travel"
    assert categorize("HERTZ 4471") == "travel"


# --- short-token substring matches -------------------------------------------
# Every case here was a live misclassification before the patterns got \b
# anchors. They're cheap to reintroduce by editing a pattern, and completely
# silent when you do — the row just quietly lands in the wrong bucket.


@pytest.mark.parametrize(
    ("description", "must_not_be"),
    [
        # MTA inside PYMTAuthDate — a card payment counted as a transport expense,
        # which inflates spending *and* hides a payment.
        ("CAPITAL ONE MOBILE PYMTAuthDate 11-Mar", "transport"),
        # ATM inside TREATMENT
        ("SPINE TREATMENT CENTER", "cash"),
        # ACH inside COACH / BEACH
        ("COACH OUTLET STORE 88", "transfer"),
        ("BEACH CLUB PARKING", "transfer"),
        # FEE inside COFFEE
        ("PEETS COFFEE 01221", "fees"),
    ],
)
def test_short_tokens_do_not_match_inside_longer_words(description, must_not_be):
    assert categorize(description) != must_not_be


def test_coffee_is_dining_at_coarse_granularity():
    assert categorize("PEETS COFFEE 01221") == "dining"
    assert categorize("BLUE BOTTLE COFFEE") == "dining"


def test_card_payment_resolves_through_the_issuer_fallback():
    """The fixture's payment row has no description rule that fires, so this is
    the issuer map doing its job — the exact case the fallback exists for."""
    description = "CAPITAL ONE MOBILE PYMTAuthDate 11-Mar"
    assert categorize(description) is None
    assert resolve_category(description, "payment/credit") == "card_payment"


# --- taxonomy integrity -------------------------------------------------------


def test_every_rule_category_is_in_the_taxonomy():
    assert {category for _, category in RULES} <= CATEGORIES


def test_every_issuer_mapping_lands_in_the_taxonomy():
    assert {c for c in ISSUER_CATEGORIES.values() if c is not None} <= CATEGORIES


def test_travel_is_in_the_taxonomy():
    """Named explicitly because it's one of the categories this project exists
    to report, and it was missing entirely until now."""
    assert "travel" in CATEGORIES


# --- end to end over the fixture ---------------------------------------------


def test_fixture_rows_categorize_correctly_end_to_end():
    """Parser output straight into the categorizer — no database needed. This is
    the combination that was broken in production."""
    parsed = CapitalOneCSVParser().parse(FIXTURE)
    resolved = {
        txn.description: resolve_category(txn.description, txn.category)
        for txn in parsed.transactions
    }
    assert resolved == {
        "CHIPOTLE MEXICAN GRILL": "dining",
        "NETFLIX.COM": "subscriptions",
        "KROGER #421": "groceries",
        "CAPITAL ONE MOBILE PYMTAuthDate 11-Mar": "card_payment",
    }
