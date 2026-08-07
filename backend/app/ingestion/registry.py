"""Maps an inbox subfolder + file extension to a parser.

Dispatch is folder-driven rather than content-sniffing: you drop the file into
inbox/<institution>/, so the institution is already known. Only the format still
has to be detected, and the extension is enough for that.
"""

from pathlib import Path

from app.ingestion.base import BaseParser
from app.ingestion.parsers.capital_one import CapitalOneCSVParser, CapitalOnePDFParser
from app.ingestion.parsers.dcu import DCUCSVParser, DCUPDFParser
from app.ingestion.parsers.fidelity import FidelityCSVParser, FidelityPDFParser
from app.ingestion.parsers.morgan_stanley import MorganStanleyReleasesParser
from app.ingestion.parsers.vanguard import VanguardCSVParser, VanguardPDFParser

# Folder name under inbox/ -> parsers to try, in order.
PARSERS: dict[str, list[type[BaseParser]]] = {
    "dcu": [DCUCSVParser, DCUPDFParser],
    "capital_one": [CapitalOneCSVParser, CapitalOnePDFParser],
    "vanguard": [VanguardCSVParser, VanguardPDFParser],
    "fidelity": [FidelityCSVParser, FidelityPDFParser],
    "morgan_stanley": [MorganStanleyReleasesParser],
}

# Seed rows for the `institutions` table.
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
