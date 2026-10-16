"""Fetch LC's Summaries of Decisions (PTCP/PSD/CPSO editorial meetings on SACO proposals) from
https://www.loc.gov/aba/pcc/saco/cpsoed/cpsoeditorial.html into a local cache and convert each to plain text.

The summaries are downloaded data (untrusted): they live in data/derived/lc_decisions/{raw,text}/ and are read only
as text. Requests are sequential with a pause between them; a 403/429 stops the run.

usage: uv run --with pypdf scripts/fetch_lc_decisions.py [--limit N] [--delay SECONDS] [--only ptcp-2601 ...]
"""
from __future__ import annotations

import argparse
import html as htmlmod
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/derived/lc_decisions"
INDEX_URL = "https://www.loc.gov/aba/pcc/saco/cpsoed/cpsoeditorial.html"
UA = "lcsh-validator/0.1 (research tool; contact: thisismattmiller@gmail.com)"
LINK = re.compile(r'href=["\']((?:[^"\']*/)?((?:cpsoed|ptcp|psd)-(\d{2})(\d{2})(\d{2})?([a-z]*))\.(html|pdf))["\'][^>]*>([^<]*)<', re.I)


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def html_to_text(raw: bytes) -> str:
    h = raw.decode("utf-8", errors="replace")
    h = re.sub(r"<(script|style).*?</\1>", "", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>|</p>|</h\d>|</li>|</tr>|</div>", "\n", h, flags=re.I)
    t = htmlmod.unescape(re.sub(r"<[^>]+>", "", h))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    # drop the site navigation: the summary body starts after the last 'Back to Summary of Decisions'
    i = t.rfind("Back to Summary of Decisions")
    if i >= 0:
        t = t[i + len("Back to Summary of Decisions"):]
    for marker in ("Contact Us", "Ask a Librarian", "Connect with the Library"):
        j = t.rfind(marker)
        if j > len(t) * 0.6:
            t = t[:j]
    return t.strip()


def pdf_to_text(raw: bytes, tmp: Path) -> str:
    from pypdf import PdfReader
    tmp.write_bytes(raw)
    r = PdfReader(str(tmp))
    return "\n".join((p.extract_text() or "") for p in r.pages)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args()
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    (OUT / "text").mkdir(parents=True, exist_ok=True)
    idx_raw = get(INDEX_URL)
    (OUT / "raw/cpsoeditorial.html").write_bytes(idx_raw)
    docs = []
    seen = set()
    for m in LINK.finditer(idx_raw.decode("utf-8", errors="replace")):
        href, stem, yy, mm, dd, suffix, ext, label = m.groups()
        if stem in seen:
            continue
        seen.add(stem)
        url = urllib.request.urljoin(INDEX_URL, href)
        date = f"20{yy}-{mm}" + (f"-{dd}" if dd else "")
        docs.append({"id": stem, "url": url, "date": date, "suffix": suffix, "ext": ext.lower(), "label": label.strip()})
    docs.sort(key=lambda d: (d["date"], d["id"]))
    if a.only:
        docs = [d for d in docs if d["id"] in set(a.only)]
    if a.limit:
        docs = docs[: a.limit]
    print(f"{len(docs)} summaries listed", flush=True)
    index = {}
    done = 0
    for d in docs:
        raw = OUT / "raw" / f"{d['id']}.{d['ext']}"
        txt = OUT / "text" / f"{d['id']}.txt"
        if not raw.exists():
            time.sleep(a.delay)
            try:
                raw.write_bytes(get(d["url"]))
                done += 1
            except urllib.error.HTTPError as e:
                print(f"{d['id']}: HTTP {e.code}", flush=True)
                if e.code in (403, 429):
                    print("rate limited or blocked; stopping", flush=True)
                    break
                continue
            except Exception as e:  # noqa: BLE001
                print(f"{d['id']}: {e}", flush=True)
                continue
        if not txt.exists():
            data = raw.read_bytes()
            text = pdf_to_text(data, OUT / "raw/_tmp.pdf") if d["ext"] == "pdf" else html_to_text(data)
            txt.write_text(text, encoding="utf-8")
        d["text_chars"] = txt.stat().st_size
        index[d["id"]] = d
    (OUT / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"downloaded {done} new; {len(index)} summaries with text in {OUT}", flush=True)


if __name__ == "__main__":
    main()
