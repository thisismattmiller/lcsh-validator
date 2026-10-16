# lcsh-validator

Decides whether a Library of Congress Subject Headings (LCSH) subject heading string is validly
constructed under the rules of the *Subject Headings Manual* (SHM), and explains why with
citations to instruction sheets.

Two layers:

1. **Deterministic facts** (Python, no model): parses the string, looks every element up in the
   full LCSH authority file (MADS/RDF dump), the LC Name Authority File (id.loc.gov), LC's
   free-floating subdivisions list and the SHM subdivision lists; resolves geographic chains
   against the authorized `781` subdivision form; runs literal checks (capitalization, `--`,
   parentheses, terminal punctuation, element order).
2. **Turn-based reasoning** (Claude Haiku 5.5 via the Anthropic API): reads the facts, consults
   the SHM through tools (`get_rule`, `search_rules`, `lookup_subdivision`, `lookup_place`,
   `established_under`, `pattern_list`, ...), and returns a structured verdict
   (`valid` / `invalid` / `questionable` / `uncertain`) with per-element status, issues, rule citations,
   suggested corrections and LC-practice notes.

Verdicts: `invalid` is reserved for defects the data or rule text establish outright (surface
defects, elements found nowhere, explicit prohibitions and UF conflicts, wrong geographic chains,
order violations). `questionable` (orange QUESTIONABLE badge on the web page) means every element is
authorized somewhere and nothing forbids the combination, but a usage statement does not clearly
cover this heading type or a category membership is inferred: a cataloger should look. `uncertain`
means something could not be verified with the tools.

Consistency guardrails. The model (Haiku 5.5) accepts no temperature setting, so two runs of a
borderline heading can disagree. Three things limit that: the facts include `rule_checks`, mechanical
tests of explicit prohibitions (H 1647 sec. 9 `--History` after a historical subdivision, H 1642
`--Government policy` where a `[topic] and state` / `[topic] policy` heading exists, H 1095 sec. E.2
subdivision forms that duplicate an established phrase heading, H 1100 sec. D social classes), and a
verdict of `valid` that ignores one is demoted to `questionable`; two- and three-element free-floating
strings (`--History--To 1500`, `--Politics and government--21st century`) and bracketed multiples
(`--Paraphrases, English, [French, etc.]`) are matched as list entries; and `LCSH_STABILIZE=1` (or
`Validator.validate(..., stabilize=True)`) runs a second independent pass for any `valid`/`invalid`
verdict below `LCSH_STABILIZE_BELOW` (default 0.8) and reports `questionable` when the passes disagree;
an `invalid` that cites an error-level rule check needs no second pass, and when the passes disagree
over a string that carries such a check the `invalid` pass is reported.
The deployed Lambda runs with `LCSH_STABILIZE=1` and `LCSH_STABILIZE_BELOW=0.86`, which second-passes
about 9% of headings for about 15% more cost; set `LCSH_STABILIZE=0` before `lambda/deploy.sh` to turn it off.

Citation and usage-statement guardrails (`lcsh_validator/audit.py`). Before a verdict is accepted, every
rule the model cites (`issues[].rule`, `elements[].basis`, the explanation and the practice notes) is
checked against the SHM corpus in `rules/`: a sheet that does not exist, or a subdivision cited to a
list it has no entry on (`--Reorganization` to H 1095 when it is on H 1105 and H 1159), is sent back
to the model with the correct list for one more round (`LCSH_PUSHBACK_ROUNDS`, default 1), and any
citation to a non-existent sheet that survives is struck from the verdict text
(`[citation to H 185 removed: no such SHM sheet]`). The facts also give each free-floating
subdivision a `usage_coverage` block that quotes the clause of its usage statement naming the main
heading's type (`... and topical headings for individual directories ...`), so the model does not stop
at the first clause that excludes the heading; a warning that doubts the usage without acknowledging
that clause is pushed back the same way. The verdict records what happened under `guardrails`
(`pushback`, `rounds`, `unresolved`, `citations_removed`) and in `verdict_note`.

