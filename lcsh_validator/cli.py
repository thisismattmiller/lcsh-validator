"""Command-line interface.

  uv run lcsh-validate "Tacos--History--20th century"
  uv run lcsh-validate --facts "650 _0 $a Taxation $z France $z Paris"     # deterministic facts only, no model
  uv run lcsh-validate --batch headings.txt --out results.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lcsh-validate", description="Validate LCSH subject heading strings against the Subject Headings Manual.")
    ap.add_argument("heading", nargs="?", help="heading string ('A--B--C' or MARC '650 _0 $a A $x B')")
    ap.add_argument("--batch", help="file with one heading per line")
    ap.add_argument("--out", help="write JSONL results here (batch mode)")
    ap.add_argument("--facts", action="store_true", help="print the deterministic facts report only (no API call)")
    ap.add_argument("--json", action="store_true", help="print the full JSON result")
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--offline", action="store_true", help="do not call id.loc.gov for name authority lookups")
    ap.add_argument("-v", "--verbose", action="store_true", help="show tool calls")
    args = ap.parse_args(argv)
    if not args.heading and not args.batch:
        ap.error("give a heading or --batch FILE")

    from .db import LCSHDB
    from .freefloating import FreeFloating
    from .parse import parse_heading
    from .analysis import Analyzer

    db = LCSHDB(online=not args.offline)
    ff = FreeFloating()
    headings = [args.heading] if args.heading else [l.strip() for l in open(args.batch) if l.strip() and not l.startswith("#")]

    if args.facts:
        an = Analyzer(db, ff)
        for h in headings:
            print(json.dumps(an.analyze(parse_heading(h)), indent=1, ensure_ascii=False, default=str))
        return

    from .agent import Validator
    kw = {"effort": args.effort, "verbose": args.verbose}
    if args.model:
        kw["model"] = args.model
    v = Validator(db=db, ff=ff, **kw)
    out = open(args.out, "a") if args.out else None
    for h in headings:
        res = v.validate(h)
        rec = res.to_dict()
        if out:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
        if args.json or args.batch:
            print(json.dumps(rec, ensure_ascii=False, indent=None if args.batch else 1))
        else:
            _pretty(res)


def _pretty(res):
    v = res.verdict
    print(f"\n{res.heading}")
    print(f"  VERDICT: {str(v.get('verdict', '?')).upper()}  (confidence {v.get('confidence', '?')})")
    if v.get("normalized_string") and v.get("normalized_string") != res.heading:
        print(f"  suggested form: {v['normalized_string']}")
    for e in v.get("elements", []) or []:
        print(f"  - {e.get('element')!s:45} {e.get('role', ''):13} {e.get('status', '')}: {e.get('basis', '')}")
    for i in v.get("issues", []) or []:
        print(f"  ! [{i.get('severity')}] {i.get('element')}: {i.get('problem')} ({i.get('rule')}) -> {i.get('fix', '')}")
    for n in v.get("lc_practice_notes", []) or []:
        print(f"  LC practice: {n}")
    for s in v.get("suggested_alternatives", []) or []:
        print(f"  alternative: {s}")
    print(f"  {v.get('explanation', '')}")
    print(f"  [{res.turns} turns; tools: {', '.join(res.tools_used())}; tokens in={res.usage['input_tokens']} cache_read={res.usage['cache_read_input_tokens']} cache_write={res.usage['cache_creation_input_tokens']} out={res.usage['output_tokens']}; cost ${res.cost['usd']:.5f}]" if res.cost else "]")


if __name__ == "__main__":
    main()
