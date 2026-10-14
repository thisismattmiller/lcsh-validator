"""LCSH subject heading validator: deterministic lookups + Claude Haiku 5.5 reasoning."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RULES = ROOT / "rules"
