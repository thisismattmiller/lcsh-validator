"""Parse the SHM Index into rules/index/shm_index.json.

The plain-text extraction (data/text/shm/SHM-Index.txt) loses indentation, which
is the only signal for the index hierarchy, so this script reads the same source
PDF (data/raw/shm/SHM-Index.pdf) with PyMuPDF to get each line's x-position and
font, then:
  * joins wrapped lines (term or sheet list continued on the next line),
  * builds the hierarchy from indentation (stack of x-positions),
  * flattens sub-entries to "Parent -- Child -- Grandchild",
  * attaches SEE / SEE ALSO lines (and their continuation targets) to the
    note of the entry they belong to,
  * skips "(Continued)" repeat headings at page tops (they only restore context),
  * normalizes sheet references ("H 1095", "H 1145.5", "Appendix B", "Glossary"),
  * records bold (primary) references in the note when a line has several.
The text file is used as a cross-check that no line was lost.

Run from project root:  uv run python scripts/parse_shm_index.py
"""
import json
import re
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data/raw/shm/SHM-Index.pdf"
TXT = ROOT / "data/text/shm/SHM-Index.txt"
OUT = ROOT / "rules/index/shm_index.json"

REF = r"(?:H\s*\d+(?:\.\d+)?(?:\s*-\s*H\s*\d+(?:\.\d+)?)?|Appendix\s+[A-Z]|Glossary)"
REFS_RE = re.compile(rf"^(?P<term>.*?)\s*:?\s*(?P<refs>{REF}(?:\s*,\s*{REF})*)\s*,?\s*$")
REF_START = re.compile(rf"^{REF}")
SEE_RE = re.compile(r"^SEE(?:\s+ALSO)?\b")
FUNC_END = re.compile(r"\b(?:under|of|for|the|and|or|to|in|with|as|a|an|specific|are|by|on)$")


def clean(s: str) -> str:
    s = s.replace("Η", "H").replace("¨", "").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def norm_ref(r: str) -> str:
    r = clean(r)
    m = re.fullmatch(r"H\s*(\d+(?:\.\d+)?)\s*-\s*H\s*(\d+(?:\.\d+)?)", r)
    if m:
        return f"H {m[1]}-H {m[2]}"
    m = re.fullmatch(r"H\s*(\d+(?:\.\d+)?)", r)
    if m:
        return f"H {m[1]}"
    m = re.fullmatch(r"Appendix\s+([A-Z])", r)
    if m:
        return f"Appendix {m[1]}"
    return r


def physical_lines():
    """Yield (page, x, y, text, bold_text) for every content line of the PDF."""
    doc = pymupdf.open(PDF)
    for pno, page in enumerate(doc, 1):
        raw = []
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                spans = [s for s in l["spans"] if s["text"]]
                if not "".join(s["text"] for s in spans).strip():
                    continue
                raw.append((l["bbox"][1], l["bbox"][0], spans))
        # merge fragments sharing a baseline, then order top-to-bottom
        raw.sort(key=lambda r: (round(r[0]), r[1]))
        rows = []
        for y, x, spans in raw:
            if rows and abs(rows[-1][0] - y) < 2:
                rows[-1][2].extend(spans)
            else:
                rows.append([y, x, list(spans)])
        for y, x, spans in rows:
            text = clean("".join(s["text"] for s in spans))
            bold = " ".join(clean(s["text"]) for s in spans if "Bold" in s["font"])
            if y > 680 or y < 60:  # running header / footer
                continue
            if re.fullmatch(r"-?\s*[A-Z]\s*-", text) or text == "INDEX":
                continue
            if x > 140 and pno == 1 and y < 170:  # introductory note on page 1
                continue
            yield pno, round(x, 1), y, text, bold


def has_refs(text: str) -> bool:
    return bool(REFS_RE.match(text)) and not SEE_RE.match(text)


def logical_lines():
    """Join wrapped physical lines into logical index lines."""
    out = []
    in_see_x = None  # x of the SEE line whose targets we are reading
    for pno, x, y, text, bold in physical_lines():
        if out:
            p = out[-1]
            if in_see_x is not None and x <= in_see_x:
                in_see_x = None
            deeper = x > p["x"]
            join = False
            if SEE_RE.match(text):
                join = False
            elif REF_START.match(text) and re.search(r"[:,]$", p["text"]):
                join = True
            elif deeper and in_see_x is not None:
                # targets are one per line; join only a mid-phrase wrap
                join = bool(FUNC_END.search(p["text"])) and text[:1].islower()
            elif deeper and not has_refs(p["text"]) and not SEE_RE.match(p["text"]):
                # sub-entries always start capitalized (or with "[", "—", quote);
                # inverted parents like "Groups of" / "Used under:" are not wraps
                join = text[:1].islower()
            if join:
                p["text"] = clean(p["text"] + " " + text)
                p["bold"] = clean(p["bold"] + " " + bold)
                p["phys"].append(text)
                continue
            # source misindentation (p. 76): a quoted "... as a subtopic under" target
            # set at the same x as its SEE line is still a cross-reference target
            if in_see_x is None and p["kind"] in ("see", "seetarget") and x == p["x"] \
                    and re.match(r'^".*" as a subtopic under', text):
                out.append(dict(page=pno, x=x, text=text, bold=bold, phys=[text], kind="seetarget"))
                in_see_x = x - 0.1
                continue
            if in_see_x is not None and x > in_see_x:
                out.append(dict(page=pno, x=x, text=text, bold=bold, phys=[text], kind="seetarget"))
                continue
        kind = "see" if SEE_RE.match(text) else "entry"
        if kind == "see":
            in_see_x = x
        out.append(dict(page=pno, x=x, text=text, bold=bold, phys=[text], kind=kind))
    return out


