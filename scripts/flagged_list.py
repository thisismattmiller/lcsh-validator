"""Cumulative list of every sampled heading the validator did not judge valid, across all runs.

usage: uv run python scripts/flagged_list.py
Reads the result files in data/derived/marva/ in run order; a later result for the same heading
(for example a rerun after a parser fix) replaces the earlier one. Writes
reports/flagged-headings.md (grouped by verdict, full headings, full reasons) and
reports/flagged-headings.tsv (one row per heading for spreadsheets).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARVA = ROOT / "data/derived/marva"
RUNS = [
    "sample100_results.jsonl", "sample100b_results.jsonl", "sample500_results.jsonl",
    "sample1000_results.jsonl", "sample1000b_results.jsonl",
    "opendate13_results.jsonl",  # rerun after the open-date parser fix; overrides earlier verdicts
    "recheck_results.jsonl",  # all previously flagged headings rerun with the current validator (2026-10-14)
    "flips45_results.jsonl",  # the 45 headings whose verdict flipped between runs, rerun with the consistency guardrails
    "sample1000c_results.jsonl",  # third 1000 (seed 20261019), run in two-pass mode
    "sample1000c_recheck_results.jsonl",  # its flagged headings rerun once more
    "dis27_results.jsonl",  # the 27 that disagreed between those two runs, rerun after the order / In-literature / category tweaks
    "sample1000d_results.jsonl",  # fourth 1000 (seed 20261020), two-pass mode
    "sample1000d_recheck_results.jsonl",  # its flagged headings rerun once more
    "dis1000d_results.jsonl",  # disagreements between those two, rerun after the next round of tweaks
    "sample2000e_results.jsonl",  # fifth round: 2000 headings (seed 20261021), two-pass mode
    "sample2000e_recheck_results.jsonl",  # its flagged headings rerun once more
    "dis2000e_results.jsonl",  # disagreements between those two, rerun after the round-5 tweaks
    "uf3_results.jsonl",  # three headings rerun after the UF-prefix rule check (H 373) was added
    "sample2000f_results.jsonl",  # sixth round: 2000 headings (seed 20261022), two-pass mode
    "sample2000f_recheck_results.jsonl",  # its flagged headings rerun once more
    "dis2000f_results.jsonl",  # disagreements between those two, rerun after the round-6 tweaks
    "sample2000g_results.jsonl",  # seventh round: 2000 headings (seed 20261023), two-pass mode
    "sample2000g_recheck_results.jsonl",  # its flagged headings rerun once more
    "dis2000g_results.jsonl",  # disagreements between those two (plus fix-affected headings), rerun after the round-7 tweaks
    "ev3_2000g_results.jsonl",  # the H 1100 sec. D / H 1155.2 headings rerun after the final round-7 tweak
    "sample5000h_results.jsonl",  # eighth round: 5000 headings (seed 20261024), two-pass mode
    "sample5000h_recheck_results.jsonl",  # its flagged headings rerun once more
    "dis5000h_results.jsonl",  # disagreements between those two, rerun after the round-8 tweaks
    "fx5000h_results.jsonl",  # headings touched by the round-8 fixes (151 main headings with phrase subdivisions, established prefixes coded May Subd Geog), rerun
    "ev2_5000h_results.jsonl",  # Outer space--In literature and Antarctica--On television--History rerun after the 151 phrase-subdivision prompt line
    "sample5000i_results.jsonl",  # ninth round: stratified 5000 (seed 20261025: 151 main headings, 4+ elements, extended prefixes, name-title/corporate, pattern+period, validation-record mains, uniform fill)
    "rc5000i_results.jsonl",  # its flagged headings rerun once more
    "fx5000i_results.jsonl",  # Musicals (BT music form), National songs, Regimental histories crash: rerun after the round-9 fixes
    "fx2_5000i_results.jsonl",  # headings whose facts changed with the three-valued 008/06 geographic coding, rerun
    "dis5000i_results.jsonl",  # disagreements between the first pass and the recheck, rerun after the round-9 fixes
    "ev9_5000i_results.jsonl",  # the flagged Bible / Qurʼan / Puranas parts, rerun after the Bible-parts prompt line
    "fx3_5000i_results.jsonl",  # headings touched by the new H 1629 foreign-relations checks, rerun
]
ORDER = ["invalid", "questionable", "uncertain", "error"]

latest: dict[str, dict] = {}
run_of: dict[str, str] = {}
first_verdict: dict[str, str] = {}
for name in RUNS:
    path = MARVA / name
    if not path.exists():
        continue
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                latest[r["heading"]] = r
                run_of[r["heading"]] = name.replace("_results.jsonl", "")
                first_verdict.setdefault(r["heading"], r.get("verdict", {}).get("verdict", "error"))

rows = []
for h, r in latest.items():
    if "error" in r:
        rows.append({"heading": h, "verdict": "error", "confidence": "", "reason": r["error"], "fix": "", "run": run_of[h]})
        continue
    v = r["verdict"]
    if v["verdict"] == "valid":
        continue
    issues = [i for i in v.get("issues") or [] if i.get("severity") in ("error", "warning")]
    reason = "; ".join(f"[{i['severity']}] {i.get('element', '')}: {i.get('problem', '')} ({i.get('rule', '')})" for i in issues) or v.get("explanation", "")
    fix = "; ".join(i["fix"] for i in issues if i.get("fix"))
    rows.append({"heading": h, "verdict": v["verdict"], "confidence": v.get("confidence", ""), "reason": reason, "fix": fix, "run": run_of[h]})

rows.sort(key=lambda x: (ORDER.index(x["verdict"]), -(x["confidence"] or 0), x["heading"]))
counts = Counter(x["verdict"] for x in rows)
total = len(latest)
cleared = sorted(h for h, r in latest.items() if "error" not in r and r["verdict"]["verdict"] == "valid" and first_verdict[h] != "valid")

md = [f"# Flagged headings ({len(rows)} of {total} sampled, all runs)", "",
      "Every heading from the Marva samples that the validator did not judge valid, with the latest verdict "
      "(reruns after fixes replace earlier results). Regenerate with `uv run python scripts/flagged_list.py`.", "",
      "| verdict | count |", "|---|---|"] + [f"| {k} | {counts[k]} |" for k in ORDER if counts[k]] + [""]
if cleared:
    md += [f"## Cleared on recheck ({len(cleared)})", "",
           "Flagged in an earlier run, judged valid by the current validator (parser fixes, multiples, free-floating strings, verdict policy).", ""]
    md += [f"- {h}" for h in cleared] + [""]
for verdict in ORDER:
    group = [x for x in rows if x["verdict"] == verdict]
    if not group:
        continue
    md += [f"## {verdict.upper()} ({len(group)})", ""]
    for x in group:
        conf = f" ({x['confidence']})" if x["confidence"] != "" else ""
        md += [f"### {x['heading']}", "", f"{x['reason']}{conf}"]
        if x["fix"]:
            md.append(f"Fix: {x['fix']}")
        md.append("")
(ROOT / "reports/flagged-headings.md").write_text("\n".join(md), encoding="utf-8")

with (ROOT / "reports/flagged-headings.tsv").open("w", encoding="utf-8") as fh:
    fh.write("heading\tverdict\tconfidence\treason\tfix\trun\n")
    for x in rows:
        fh.write("\t".join(str(x[k]).replace("\t", " ").replace("\n", " ") for k in ("heading", "verdict", "confidence", "reason", "fix", "run")) + "\n")
print(f"{len(rows)} flagged of {total}: " + ", ".join(f"{k} {counts[k]}" for k in ORDER if counts[k]))
