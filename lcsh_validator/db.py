"""Access to the local LCSH database (data/derived/lcsh.sqlite) and the id.loc.gov name authority file."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

from . import DATA
from .parse import normalize_label

DB_PATH = Path(os.environ.get("LCSH_DB", DATA / "derived/lcsh.sqlite"))
# the name cache is written to; LCSH_NAME_CACHE lets a read-only deployment (Lambda) point it at /tmp
CACHE_PATH = Path(os.environ.get("LCSH_NAME_CACHE", DATA / "derived/name_cache.sqlite"))
USER_AGENT = "lcsh-validator/0.1 (https://github.com/thisismattmiller; local cataloging tool)"

KIND_LABEL = {
    "topic": "topical heading (150)", "geographic": "geographic heading (151)", "genreform": "genre/form (155)",
    "personal_name": "personal name heading (100)", "corporate_name": "corporate name heading (110)",
    "conference_name": "conference name heading (111)", "title": "uniform title heading (130)",
    "complex": "established precoordinated heading string (heading + subdivisions)",
    "subdivision_topical": "topical subdivision record (180)", "subdivision_geographic": "geographic subdivision record (181)",
    "subdivision_temporal": "chronological subdivision record (182)", "subdivision_form": "form subdivision record (185)",
}

# well-known roots of pattern-heading categories (H 1146) — used for category hints via the BT hierarchy
CATEGORY_ROOTS = {
    "Animals": ("H 1147", "animals"), "Fishes": ("H 1147", "animals"), "Cattle": ("H 1147", "animals"),
    "Plants": ("H 1180", "plants and crops"), "Crops": ("H 1180", "plants and crops"), "Corn": ("H 1180", "plants and crops"),
    "Diseases": ("H 1150", "diseases"), "Cancer": ("H 1150", "diseases"), "Tuberculosis": ("H 1150", "diseases"),
    "Chemicals": ("H 1149", "chemicals"), "Copper": ("H 1149", "chemicals"), "Insulin": ("H 1149", "chemicals"), "Drugs": ("H 1149", "chemicals"),
    "Materials": ("H 1158", "materials"), "Concrete": ("H 1158", "materials"), "Metals": ("H 1158", "materials"),
    "Musical instruments": ("H 1161", "musical instruments"), "Piano": ("H 1161", "musical instruments"),
    "Musical form": ("H 1160", "musical compositions"), "Operas": ("H 1160", "musical compositions"),
    "Language and languages": ("H 1154", "languages"), "English language": ("H 1154", "languages"),
    "Literature": ("H 1156", "literatures"), "English literature": ("H 1156", "literatures"),
    "Authors": ("H 1155.2", "groups of literary authors"), "Authors, English": ("H 1155.2", "groups of literary authors"),
    "Religions": ("H 1185", "religions"), "Buddhism": ("H 1185", "religions"),
    "Christian sects": ("H 1187", "Christian denominations"), "Catholic Church": ("H 1187", "Christian denominations"),
    "Monasticism and religious orders": ("H 1186", "religious and monastic orders"), "Jesuits": ("H 1186", "religious and monastic orders"),
    "Sacred books": ("H 1188", "sacred works"), "Bible": ("H 1188", "sacred works"),
    "Industries": ("H 1153", "industries"), "Construction industry": ("H 1153", "industries"), "Retail trade": ("H 1153", "industries"),
    "Universities and colleges": ("H 1151.5", "types of educational institutions"), "Schools": ("H 1151.5", "types of educational institutions"),
    "Educational institutions": ("H 1151.5", "types of educational institutions"),
    "Law": ("H 1154.5", "legal topics"), "Labor laws and legislation": ("H 1154.5", "legal topics"),
    "Vehicles": ("H 1195", "land vehicles"), "Automobiles": ("H 1195", "land vehicles"), "Motor vehicles": ("H 1195", "land vehicles"),
    "Anatomy": ("H 1164", "organs and regions of the body"), "Heart": ("H 1164", "organs and regions of the body"), "Foot": ("H 1164", "organs and regions of the body"),
    "Organs (Anatomy)": ("H 1164", "organs and regions of the body"), "Body, Human": ("H 1164", "organs and regions of the body"),
    "War": ("H 1200", "wars"), "World War, 1939-1945": ("H 1200", "wars"), "Military history": ("H 1200", "wars"),
    "Armed Forces": ("H 1159", "military services"), "Armies": ("H 1159", "military services"), "Navies": ("H 1159", "military services"),
    "Legislative bodies": ("H 1155", "legislative bodies"),
    "Persons": ("H 1100", "classes of persons"), "Prisoners": ("H 1100", "classes of persons"), "Students": ("H 1100", "classes of persons"),
    "Women": ("H 1100", "classes of persons"), "Men": ("H 1100", "classes of persons"), "Children": ("H 1100", "classes of persons"),
    "Females": ("H 1100", "classes of persons"), "Males": ("H 1100", "classes of persons"), "Patients": ("H 1100", "classes of persons"),
    "Employees": ("H 1100", "classes of persons"), "Clergy": ("H 1100", "classes of persons"), "Youth": ("H 1100", "classes of persons"),
    "Older people": ("H 1100", "classes of persons"), "Artists": ("H 1100", "classes of persons"), "Scholars": ("H 1100", "classes of persons"),
    "Ethnology": ("H 1103", "ethnic groups"), "Ethnic groups": ("H 1103", "ethnic groups"), "Indigenous peoples": ("H 1103", "ethnic groups"),
    "Disasters": ("H 1095", "historic events"), "Epidemics": ("H 1095", "historic events"), "Riots": ("H 1095", "historic events"),
    "Colonies": ("H 1149.5", "colonies of individual countries"),
    "Art": ("H 1148", "art (headings qualified by nationality)"), "Art, Chinese": ("H 1148", "art"), "Art, Japanese": ("H 1148", "art"),
    "Ethnology": ("H 1103", "ethnic groups"), "Ethnic groups": ("H 1103", "ethnic groups"), "Indigenous peoples": ("H 1103", "ethnic groups"),
    "Comic books, strips, etc.": ("H 1149.7", "comics and graphic novels"), "Graphic novels": ("H 1149.7", "comics and graphic novels"),
    "Bodies of water": ("H 1145.5", "bodies of water"), "Rivers": ("H 1145.5", "bodies of water"), "Lakes": ("H 1145.5", "bodies of water"),
}

HEADING_COLS = ["id", "label", "tag", "kind", "marc_key", "authorized", "deprecated", "may_subd_geog", "is_subdivision", "is_complex",
                "pattern_collections", "collections", "gac", "lcc", "scope_note", "editorial_note", "history_note", "example_note",
                "deletion_note", "use_instead", "broader", "narrower", "related", "earlier_forms", "generated_from", "record_date"]
JSON_COLS = {"pattern_collections", "collections", "lcc", "use_instead", "broader", "narrower", "related", "earlier_forms"}


def geog_tristate(d: dict) -> bool | None:
    """True: coded (May Subd Geog) (008/06 'i' or 'd'). False: LC coded the record not subdivided geographically
    (008/06 blank or 'n'), or it is a single-element heading without the coding (H 364: only headings coded
    (May Subd Geog) take a place). None: an established string with subdivisions that LC never evaluated
    (008/06 '|', e.g. the 2008-2010 validation records) or whose MARC code is unknown: the coding of its last
    subdivision (free-floating list entry or 180 record) governs."""
    if d.get("may_subd_geog"):
        return True
    if d.get("geog_code") in (" ", "n"):
        return False
    if "--" not in (d.get("label") or ""):
        return False
    return None


class LCSHDB:
    def __init__(self, path: Path = DB_PATH, cache_path: Path = CACHE_PATH, online: bool = True):
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run `uv run scripts/build_lcsh_db.py`")
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.con.row_factory = sqlite3.Row
        self.online = online
        self.cache = sqlite3.connect(cache_path)
        self.cache.execute("create table if not exists names(key text primary key, fetched real, data text)")
        self.cache.commit()

    # ---------- row helpers ----------
    def _row(self, r) -> dict | None:
        if r is None:
            return None
        d = {k: r[k] for k in r.keys()}
        for k in JSON_COLS:
            if k in d and isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except json.JSONDecodeError:
                    pass
        d["kind_label"] = KIND_LABEL.get(d.get("kind", ""), d.get("kind", ""))
        if "may_subd_geog" in d:
            d["may_subd_geog"] = geog_tristate(d)
        return d

    def get(self, hid: str) -> dict | None:
        return self._row(self.con.execute("select * from headings where id=?", (hid,)).fetchone())

    def label_of(self, hid: str) -> str:
        r = self.con.execute("select label from headings where id=?", (hid,)).fetchone()
        return r[0] if r else hid

    # ---------- lookups ----------
    def lookup_exact(self, label: str, subdivisions: bool | None = None) -> list[dict]:
        """Authorized or deprecated records whose authoritative label matches (normalized)."""
        n = normalize_label(label)
        q = "select * from headings where norm=?"
        if subdivisions is True:
            q += " and is_subdivision=1"
        elif subdivisions is False:
            q += " and is_subdivision=0"
        rows = [self._row(r) for r in self.con.execute(q, (n,))]
        rows.sort(key=lambda d: (d["deprecated"], not d["authorized"], d["is_complex"]))
        return rows

    def lookup_loose(self, label: str) -> list[dict]:
        """Authorized headings that differ from the label only in hyphenation or spacing ('Water supply' -> 'Water-supply')."""
        n = normalize_label(label).replace("-", " ")
        n = " ".join(n.split())
        if "-" not in normalize_label(label) and " " not in n:
            return []
        rows = self.con.execute("select * from headings where replace(norm,'-',' ') = ? and authorized=1 and deprecated=0 and is_subdivision=0", (n,)).fetchall()
        return [d for d in (self._row(r) for r in rows) if d and normalize_label(d["label"]) != normalize_label(label)]

    def lookup_variant(self, label: str) -> list[dict]:
        """Headings for which `label` is a UF (variant / see-from) reference."""
        n = normalize_label(label)
        out = []
        for r in self.con.execute("select distinct heading_id, label from variants where norm=?", (n,)):
            h = self.get(r["heading_id"])
            if h:
                h["matched_variant"] = r["label"]
                out.append(h)
        return out

    def search(self, query: str, limit: int = 8, kinds: tuple[str, ...] | None = None) -> list[dict]:
        """Full-text search over authoritative labels (for suggestions)."""
        toks = [t for t in re.findall(r"\w+", query) if len(t) > 1]
        if not toks:
            return []
        fts = " ".join(f'"{t}"' for t in toks)
        rows = []
        try:
            for r in self.con.execute("select id, label from headings_fts where headings_fts match ? order by rank limit ?", (fts, limit * 4)):
                h = self.get(r["id"])
                if h and (kinds is None or h["kind"] in kinds):
                    rows.append(h)
                if len(rows) >= limit:
                    break
        except sqlite3.OperationalError:
            pass
        return rows

    def established_under(self, prefix: str, limit: int = 60) -> list[dict]:
        """Established precoordinated strings that begin with `prefix--`; returns the next element of each."""
        n = normalize_label(prefix) + "--"
        seen = {}
        for r in self.con.execute("select id, label, norm from headings where is_complex=1 and norm >= ? and norm < ? and authorized=1 order by norm limit ?",
                                  (n, n + "￿", limit * 3)):
            rest = r["label"].split("--")[len(prefix.split("--")):]
            if not rest:
                continue
            nxt = rest[0]
            seen.setdefault(nxt, {"next_element": nxt, "example": r["label"], "id": r["id"], "count": 0})
            seen[nxt]["count"] += 1
        return list(seen.values())[:limit]

    def strings_using_subdivision(self, main: str, sub: str, limit: int = 5) -> list[str]:
        """Established strings that begin with `main--` and contain `--sub` as a later element (any position)."""
        n = normalize_label(main) + "--"
        target = normalize_label(sub)
        out = []
        for r in self.con.execute("select label, norm from headings where is_complex=1 and authorized=1 and norm >= ? and norm < ? order by norm limit 400",
                                  (n, n + "\uffff")):
            if target in r["norm"].split("--")[1:]:
                out.append(r["label"])
                if len(out) >= limit:
                    break
        return out

    def complex_components(self, hid: str) -> list[dict]:
        return [dict(r) for r in self.con.execute("select pos, component_id, component_type, component_label from complex_components where complex_id=? order by pos", (hid,))]

    def broader_chain(self, hid: str, max_depth: int = 8) -> list[list[str]]:
        """All BT ancestor paths (labels) up to max_depth."""
        paths = []
        def walk(cur, path, depth):
            if depth > max_depth:
                return
            h = self.get(cur)
            if not h:
                return
            bts = [b for b in h.get("broader", []) if not str(b).startswith("label:")]
            if not bts or depth == max_depth:
                paths.append(path)
                return
            for b in bts[:4]:
                walk(b, path + [self.label_of(b)], depth + 1)
        walk(hid, [], 0)
        return paths[:12]

    def category_hints(self, hid: str) -> list[dict]:
        """Pattern-heading categories (H 1146) the heading plausibly belongs to, via the BT hierarchy and usePatternCollection."""
        hints = {}
        h = self.get(hid)
        if not h:
            return []
        for pc in h.get("pattern_collections", []):
            m = re.search(r"PatternHeadingH([\d.]+)", pc)
            if m:
                hints[f"H {m.group(1)}"] = {"sheet": f"H {m.group(1)}", "category": "declared via usePatternCollection", "via": h["label"]}
        if h["label"] in CATEGORY_ROOTS and h["label"] not in ("Nobility", "Working class", "Families", "Clans"):
            sheet, cat = CATEGORY_ROOTS[h["label"]]
            hints[sheet] = {"sheet": sheet, "category": cat, "via": h["label"]}
        persons_via = None  # a BT path that reaches a classes-of-persons root (e.g. Persons) without passing through Social classes
        for path in self.broader_chain(hid, max_depth=6):
            for anc in path:
                if anc == "Social classes" or h["label"] in ("Nobility", "Working class", "Families", "Clans"):
                    # H 1100 sec. D: the classes-of-persons list does not apply to social classes or collective social groupings
                    hints["H 1100"] = {"sheet": "H 1100", "category": "social class / collective social grouping: H 1100 sec. D says the classes-of-persons list does NOT apply",
                                       "excluded": True, "via": " > ".join([h["label"]] + path[:path.index(anc) + 1] if anc in path else [h["label"]])}
                    break
                root = anc.split("--")[0]  # BT "Ethnology--South Asia" (Dalits) counts as the Ethnology root
                if root in CATEGORY_ROOTS:
                    sheet, cat = CATEGORY_ROOTS[root]
                    if sheet == "H 1100" and persons_via is None and h["label"] not in ("Nobility", "Working class", "Families", "Clans"):
                        persons_via = " > ".join([h["label"]] + path[:path.index(anc) + 1])
                    hints.setdefault(sheet, {"sheet": sheet, "category": cat, "via": " > ".join([h["label"]] + path[:path.index(anc) + 1])})
        if hints.get("H 1100", {}).get("excluded") and persons_via:
            # e.g. Intellectuals: BT Persons and BT Social classes. LC treats such headings as classes of persons in practice
            # (Intellectuals--Interviews, Intellectuals--Biography are established), so the exclusion is a doubt, not a bar.
            hints["H 1100"]["mixed"] = True
            hints["H 1100"]["also_classes_of_persons_via"] = persons_via
            hints["H 1100"]["category"] += "; but it is also a class of persons by another BT path, so treat the exclusion as a doubt, not a bar"
        # literatures and literary genres never reach a 'Literature' root (their BTs end in 'Balkan literature', 'Cyprus--Literatures'):
        # recognise them by the form of the label (H 1156: [...] literature, [...] poetry, [...] fiction, [...] drama, [...] essays, [...] prose literature)
        art = re.compile(r"^(Art|Arts|Painting|Sculpture|Drawing|Prints|Engraving|Decorative arts|Pottery|Ceramics|Jewelry|Mosaics|Illumination of books and manuscripts|Photography, Artistic|Folk art|Textile fabrics|Bronzes|Calligraphy|Wood-carving), [A-Z]")
        if "H 1148" not in hints and art.match(h["label"]):
            hints["H 1148"] = {"sheet": "H 1148", "category": "art forms qualified by nationality, ethnic group or religion (recognised by the form of the label)", "via": h["label"]}
        if "H 1160" not in hints and (h["label"] == "Music" or re.search(r"\bmusic$|\(Music\)$", h["label"], re.I)):
            hints["H 1160"] = {"sheet": "H 1160", "category": "music / musical compositions (recognised by the form of the label)", "via": h["label"]}
        if "H 1160" not in hints and not re.search(r"--| and | in ", h["label"]):
            # a heading whose direct BT is a type of music (Musicals > Dramatic music; Polkas > Dance music) is a music form or type (H 1160)
            for path in self.broader_chain(hid, max_depth=1):
                if path and path[0] != "Music" and re.search(r"\b\w+ music$", path[0], re.I):
                    hints["H 1160"] = {"sheet": "H 1160", "category": "musical compositions (the broader term is a type of music)", "via": f"{h['label']} > {path[0]}"}
                    break
        # groups of literary authors (H 1155.2) qualified by language/nationality have no BT (Authors, Urdu; Poets, Urdu; Women authors, French)
        authors = re.compile(r"^(?:[A-Z][a-z' ]* )?(Authors|Poets|Novelists|Dramatists|Playwrights|Essayists|Humorists|Satirists|Short story writers|Prose writers|Children's authors|Science fiction writers|Women authors|Women poets|Women novelists|Women dramatists), [A-Z]")
        if "H 1155.2" not in hints and authors.match(h["label"]):
            hints["H 1155.2"] = {"sheet": "H 1155.2", "category": "groups of literary authors (recognised by the form of the label)", "via": h["label"]}
        lit = re.compile(r"\b(literature|literatures|poetry|fiction|drama|essays|prose literature)$", re.I)
        if "H 1156" not in hints and (lit.search(h["label"]) or any(lit.search(anc) for path in self.broader_chain(hid, max_depth=3) for anc in path)):
            hints["H 1156"] = {"sheet": "H 1156", "category": "literatures / literary genres (recognised by the form of the label)", "via": h["label"]}
        if hints.get("H 1100", {}).get("excluded"):
            hints.pop("H 1103", None)
        return list(hints.values())

    def pattern_subdivisions(self, sheet: str) -> list[dict]:
        """Subdivision authority records tagged for a pattern collection, e.g. 'H 1147'."""
        key = "collection_PatternHeadingH" + sheet.replace("H", "").strip()
        out = []
        for r in self.con.execute("select * from headings where is_subdivision=1 and collections like ?", (f'%"{key}"%',)):
            d = self._row(r)
            out.append({"label": d["label"], "tag": d["tag"], "may_subd_geog": d["may_subd_geog"], "note": d["scope_note"]})
        return out

    def geographic_subdivision_form(self, label: str) -> list[dict]:
        """181 records (sh...-781) for a geographic subject heading: the authorized $z chain, e.g. 'Oregon--Trail Creek Watershed (Jackson County)'."""
        n = normalize_label(label)
        out = []
        ids = [h["id"] for h in self.lookup_exact(label) if h["tag"] == "151"]
        q = "select * from headings where tag='181' and (norm=? or norm like ?" + (" or generated_from in (%s)" % ",".join("?" * len(ids)) if ids else "") + ")"
        for r in self.con.execute(q, (n, "%--" + n, *ids)):
            d = self._row(r)
            out.append({"form": d["label"], "chain": d["label"].split("--"), "generated_from": d["generated_from"], "id": d["id"]})
        # the 181 generated from the heading itself comes first ('Andes Region' before 'Venezuela--Andes Region',
        # which belongs to the differently qualified 'Andes Region (Venezuela)')
        out.sort(key=lambda f: (f["generated_from"] not in ids, normalize_label(f["form"]) != n))
        return out

    # ---------- id.loc.gov name authority file ----------
    def _cached(self, key: str):
        r = self.cache.execute("select data from names where key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def _store(self, key: str, data):
        self.cache.execute("insert or replace into names values (?,?,?)", (key, time.time(), json.dumps(data)))
        self.cache.commit()

    def _http(self, url: str, accept: str = "*/*", allow_redirects: bool = True):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
        opener = urllib.request.build_opener() if allow_redirects else urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(req, timeout=20) as resp:
                return resp.status, resp.geturl(), resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Location", ""), ""
        except Exception as e:  # noqa: BLE001
            return 0, "", str(e)

    def fill_geog_code(self, d: dict | None) -> dict | None:
        """Complete the three-valued may_subd_geog of a record whose MARC 008/06 code is unknown locally.

        The bulk codes come from LC's 2015-12-29 MARC snapshot (scripts/extract_marc_008.py) and from a per-record
        backfill (scripts/fetch_marc_008.py); a record created or changed after the last backfill has geog_code NULL.
        When that matters (a multi-element string not in collection_SubdivideGeographically, so may_subd_geog is None)
        the code is read from the record's MARCXML on id.loc.gov and cached."""
        if not d or d.get("may_subd_geog") is not None or d.get("geog_code") is not None or not self.online:
            return d
        hid = d.get("id") or ""
        if not hid.startswith("sh") or "-" in hid:
            return d
        key = "geog:" + hid
        code = self._cached(key)
        if code is None:
            st, _, xml = self._http(f"https://id.loc.gov/authorities/subjects/{hid}.marcxml.xml")
            m = re.search(r'tag="008"[^>]*>([^<]*)<', xml) if st == 200 else None
            if not m or len(m.group(1)) < 7:
                return d
            code = m.group(1)[6]
            self._store(key, code)
        d["geog_code"] = code
        d["may_subd_geog"] = geog_tristate({**d, "may_subd_geog": code in ("i", "d")})
        d["geog_code_source"] = "id.loc.gov"
        return d

    def lookup_name(self, label: str) -> dict:
        """Look up a heading in the LC Name Authority File (LCNAF) via id.loc.gov.

        Returns {found, id, label, kind, geographic_subdivision_form (781), notes, variants} or {found: False}.
        """
        key = "name:" + normalize_label(label)
        c = self._cached(key)
        if c is not None and ((c.get("found") and c.get("v", 0) >= 2) or (not c.get("found") and c.get("v", 0) >= 3)):
            return c  # positives before v2 (occupation/372/374/670/008 fields) and negatives before v3 (dateless-name candidates) are refetched once
        if not self.online:
            return {"found": False, "offline": True}
        q = urllib.parse.quote(label.strip().rstrip("."), safe="")
        status, loc, _ = self._http(f"https://id.loc.gov/authorities/names/label/{q}", allow_redirects=False)
        result = {"found": False, "status": status}
        m = re.search(r"/authorities/names/(n[a-z]*\d+)", loc or "")
        if status in (301, 302, 303) and m:
            nid = m.group(1)
            st, _, xml = self._http(f"https://id.loc.gov/authorities/names/{nid}.marcxml.xml")
            result = {"found": True, "id": nid, "uri": f"http://id.loc.gov/authorities/names/{nid}", **_parse_marcxml(xml)}
            result["matched_as"] = "authorized label" if normalize_label(result.get("label", "")) == normalize_label(label) else "variant/see-from"
        else:
            # try a left-anchored suggest to offer candidates
            st, _, body = self._http(f"https://id.loc.gov/authorities/names/suggest2?q={q}&count=5")
            try:
                hits = json.loads(body).get("hits", [])
                result["candidates"] = [{"label": h.get("aLabel"), "uri": h.get("uri")} for h in hits if h.get("aLabel")]
            except Exception:  # noqa: BLE001
                result["candidates"] = []
            # a personal name supplied with dates the record does not carry (or vice versa): offer the dateless form as a candidate
            if not result["candidates"]:
                mb = re.match(r"^(?P<base>[^,]+,[^,]+?)(?:,\s*(?:approximately |ca\. |active |fl\. |b\. |d\. )?\d{3,4}.*)?$", label.strip().rstrip("."))
                base = mb.group("base").strip() if mb and mb.group("base") and mb.group("base").strip() != label.strip().rstrip(".") else None
                if base:
                    _, _, body2 = self._http(f"https://id.loc.gov/authorities/names/suggest2?q={urllib.parse.quote(base, safe='')}&count=5")
                    try:
                        hits2 = json.loads(body2).get("hits", [])
                        result["candidates"] = [{"label": h.get("aLabel"), "uri": h.get("uri"), "note": "found by the name without its dates; compare the dates/qualifier with the authorized form"}
                                                for h in hits2 if h.get("aLabel") and normalize_label(h["aLabel"]).startswith(normalize_label(base))]
                    except Exception:  # noqa: BLE001
                        pass
            # the label service misses some records (punctuation, recent additions); an exact suggest hit is the same thing
            n = normalize_label(label)
            exact = next((c for c in result["candidates"] if normalize_label(c["label"] or "") == n), None)
            m2 = re.search(r"/authorities/names/(n[a-z]*\d+)", (exact or {}).get("uri") or "")
            if m2:
                nid = m2.group(1)
                st, _, xml = self._http(f"https://id.loc.gov/authorities/names/{nid}.marcxml.xml")
                parsed = _parse_marcxml(xml) if st == 200 else {}
                if parsed.get("label"):
                    result = {"found": True, "id": nid, "uri": f"http://id.loc.gov/authorities/names/{nid}", **parsed,
                              "matched_as": "authorized label (exact suggest hit)"}
            result.setdefault("v", 3)
        self._store(key, result)
        return result

    def name_record(self, nid: str) -> dict:
        key = "rec:" + nid
        c = self._cached(key)
        if c is not None:
            return c
        if not self.online:
            return {}
        _, _, xml = self._http(f"https://id.loc.gov/authorities/names/{nid}.marcxml.xml")
        rec = {"id": nid, "uri": f"http://id.loc.gov/authorities/names/{nid}", **_parse_marcxml(xml)} if xml else {}
        self._store(key, rec)
        return rec

    def place_candidates(self, text: str, limit: int = 60) -> list[dict]:
        """Geographic name-authority candidates whose label begins with `text` (e.g. 'Buffalo' -> 'Buffalo (N.Y.)'), with their 781 forms."""
        key = "cand:" + normalize_label(text)
        c = self._cached(key)
        if c:
            return c  # an empty cached list predates the qualifier-aware search; retry it
        if not self.online:
            return []
        # 'Hasa (Province)' is written with a type qualifier only; the authority label is 'Hasa (Saudi Arabia : Province)'
        mq = re.match(r"^(?P<base>.+?)\s*\((?P<qual>[^()]+)\)\s*$", text.strip())
        base = mq.group("base").strip() if mq else text.strip()
        qual_words = {w for w in re.sub(r"[:,;]", " ", normalize_label(mq.group("qual"))).split() if w} if mq else set()
        q = urllib.parse.quote(base, safe="")
        _, _, body = self._http(f"https://id.loc.gov/authorities/names/suggest2?q={q}&count={limit}&rdftype=Geographic&searchtype=keyword")
        out = []
        try:
            hits = json.loads(body).get("hits", [])
        except Exception:  # noqa: BLE001
            hits = []
        n = normalize_label(text)
        nb = normalize_label(base)
        for h in hits:
            lab = h.get("aLabel") or ""
            nl = normalize_label(lab)
            if not (nl == n or nl.startswith(n + " (") or nl == nb or nl.startswith(nb + " (")):
                continue
            if qual_words and nl != n:
                # keep only candidates whose own qualifier contains the supplied qualifier words (e.g. 'province')
                mql = re.search(r"\(([^()]+)\)\s*$", nl)
                if not mql or not qual_words <= set(re.sub(r"[:,;]", " ", mql.group(1)).split()):
                    continue
            token = (h.get("token") or "").replace("-781", "")
            rec = self.name_record(token) if token else {}
            out.append({"label": lab, "id": token, "geographic_subdivision_form": rec.get("geographic_subdivision_form"), "entity_type": rec.get("entity_type", "")})
            if len(out) >= 10:
                break
        self._store(key, out)
        return out

    def lookup_subject_online(self, label: str) -> dict:
        """Fallback online lookup in the subject file (for headings newer than the local dump)."""
        key = "subj:" + normalize_label(label)
        c = self._cached(key)
        if c is not None:
            return c
        if not self.online:
            return {"found": False, "offline": True}
        q = urllib.parse.quote(label.strip().rstrip("."), safe="")
        status, loc, _ = self._http(f"https://id.loc.gov/authorities/subjects/label/{q}", allow_redirects=False)
        m = re.search(r"/authorities/subjects/(sh[a-z]*\d+)", loc or "")
        result = {"found": bool(m), "id": m.group(1) if m else None, "status": status}
        self._store(key, result)
        return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _parse_marcxml(xml: str) -> dict:
    fields = []
    for m in re.finditer(r'<(?:marcxml:)?datafield[^>]*tag="(\d{3})"[^>]*>(.*?)</(?:marcxml:)?datafield>', xml, re.S):
        subs = re.findall(r'<(?:marcxml:)?subfield code="(\w)">(.*?)</(?:marcxml:)?subfield>', m.group(2), re.S)
        fields.append((m.group(1), [(c, _unescape(v)) for c, v in subs]))
    out = {"label": "", "kind": "", "geographic_subdivision_form": None, "variants": [], "notes": [], "gac": ""}
    m008 = re.search(r'<(?:marcxml:)?controlfield tag="008"[^>]*>([^<]*)</(?:marcxml:)?controlfield>', xml)
    if m008 and len(m008.group(1)) > 6:
        code = m008.group(1)[6]
        out["geog_subdiv_code_008_06"] = {"d": "d (may be subdivided geographically, direct)", "i": "i (may be subdivided geographically, indirect)",
                                          "n": "n (not subdivided geographically)", " ": "blank (no information)"}.get(code, code)
    for tag, subs in fields:
        if tag in ("100", "110", "111", "130", "150", "151", "155"):
            out["label"] = " ".join(v for c, v in subs if c not in "0123456789eiw")
            out["kind"] = {"100": "personal name", "110": "corporate name", "111": "conference name", "130": "uniform title",
                           "150": "topic", "151": "geographic (jurisdiction or place)", "155": "genre/form"}[tag]
            out["marc"] = tag + " " + " ".join(f"${c} {v}" for c, v in subs)
        elif tag == "781":
            out["geographic_subdivision_form"] = "--".join(v for c, v in subs if c == "z")
        elif tag in ("400", "410", "411", "430", "450", "451"):
            out["variants"].append(" ".join(v for c, v in subs if c not in "0123456789eiw"))
        elif tag in ("667", "680"):
            out["notes"].append(" ".join(v for c, v in subs if c in "ai"))
        elif tag == "043":
            out["gac"] = ";".join(v for c, v in subs if c == "a")
        elif tag == "368":
            out["entity_type"] = ", ".join(v for c, v in subs if c in "abcd")
        elif tag == "370":
            out["place_associated"] = ", ".join(f"${c} {v}" for c, v in subs if c in "aceft")
        elif tag == "372":
            out.setdefault("field_of_activity", []).extend(v for c, v in subs if c == "a")
        elif tag == "374":
            out.setdefault("occupation", []).extend(v for c, v in subs if c == "a")
        elif tag == "670":
            out.setdefault("sources_670", []).append(" ".join(v for c, v in subs if c in "ab")[:300])
    if "sources_670" in out:
        out["sources_670"] = out["sources_670"][:4]
    out["v"] = 2
    return out


def _unescape(s: str) -> str:
    return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")


@lru_cache(maxsize=1)
def default_db() -> LCSHDB:
    return LCSHDB()
