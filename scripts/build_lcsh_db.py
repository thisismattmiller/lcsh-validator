"""Build data/derived/lcsh.sqlite from subjects.madsrdf.xml.gz.

The gz file holds one complete <rdf:RDF> document per line (one LCSH authority record each).
Usage: uv run scripts/build_lcsh_db.py [--limit N]
"""
from __future__ import annotations

import gzip
import json
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "subjects.madsrdf.xml.gz"
DST = ROOT / "data/derived/lcsh.sqlite"

NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "madsrdf": "http://www.loc.gov/mads/rdf/v1#",
    "bflc": "http://id.loc.gov/ontologies/bflc/",
    "identifiers": "http://id.loc.gov/vocabulary/identifiers/",
}
RDF = "{%s}" % NS["rdf"]
MADS = "{%s}" % NS["madsrdf"]
BFLC = "{%s}" % NS["bflc"]
SUBJ = "http://id.loc.gov/authorities/subjects/"
MADS_URI = NS["madsrdf"]

TAG_KIND = {
    "150": "topic", "151": "geographic", "155": "genreform", "148": "temporal",
    "100": "personal_name", "110": "corporate_name", "111": "conference_name", "130": "title",
    "180": "subdivision_topical", "181": "subdivision_geographic", "182": "subdivision_temporal",
    "185": "subdivision_form",
}

SCHEMA = """
PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
DROP TABLE IF EXISTS headings; DROP TABLE IF EXISTS variants; DROP TABLE IF EXISTS labels;
DROP TABLE IF EXISTS headings_fts; DROP TABLE IF EXISTS complex_components;
CREATE TABLE headings(
  id TEXT PRIMARY KEY, label TEXT, norm TEXT, tag TEXT, kind TEXT, marc_key TEXT,
  authorized INT, deprecated INT, may_subd_geog INT, is_subdivision INT, is_complex INT,
  pattern_collections TEXT, collections TEXT, gac TEXT, lcc TEXT,
  scope_note TEXT, editorial_note TEXT, history_note TEXT, example_note TEXT, deletion_note TEXT,
  use_instead TEXT, broader TEXT, narrower TEXT, related TEXT, earlier_forms TEXT, generated_from TEXT,
  record_date TEXT
);
CREATE TABLE variants(label TEXT, norm TEXT, heading_id TEXT);
CREATE TABLE complex_components(complex_id TEXT, pos INT, component_id TEXT, component_type TEXT, component_label TEXT);
CREATE VIRTUAL TABLE headings_fts USING fts5(label, id UNINDEXED, tokenize='unicode61 remove_diacritics 2');
"""


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("—", "--").replace("–", "--").replace("ʻ", "").replace("ʼ", "")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def local(uri: str) -> str:
    return uri.rsplit("/", 1)[-1].split("#")[-1]


