"""Build the two benchmarks drawn from LC's own 2007-2010 validation records (strings LC confirmed as correctly
built from free-floating subdivisions; 667 "Record generated for validation purposes").

known_valid.tsv   1000 such strings. They are run against a copy of the database with their own records removed
                  (data/derived/lcsh_hidden.sqlite, git-ignored; LCSH_DB=... when running), so the rule layer and the
                  model have to rebuild each string from the free-floating lists: every flag is a false positive.
known_invalid.tsv 700 strings broken in a rule-specific way, each with the rule it breaks: the main heading replaced by
                  one of its UF variants; a pattern subdivision outside its category (--Grammar under a non-language);
                  an unestablished period under a topic; a locality as its qualified heading form instead of the indirect
                  chain; a form subdivision before a topical one (contested since LC's June 2026 180 records for form terms, see
                  scripts/score_benchmark.py); a cancelled heading replaced by another LCSH record.

usage: uv run scripts/build_benchmark.py      (seed 20261026; rewrites tests/benchmarks/*.tsv and the hidden DB)
       then scripts/score_benchmark.py on the result files.
"""
import json, random, shutil, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lcsh_validator.db import LCSHDB
from lcsh_validator.parse import normalize_label
SP = str(ROOT / "tests/benchmarks") + "/"
SRC = str(ROOT / "data/derived/lcsh.sqlite")
rng = random.Random(20261026)
db = LCSHDB(online=False)
con = sqlite3.connect(SRC)
pool = con.execute("select id, label from headings where editorial_note like '%validation%' and authorized=1 and tag='150' and label like '%--%'").fetchall()
rng.shuffle(pool)
valid, rest = pool[:1000], pool[1000:]
open(SP + "known_valid.tsv", "w", encoding="utf-8").write("id\tlabel\n" + "".join(f"{i}\t{l}\n" for i, l in valid))
# hidden DB: the 1000 known-valid strings removed everywhere
hid = str(ROOT / "data/derived/lcsh_hidden.sqlite")
shutil.copyfile(SRC, hid)
h = sqlite3.connect(hid)
ids = [i for i, _ in valid]
for sql in ("delete from headings where id=?", "delete from headings_fts where id=?", "delete from complex_components where complex_id=?", "delete from variants where heading_id=?"):
    h.executemany(sql, [(i,) for i in ids])
for col in ("narrower", "related"):  # other records point at the hidden ones by id; scrub those pointers too
    for i in ids:
        h.execute(f"update headings set {col}=replace(replace(replace({col}, '\"{i}\", ', ''), ', \"{i}\"', ''), '\"{i}\"', '') where {col} like '%\"{i}\"%'")
h.commit(); h.execute("vacuum"); h.close()
print("valid:", len(valid), "hidden db written")

norms = set(r[0] for r in con.execute("select norm from headings where authorized=1"))
def comps(hid_):
    return con.execute("select pos, component_id, component_type, component_label from complex_components where complex_id=? order by pos", (hid_,)).fetchall()
def exists(label):
    return normalize_label(label) in norms
inv = []  # (heading, mutation, rule, base)
NARROW = [("--Grammar", "H 1154 (languages)", "language"), ("--Dialects", "H 1154 (languages)", "language"), ("--Seeds", "H 1180 (plants and crops)", "plant"),
          ("--Side effects", "H 1149 (chemicals, drugs)", "chemical"), ("--Transplantation", "H 1164 (organs of the body)", "organ"), ("--Regimental histories", "H 1200 (wars)", "war"),
          ("--Spectra", "H 1149 (chemicals)", "chemical"), ("--Officers", "H 1159 (military services)", "arm")]
# a main heading is outside the category when it has no category hint and its label does not carry the category word
# (Russian language, Petroleum chemicals and the like are inside their categories although the BT walk may miss them)
def outside(main, hint_word):
    return hint_word not in main.lower() and ("drug" not in main.lower() if hint_word == "chemical" else True) and ("force" not in main.lower() if hint_word == "arm" else True)
