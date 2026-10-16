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
from lcsh_validator.rules import Rules, sheet_outline  # noqa: E402

OUT = ROOT / "docs/rules"
MAX_SECTION = 6000


def split_sections(body: str) -> tuple[list[str], list[dict]]:
    """The numbered validation rules and the full-text sections of a sheet, using the same outline as the model's
    get_rule tool (lcsh_validator.rules.sheet_outline) so a citation resolves to the same text in both places."""
    rules: list[str] = []
    sections: list[dict] = []
    for o in sheet_outline(body):
        text = body[o["content_start"]:o["text_end"]].strip()
        title = o["heading"]
        if title.lower().startswith("validation rules"):
            rules = [re.sub(r"^\d+\.\s*", "", ln).strip() for ln in text.splitlines() if re.match(r"^\d+\.\s", ln)]
            continue
        if title.lower().startswith("full text") or o["level"] == 2:
            continue
        if len(text) > MAX_SECTION:
            text = text[:MAX_SECTION].rstrip() + "\n[... section truncated; the full sheet is in rules/shm]"
        sections.append({"id": o["id"], "own": o["own"], "heading": title, "level": o["level"], "text": text})
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