def parse_record(xml: str):
    root = etree.fromstring(xml.encode("utf-8"))
    descs = {}
    for d in root.findall(RDF + "Description"):
        key = d.get(RDF + "about") or d.get(RDF + "nodeID")
        descs.setdefault(key, []).append(d)
    # the main record is the rdf:about with SUBJ prefix that has an authoritativeLabel or variantLabel and marcKey/lccn
    main = None
    for key, ds in descs.items():
        if key and key.startswith(SUBJ) and "collection_" not in key:
            for d in ds:
                if d.find("identifiers:lccn", NS) is not None or d.find(BFLC + "marcKey") is not None:
                    main = (key, d)
                    break
        if main:
            break
    if main is None:
        # deprecated records: rdf:about subject with DeprecatedAuthority type
        for key, ds in descs.items():
            if key and key.startswith(SUBJ) and "collection_" not in key:
                for d in ds:
                    if any(local(t.get(RDF + "resource", "")) == "DeprecatedAuthority" for t in d.findall(RDF + "type")):
                        main = (key, d)
                        break
            if main:
                break
    if main is None:
        return None
    key, d = main
    rec = {"id": local(key)}
    types = [local(t.get(RDF + "resource", "")) for t in d.findall(RDF + "type")]
    rec["types"] = types
    mk = d.findtext(BFLC + "marcKey") or ""
    rec["marc_key"] = mk
    rec["tag"] = mk[:3] if mk else ""
    lab = d.findtext(MADS + "authoritativeLabel")
    if lab is None:
        lab = d.findtext(MADS + "variantLabel") or ""
    rec["label"] = lab
    colls = [local(c.get(RDF + "resource", "")) for c in d.findall(MADS + "isMemberOfMADSCollection")]
    rec["collections"] = colls
    rec["pattern_collections"] = sorted({local(c.get(RDF + "resource", "")) for c in d.findall(MADS + "usePatternCollection")}
                                        | {c for c in colls if c.startswith("collection_PatternHeadingH")})
    rec["authorized"] = int("collection_LCSHAuthorizedHeadings" in colls)
    rec["deprecated"] = int("DeprecatedAuthority" in types)
    rec["may_subd_geog"] = int("collection_SubdivideGeographically" in colls)
    rec["is_subdivision"] = int("collection_Subdivisions" in colls or rec["tag"] in ("180", "181", "182", "185"))
    rec["is_complex"] = int("ComplexSubject" in types)
    kind = TAG_KIND.get(rec["tag"], "")
    if rec["is_complex"]:
        kind = "complex"
    elif not kind:
        for t in types:
            if t in ("Topic", "Geographic", "GenreForm", "Temporal", "PersonalName", "CorporateName", "ConferenceName", "Title", "NameTitle", "FamilyName"):
                kind = t.lower()
                break
    rec["kind"] = kind
    codes = [c.text for c in d.findall(MADS + "code") if c.text]
    rec["gac"] = ";".join(c for c in codes)
    rec["lcc"] = [c.text for c in d.findall(MADS + "classification") if c.text]
    for name, el in [("scope_note", "note"), ("editorial_note", "editorialNote"), ("history_note", "historyNote"),
                     ("example_note", "exampleNote"), ("deletion_note", "deletionNote")]:
        vals = [x.text for x in d.findall(MADS + el) if x.text]
        rec[name] = "\n".join(vals)
    rec["use_instead"] = [local(x.get(RDF + "resource", "")) for x in d.findall(MADS + "useInstead")]
    def rel(el):
        out = []
        for x in d.findall(MADS + el):
            r = x.get(RDF + "resource")
            if r:
                out.append(local(r))
            else:
                nid = x.get(RDF + "nodeID")
                for nd in descs.get(nid, []):
                    l2 = nd.findtext(MADS + "authoritativeLabel")
                    if l2:
                        out.append("label:" + l2)
        return out
    rec["broader"] = rel("hasBroaderAuthority")
    rec["narrower"] = rel("hasNarrowerAuthority")
    rec["related"] = rel("hasReciprocalAuthority")
    rec["earlier_forms"] = []
    for x in d.findall(MADS + "hasEarlierEstablishedForm"):
        nid = x.get(RDF + "nodeID")
        for nd in descs.get(nid, []):
            v = nd.findtext(MADS + "variantLabel")
            if v:
                rec["earlier_forms"].append(v)
    m = re.search(r"generated from LCCN (\S+)\]", rec["editorial_note"])
    rec["generated_from"] = m.group(1) if m else ""
    # variants
    variants = []
    for x in d.findall(MADS + "hasVariant"):
        nid = x.get(RDF + "nodeID")
        for nd in descs.get(nid, []):
            v = nd.findtext(MADS + "variantLabel")
            if v:
                variants.append(v)
    rec["variants"] = variants
    # record change dates
    dates = []
    for x in d.findall(MADS + "adminMetadata"):
        nid = x.get(RDF + "nodeID")
        for nd in descs.get(nid, []):
            for c in nd:
                if c.tag.endswith("recordChangeDate") and c.text:
                    dates.append(c.text[:10])
    rec["record_date"] = max(dates) if dates else ""
    # complex components
    comps = []
    if rec["is_complex"]:
        cl = d.find(MADS + "componentList")
        nid = cl.get(RDF + "nodeID") if cl is not None else None
        while nid:
            nodes = descs.get(nid, [])
            if not nodes:
                break
            nd = nodes[0]
            first = nd.find(RDF + "first")
            if first is None:
                break
            cid = first.get(RDF + "resource") or first.get(RDF + "nodeID")
            ctype = ""
            clabel = ""
            for cd in descs.get(cid, []):
                for t in cd.findall(RDF + "type"):
                    tt = local(t.get(RDF + "resource", ""))
                    if tt not in ("Authority", "Variant"):
                        ctype = tt
                clabel = cd.findtext(MADS + "authoritativeLabel") or clabel
            comps.append({"id": local(cid) if cid and cid.startswith("http") else cid, "type": ctype, "label": clabel})
            rest = nd.find(RDF + "rest")
            nid = rest.get(RDF + "nodeID") if rest is not None else None
    rec["components"] = comps
    return rec


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    DST.parent.mkdir(parents=True, exist_ok=True)
    if DST.exists():
        DST.unlink()
    con = sqlite3.connect(DST)
    con.executescript(SCHEMA)
    t0 = time.time()
    n = bad = 0
    hb, vb, cb, fb = [], [], [], []
    with gzip.open(SRC, "rt", encoding="utf-8") as fh:
        for line in fh:
            n += 1
            if limit and n > limit:
                break
            try:
                rec = parse_record(line)
            except Exception as e:  # noqa: BLE001
                bad += 1
                if bad < 20:
                    print("PARSE FAIL", n, e, file=sys.stderr)
                continue
            if rec is None:
                bad += 1
                continue
            label = rec["label"]
            comps = rec["components"]
            if comps:
                parts = label.split("--")
                if len(parts) == len(comps):
                    for i, (p, c) in enumerate(zip(parts, comps)):
                        if not c["label"]:
                            c["label"] = p
            hb.append((rec["id"], label, norm(label), rec["tag"], rec["kind"], rec["marc_key"], rec["authorized"], rec["deprecated"],
                       rec["may_subd_geog"], rec["is_subdivision"], rec["is_complex"], json.dumps(rec["pattern_collections"]),
                       json.dumps(rec["collections"]), rec["gac"], json.dumps(rec["lcc"]), rec["scope_note"], rec["editorial_note"],
                       rec["history_note"], rec["example_note"], rec["deletion_note"], json.dumps(rec["use_instead"]),
                       json.dumps(rec["broader"]), json.dumps(rec["narrower"]), json.dumps(rec["related"]), json.dumps(rec["earlier_forms"]),
                       rec["generated_from"], rec["record_date"]))
            fb.append((label, rec["id"]))
            for v in rec["variants"]:
                vb.append((v, norm(v), rec["id"]))
            for i, c in enumerate(comps):
                cb.append((rec["id"], i, c["id"], c["type"], c["label"]))
            if len(hb) >= 5000:
                flush(con, hb, vb, cb, fb)
                hb, vb, cb, fb = [], [], [], []
            if n % 50000 == 0:
                print(f"{n} records, {time.time()-t0:.0f}s", file=sys.stderr)
    flush(con, hb, vb, cb, fb)
    con.executescript("""
    CREATE INDEX idx_h_norm ON headings(norm);
    CREATE INDEX idx_h_label ON headings(label);
    CREATE INDEX idx_h_tag ON headings(tag);
    CREATE INDEX idx_h_gen ON headings(generated_from);
    CREATE INDEX idx_v_norm ON variants(norm);
    CREATE INDEX idx_v_hid ON variants(heading_id);
    CREATE INDEX idx_cc_cid ON complex_components(component_id);
    CREATE INDEX idx_cc_complex ON complex_components(complex_id);
    """)
    con.commit()
    print(f"done: {n} lines, {bad} skipped, {time.time()-t0:.0f}s", file=sys.stderr)
    for row in con.execute("select kind, count(*) from headings group by kind order by 2 desc"):
        print(row, file=sys.stderr)


def flush(con, hb, vb, cb, fb):
    con.executemany("insert or replace into headings values (" + ",".join("?" * 27) + ")", hb)
    con.executemany("insert into variants values (?,?,?)", vb)
    con.executemany("insert into complex_components values (?,?,?,?,?)", cb)
    con.executemany("insert into headings_fts(label,id) values (?,?)", fb)
    con.commit()


if __name__ == "__main__":
    main()
