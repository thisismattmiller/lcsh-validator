"""Merge extracted Summaries-of-Decisions notes (data/derived/lc_decisions/notes/*.json, one list per batch) into
rules/lc_decisions.json, the curated file the analyzer reads. Entries are deduplicated on (source_id, headings,
subdivisions, patterns); the curated file is rewritten sorted by date. Edit rules/lc_decisions.json by hand afterwards
if a note needs trimming; re-running keeps hand edits to the 'note' text of an entry with the same key.

usage: uv run scripts/merge_lc_decisions.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "data/derived/lc_decisions/notes"
OUT = ROOT / "rules/lc_decisions.json"
KINDS = {"subdivision_usage", "pattern", "free_floating_addition", "heading", "other"}


def key(n: dict) -> tuple:
    return (n.get("source_id"), tuple(sorted(n.get("headings") or [])), tuple(sorted(n.get("subdivisions") or [])), tuple(sorted(n.get("patterns") or [])))


_FF = None


def _template_on_free_floating(pattern: str) -> bool:
    global _FF
    parts = [x.strip() for x in pattern.split("--")]
    literal = [x for x in parts if not x.startswith("[")]
    if len(literal) != 1 or not parts[0].startswith("["):
        return False
    if _FF is None:
        sys.path.insert(0, str(ROOT))
        from lcsh_validator.freefloating import FreeFloating
        from lcsh_validator.parse import normalize_label
        _FF = (FreeFloating(), normalize_label)
    ff, norm = _FF
    return norm(literal[0]) in ff.by_norm


def _restates(pattern: str, subs: set[str]) -> bool:
    parts = [x.strip() for x in pattern.split("--")]
    literal = [x.lower() for x in parts if not x.startswith("[")]
    return bool(literal) and all(x in subs for x in literal)


def clean(n: dict) -> dict | None:
    subs = [("--" + s.lstrip("-").strip()) for s in (n.get("subdivisions") or []) if s and s.strip("- ")]
    pats = [p.strip() for p in (n.get("patterns") or []) if p and "--" in p]
    # "[Topic]--Vapor pressure" restates the subdivision "--Vapor pressure": keep only genuine pattern decisions
    subn = {re.sub(r"\s+", " ", x.lstrip("-").strip().lower()) for x in subs}
    pats = [p for p in pats if n.get("kind") == "pattern" or not _restates(p, subn)]
    # "[Class of persons]--Fiction" would attach to every string ending in a free-floating subdivision: drop templates
    # whose only literal element is itself free-floating
    pats = [p for p in pats if not _template_on_free_floating(p)]
    pats = [p for p in pats if any(not x.strip().startswith("[") for x in p.split("--"))]  # needs a literal element
    heads = [h.strip() for h in (n.get("headings") or []) if h and h.strip()]
    if not (subs or pats or heads):
        return None
    if not (n.get("note") or "").strip() or not n.get("source_id") or not n.get("date"):
        return None
    kind = n.get("kind") if n.get("kind") in KINDS else "other"
    return {"source_id": n["source_id"], "date": n["date"], "url": n.get("url"), "kind": kind, "subdivisions": subs, "patterns": pats,
            "headings": heads, "shm_cited": [c for c in (n.get("shm_cited") or []) if re.match(r"^(H \d|Appendix)", str(c))],
            "decision": (n.get("decision") or "").strip().lower() or None, "note": n["note"].strip()}


def main() -> None:
    existing = {}
    if OUT.exists():
        for n in json.loads(OUT.read_text(encoding="utf-8")).get("notes", []):
            existing[key(n)] = n
    merged = dict(existing)
    added = 0
    for f in sorted(NOTES.glob("*.json")):
        try:
            batch = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"{f.name}: bad JSON ({e})", file=sys.stderr)
            continue
        for raw in batch if isinstance(batch, list) else batch.get("notes", []):
            n = clean(raw)
            if not n:
                continue
            k = key(n)
            if k in merged:
                merged[k].update({x: n[x] for x in ("url", "kind", "shm_cited", "decision") if n.get(x)})
            else:
                merged[k] = n
                added += 1
    notes = sorted(merged.values(), key=lambda n: (n["date"], n["source_id"], n["headings"], n["subdivisions"], n["patterns"]))
    OUT.write_text(json.dumps({"source": "Library of Congress, Summaries of Decisions of the subject policy office (PTCP; earlier PSD and CPSO) on SACO proposals, https://www.loc.gov/aba/pcc/saco/cpsoed/cpsoeditorial.html",
                               "description": "Dated decisions tied to a subdivision, heading or heading pattern. The analyzer attaches a note to the facts when the string under test uses that subdivision, heading or pattern; the model reports it as LC practice, not as an SHM rule.",
                               "notes": notes}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(notes)} notes ({added} new) -> {OUT}")


if __name__ == "__main__":
    main()
