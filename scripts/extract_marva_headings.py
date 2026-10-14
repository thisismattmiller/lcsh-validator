"""Pull every subject heading out of a Marva (BIBFRAME editor) MongoDB dump.

Reads the `resourcesProduction.bson` collection on stdin (stream it straight out of the tarball, no
need to unpack 26 GB), takes the latest version of each record, and writes:

  <out>/headings.jsonl      one line per subject occurrence: label, MARC-style string built from
                            the component marcKeys, scheme, tag, LCCN, record id/status/modified
  <out>/unique.tsv          count, scheme, label  (one line per distinct label+scheme, most used first)
  <out>/lcsh.txt            distinct LCSH + name-authority labels, one per line (validator batch input)

    tar -xzOf ~/Data/marva-records/080000.bfe2.tar.gz data/db/bkup/bfe2/resourcesProduction.bson \\
      | uv run --with pymongo python -I scripts/extract_marva_headings.py data/derived/marva
"""
from __future__ import annotations

import collections
import html
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import bson

SUBJECT_RE = re.compile(r"<bf:subject(?![^>]*/>)(?:\s[^>]*)?>(.*?)</bf:subject>", re.S)
COMPONENTS_RE = re.compile(r"<madsrdf:componentList[^>]*>(.*?)</madsrdf:componentList>", re.S)
LABEL_RE = re.compile(r"<(?:madsrdf:authoritativeLabel|rdfs:label)(?:\s[^>]*)?>(.*?)</(?:madsrdf:authoritativeLabel|rdfs:label)>", re.S)
MARCKEY_RE = re.compile(r"<bflc:marcKey(?:\s[^>]*)?>(.*?)</bflc:marcKey>", re.S)
SOURCE_RE = re.compile(r'<bf:Source rdf:about="([^"]+)"')
SCHEME_RE = re.compile(r'<madsrdf:isMemberOfMADSScheme rdf:resource="([^"]+)"')
TYPE_RE = re.compile(r"^\s*<madsrdf:(\w+)")
COMPONENT_RE = re.compile(r"<madsrdf:(\w+)(?:\s[^>]*)?>(.*?)</madsrdf:\1>", re.S)
AUTH_LABEL_RE = re.compile(r"<madsrdf:authoritativeLabel(?:\s[^>]*)?>(.*?)</madsrdf:authoritativeLabel>", re.S)
SOURCE_BLOCK_RE = re.compile(r"<bf:source>.*?</bf:source>", re.S)
TYPE_SUBFIELD = {"Geographic": "z", "Temporal": "y", "GenreForm": "v"}

SCHEME_LABELS = [
    ("subjectSchemes/lcsh", "lcsh"), ("authorities/subjects", "lcsh"), ("childrensSubjects", "lcshac"),
    ("subjectSchemes/cyac", "lcshac"), ("subjectSchemes/fast", "fast"), ("authorities/names", "naf"),
    ("subjectSchemes/naf", "naf"), ("genreForms", "lcgft"), ("subjectSchemes/mesh", "mesh"),
]


def scheme_of(block: str) -> str:
    for m in SOURCE_RE.findall(block) + SCHEME_RE.findall(block):
        for key, label in SCHEME_LABELS:
            if key in m:
                return label
    srcs = SOURCE_RE.findall(block)
    return srcs[0].rsplit("/", 1)[-1] if srcs else ""


