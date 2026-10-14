"""Summarize a batch of validator results and list every heading that was not judged valid.

usage: uv run python scripts/report_sample.py OUT.md RESULTS.jsonl [RESULTS2.jsonl ...]
"""
from __future__ import annotations

import json
import sys
from collections import Counter

out_path, *inputs = sys.argv[1:]
recs = []
for p in inputs:
    with open(p, encoding="utf-8") as fh:
        recs.extend(json.loads(l) for l in fh if l.strip())

ORDER = {"invalid": 0, "questionable": 1, "uncertain": 2, "error": 3}
verdicts = Counter()
cost = secs = 0.0
usage = Counter()
flagged = []
for r in recs:
    if "error" in r:
        verdicts["error"] += 1
        flagged.append((3, r))
        continue
    v = r["verdict"]["verdict"]
    verdicts[v] += 1
    cost += r.get("cost") or 0
    secs += r.get("secs") or 0
    for k, n in (r.get("usage") or {}).items():
        usage[k] += n
    if v != "valid":
        flagged.append((ORDER.get(v, 9), r))
flagged.sort(key=lambda t: (t[0], -(t[1].get("verdict") or {}).get("confidence", 0)))

n = len(recs)
lines = [f"# Validator sample report ({n} headings)", ""]
lines.append("| verdict | count |")
lines.append("|---|---|")
for k in ("valid", "questionable", "uncertain", "invalid", "error"):
    if verdicts[k]:
        lines.append(f"| {k} | {verdicts[k]} |")
lines += ["", f"- total cost: ${cost:.4f} (avg ${cost / max(n, 1):.4f} per heading)",
          f"- tokens: input {usage['input_tokens']:,}, cache read {usage['cache_read_input_tokens']:,}, "
          f"cache write {usage['cache_creation_input_tokens']:,}, output {usage['output_tokens']:,}",
          f"- wall time per heading (sequential within a runner): {secs / max(n, 1):.1f} s", ""]

for label, code in (("INVALID", 0), ("QUESTIONABLE (review)", 1), ("UNCERTAIN", 2), ("ERRORS", 3)):
    group = [r for c, r in flagged if c == code]
    if not group:
        continue
    lines += [f"## {label} ({len(group)})", ""]
    for r in group:
        if "error" in r:
            lines += [f"### {r['heading']}", "", f"- error: `{r['error']}`", ""]
            continue
        v = r["verdict"]
        lines += [f"### {r['heading']}", "",
                  f"- verdict: **{v['verdict']}** (confidence {v.get('confidence')}) · {v.get('heading_type', '')}",
                  f"- {v.get('explanation', '').strip()}"]
        for iss in v.get("issues") or []:
            if iss.get("severity") in ("error", "warning"):
                fix = f" Fix: {iss['fix']}" if iss.get("fix") else ""
                lines.append(f"- [{iss['severity']}] {iss.get('element', '')}: {iss.get('problem', '')} "
                             f"({iss.get('rule', '')}).{fix}")
        if v.get("suggested_alternatives"):
            alts = "; ".join(a if isinstance(a, str) else a.get("heading", str(a)) for a in v["suggested_alternatives"])
            lines.append(f"- alternatives: {alts}")
        lines.append("")

with open(out_path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines))
print("\n".join(lines[:12]))
