"""Parse data/text/lcsh/SUBDIVISIONS.txt (LC's free-floating subdivisions list, April 2026)
into data/derived/free_floating_subdivisions.json.

Layout per entry (PyMuPDF text):
  —<U+2006>Label<NBSP> (May Subd Geog)      entry header (label may wrap to the next line)
  H 1095; H 1154                             controlling SHM sheet(s)
  Use as a topical subdivision under ...     usage / notes (wrapped lines)
  UF —<U+2006>Variant [Former subdivision]   references: UF, BT, NT, RT, SA (continuations start with NBSP)
  —<U+2006>Variant                           a reference entry
  USE —<U+2006>Label
Usage: uv run scripts/parse_free_floating.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/text/lcsh/SUBDIVISIONS.txt"
DST = ROOT / "data/derived/free_floating_subdivisions.json"

DASH = "— "
NBSP = "\xa0"
REF_KEYS = ("UF", "BT", "NT", "RT", "SA", "USE")


def clean_label(s: str) -> str:
    s = s.replace(DASH, "--").replace("—", "--")
    s = s.replace(NBSP, " ")
    return re.sub(r"\s+", " ", s).strip()


def main():
    raw = SRC.read_text().split("\n")
    lines = []
    for l in raw:
        if l.startswith("<<<PAGE") or re.fullmatch(r"SD-\d+", l.strip()):
            continue
        lines.append(l.rstrip())

    entries = []
    cur = None
    field = None  # which list continuation lines append to: 'label','notes', or a ref key
    i = 0
    while i < len(lines):
        l = lines[i]
        i += 1
        if not l.strip():
            continue
        if l.startswith(DASH) and "(Continued)" in l:
            # page-break continuation of an existing entry: find it and keep appending notes
            raw = l[len(DASH):].split("(Continued)")[0]
            depth = 0
            while raw.startswith(DASH) or raw.startswith("\u2014"):
                raw = raw[len(DASH):] if raw.startswith(DASH) else raw[1:]
                depth += 1
            base = clean_label(raw)
            full = base
            if depth:
                # the page top repeats the parent header ("— History") just before "— —Humor (Continued)": drop that stub
                stub = entries[-1] if entries else None
                if stub and not stub["sheets"] and not stub["notes"] and not stub["USE"] and not any(stub[k] for k in ("UF", "BT", "NT", "RT", "SA")):
                    entries.pop()
                    full = stub["label"] + "--" + base
                else:
                    parent = next((e["label"] for e in reversed(entries) if e.get("depth", 0) < depth), "")
                    full = (parent + "--" + base) if parent else base
            prev = next((e for e in reversed(entries) if e["label"] == full), None)
            if prev is None:
                prev = next((e for e in reversed(entries) if e["label"].lstrip("-").strip() == base), None)
            if prev is None:
                prev = entries[-1]
            cur = prev
            tail = l.split("(Continued)", 1)[1].strip()
            field = "notes"
            if tail:
                cur["notes"].append(tail)
            continue
        if l.startswith(DASH):
            # new entry header
            cur = {"label": "", "may_subd_geog": False, "sheets": [], "notes": [], "UF": [], "BT": [], "NT": [], "RT": [], "SA": [], "USE": []}
            entries.append(cur)
            body = l[len(DASH):]
            depth = 0
            while body.startswith(DASH) or body.startswith("\u2014"):
                body = body[len(DASH):] if body.startswith(DASH) else body[1:]
                depth += 1
            if depth:
                # "— —Dictionaries" is the subdivision combination [parent]--Dictionaries
                parent = next((e["label"] for e in reversed(entries[:-1]) if e.get("depth", 0) < depth), "")
                cur["depth"] = depth
                parent_prefix = parent + "--"
            else:
                cur["depth"] = 0
                parent_prefix = ""
            if "(May Subd Geog)" in body:
                cur["may_subd_geog"] = True
                body = body.replace("(May Subd Geog)", "")
            cur["label"] = parent_prefix + clean_label(body)
            field = "label"
            continue
        if cur is None:
            continue
        m = re.match(r"^(UF|BT|NT|RT|SA|USE)\s+(.*)$", l)
        if m:
            field = m.group(1)
            cur[field].append(clean_label(m.group(2)))
            continue
        if re.match(r"^H \d", l):
            sheet_line = l
            while i < len(lines) and (sheet_line.rstrip().endswith("H") or re.match(r"^(H )?\d{3,4}(\.\d+)?\s*(;|$)", lines[i])):
                sheet_line = sheet_line.rstrip() + " " + lines[i].strip()
                i += 1
            sheet_line = re.sub(r"H\s+(\d)", r"H \1", sheet_line)
            cur["sheets"] = [s.strip() for s in sheet_line.split(";") if s.strip()]
            field = "notes"
            continue
        if l.startswith(NBSP):
            # continuation of a reference field, or an additional value in it
            txt = l.replace(NBSP, " ").strip()
            if not txt:
                continue
            if field in REF_KEYS:
                if txt.startswith("—"):
                    cur[field].append(clean_label(txt))
                elif cur[field]:
                    cur[field][-1] = clean_label(cur[field][-1] + " " + txt)
                else:
                    cur[field].append(clean_label(txt))
            elif field == "label":
                cur["label"] = clean_label(cur["label"] + " " + txt)
            else:
                cur["notes"].append(txt)
            continue
        # plain text line
        if field == "label":
            # label continuation (wrapped) unless it looks like a note
            if re.match(r"^(Use |Further |Subdivide|Do not|Assign|When |For |This |Only |Also |Complete)", l):
                field = "notes"
                cur["notes"].append(l.strip())
            else:
                cur["label"] = clean_label(cur["label"] + " " + l)
            continue
        if field in REF_KEYS:
            # wrapped reference text
            if cur[field]:
                cur[field][-1] = clean_label(cur[field][-1] + " " + l.strip())
            continue
        cur["notes"].append(l.strip())

    # post-process: strip "(May Subd Geog)" that survived a line wrap, merge stub duplicates
    for e in entries:
        if "(May Subd Geog)" in e["label"] or "(May Subd" in e["label"]:
            e["may_subd_geog"] = True
            e["label"] = clean_label(re.sub(r"\(May Subd\s*Geog\)", "", e["label"]))
    merged = []
    for e in entries:
        if not e["sheets"] and not e["USE"] and not e["notes"]:
            twin = next((m for m in merged if m["label"] == e["label"] and not m["USE"]), None)
            if twin:
                for k in ("UF", "BT", "NT", "RT", "SA"):
                    twin[k] = twin[k] + [v for v in e[k] if v not in twin[k]]
                continue
        merged.append(e)
    entries = merged
    out = []
    for e in entries:
        label = e["label"]
        if e["USE"]:
            out.append({"label": label, "reference": True, "use": e["USE"], "sheets": e["sheets"]})
            continue
        notes = " ".join(e["notes"])
        notes = re.sub(r"(\w)- (\w)", r"\1\2", notes)  # rejoin hyphenated wraps like "free- floating"
        sents = [s.strip() for s in re.split(r"(?<=\.)\s+(?=[A-Z])", notes) if s.strip()]
        usage = [s for s in sents if s.startswith("Use")]
        other = [s for s in sents if not s.startswith("Use")]
        types = []
        u = " ".join(usage).lower()
        for t in ("topical", "form", "chronological", "geographic"):
            if f"as a {t} subdivision" in u or f"as {t} subdivision" in u:
                types.append(t)
        if not types and label == "Foreign countries":
            types = ["geographic"]
        former = [v for v in e["UF"]]
        out.append({
            "label": label,
            "may_subd_geog": e["may_subd_geog"],
            "types": types,
            "sheets": e["sheets"],
            "usage": usage,
            "notes": other,
            "UF": former,
            "BT": e["BT"], "NT": e["NT"], "RT": e["RT"], "SA": e["SA"],
        })
    DST.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    auth = [e for e in out if not e.get("reference")]
    refs = [e for e in out if e.get("reference")]
    notype = [e["label"] for e in auth if not e["types"]]
    nosheet = [e["label"] for e in auth if not e["sheets"]]
    print(f"entries: {len(out)}  authorized: {len(auth)}  references: {len(refs)}")
    print(f"no type: {len(notype)}  e.g. {notype[:15]}")
    print(f"no sheet: {len(nosheet)}  e.g. {nosheet[:15]}")
    import collections
    print(collections.Counter(tuple(e["types"]) for e in auth).most_common())
    longlab = [e["label"] for e in auth if len(e["label"]) > 70]
    print("long labels:", longlab[:10])


if __name__ == "__main__":
    main()