Lookups fold case, diacritics and the apostrophe-like characters ʻ ʼ ʿ ʾ ’ (so `Shīʿah` finds
`Shīʻah`) and the facts then state the exact authorized spelling; a bare place name that also exists
as differently qualified jurisdictions (`Rome` vs. `Rome (Italy)`) lists the other `$z` forms; a bare
name with several 181 records (`Sierra`: `Ecuador--Sierra`, `Peru--Sierra`) is checked against the
chain actually given; H 362 phrases (`Prague Region`) are accepted as `$z` in the base city's chain;
a heading that differs from an LCSH form only in hyphenation (`Water supply` / `Water-supply`) is
reported as a near match; and literature, art, music and literary-author-group headings are
recognised by the form of their labels (`Authors, Urdu`) so the H 1156 / H 1148 / H 1160 / H 1155.2
pattern rules apply to them (including H 1155.2's bar on a period subdivision after a place). The H 1100 sec. D "social class" exclusion is only a warning when the
heading is also a class of persons by another BT path, and only a note when LC has established the
same subdivision under it (`Intellectuals--Interviews`); the facts report whether an established prefix such as
`Murder--Investigation` is coded (May Subd Geog), and that coding outranks the free-floating list entry
(`Copyright--Art--Australia` is fine although the list does not mark `--Art` May Subd Geog). The coding is
three-valued, from MARC 008/06: `i` means coded (May Subd Geog); blank means LC coded the string "not
subdivided geographically" (`United States--History--Civil War, 1861-1865--Regimental histories`), an error
or a warning when a place follows it; `|` means LC never evaluated the string, as on `Art, Modern--19th century`
and the 2008-2010 validation records, so the coding of its last subdivision on the free-floating list governs
(`Dementia--Patients--Care--India` is fine). The codes come from LC's 2015-12-29 MARC snapshot completed by a
per-record backfill from id.loc.gov (`scripts/fetch_marc_008.py`, 36k records changed or created since); a record
still unknown locally is read live from its MARCXML on id.loc.gov when the coding matters, and cached. A
single-element heading without the coding may not take a place
(H 364). A country followed by a locality (`Jesuits--Missions--Brazil--Rio Grande do Sul (State)`) is one indirect
place: the record for `Jesuits--Missions--Brazil` does not bar the locality. A heading whose broader term is a
type of music (`Musicals`, BT `Dramatic music`) is an H 1160 music form, so it takes the H 1160 period
subdivisions in the order place, period, topic; a geographic heading (151) such as
`Antarctica` or `Outer space` takes `--In literature`, `--On television` and the other phrase
subdivisions like any place; `--History` under a nationally qualified art heading (`Art, Mexican--History--20th century`)
is an error (H 1647 sec. 1); untraced-reference records (`Districts`) and deletion notes (headings
redistributed as juvenile `sj` records) are surfaced so the model does not mistake them for
headings.

## Setup

```bash
uv sync                                   # Python 3.14, deps: pymupdf, lxml, anthropic, pyyaml
ant auth login                            # or: export ANTHROPIC_API_KEY=...
```

Data build (already done in this checkout; rerun if the sources change):

```bash
uv run scripts/extract_pdf_text.py        # data/raw/*.pdf -> data/text/*.txt
uv run scripts/build_lcsh_db.py           # subjects.madsrdf.xml.gz -> data/derived/lcsh.sqlite (~10 min, 360 MB)
uv run -I scripts/extract_marc_008.py data/raw/lcsh_marc2016/Subjects.2016.part01.utf8.gz data/raw/lcsh_marc2016/Subjects.2016.part02.utf8.gz data/derived/geog_code_008_06.tsv
                                          # LC MDSConnect 2016 MARC (loc.gov/cds/downloads/MDSConnect/) -> id, 008/06 geographic-subdivision code
uv run python -I scripts/fetch_marc_008.py   # the 2016 files are a 2015-12-29 snapshot: reads the records created or changed since from id.loc.gov (MARCXML, 2 requests/s, resumable; ~5 h)
uv run scripts/apply_geog_codes.py        # adds headings.geog_code to lcsh.sqlite (blank / i / | / n) from both files, see "Guardrails"
uv run scripts/export_rules_json.py       # docs/rules/*.json: the SHM sheets and lists for the web page's rule popups
uv run scripts/parse_free_floating.py     # SUBDIVISIONS.pdf text -> data/derived/free_floating_subdivisions.json
uv run scripts/parse_shm_index.py         # SHM-Index.pdf -> rules/index/shm_index.json
uv run scripts/lint_rules.py              # sanity-check rules/shm/*.md and rules/lists/*.json
```

## Usage

```bash
uv run lcsh-validate "Taxation--France--Paris"
uv run lcsh-validate "650 _0 \$a Tacos \$x History \$y 20th century"
uv run lcsh-validate --facts "Music--Canada--Toronto"       # deterministic report only, no API call
uv run lcsh-validate --batch headings.txt --out results.jsonl
uv run lcsh-validate -v --effort high "Joints--Biopsy"      # show tool calls; raise reasoning effort
uv run scripts/run_eval.py                                  # run tests/headings.jsonl and score
```

Input forms accepted: `A--B--C`, MARC `650 _0 $a A $x B $z C $y D $v E` (also `‡` delimiters,
with or without `$a`), MarcEdit `=650  \0$aA$xB`. Separator syntax is normalized before
validation and only noted, never judged: spaces around `--`, a spaced single hyphen ` - `,
em/en dashes and the U+2011 non-breaking hyphen pairs that id.loc.gov emits all become `--`.
Capitalization, spelling and qualifier punctuation are still judged.

Python API:

```python
from lcsh_validator.agent import Validator
v = Validator()                       # model="claude-haiku-5-5", effort="medium"
res = v.validate("Salmon--Diseases--Treatment")
res.verdict["verdict"], res.verdict["issues"], res.facts
```

## Web service (AWS Lambda) and web page (GitHub Pages)

The validator also runs as a container-image Lambda behind a public Function URL, with a static
page that calls it and shows the verdict, the elements, every issue with its rule citation, the
model's turns and tool calls (with the data each tool returned) and the deterministic facts.

```bash
echo 'ANTHROPIC_KEY=sk-ant-...' > .env            # the key the function will use (git-ignored)
./lambda/deploy.sh                                # build arm64 image, push to ECR, create/update role, function, URL
./lambda/deploy.sh --no-build                     # configuration / URL only
```

`lambda/deploy.sh` is idempotent. It writes the Function URL into `docs/config.js`, leaves the
function uncapped (set `LCSH_LAMBDA_CONCURRENCY` to add a reserved-concurrency cap; a cap makes
parallel batches fail with HTTP 429), and falls back to the existing `lambda_basic_execution` role when the AWS
user is not allowed to create roles (`LCSH_LAMBDA_ROLE` names any other existing role).
The image holds the package, `rules/` and `data/derived/{lcsh,rules,name_cache}.sqlite`; the two
writable SQLite files are copied to `/tmp` at cold start (`lambda/handler.py`).

API:

```bash
curl -s -X POST "$URL" -H 'content-type: application/json' -d '{"heading": "Music--Canada--Toronto", "effort": "medium"}'
curl -s "$URL?heading=Joints--Biopsy"              # GET works too
curl -s -X POST "$URL" -d '{"heading": "...", "facts_only": true}'   # deterministic facts, no model call
curl -s "$URL"                                     # health check; also warms the container
```

The response is `{heading, verdict, facts, transcript, turns, usage, cost, effort, model, elapsed}`
(`cost.usd` is estimated from the usage counters with the rates in `agent.PRICING`);
`transcript` holds `{"type": "text"}` entries for the model's intermediate text and
`{"type": "tool", tool, input, result, chars, secs}` entries for each tool call. Warm requests take
roughly 8–15 s; the first request on a fresh container can take up to a minute while Lambda pages in
the 350 MB image, which is why the page pings the health endpoint on load.

Web page: `docs/` is plain HTML/JS with no build step. `.github/workflows/pages.yml` publishes it
to GitHub Pages (https://thisismattmiller.github.io/lcsh-validator/) on every push to `main` that
touches `docs/`; the repository's Pages source is set to "GitHub Actions". To run it locally:
`cd docs && python3 -m http.server 8765` then open http://localhost:8765/. It accepts
`?heading=...` and `?lccn=...` in the URL. Every rule citation in a verdict (`H 1095 sec. E.3`,
`Appendix D`) is a hover target: `docs/rules.js` shows the cited sheet's title and the cited section's
text, or the list entry for the subdivision named in the citation (`H 1095 sec. F (--Directories ...)`
shows the --Directories usage statement), otherwise the sheet summary and its numbered validation
rules; a citation to a sheet that is not in the corpus says so. Click pins the popup, Esc closes it.
The sheets are served as static JSON from `docs/rules/` (one file per sheet plus `index.json`, 4.5 MB
in all), written by `uv run scripts/export_rules_json.py`; rerun it after editing `rules/`. The LCCN box resolves
`https://id.loc.gov/resources/instances/identifier/<lccn>` (following the `Location` redirect with
an RDF `Accept` header, because the `.html` landing page is served without CORS headers), loads the
instance's `.cbd.rdf`, lists every `bf:subject` on the Work with its MARC tag and scheme, and
validates all of them immediately. When several headings are queued, the first request runs alone so it
warms a container and writes the prompt cache; after 10 s (or when it finishes) the rest run in
parallel, up to 10 at a time, and the gate closes again after 5 idle minutes. The API URL can be
overridden with `?api=`.

### Feedback reports

Every result card has a "This validation is wrong" button. One click sends the report; a comment
box then appears and an optional comment updates the same stored object. The page posts the
heading, comment, the full validation response (verdict, facts, transcript, usage, cost)
and the page URL to a second, tiny Lambda (`lambda/feedback_handler.py`, deployed by
`lambda/deploy_feedback.sh`, URL kept in `docs/config.js` as `LCSH_FEEDBACK_URL`). The function
adds the caller's IP address and user agent and writes one object per report to
`s3://lcsh-validator-feedback-<account>/reports/YYYY/MM/DD/<timestamp>-<id>.json`. Write access is
granted to the `lambda_basic_execution` role by a bucket policy, so no IAM changes are needed.

```bash
aws s3 ls s3://lcsh-validator-feedback-323998827103/reports/ --recursive
aws s3 cp s3://lcsh-validator-feedback-323998827103/reports/2026/10/14/<file>.json - | jq .
```

## Real-world heading list (Marva dump)

`scripts/extract_marva_headings.py` streams the `resourcesProduction` collection out of a Marva
MongoDB backup and collects every subject on the latest version of each record:

```bash
tar -xzOf ~/Data/marva-records/080000.bfe2.tar.gz data/db/bkup/bfe2/resourcesProduction.bson \
  | uv run --with pymongo python -I scripts/extract_marva_headings.py data/derived/marva
```

Output in `data/derived/marva/` (git-ignored): `headings.jsonl` (one line per occurrence with a
MARC-style string rebuilt from the component marcKeys, scheme, tag, LCCN, record id, status),
`unique.tsv` (count, scheme, label), and `lcsh.txt` (every distinct LCSH / name-authority / untagged
label once, NFC-normalized, most used first; drop straight into `lcsh-validate --batch`).
Non-LCSH vocabularies (FAST, RVM, BISAC, MeSH, ...) are kept in the first two files only.

Sample runs: `scripts/report_sample.py OUT.md RESULTS.jsonl...` summarizes one run and lists every
non-valid heading; `scripts/flagged_list.py` merges all runs into `reports/flagged-headings.md` and
`.tsv` (later reruns of a heading replace earlier verdicts). Cost has been about $0.002 per heading at
medium effort with ten runners in parallel.

## Benchmarks (LC validation records)

The Marva samples measure self-consistency; these two sets measure correctness against LC's own decisions. Both are
drawn (seed 20261026) from the 77,506 *validation records* LC created in 2007-2010, strings LC confirmed as correctly
built from free-floating subdivisions (667 "Record generated for validation purposes").

- `tests/benchmarks/known_valid.tsv`: 1000 such strings, run against a copy of the database with their own records
  removed (`data/derived/lcsh_hidden.sqlite`: the rows, their FTS entries, components, variants and the pointers to them
  from other records), so the rule layer and the model have to rebuild each string from the lists. Every flag is a
  false positive.
- `tests/benchmarks/known_invalid.tsv`: 700 strings broken in a rule-specific way, with the rule each breaks: the main
  heading replaced by one of its UF variants; a pattern subdivision outside its category (`--Grammar` under a
  non-language); an unestablished period under a topic; a locality as its qualified heading form instead of the
  indirect chain; a cancelled heading replaced by another LCSH record; and a form subdivision before a topical one.

```bash
uv run scripts/build_benchmark.py                 # rebuilds both TSVs and the hidden DB copy
LCSH_DB=data/derived/lcsh_hidden.sqlite LCSH_STABILIZE=1 ... run known_valid.tsv (column 2) through the validator
LCSH_STABILIZE=1 ...                               run known_invalid.tsv (column 1) against the normal DB
uv run scripts/score_benchmark.py reports/benchmark.md VALID_RESULTS.jsonl... -- INVALID_RESULTS.jsonl...
```

Results on 2026-10-16 (`reports/benchmark.md`, $5.78): known-valid 962 valid, 35 questionable, 3 invalid (false-positive
rate 3.8%, hard 0.3%; the deterministic rule checks alone raise an error on 1 of the 1000). The three invalids are not
validator defects: `Education--Congo (Democratic Republic)` uses a name form the NAF has since replaced,
`Vocal music--To 1800` is not on the H 1160 period list, and `Gastrointestinal system--Cancer--Surgery` turns on how far
H 1150 note 3 reaches. The questionables are mostly the usage-statement doubt family at 0.5-0.6. Known-invalid, five
sound classes (580): 573 invalid, 7 questionable, 0 valid (recall 98.8%, 100% counting questionable). The sixth class,
a form subdivision before a topical one, is contested: in June 2026 LC created 180 (topical) records for 144 form
subdivisions ("Use as a topical subdivision under subjects", e.g. sh2026001146 Juvenile literature), so
`[topic]--Juvenile literature--History` also reads as topical--topical; the validator split 66 invalid / 39
questionable / 15 valid on it. Two caveats: the live subject label lookup still reaches a hidden record on id.loc.gov
(9 of 1000, 2 of them still flagged), and `--Congresses` / `--Periodicals` were dropped from the order class because
they have always had topical usages.

## Layout

```
subjects.madsrdf.xml.gz        LCSH MADS/RDF dump (521k records, one rdf:RDF per line)
data/raw/lcsh_marc2016/        LC MDSConnect 2016 subject authority MARC files (for the 008/06 codes; git-ignored)
data/raw/shm/*.pdf             313 SHM instruction sheets, appendices, glossary, index (loc.gov FreeSHM)
data/raw/lcsh/*.pdf            LCSH introduction, free-floating subdivisions intro + list (FreeLCSH)
data/text/                     PyMuPDF text extractions
data/derived/lcsh.sqlite       headings, variants, complex-string components, FTS index
data/derived/free_floating_subdivisions.json   4.7k entries parsed from SUBDIVISIONS.pdf
data/derived/name_cache.sqlite cache of id.loc.gov name-authority lookups
rules/FORMAT.md                spec for the LLM-friendly rule files
rules/shm/<sheet>.md           one file per sheet: YAML frontmatter, "Validation rules", "Full text"
rules/lists/<sheet>.json       structured subdivision lists (H 1095, H 1100-H 1145.5, pattern lists H 1147-H 1200, H 362, H 1917.5)
rules/index/shm_index.json     the SHM index as term -> sheets
lcsh_validator/parse.py        heading string / MARC parser
lcsh_validator/db.py           SQLite access + id.loc.gov name authority (781 forms) with cache
lcsh_validator/freefloating.py free-floating list + SHM list lookups
lcsh_validator/rules.py        rule retrieval: by sheet, by section, FTS search, SHM index
lcsh_validator/analysis.py     deterministic facts report
lcsh_validator/agent.py        Haiku 5.5 tool loop + verdict schema + guardrail pushback
lcsh_validator/audit.py        citation / list-membership / usage-clause checks on the verdict
lcsh_validator/cli.py          command line
scripts/extract_marva_headings.py  subject headings from a Marva MongoDB dump -> data/derived/marva/
lambda/handler.py              Lambda Function URL handler (POST {heading, effort} -> verdict + facts + transcript)
lambda/Dockerfile, deploy.sh   container image (public.ecr.aws/lambda/python:3.14, arm64) and idempotent AWS deploy
lambda/feedback_handler.py, deploy_feedback.sh   'report incorrect validation' Lambda -> one JSON per report in S3
docs/                          GitHub Pages front end (index.html, app.js, style.css, config.js = Function URL)
docs/rules.js, docs/rules/     rule-citation hover popups and the SHM sheets as JSON (scripts/export_rules_json.py)
tests/headings.jsonl           headings with expected verdicts (eval set)
tests/benchmarks/              known_valid.tsv / known_invalid.tsv from LC's validation records (see Benchmarks)
scripts/build_benchmark.py     known-valid / known-invalid sets from LC's validation records (+ hidden DB copy)
scripts/score_benchmark.py     false-positive rate and per-class recall -> reports/benchmark.md
```

## What the data can and cannot tell you

- The subjects dump holds every LCSH topical/geographic/genre heading, 200k established
  precoordinated strings with typed components, subdivision authority records (180/181/182/185
  with their usage notes and pattern-collection tags), UF variants, deprecated records with
  replacements, and scope/history notes.
- Jurisdictional place names (countries, states, cities), persons, corporate bodies and titles
  live in the *name* authority file, which is not local; they are fetched from id.loc.gov on
  demand (and cached). Their `781` field gives the authorized geographic-subdivision chain, which
  encodes H 830 practice (e.g. `Paris (France)` -> `France--Paris`, `Toronto (Ont.)` ->
  `Ontario--Toronto`). Offline runs (`--offline`) skip these lookups.
- Pattern-category membership (is *Salmon* an animal? is *Joints* an organ?) is inferred from
  the BT hierarchy and reported as hints; the model decides.
- Since 2025/2026 LC catalogers no longer assign form subdivisions (`$v`) and use LCGFT instead.
  The validator treats a correctly used form subdivision as valid LCSH and adds an LC-practice note.

## Status (2026-10-13)

`uv run scripts/run_eval.py` on the 61 headings in `tests/headings.jsonl`: 61/61 verdicts agree with
the expected ones at `--effort medium`. Typical run: 1–3 model turns, about 8 seconds and well under
a cent per heading (the 12k-token system prompt is prompt-cached; most calls read ~40k cached
tokens and write ~1.5k). Verdicts are schema-constrained via `output_config.format`, with a
repair pass if a response still fails to parse.

Two test expectations were corrected by the model during tuning and are worth knowing about:
`Shakespeare, William, 1564-1616--Biography` is valid because an established precoordinated
record exists, even though H 1110 steers away from it; and the H 362 example
`Rudolf, Lake, Region (Kenya and Ethiopia)` is now invalid because the lake heading was renamed
`Turkana, Lake (Kenya and Ethiopia)`.
