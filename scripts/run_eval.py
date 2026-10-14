"""Run the validator over tests/headings.jsonl and score verdicts.
Usage: uv run scripts/run_eval.py [--effort medium] [--limit N] [--out results.jsonl]
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lcsh_validator.agent import Validator  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", help="substring filter on heading")
    ap.add_argument("--out", default=str(ROOT / "data/derived/eval_results.jsonl"))
    args = ap.parse_args()
    cases = [json.loads(l) for l in (ROOT / "tests/headings.jsonl").read_text().splitlines() if l.strip()]
    if args.only:
        cases = [c for c in cases if args.only.lower() in c["heading"].lower()]
    if args.limit:
        cases = cases[: args.limit]
    v = Validator(effort=args.effort, verbose=False)
    out = open(args.out, "w")
    agree = 0
    rows = []
    for c in cases:
        t0 = time.time()
        try:
            res = v.validate(c["heading"])
            got = res.verdict.get("verdict", "?")
            rec = {"heading": c["heading"], "expect": c["expect"], "got": got, "confidence": res.verdict.get("confidence"),
                   "issues": res.verdict.get("issues"), "explanation": res.verdict.get("explanation"), "turns": res.turns,
                   "tools": res.tools_used(), "usage": res.usage, "secs": round(time.time() - t0, 1)}
        except Exception as e:  # noqa: BLE001
            got = "error"
            rec = {"heading": c["heading"], "expect": c["expect"], "got": "error", "error": str(e)}
        ok = got == c["expect"]
        agree += ok
        rows.append(rec)
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        print(f"{'OK ' if ok else 'XX '} {c['heading'][:60]:60} expect={c['expect']:8} got={got:9} {rec.get('secs', '')}s turns={rec.get('turns', '')}")
    print(f"\nagreement: {agree}/{len(cases)}")
    tot_in = sum(r.get("usage", {}).get("input_tokens", 0) + r.get("usage", {}).get("cache_read_input_tokens", 0) for r in rows)
    tot_out = sum(r.get("usage", {}).get("output_tokens", 0) for r in rows)
    print(f"tokens: in+cached={tot_in} out={tot_out}")


if __name__ == "__main__":
    main()
