"""Score the validator on the two benchmarks built by scripts/build_benchmark.py.

usage: uv run scripts/score_benchmark.py reports/benchmark.md VALID_RESULTS.jsonl... -- INVALID_RESULTS.jsonl...
Known-valid (LC validation records, their own records hidden): every verdict other than "valid" is a false positive.
Known-invalid (rule-specific mutations): "invalid" is a hit, "questionable" a partial hit, "valid" or "uncertain" a miss;
a hit also counts as rule-matched when the model cites the sheet the mutation breaks.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "tests/benchmarks"
# In June 2026 LC created 180 (topical) records for 144 form subdivisions ("Use as a topical subdivision under subjects"),
# so [topic]--Juvenile literature--History now also reads as topical--topical; this class is reported but kept out of the
# headline recall.
CONTESTED = {"form_before_topical": "LC's June 2026 180 records make the form term readable as a topical subdivision"}


def load(files):
    rows = {}
    for f in files:
        for line in open(f, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                rows[r["heading"]] = r
    return rows


def verdict(r):
    return r["verdict"]["verdict"] if "verdict" in r else "error"


def reason(r):
    if "verdict" not in r:
        return r.get("error", "")
    v = r["verdict"]
    iss = [i for i in v.get("issues") or [] if i.get("severity") in ("error", "warning")]
    return "; ".join(f"[{i['severity']}] {i.get('element', '')}: {i.get('problem', '')} ({i.get('rule', '')})" for i in iss) or v.get("explanation", "")


def cost(rows):
    return sum(r.get("cost") or 0 for r in rows.values())


def main():
    out = Path(sys.argv[1])
    args = sys.argv[2:]
    split = args.index("--")
    valid_res, invalid_res = load(args[:split]), load(args[split + 1:])
    md = ["# Benchmark: LC validation records", "",
          "Two sets drawn from LC's own 2007-2010 validation records (`scripts/build_benchmark.py`, seed 20261026). "
          "Known-valid strings are run against a database copy with their own records removed, so every flag is a false positive. "
          "Known-invalid strings are those records broken in a rule-specific way, so every non-invalid verdict is a miss.", ""]

    # ---- known valid ----
    kv = [l.rstrip("\n").split("\t") for l in open(BENCH / "known_valid.tsv", encoding="utf-8")][1:]
    got = [(i, l, valid_res[l]) for i, l in kv if l in valid_res]
    c = Counter(verdict(r) for _, _, r in got)
    n = len(got)
    md += [f"## Known-valid: {n} of {len(kv)} run, cost ${cost(valid_res):.2f}", "", "| verdict | count | share |", "|---|---|---|"]
    md += [f"| {k} | {c[k]} | {100 * c[k] / n:.1f}% |" for k in ("valid", "questionable", "uncertain", "invalid", "error") if c[k]]
    fp = [(i, l, r) for i, l, r in got if verdict(r) != "valid"]
    md += ["", f"False-positive rate (anything not valid): {100 * len(fp) / n:.1f}%; hard false positives (invalid): {100 * c['invalid'] / n:.1f}%.", ""]
    md += [f"### Flagged ({len(fp)})", ""]
    for i, l, r in sorted(fp, key=lambda x: (verdict(x[2]) != "invalid", x[1])):
        md += [f"- **{l}** ({i}) — {verdict(r)} {r.get('verdict', {}).get('confidence', '')}: {reason(r)}"]
    md.append("")

    # ---- known invalid ----
    ki = [l.rstrip("\n").split("\t") for l in open(BENCH / "known_invalid.tsv", encoding="utf-8")][1:]
    got = [(h, m, rule, base, invalid_res[h]) for h, m, rule, base in ki if h in invalid_res]
    md += [f"## Known-invalid: {len(got)} of {len(ki)} run, cost ${cost(invalid_res):.2f}", "",
           "| mutation | n | invalid | questionable | uncertain | valid | rule cited |", "|---|---|---|---|---|---|---|"]
    per = defaultdict(list)
    for x in got:
        per[x[1]].append(x)
    tot = Counter()
    for m, xs in per.items():
        cc = Counter(verdict(r) for *_, r in xs)
        sheet = Counter()
        for h, _, rule, base, r in xs:
            sheets = set(re.findall(r"H \d+(?:\.\d+)?", rule))
            cited = " ".join(i.get("rule", "") for i in (r.get("verdict", {}).get("issues") or []))
            if verdict(r) == "invalid" and (not sheets or any(s in cited for s in sheets)):
                sheet["cited"] += 1
        tot.update(cc)
        md += [f"| {m} | {len(xs)} | {cc['invalid']} | {cc['questionable']} | {cc['uncertain']} | {cc['valid']} | {sheet['cited']} |"]
    N = len(got)
    md += [f"| **all** | {N} | {tot['invalid']} | {tot['questionable']} | {tot['uncertain']} | {tot['valid']} | |", ""]
    sound = [x for x in got if x[1] not in CONTESTED]
    st = Counter(verdict(r) for *_, r in sound)
    S = len(sound)
    md += [f"Sound classes ({S} strings, {', '.join(m for m in per if m not in CONTESTED)}): recall (invalid) {100 * st['invalid'] / S:.1f}%; "
           f"counting questionable {100 * (st['invalid'] + st['questionable']) / S:.1f}%; misses (valid or uncertain) {100 * (st['valid'] + st['uncertain']) / S:.1f}%.", ""]
    for m, why in CONTESTED.items():
        if m in per:
            cm = Counter(verdict(r) for *_, r in per[m])
            md += [f"Contested class {m} ({len(per[m])}): {cm['invalid']} invalid, {cm['questionable']} questionable, {cm['valid']} valid. {why}; the split verdicts reflect that ambiguity and are not counted as misses.", ""]
    md += [f"All classes: recall (invalid) {100 * tot['invalid'] / N:.1f}%; counting questionable {100 * (tot['invalid'] + tot['questionable']) / N:.1f}%.", ""]
    misses = [x for x in got if verdict(x[4]) in ("valid", "uncertain", "questionable", "error")]
    md += [f"### Not caught as invalid ({len(misses)})", ""]
    for h, m, rule, base, r in sorted(misses, key=lambda x: (x[1], x[0])):
        md += [f"- **{h}** [{m}] — {verdict(r)} {r.get('verdict', {}).get('confidence', '')}: {reason(r)[:400]}"]
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"known-valid {n}: " + ", ".join(f"{k} {c[k]}" for k in c) + f" | known-invalid {N}: " + ", ".join(f"{k} {tot[k]}" for k in tot))


if __name__ == "__main__":
    main()
