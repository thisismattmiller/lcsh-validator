"""Export the SHM rule sheets (rules/shm/*.md) and lists (rules/lists/*.json) as JSON for the web UI's
rule popups: docs/rules/index.json (sheet -> file, title) and docs/rules/<file>.json per sheet with the
summary, the numbered validation rules, the full-text sections keyed by their label (E.1, F, 2.b ...) and,
for list sheets, the entries keyed by subdivision.

usage: uv run scripts/export_rules_json.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lcsh_validator.freefloating import FreeFloating  # noqa: E402
from lcsh_validator.parse import normalize_label  # noqa: E402
from lcsh_validator.rules import Rules  # noqa: E402

OUT = ROOT / "docs/rules"
HEAD = re.compile(r"^(#{2,4})\s*(.*?)\s*$", re.M)
LABEL = re.compile(r"^([A-Z]|\d{1,2}|[a-z]|[ivx]+)(?:\.(\d{1,2}|[a-z]|\(\d+\)|[ivx]+))*\.?(?=\s)")
MAX_SECTION = 6000


def section_label(heading: str) -> str | None:
    """'E.1. Authorized usage' -> 'E.1'; 'F. Topical Subdivisions' -> 'F'; '2. Use of existing ...' -> '2'; 'a. General' -> 'a'."""
    m = LABEL.match(heading + " ")
    if not m:
        return None
    return m.group(0).rstrip(".").strip()


def split_sections(body: str) -> tuple[list[str], list[dict]]:
    heads = list(HEAD.finditer(body))
    rules: list[str] = []
    sections: list[dict] = []
    stack: list[tuple[int, str]] = []  # (level, label) for nesting: '2' then 'b' -> '2.b'
    for i, h in enumerate(heads):
        level, title = len(h.group(1)), h.group(2)
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        text = body[h.end():end].strip()
        if title.lower().startswith("validation rules"):
            rules = [re.sub(r"^\d+\.\s*", "", ln).strip() for ln in text.splitlines() if re.match(r"^\d+\.\s", ln)]
            continue
        if title.lower().startswith("full text") or level == 2:
            stack = []
            continue
        label = section_label(title)
        while stack and stack[-1][0] >= level:
            stack.pop()
        full = ".".join([s[1] for s in stack] + [label]) if label else None
        if label:
            stack.append((level, label))
        if len(text) > MAX_SECTION:
            text = text[:MAX_SECTION].rstrip() + "\n[... section truncated; the full sheet is in rules/shm]"
        sections.append({"id": full, "own": label, "heading": title, "level": level, "text": text})
    return rules, sections


def main() -> None:
    rules = Rules()
    ff = FreeFloating()
    OUT.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}
    seen = set()
    for s in rules.sheets.values():
        if s["key"] in seen:
            continue
        seen.add(s["key"])
        meta, body = s["meta"], s["body"]
        vr, sections = split_sections(body)
        doc = {"sheet": s["key"], "file": s["file"], "title": meta.get("title"), "revised": meta.get("revised"),
               "summary": (meta.get("summary") or "").strip(), "related": meta.get("related") or [],
               "validation_rules": vr, "sections": sections}
        lst = ff.lists.get(s["key"])
        if lst:
            entries = {}
            for e in lst.get("entries", []):
                lab = e.get("subdivision") or e.get("pattern")
                if not lab:
                    continue
                key = "--" + normalize_label(str(lab).lstrip("-"))
                ent = {k: e[k] for k in ("subdivision", "pattern", "subfield", "type", "may_subd_geog", "use_under", "notes", "see_also", "consult", "endnote", "section", "examples", "exceptions", "rule") if e.get(k) not in (None, "", [], False)}
                entries.setdefault(key, []).append(ent)
            doc["list"] = {"scope": lst.get("scope"), "pattern_headings": lst.get("pattern_headings"), "pattern_category": lst.get("pattern_category"),
                           "general_notes": lst.get("general_notes"), "entries": entries}
        (OUT / f"{s['file']}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        index[s["key"]] = {"file": s["file"], "title": meta.get("title"), "relevance": meta.get("validation_relevance")}
    # lists that have no sheet file of their own
    for key, lst in ff.lists.items():
        if key in index:
            continue
        file = key.replace(" ", "").replace(".", "_")
        entries = {}
        for e in lst.get("entries", []):
            lab = e.get("subdivision") or e.get("pattern")
            if lab:
                entries.setdefault("--" + normalize_label(str(lab).lstrip("-")), []).append(e)
        (OUT / f"{file}.json").write_text(json.dumps({"sheet": key, "file": file, "title": lst.get("title"), "summary": lst.get("scope") or "", "validation_rules": [], "sections": [],
                                                      "list": {"scope": lst.get("scope"), "general_notes": lst.get("general_notes"), "entries": entries}}, ensure_ascii=False), encoding="utf-8")
        index[key] = {"file": file, "title": lst.get("title"), "relevance": "list"}
    (OUT / "index.json").write_text(json.dumps(dict(sorted(index.items())), ensure_ascii=False, indent=0), encoding="utf-8")
    total = sum(p.stat().st_size for p in OUT.glob("*.json"))
    print(f"{len(index)} sheets -> {OUT} ({total / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
