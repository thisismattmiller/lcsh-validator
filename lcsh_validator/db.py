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
        for path in self.broader_chain(hid, max_depth=5):
            for anc in path:
                if anc in CATEGORY_ROOTS:
                    sheet, cat = CATEGORY_ROOTS[anc]
                    hints.setdefault(sheet, {"sheet": sheet, "category": cat, "via": " > ".join([h["label"]] + path[:path.index(anc) + 1])})
        return list(hints.values())

    def pattern_subdivisions(self, sheet: str) -> list[dict]:
        """Subdivision authority records tagged for a pattern collection, e.g. 'H 1147'."""
        key = "collection_PatternHeadingH" + sheet.replace("H", "").strip()
        out = []
        for r in self.con.execute("select * from headings where is_subdivision=1 and collections like ?", (f'%"{key}"%',)):
            d = self._row(r)
            out.append({"label": d["label"], "tag": d["tag"], "may_subd_geog": bool(d["may_subd_geog"]), "note": d["scope_note"]})
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

    def lookup_name(self, label: str) -> dict:
        """Look up a heading in the LC Name Authority File (LCNAF) via id.loc.gov.

        Returns {found, id, label, kind, geographic_subdivision_form (781), notes, variants} or {found: False}.
        """
        key = "name:" + normalize_label(label)
        c = self._cached(key)
        if c is not None:
            return c
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
        if c is not None:
            return c
        if not self.online:
            return []
        q = urllib.parse.quote(text.strip(), safe="")
        _, _, body = self._http(f"https://id.loc.gov/authorities/names/suggest2?q={q}&count={limit}&rdftype=Geographic&searchtype=keyword")
        out = []
        try:
            hits = json.loads(body).get("hits", [])
        except Exception:  # noqa: BLE001
            hits = []
        n = normalize_label(text)
        for h in hits:
            lab = h.get("aLabel") or ""
            if not (normalize_label(lab) == n or normalize_label(lab).startswith(n + " (")):
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
    return out


def _unescape(s: str) -> str:
    return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")


@lru_cache(maxsize=1)
def default_db() -> LCSHDB:
    return LCSHDB()