want = {"variant_main": 120, "wrong_category_pattern": 120, "unestablished_period": 120, "qualified_place_as_subdivision": 120, "form_before_topical": 120}
got = {k: 0 for k in want}
for i, l in rest:
    if all(got[k] >= want[k] for k in want): break
    cs = comps(i)
    if not cs or cs[0][2] != "Topic": continue
    main = cs[0][3]; els = l.split("--")
    types = [c[2] for c in cs]
    if got["variant_main"] < want["variant_main"]:
        vs = [v for (v,) in con.execute("select label from variants where heading_id=?", (cs[0][1],)) if not exists(v) and "--" not in v]
        if vs:
            v = rng.choice(vs); m = v + "--" + "--".join(els[1:])
            if not exists(m): inv.append((m, "variant_main", "main heading is a UF/variant, not the authorized form (H 373; use " + main + ")", l)); got["variant_main"] += 1; continue
    if got["wrong_category_pattern"] < want["wrong_category_pattern"] and len(els) == 2 and types == ["Topic", "Topic"] and not db.category_hints(cs[0][1]):
        s, rule, word = rng.choice(NARROW); m = l + s
        if not exists(m) and outside(main, word): inv.append((m, "wrong_category_pattern", "pattern subdivision outside its category: " + rule, l)); got["wrong_category_pattern"] += 1; continue
    if got["unestablished_period"] < want["unestablished_period"] and len(els) == 2 and types == ["Topic", "Topic"] and "History" not in l:
        a = rng.randint(1700, 1990); b = a + rng.randint(3, 40); m = f"{l}--History--{a}-{b}"
        if not exists(m): inv.append((m, "unestablished_period", "chronological subdivision under a topic must be established; not on the H 1647 free-floating list (H 620)", l)); got["unestablished_period"] += 1; continue
    if got["qualified_place_as_subdivision"] < want["qualified_place_as_subdivision"] and len(cs) >= 3 and types[-2:] == ["Geographic", "Geographic"]:
        tail = "--".join(els[-2:])
        r = con.execute("select p.label from headings d join headings p on p.id=d.generated_from where d.id like '%-781' and d.label=?", (tail,)).fetchone()
        if r and "(" in r[0]:
            m = "--".join(els[:-2]) + "--" + r[0]
            if not exists(m): inv.append((m, "qualified_place_as_subdivision", "a locality is subdivided indirectly through its country, never as its qualified heading form (H 830)", l)); got["qualified_place_as_subdivision"] += 1; continue
    if got["form_before_topical"] < want["form_before_topical"] and len(els) == 2 and types == ["Topic", "Topic"]:
        # --Juvenile literature and --Problems, exercises, etc. are form-only (no topical usage), unlike --Congresses / --Periodicals
        f = rng.choice(["--Juvenile literature", "--Problems, exercises, etc."]); m = els[0] + f + "--" + els[1]
        if not exists(m): inv.append((m, "form_before_topical", "a form subdivision comes last, after topical subdivisions (H 1075 sec. B; H 1095 sec. E)", l)); got["form_before_topical"] += 1; continue
dep = con.execute("select label, use_instead from headings where deprecated=1 and use_instead not in ('[]','') and use_instead is not null and label not like '%--%'").fetchall()
dep = [(l, u) for l, u in dep if not exists(l) and all(x.startswith("sh") for x in json.loads(u)) and all(db.get(x) and db.get(x)["authorized"] for x in json.loads(u))]  # replaced by other LCSH records, not moved to the name file
rng.shuffle(dep)
for l, u in dep[:100]:
    inv.append((l, "deprecated_heading", "heading cancelled or replaced; use " + ", ".join(db.label_of(x) for x in json.loads(u)[:2]), ""))
print(got, "deprecated", min(100, len(dep)), "total", len(inv))
open(SP + "known_invalid.tsv", "w", encoding="utf-8").write("heading\tmutation\trule\tbase\n" + "".join("\t".join(x) + "\n" for x in inv))
