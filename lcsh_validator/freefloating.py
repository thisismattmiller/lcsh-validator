"""Free-floating subdivision knowledge: LC's SUBDIVISIONS list (authority-record derived) + the SHM list sheets (rules/lists/*.json)."""
from __future__ import annotations

import json
import re
from functools import lru_cache

from . import DATA, RULES
from .parse import normalize_label

FF_PATH = DATA / "derived/free_floating_subdivisions.json"
LISTS_DIR = RULES / "lists"

SHEET_SCOPE = {
    "H 1095": "general application (see each entry's usage statement)",
    "H 1100": "classes of persons", "H 1103": "ethnic groups", "H 1105": "names of individual corporate bodies",
    "H 1110": "names of individual persons", "H 1120": "names of families", "H 1140": "names of places (regions, countries, cities, etc.)",
    "H 1145.5": "names of bodies of water", "H 1147": "individual animals and groups of animals", "H 1148": "art headings qualified by nationality",
    "H 1149": "chemicals", "H 1149.5": "colonies of individual countries", "H 1149.7": "comics and graphic novels", "H 1150": "diseases",
    "H 1151": "individual educational institutions", "H 1151.5": "types of educational institutions", "H 1153": "industries",
    "H 1154": "languages and groups of languages", "H 1154.5": "legal topics", "H 1155": "legislative bodies",
    "H 1155.2": "groups of literary authors", "H 1155.6": "literary works entered under author", "H 1155.8": "literary works entered under title",
    "H 1156": "literatures", "H 1158": "materials", "H 1159": "military services", "H 1160": "musical compositions",
    "H 1161": "musical instruments", "H 1164": "organs and regions of the body", "H 1180": "plants and crops", "H 1185": "religions",
    "H 1186": "religious and monastic orders", "H 1187": "Christian denominations", "H 1188": "sacred works", "H 1195": "land vehicles",
    "H 1200": "wars",
}


MULTIPLE_RE = re.compile(r",?\s*\[[^\]]*\betc\.?\]")


def multiple_pattern(norm_label: str) -> re.Pattern | None:
    """Turn a 'multiple' such as 'paraphrases, english, [french, german, etc.]' into a regex.

    LC lists multiples with one example followed by bracketed alternatives; any value may fill the
    slot. The slot is the piece before the bracket (back to the previous ', ', '--' or space), extended
    backwards over date-like pieces so 'history--revolution, 1775-1783, [war of 1812, etc.]' becomes
    'history--(.+)'. Returns None when the label is not a multiple.
    """
    m = MULTIPLE_RE.search(norm_label)
    if not m:
        return None
    before, after = norm_label[: m.start()], norm_label[m.end():]
    pieces = re.split(r"(, |--| )", before)
    # pieces alternate text/separator; walk back over the slot
    i = len(pieces) - 1
    while i >= 2 and re.search(r"\d", pieces[i]) and pieces[i - 1] == ", ":
        i -= 2
    prefix = "".join(pieces[:i])
    return re.compile(re.escape(prefix) + r"(?P<slot>(?:(?!--).)+)" + re.escape(after))


class FreeFloating:
    def __init__(self):
        self.entries = json.loads(FF_PATH.read_text()) if FF_PATH.exists() else []
        self.by_norm: dict[str, list[dict]] = {}
        self.multiples: list[tuple[re.Pattern, str]] = []  # (regex, by_norm key)
        for e in self.entries:
            n = normalize_label(e["label"])
            self.by_norm.setdefault(n, []).append(e)
            pat = multiple_pattern(n)
            if pat and n not in {k for _, k in self.multiples}:
                self.multiples.append((pat, n))
        self.lists: dict[str, dict] = {}
        self.list_by_norm: dict[str, list[tuple[str, dict]]] = {}
        self.list_multiples: list[tuple[re.Pattern, str]] = []
        for f in sorted(LISTS_DIR.glob("*.json")):
            try:
                d = json.loads(f.read_text())
            except json.JSONDecodeError:
                continue
            sheet = d.get("sheet") or f.stem
            self.lists[sheet] = d
            for e in d.get("entries", []):
                lab = e.get("subdivision") or e.get("pattern") or ""
                if lab:
                    n = normalize_label(lab.lstrip("-"))
                    self.list_by_norm.setdefault(n, []).append((sheet, e))
                    pat = multiple_pattern(n)
                    if pat and n not in {k for _, k in self.list_multiples}:
                        self.list_multiples.append((pat, n))

    def _match_multiple(self, n: str, table: list[tuple[re.Pattern, str]]) -> str | None:
        """A multiple's slot holds a language, name, denomination, war etc.; a value that is itself a listed
        subdivision (e.g. 'history' in 'study and teaching--history') is not filling the slot."""
        for pat, key in table:
            m = pat.fullmatch(n)
            if m and normalize_label(m.group("slot")) not in self.by_norm and normalize_label(m.group("slot")) not in self.list_by_norm:
                return key
        return None

    def lookup(self, label: str) -> dict:
        """Everything known about a subdivision string from the free-floating list and the SHM list sheets."""
        n = normalize_label(label.lstrip("-"))
        matched_pattern = None
        ff = self.by_norm.get(n, [])
        literal = bool(ff) or n in self.list_by_norm
        if not literal:
            key = self._match_multiple(n, self.multiples)
            if key:
                ff = self.by_norm[key]
                matched_pattern = ff[0]["label"]
        list_key = n if n in self.list_by_norm else (None if literal else self._match_multiple(n, self.list_multiples))
        if list_key and list_key != n and not matched_pattern:
            matched_pattern = (self.list_by_norm[list_key][0][1].get("subdivision") or self.list_by_norm[list_key][0][1].get("pattern"))
        auth = [e for e in ff if not e.get("reference")]
        refs = [e for e in ff if e.get("reference")]
        sheets = sorted({s for e in auth for s in e.get("sheets", [])})
        return {
            "label": label,
            "matched_pattern": matched_pattern,  # set when the string fills the slot of a multiple like 'X, English, [French, etc.]'
            "free_floating_list": [
                {"types": e["types"], "may_subd_geog": e["may_subd_geog"], "controlling_sheets": e["sheets"],
                 "usage": e["usage"], "notes": e["notes"], "UF": e["UF"], "BT": e["BT"], "NT": e["NT"][:8], "RT": e["RT"], "SA": e["SA"]}
                for e in auth
            ],
            "use_instead": [u for e in refs for u in e.get("use", [])],
            "controlling_sheets": [{"sheet": s, "applies_under": SHEET_SCOPE.get(s, "")} for s in sheets],
            "shm_list_entries": [
                {"sheet": s, **{k: v for k, v in e.items() if k in ("subdivision", "subfield", "type", "may_subd_geog", "use_under", "notes", "see_also", "consult", "endnote")}}
                for s, e in (self.list_by_norm.get(list_key, []) if list_key else [])
            ][:12],
        }

    def sheet_entries(self, sheet: str) -> dict | None:
        d = self.lists.get(sheet)
        if not d:
            # tolerate "H1147" style
            for k, v in self.lists.items():
                if k.replace(" ", "") == sheet.replace(" ", ""):
                    d = v
                    break
        return d

    def known_subdivision(self, label: str) -> bool:
        n = normalize_label(label.lstrip("-"))
        if [e for e in self.by_norm.get(n, []) if not e.get("reference")] or n in self.list_by_norm:
            return True
        return bool(self._match_multiple(n, self.multiples) or self._match_multiple(n, self.list_multiples))


@lru_cache(maxsize=1)
def default_ff() -> FreeFloating:
    return FreeFloating()
