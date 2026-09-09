"""Maps an inbox subfolder + file extension to a parser.

Dispatch is folder-driven rather than content-sniffing: you drop the file into
inbox/<institution>/, so the institution is already known. Only the format still
has to be detected, and the extension is enough for that.
"""

from pathlib import Path

from app.ingestion.base import BaseParser
from app.ingestion.parsers.capital_one import CapitalOneCSVParser

# Folder name under inbox/ -> parsers to try, in order.
#
# Only the credit card path is automated. Investment accounts are hand-entered
# quarterly holdings snapshots by design, not a backlog: those parsers are the
# most expensive to write and add no architecture this one does not already
# demonstrate. See docs/HOW-IT-WORKS.md §1.1.
PARSERS: dict[str, list[type[BaseParser]]] = {
    "capital_one": [CapitalOneCSVParser],
}

# Seed rows for the `institutions` table. Deliberately longer than PARSERS:
# an institution needs a row here to own hand-entered holdings, whether or not
# anything parses its statements.
INSTITUTIONS: list[tuple[str, str]] = [
    ("DCU", "checking"),
    ("Capital One", "credit"),
    ("Vanguard", "brokerage"),
    ("Fidelity", "401k"),
    ("Morgan Stanley", "espp"),
]

FOLDER_TO_INSTITUTION = {
    "dcu": "DCU",
    "capital_one": "Capital One",
    "vanguard": "Vanguard",
    "fidelity": "Fidelity",
    "morgan_stanley": "Morgan Stanley",
}


def resolve(folder: str, path: Path) -> BaseParser | None:
    """Return an instantiated parser for `path`, or None if nothing handles it."""
    for parser_cls in PARSERS.get(folder, []):
        if parser_cls.handles(path):
            return parser_cls()
    return None
