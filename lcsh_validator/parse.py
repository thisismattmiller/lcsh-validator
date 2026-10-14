"""Parse a subject heading string into its components.

Accepted inputs:
  "Tacos--History--20th century"                  (double hyphen, em/en dash, or " -- ")
  "650 _0 $a Tacos $x History $y 20th century"    (MARC-ish; indicators optional; $ or ‡ delimiters)
  "=650  \\0$aTacos$xHistory"                      (MarcEdit style)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

SUBFIELD_RE = re.compile(r"[\$‡]([a-z0-9])")
TAG_RE = re.compile(r"^=?\s*(6\d\d)\s*([ _#\\0-9]{0,2})\s*(?=[\$‡])")
DASH_SPLIT = re.compile(r"\s*(?:--|—|–|\s-\s)\s*")

# subfields that belong to the main heading (name headings use several)
MAIN_CODES = set("abcdefghjklmnopqrstu")
SUBDIV_CODES = {"x": "topical", "y": "chronological", "z": "geographic", "v": "form"}


@dataclass
class Component:
    text: str
    code: str | None  # MARC subfield code if known
    role: str  # "main" | "topical" | "chronological" | "geographic" | "form" | "unknown"

    def to_dict(self):
        return {"text": self.text, "code": self.code, "role": self.role}


@dataclass
class ParsedHeading:
    raw: str
    tag: str | None
    indicators: str | None
    main: str
    main_subfields: list[tuple[str, str]]
    subdivisions: list[Component]
    notes: list[str] = field(default_factory=list)

    @property
    def components(self) -> list[Component]:
        return [Component(self.main, "a", "main")] + self.subdivisions

    @property
    def string(self) -> str:
        return "--".join([self.main] + [c.text for c in self.subdivisions])

    def to_dict(self):
        return {
            "raw": self.raw,
            "tag": self.tag,
            "indicators": self.indicators,
            "main": self.main,
            "main_subfields": self.main_subfields,
            "subdivisions": [c.to_dict() for c in self.subdivisions],
            "string": self.string,
            "notes": self.notes,
        }


def normalize_label(s: str) -> str:
    """Normalization used for lookups: NFKD, strip diacritics, lower, collapse whitespace, dashes -> '--'."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("—", "--").replace("–", "--").replace("ʻ", "").replace("ʼ", "")
    s = re.sub(r"\s*--\s*", "--", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s.rstrip(".") if not s.endswith("etc.") else s


def _strip_trailing_period(text: str, notes: list[str]) -> str:
    t = text.strip()
    if t.endswith(".") and not re.search(r"\b(etc|Jr|Sr|St|Mt|Ft|Co|Inc|Ltd|[A-Z])\.$", t) and not re.search(r"\b\d{4}\.$", t):
        notes.append("Trailing period removed from the last element (MARC terminal punctuation).")
        t = t[:-1].rstrip()
    return t


def parse_heading(raw: str) -> ParsedHeading:
    s = raw.strip()
    notes: list[str] = []
    tag = indicators = None
    m = TAG_RE.match(s)
    if m:
        tag = m.group(1)
        ind = m.group(2).replace("_", " ").replace("#", " ").replace("\\", " ")
        indicators = ind if ind.strip() else None
        s = s[m.end():]
    if SUBFIELD_RE.search(s):
        # MARC subfield form
        parts = SUBFIELD_RE.split(s)
        # parts = [pre, code, text, code, text, ...]
        pre = parts[0].strip()
        if pre:
            notes.append(f"Ignored text before the first subfield: {pre!r}")
        pairs = [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]
        main_sub = []
        subdivs: list[Component] = []
        for code, text in pairs:
            if code in SUBDIV_CODES:
                subdivs.append(Component(text, code, SUBDIV_CODES[code]))
            elif code in MAIN_CODES and not subdivs:
                main_sub.append((code, text))
            elif code in ("0", "1", "2", "4", "e", "6", "8"):
                notes.append(f"Ignored control subfield ${code} {text!r}")
            else:
                notes.append(f"Subfield ${code} {text!r} appeared after a subdivision; treated as a topical subdivision")
                subdivs.append(Component(text, code, "unknown"))
        main = " ".join(t for _, t in main_sub).strip()
        # name headings: $a $d etc are joined with the punctuation they carry; collapse double spaces
        main = re.sub(r"\s+", " ", main)
        if subdivs:
            subdivs[-1].text = _strip_trailing_period(subdivs[-1].text, notes)
        else:
            main = _strip_trailing_period(main, notes)
        return ParsedHeading(raw, tag, indicators, main, main_sub, subdivs, notes)
    # plain string form
    parts = [p.strip() for p in DASH_SPLIT.split(s) if p.strip()]
    if not parts:
        raise ValueError("empty heading")
    if "--" not in s and ("—" in s or "–" in s):
        notes.append("Subdivisions were delimited with an em/en dash; LCSH convention is a double hyphen '--'.")
    main = parts[0]
    subdivs = [Component(p, None, "unknown") for p in parts[1:]]
    if subdivs:
        subdivs[-1].text = _strip_trailing_period(subdivs[-1].text, notes)
    else:
        main = _strip_trailing_period(main, notes)
    return ParsedHeading(raw, tag, indicators, main, [("a", main)], subdivs, notes)
