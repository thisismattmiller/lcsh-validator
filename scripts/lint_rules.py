"""Check rules/shm/*.md frontmatter and structure, and rules/lists/*.json shape.
Usage: uv run scripts/lint_rules.py
"""
import glob
import json
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQ = ["id", "file", "title", "revised", "category", "validation_relevance", "applies_to", "heading_types", "subdivisions_governed",
       "pattern_headings", "pattern_category", "related", "summary"]
CATS = {"general-principles", "heading-construction", "subdivision-general", "free-floating-list", "pattern-heading-list", "geographic",
        "chronological", "names-as-subjects", "authority-procedures", "references-and-notes", "special-topic", "appendix", "glossary", "introduction", "index"}

problems = []
src = {os.path.basename(f)[:-4] for f in glob.glob(str(ROOT / "data/text/shm/*.txt"))} - {"SHM-Index"}
src |= {"LCSH-Main-intro", "LCSH-FF-intro"}
have = {os.path.basename(f)[:-3] for f in glob.glob(str(ROOT / "rules/shm/*.md"))}
for m in sorted(src - have):
    problems.append(f"MISSING rules/shm/{m}.md")
for f in sorted(glob.glob(str(ROOT / "rules/shm/*.md"))):
    stem = os.path.basename(f)[:-3]
    text = open(f).read()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        problems.append(f"{stem}: no frontmatter")
        continue
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        problems.append(f"{stem}: YAML error {str(e)[:60]}")
        continue
    for k in REQ:
        if k not in fm:
            problems.append(f"{stem}: missing key {k}")
    if fm.get("category") not in CATS:
        problems.append(f"{stem}: bad category {fm.get('category')!r}")
    if fm.get("validation_relevance") not in ("high", "medium", "low"):
        problems.append(f"{stem}: bad validation_relevance {fm.get('validation_relevance')!r}")
    body = m.group(2)
    if "## Validation rules" not in body:
        problems.append(f"{stem}: no '## Validation rules' section")
    if "## Full text" not in body and fm.get("category") != "index":
        problems.append(f"{stem}: no '## Full text' section")
    if "<<<PAGE" in body:
        problems.append(f"{stem}: leftover <<<PAGE marker")
    if re.search(r"\bB(In|Juvenile|History|Biography)\b", body):
        problems.append(f"{stem}: possible broken dash glyph 'B...'")
    if len(body) < 400:
        problems.append(f"{stem}: body suspiciously short ({len(body)} chars)")
for f in sorted(glob.glob(str(ROOT / "rules/lists/*.json"))):
    stem = os.path.basename(f)[:-5]
    try:
        d = json.load(open(f))
    except json.JSONDecodeError as e:
        problems.append(f"lists/{stem}: JSON error {e}")
        continue
    if "entries" not in d or not isinstance(d["entries"], list):
        problems.append(f"lists/{stem}: no entries list")
    elif d["entries"] and not any(k in d["entries"][0] for k in ("subdivision", "pattern", "category")):
        problems.append(f"lists/{stem}: entries lack subdivision/pattern key")
print(f"{len(have)} sheet files, {len(glob.glob(str(ROOT / 'rules/lists/*.json')))} list files, {len(problems)} problems")
for p in problems:
    print(" -", p)
sys.exit(1 if problems else 0)