def main():
    lines = logical_lines()
    entries, failures, stack = [], [], []  # stack: list of (x, term, entry|None)
    last_see_owner = None
    for ln in lines:
        x, text = ln["x"], ln["text"]
        if ln["kind"] in ("see", "seetarget"):
            if ln["kind"] == "see":
                while stack and stack[-1][0] >= x:
                    stack.pop()
                owner = stack[-1][2] if stack else None
                m = re.match(r"^(SEE(?:\s+ALSO)?)\s*(.*)$", text)
                label, target = m[1], m[2]
                if owner is None:
                    failures.append(("see-without-owner", ln))
                    continue
                owner["_see"].append([label, [target]])
                last_see_owner = owner
            else:
                last_see_owner["_see"][-1][1].append(text)
            continue
        while stack and stack[-1][0] >= x:
            stack.pop()
        if re.search(r"\(Continued\)\s*$", text, re.I):
            term = re.sub(r"\s*\(Continued\)\s*$", "", text, flags=re.I)
            m = REFS_RE.match(term)
            if m:
                term = m["term"]
            term = term.rstrip(": ").strip()
            # reuse the original entry so later SEE lines attach correctly
            prefix = " -- ".join([s[1] for s in stack] + [term])
            orig = next((e for e in reversed(entries) if e["term"] == prefix), None)
            if orig is None:
                failures.append(("continued-without-original", ln))
            stack.append((x, term, orig))
            continue
        m = REFS_RE.match(text)
        if m:
            term = m["term"].rstrip(": ").strip()
            refs = re.findall(REF, m["refs"])
            sheets = []
            for r in refs:
                r = norm_ref(r)
                if r not in sheets:
                    sheets.append(r)
        else:
            term, sheets = text.rstrip(": ").strip(), []
        if not term:
            failures.append(("empty-term", ln))
            continue
        notes = []
        if len(sheets) > 1 and ln["bold"]:
            boldrefs = [norm_ref(r) for r in re.findall(REF, ln["bold"])]
            prim = [s for s in sheets if s in boldrefs]
            if prim and len(prim) < len(sheets):
                notes.append("primary: " + ", ".join(prim))
        if any("-H " in s for s in sheets):
            notes.append("includes sheet range")
        full = " -- ".join([s[1] for s in stack] + [term])
        e = {"term": full, "sheets": sheets, "note": "; ".join(notes),
             "_see": [], "_page": ln["page"], "_raw": " | ".join(ln["phys"])}
        entries.append(e)
        stack.append((x, term, e))

    # finalize notes; check entries with no sheets
    nosheets_unexplained = []
    children = {}
    for e in entries:
        parts = e["term"].split(" -- ")
        for i in range(1, len(parts)):
            children[" -- ".join(parts[:i])] = True
    for e in entries:
        for label, targets in e.pop("_see"):
            seg = f"{label} " + "; ".join(t.strip() for t in targets)
            e["note"] = "; ".join(filter(None, [e["note"], seg]))
        if not e["sheets"] and "SEE" not in e["note"] and e["term"] not in children:
            nosheets_unexplained.append(e)

    # cross-check against text extraction: every content line of the txt must be used
    used = []
    for ln in lines:
        used.extend(ln["phys"])
    used_set = {re.sub(r"\W", "", t) for t in used}
    txt_missing = []
    for t in TXT.read_text().splitlines():
        t = clean(t)
        if (not t or t.startswith("<<<PAGE") or t in ("Subject Headings Manual", "August 2023", "INDEX")
                or re.fullmatch(r"Index - Page \d+", t) or re.fullmatch(r"-?\s*[A-Z]\s*-", t)):
            continue
        k = re.sub(r"\W", "", t)
        if k not in used_set and not any(k in u for u in used_set):
            txt_missing.append(t)

    debug = "--debug" in sys.argv
    out = [{k: v for k, v in e.items() if debug or not k.startswith("_")} for e in entries]
    OUT.write_text(json.dumps({"entries": out}, ensure_ascii=False, indent=1) + "\n")

    print(f"physical lines: {sum(len(l['phys']) for l in lines)}  logical lines: {len(lines)}")
    print(f"entries: {len(entries)}  with sheets: {sum(1 for e in entries if e['sheets'])}")
    print(f"parse failures: {len(failures)}")
    for kind, ln in failures:
        print("  FAIL", kind, ln["page"], ln["x"], ln["text"])
    print(f"entries without sheets, no SEE, no children: {len(nosheets_unexplained)}")
    for e in nosheets_unexplained:
        print("  NOSHEET", e["_page"], e["term"], "||", e["_raw"])
    print(f"txt lines not found in PDF parse: {len(txt_missing)}")
    for t in txt_missing[:40]:
        print("  MISSING", t)


if __name__ == "__main__":
    main()