def clean(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def marc_tag(key: str) -> str:
    m = re.match(r"\s*(\d{3})", key)
    return ("6" + m.group(1)[1:]) if m else ""


def subfield_of(key: str) -> str:
    m = re.search(r"\$([a-z])", key)
    return m.group(1) if m else ""


def extract_subject(block: str) -> dict | None:
    comps = COMPONENTS_RE.search(block)
    top = block[:comps.start()] + block[comps.end():] if comps else block
    top = SOURCE_BLOCK_RE.sub("", top)  # bf:Source carries its own rdfs:label
    labels = AUTH_LABEL_RE.findall(top) or LABEL_RE.findall(top)
    if not labels:
        return None
    label = clean(labels[0])
    if not label:
        return None
    keys = MARCKEY_RE.findall(top)
    tag = marc_tag(keys[0]) if keys else ""
    marc = ""
    if keys:
        key = clean(keys[0])
        m = re.match(r"(\d{3})\s?(.)?(.)?\s*(\$.*)", key)
        if m:
            tag = "6" + m.group(1)[1:]
            ind2 = "0" if m.group(1)[0] == "1" else (m.group(3) or "_")
            marc = f"{tag} _{ind2} " + re.sub(r"\$([a-z0-9])", r" $\1 ", m.group(4)).strip()
            marc = re.sub(r"\s+", " ", marc)
    elif comps:
        parts = []
        for ctype, cbody in COMPONENT_RE.findall(comps.group(1)):
            cl = LABEL_RE.findall(cbody)
            ck = MARCKEY_RE.findall(cbody)
            if not cl:
                continue
            # 18X subdivision records carry the right subfield in their marcKey; a 1XX heading used as a
            # later component (e.g. 151 Australia) is coded by its type
            code = subfield_of(ck[0]) if ck and re.match(r"\s*18\d", ck[0]) else TYPE_SUBFIELD.get(ctype, "x")
            if not parts:
                tag = marc_tag(ck[0]) if ck else {"PersonalName": "600", "CorporateName": "610", "ConferenceName": "611",
                                                   "Title": "630", "NameTitle": "600", "Geographic": "651", "GenreForm": "655"}.get(ctype, "650")
                code = "a"
            parts.append(f"${code} {clean(cl[0])}")
        if parts:
            marc = f"{tag or '650'} _0 " + " ".join(parts)
    t = TYPE_RE.match(block)
    return {"label": label, "marc": marc, "scheme": scheme_of(block), "tag": tag, "type": t.group(1) if t else ""}


def latest_xml(doc: dict) -> str:
    best = None
    for v in doc.get("versions") or []:
        c = v.get("content")
        if isinstance(c, str) and "<rdf:RDF" in c[:2000]:
            if best is None or str(v.get("v_created", "")) >= str(best.get("v_created", "")):
                best = v
    return best["content"] if best else ""


def _docs(stream):
    try:
        yield from bson.decode_file_iter(stream)
    except bson.errors.InvalidBSON as e:  # truncated stream: keep what was read
        print(f"stopped on invalid BSON: {e}", file=sys.stderr)


def write_lcsh_list(out: Path, rows) -> int:
    """lcsh.txt: each distinct label once (whitespace-trimmed; the same string may occur under
    several scheme tags), most used first; LCSH, name-authority and untagged subjects only."""
    seen = set()
    with open(out / "lcsh.txt", "w", encoding="utf-8") as fh:
        for (scheme, label), n in rows:
            label = unicodedata.normalize("NFC", " ".join(label.split()))
            if scheme in ("lcsh", "naf", "") and label and label not in seen:
                seen.add(label)
                fh.write(label + "\n")
    return len(seen)


def main(out_dir: str):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    counts: collections.Counter[tuple[str, str]] = collections.Counter()
    docs = subjects = 0
    t0 = time.time()
    with open(out / "headings.jsonl", "w", encoding="utf-8") as fh:
        for doc in _docs(sys.stdin.buffer):
            docs += 1
            xml = latest_xml(doc)
            if not xml:
                continue
            idx = doc.get("index") or {}
            def text(v):  # index values are whatever the editor stored: str, int, list, None
                if isinstance(v, list):
                    v = v[0] if v else ""
                return "" if v is None else str(v)
            ctx = {"eid": text(doc.get("uri")), "lccn": text(idx.get("lccn")), "status": text(idx.get("status")),
                   "modified": text(doc.get("modified")), "title": text(idx.get("title"))[:120]}
            for m in SUBJECT_RE.finditer(xml):
                s = extract_subject(m.group(1))
                if not s:
                    continue
                subjects += 1
                counts[(s["scheme"], s["label"])] += 1
                fh.write(json.dumps({**s, **ctx}, ensure_ascii=False) + "\n")
            if docs % 10000 == 0:
                print(f"{docs} docs, {subjects} subjects, {len(counts)} distinct, {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    with open(out / "unique.tsv", "w", encoding="utf-8") as fh:
        fh.write("count\tscheme\tlabel\n")
        for (scheme, label), n in counts.most_common():
            fh.write(f"{n}\t{scheme}\t{label}\n")
    write_lcsh_list(out, counts.most_common())
    by_scheme = collections.Counter()
    for (scheme, _), n in counts.items():
        by_scheme[scheme] += n
    print(f"done: {docs} docs, {subjects} subject occurrences, {len(counts)} distinct; by scheme: {dict(by_scheme.most_common())}; {time.time() - t0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/derived/marva")
