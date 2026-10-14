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
   (`valid` / `invalid` / `uncertain`) with per-element status, issues, rule citations,
   suggested corrections and LC-practice notes.

## Setup

```bash
uv sync                                   # Python 3.14, deps: pymupdf, lxml, anthropic, pyyaml
ant auth login                            # or: export ANTHROPIC_API_KEY=...
```

Data build (already done in this checkout; rerun if the sources change):

```bash
uv run scripts/extract_pdf_text.py        # data/raw/*.pdf -> data/text/*.txt
uv run scripts/build_lcsh_db.py           # subjects.madsrdf.xml.gz -> data/derived/lcsh.sqlite (~10 min, 360 MB)
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

Input forms accepted: `A--B--C` (also em/en dashes), MARC `650 _0 $a A $x B $z C $y D $v E`,
MarcEdit `=650  \0$aA$xB`.

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
`?heading=...` and `?lccn=...` in the URL. The LCCN box resolves
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

## Layout

```
subjects.madsrdf.xml.gz        LCSH MADS/RDF dump (521k records, one rdf:RDF per line)
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
lcsh_validator/agent.py        Haiku 5.5 tool loop + verdict schema
lcsh_validator/cli.py          command line
scripts/extract_marva_headings.py  subject headings from a Marva MongoDB dump -> data/derived/marva/
lambda/handler.py              Lambda Function URL handler (POST {heading, effort} -> verdict + facts + transcript)
lambda/Dockerfile, deploy.sh   container image (public.ecr.aws/lambda/python:3.14, arm64) and idempotent AWS deploy
lambda/feedback_handler.py, deploy_feedback.sh   'report incorrect validation' Lambda -> one JSON per report in S3
docs/                          GitHub Pages front end (index.html, app.js, style.css, config.js = Function URL)
tests/headings.jsonl           headings with expected verdicts (eval set)
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
