"""Retrieval over the LLM-friendly rule files (rules/shm/*.md) and the SHM index."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

import yaml

from . import DATA, RULES

SHM_DIR = RULES / "shm"
INDEX_PATH = RULES / "index/shm_index.json"
# LCSH_RULES_FTS lets a read-only deployment point the FTS index at a writable copy (or a prebuilt one)
FTS_PATH = Path(os.environ.get("LCSH_RULES_FTS", DATA / "derived/rules.sqlite"))


def _split_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, m.group(2)


def sheet_key(s: str) -> str:
    """'H1145_5' / 'H 1145.5' / 'h1145.5' -> 'H 1145.5'; appendices and others pass through."""
    s = s.strip()
    m = re.match(r"^[Hh]\s*(\d{2,4})(?:[._](\d+))?$", s)
    if m:
        return f"H {int(m.group(1))}" + (f".{m.group(2)}" if m.group(2) else "")
    return s


_HEAD_RE = re.compile(r"^(#{2,4})\s*(.*?)\s*$", re.M)
_LABEL_RE = re.compile(r"^([A-Z]|\d{1,2}|[a-z]|[ivx]+)(?:\.(\d{1,2}|[a-z]|\(\d+\)|[ivx]+))*\.?(?=\s)")


def section_label(heading: str) -> str | None:
    """'E.1. Authorized usage' -> 'E.1'; 'F. Topical Subdivisions' -> 'F'; '2. Use of ...' -> '2'; 'a. General' -> 'a'."""
    m = _LABEL_RE.match(heading + " ")
    return m.group(0).rstrip(".").strip() if m else None


def label_rank(label: str) -> int:
    """SHM outline order: A. > 1. > a. > (1)/i. ; a dotted label ('E.1') ranks by its last component."""
    last = label.rsplit(".", 1)[-1]
    if re.fullmatch(r"[A-Z]", last):
        return 0
    if re.fullmatch(r"\d{1,2}", last):
        return 1
    if re.fullmatch(r"[a-z]", last):
        return 2
    return 3


def sheet_outline(body: str) -> list[dict]:
    """Every heading of a sheet with its full outline id and the span of its text including its subsections:
    [{id, own, heading, level, start, end, text_end}]. Subsections nest by deeper heading level or by a
    lower-ranking label at the same level ('### 2.' then '### a.' -> '2.a'). `text_end` is where the section's
    own text stops (the next heading); `end` is where its last descendant stops."""
    heads = list(_HEAD_RE.finditer(body))
    out: list[dict] = []
    stack: list[tuple[int, int, int]] = []  # (level, rank, index into out)
    for i, h in enumerate(heads):
        level, title = len(h.group(1)), h.group(2)
        text_end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        label = section_label(title) if level >= 3 else None
        if level == 2:
            stack = []
            full = None
            rank = -1
        elif label and "." in label:
            while stack and not label.startswith((out[stack[-1][2]]["id"] or "") + "."):
                stack.pop()
            full, rank = label, label_rank(label)
        elif label:
            rank = label_rank(label)
            while stack and (stack[-1][0] > level or (stack[-1][0] == level and stack[-1][1] >= rank)):
                stack.pop()
            full = f"{out[stack[-1][2]]['id']}.{label}" if stack else label
        else:
            full, rank = None, 3
            while stack and stack[-1][0] >= level:
                stack.pop()
        node = {"id": full, "own": label, "heading": title, "level": level, "start": h.start(), "text_end": text_end, "end": text_end}
        for _, _, j in stack:
            out[j]["end"] = text_end
        if level >= 3 and label:
            stack.append((level, rank, len(out)))
        out.append(node)
    for o in out:
        o["content_start"] = body.find("\n", o["start"]) + 1 if body.find("\n", o["start"]) >= 0 else len(body)
    return out


class Rules:
    def __init__(self):
        self.sheets: dict[str, dict] = {}
        for f in sorted(SHM_DIR.glob("*.md")):
            fm, body = _split_frontmatter(f.read_text())
            key = sheet_key(str(fm.get("id") or f.stem))
            self.sheets[key] = {"key": key, "file": f.stem, "path": f, "meta": fm, "body": body}
            self.sheets[f.stem] = self.sheets[key]
        self.index = json.loads(INDEX_PATH.read_text())["entries"] if INDEX_PATH.exists() else []
        self._fts = None

    # ---------- direct access ----------
    def get(self, sheet: str, section: str | None = None, max_chars: int = 40000) -> dict | None:
        s = self.sheets.get(sheet_key(sheet)) or self.sheets.get(sheet)
        if not s:
            return None
        body = s["body"]
        if section:
            body = self._section(body, section) or body
        return {"sheet": s["key"], "title": s["meta"].get("title"), "summary": s["meta"].get("summary"),
                "validation_relevance": s["meta"].get("validation_relevance"), "related": s["meta"].get("related"),
                "text": body[:max_chars] + ("\n[... truncated; ask for a section]" if len(body) > max_chars else "")}

    def validation_rules(self, sheet: str) -> str | None:
        s = self.sheets.get(sheet_key(sheet))
        if not s:
            return None
        sec = self._section(s["body"], "Validation rules")
        return sec

    @staticmethod
    def _section(body: str, name: str) -> str | None:
        """A section of a sheet by its outline id ('2.b', 'E.1'), its own label ('b', 'E') or a heading substring
        ('Validation rules'). The text runs through the section's subsections, including those that the sheet marks
        only by label style at the same heading level ('### 2.' followed by '### a.', '### b.')."""
        outline = sheet_outline(body)
        want = name.strip().rstrip(".").lower()
        hit = next((o for o in outline if (o["id"] or "").lower() == want), None)
        if not hit:
            hit = next((o for o in outline if (o["own"] or "").lower() == want), None)
        if not hit:
            hit = next((o for o in outline if want in o["heading"].lower()), None)
        if not hit:
            return None
        return body[hit["start"]:hit["end"]].strip()

    def toc(self) -> list[dict]:
        seen = set()
        out = []
        for s in self.sheets.values():
            if s["key"] in seen:
                continue
            seen.add(s["key"])
            m = s["meta"]
            out.append({"sheet": s["key"], "title": m.get("title"), "category": m.get("category"),
                        "relevance": m.get("validation_relevance"), "subdivisions_governed": m.get("subdivisions_governed") or []})
        return sorted(out, key=lambda d: d["sheet"])

    def sheets_for_subdivision(self, subdivision: str) -> list[str]:
        want = subdivision.strip().lstrip("-").lower()
        hits = []
        for s in self.toc():
            for g in s["subdivisions_governed"]:
                if str(g).lstrip("-").lower() == want:
                    hits.append(s["sheet"])
        return hits

    # ---------- index ----------
    def index_lookup(self, term: str, limit: int = 15) -> list[dict]:
        t = term.lower().strip().lstrip("-")
        hits = [e for e in self.index if t in e["term"].lower()]
        if not hits:
            # token match with crude stemming (plural -> singular)
            toks = [w.rstrip("s") for w in re.findall(r"[a-z0-9]+", t) if len(w) > 2]
            if toks:
                hits = [e for e in self.index if all(any(w.rstrip("s") == tok or w.startswith(tok) for w in re.findall(r"[a-z0-9]+", e["term"].lower())) for tok in toks)]
        hits.sort(key=lambda e: (not e["term"].lower().startswith(t), len(e["term"])))
        return hits[:limit]

    # ---------- full text search ----------
    def _ensure_fts(self):
        if self._fts:
            return self._fts
        newest = max((f.stat().st_mtime for f in SHM_DIR.glob("*.md")), default=0)
        rebuild = not FTS_PATH.exists() or FTS_PATH.stat().st_mtime < newest
        if rebuild and not os.access(FTS_PATH.parent, os.W_OK):
            rebuild = False  # read-only deployment: use the shipped index as is
        con = sqlite3.connect(FTS_PATH) if rebuild else sqlite3.connect(f"file:{FTS_PATH}?mode=ro", uri=True)
        if rebuild:
            con.executescript("drop table if exists chunks; create virtual table chunks using fts5(sheet, title, section, text, tokenize='porter unicode61');")
            rows = []
            seen = set()
            for s in self.sheets.values():
                if s["key"] in seen:
                    continue
                seen.add(s["key"])
                for sec_title, sec_text in self._chunks(s["body"]):
                    rows.append((s["key"], s["meta"].get("title", ""), sec_title, sec_text))
            con.executemany("insert into chunks values (?,?,?,?)", rows)
            con.commit()
        self._fts = con
        return con

    @staticmethod
    def _chunks(body: str, max_len: int = 2500):
        pat = re.compile(r"^(#{1,4})\s*(.*)$", re.M)
        heads = list(pat.finditer(body))
        if not heads:
            yield "", body
            return
        for i, h in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
            text = body[h.end():end].strip()
            if not text:
                continue
            for j in range(0, len(text), max_len):
                yield h.group(2), text[j:j + max_len]

    def search(self, query: str, limit: int = 6) -> list[dict]:
        con = self._ensure_fts()
        toks = [t for t in re.findall(r"[\w'-]+", query) if len(t) > 1]
        if not toks:
            return []
        q = " OR ".join(f'"{t}"' for t in toks)
        out = []
        try:
            for r in con.execute("select sheet, title, section, snippet(chunks, 3, '>>', '<<', ' … ', 40), text from chunks where chunks match ? order by rank limit ?", (q, limit)):
                out.append({"sheet": r[0], "title": r[1], "section": r[2], "snippet": r[3], "text": r[4][:1800]})
        except sqlite3.OperationalError as e:
            out.append({"error": str(e)})
        return out


@lru_cache(maxsize=1)
def default_rules() -> Rules:
    return Rules()
