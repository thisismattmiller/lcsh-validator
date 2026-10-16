"""Fetch the MARC 008/06 geographic-subdivision code from id.loc.gov for the records the 2016 bulk file misses.

The LC MDSConnect "2016" files are a 2015-12-29 snapshot. For every authorized multi-element heading string
(label with '--') that is not in collection_SubdivideGeographically and either has no code from the snapshot or
has been changed since, this reads https://id.loc.gov/authorities/subjects/{id}.marcxml.xml and records the code.
(Single-element headings and records in the SubdivideGeographically collection need no fetch: H 364 and the
collection already decide them.) Resumable: ids already in the output file are skipped.

usage: uv run python -I scripts/fetch_marc_008.py [data/derived/geog_code_008_06_idloc.tsv] [--all] [--rate 2]
Polite by design: one request at a time, at most --rate requests per second (default 2); back off on errors.
output rows: id<TAB>code<TAB>005 (code '-' = record not found / no 008)
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data/derived/lcsh.sqlite"
SNAPSHOT_DATE = "2015-12-29"
USER_AGENT = "lcsh-validator/0.1 (https://github.com/thisismattmiller; local cataloging tool)"
# control fields on recently changed records carry extra attributes (xmlns:streams=...), hence [^>]*
RE_008 = re.compile(r'tag="008"[^>]*>([^<]*)<')
RE_005 = re.compile(r'tag="005"[^>]*>([^<]*)<')


def select_ids(con: sqlite3.Connection, everything: bool) -> list[str]:
    where = "id not like '%-%' and authorized=1"
    if not everything:
        where += (" and label like '%--%' and may_subd_geog=0"
                  f" and (geog_code is null or record_date>='{SNAPSHOT_DATE}')")
    return [r[0] for r in con.execute(f"select id from headings where {where} order by id")]


class Pacer:
    """At most `rate` requests per second."""

    def __init__(self, rate: float):
        self.gap, self.next_at = 1.0 / rate, 0.0

    def wait(self):
        now = time.monotonic()
        if now < self.next_at:
            time.sleep(self.next_at - now)
        self.next_at = max(now, self.next_at) + self.gap


def fetch(hid: str, pacer: Pacer) -> tuple[str, str, str]:
    url = f"https://id.loc.gov/authorities/subjects/{hid}.marcxml.xml"
    for attempt in range(5):
        pacer.wait()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", "replace")
            m = RE_008.search(body)
            if not m or len(m.group(1)) < 7:
                return hid, "-", ""
            m5 = RE_005.search(body)
            return hid, m.group(1)[6], (m5.group(1) if m5 else "")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return hid, "-", ""
            time.sleep(10 * 2 ** attempt)  # 429 / 503: back off hard
        except Exception:  # noqa: BLE001 network hiccups
            time.sleep(2 ** attempt)
    return hid, "?", ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", type=Path, default=ROOT / "data/derived/geog_code_008_06_idloc.tsv")
    ap.add_argument("--all", action="store_true", help="every authorized record, not only the ones whose code matters and may be missing")
    ap.add_argument("--rate", type=float, default=2.0, help="requests per second (default 2)")
    a = ap.parse_args()
    out, rate = a.out, a.rate
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ids = select_ids(con, a.all)
    done = set()
    if out.exists():
        done = {line.split("\t", 1)[0] for line in out.read_text(encoding="utf-8").splitlines() if "\t" in line}
    todo = [i for i in ids if i not in done]
    print(f"{len(ids)} records in scope, {len(done)} already fetched, {len(todo)} to fetch", flush=True)
    pacer = Pacer(rate)
    counts: dict[str, int] = {}
    t0 = time.time()
    with out.open("a", encoding="utf-8") as fh:
        for n, hid in enumerate(todo, 1):
            hid, code, f005 = fetch(hid, pacer)
            fh.write(f"{hid}\t{code}\t{f005}\n")
            counts[code] = counts.get(code, 0) + 1
            if n % 1000 == 0:
                fh.flush()
                print(f"{n}/{len(todo)} {time.time() - t0:.0f}s {counts}", flush=True)
    print(f"done: {counts}")


if __name__ == "__main__":
    main()
