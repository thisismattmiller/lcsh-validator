# Rule file format for the LCSH validator

This directory holds the Library of Congress *Subject Headings Manual* (SHM) and the
*Introduction to LCSH* re-expressed in a form that is easy for a language model to
retrieve and apply when deciding whether a subject heading string is validly
constructed. Source text lives in `data/text/shm/*.txt` (PyMuPDF extraction of the
official PDFs, with `<<<PAGE n>>>` markers) and `data/text/lcsh/*.txt`.

Three kinds of output:

1. `rules/shm/<FILE>.md` — one Markdown file per instruction sheet (and per appendix,
   glossary, and LCSH intro). **Every sheet gets one of these.**
2. `rules/lists/<FILE>.json` — structured JSON for sheets whose main content is a *list*
   of subdivisions (H 1095, H 1100, H 1103, H 1105, H 1110, H 1120, H 1140, H 1145.5,
   and every pattern-heading list H 1147–H 1200) or a list of free-floating phrases
   (H 362) or a chart (H 1146 pattern-heading chart). Only sheets that contain such a
   list get one.
3. `rules/index/shm_index.json` — the SHM Index (SHM-Index) converted to JSON.

File stem rule: use the source stem exactly (`H1075`, `H1145_5`, `Appenda`, `Glossary`,
`LCSH-Main-intro`, `LCSH-FF-intro`).

## 1. Markdown sheet files: `rules/shm/<FILE>.md`

### Frontmatter (YAML, required keys in this order)

```yaml
---
id: "H 1075"                 # as printed, e.g. "H 1145.5", "Appendix B", "Glossary"
file: H1075                  # source stem
title: "Subdivisions"
revised: "2026-01"           # latest date in the sheet's revision history / header; "" if none
category: subdivision-general
validation_relevance: high
applies_to: [subdivision-order, form-subdivisions, chronological-subdivisions, geographic-subdivisions]
heading_types: [topical, geographic]
subdivisions_governed: ["--History", "--Periodicals"]
pattern_headings: []         # for pattern lists: the pattern heading(s), e.g. ["Fishes", "Cattle"]
pattern_category: ""         # for pattern lists: the category description, e.g. "individual animals and groups of animals"
related: ["H 1095", "H 830", "H 620"]
summary: >
  Two to five sentences stating what the sheet governs and the main rules a
  validator would need from it.
---
```

`category` is one of:
`general-principles` (H 180, H 80, etc.), `heading-construction` (H 285–H 362: form of
headings, qualifiers, plurals, inverted forms, phrases), `subdivision-general` (H 1075,
H 1090, H 1095 narrative parts, H 860, H 870), `free-floating-list` (H 1095 list, H 1100,
H 1103, H 1105, H 1110, H 1120, H 1140, H 1145.5), `pattern-heading-list` (H 1146–H 1200),
`geographic` (H 690–H 1055, H 830–H 836), `chronological` (H 620, H 1078),
`names-as-subjects` (H 405–H 475), `authority-procedures` (H 40, H 165, H 187–H 250,
H 364–H 400: proposals, references, scope notes, class numbers), `special-topic`
(H 1205–H 2400 instruction sheets about a particular subdivision or kind of material),
`appendix`, `glossary`, `introduction`, `index`.

`validation_relevance`: `high` if the sheet directly decides whether a *string* is well
formed (order, allowed subdivisions, punctuation, qualifiers, geographic chains, which
subdivision to use under which heading type); `medium` if it governs assignment choices
or special subdivisions that a validator would consult when that subdivision appears;
`low` if it is about internal LC procedure (proposals, workflow, authority record coding)
or history.

`applies_to`: short kebab-case tags. Reuse these where they fit: `subdivision-order`,
`form-subdivisions`, `topical-subdivisions`, `chronological-subdivisions`,
`geographic-subdivisions`, `indirect-subdivision`, `qualifiers`, `inverted-headings`,
`punctuation`, `capitalization`, `singular-plural`, `free-floating`, `pattern-headings`,
`multiples`, `names-as-subjects`, `name-authority`, `literature`, `music`, `art`,
`biography`, `history`, `law`, `religion`, `lc-practice-lcgft`.

`heading_types`: from `topical`, `geographic`, `personal-name`, `corporate-name`,
`family-name`, `uniform-title`, `class-of-persons`, `ethnic-group`, `language`,
`literature`, `music`, `all`.

`subdivisions_governed`: literal subdivision strings this sheet explains (with the
leading `--`), e.g. `["--Biography", "--Correspondence"]`. Empty list if none.

### Body

```
# H 1075 Subdivisions

## Validation rules

1. ... (H 1075 sec. C.4)
2. ...

## Full text

### A. Background
...
```

**Validation rules** — a numbered list of atomic, testable statements a validator
could apply to a heading string, distilled from the whole sheet. Each rule:

- states one thing, in the imperative or as a condition ("A form subdivision is the last
  element of the string, except ...");
- is **literal** where the sheet is literal: exact subdivision wording, exact punctuation
  (`--`, commas, parentheses, qualifier wording such as `(Fictitious character)`), exact
  order, exact exceptions and the lists of headings they apply to;
- ends with a citation in parentheses: `(H 830 sec. C.5.a)`. Use the sheet's own section
  labels; for old-template sheets use the numbered paragraphs, e.g. `(H 362 sec. 2)`;
- distinguishes general LCSH validity from **LC practice**. Where the sheet says LC
  catalogers no longer do something that remains valid LCSH for other institutions (the
  2025/2026 phase-out of form subdivisions in favor of LCGFT is the main case), write the
  rule as valid LCSH and add a separate rule tagged `[LC practice]`;
- include "do not" rules and conflicts (e.g. "do not use X under Y; use the established
  phrase heading Z instead").

Aim for completeness over brevity: a 10-page sheet may yield 20–40 rules; a one-page
sheet may yield 3. Do not invent rules that are not in the sheet.

**Full text** — the complete sheet re-expressed as clean Markdown. Requirements:

- Keep every rule, example, note, exception, table row, and endnote. Do not summarize
  or omit content. Drop only: running page headers/footers ("Subject Headings Manual |
  ... | Page n", "H 1234 Page n", "June 2013" footers), the `<<<PAGE n>>>` markers, the
  table of contents with dot leaders, and the "Revision history" section (put the latest
  date in `revised` instead).
- Re-join lines that were wrapped by the PDF; fix hyphenation splits; keep paragraphs.
- Section headings become `###` (A., B., C.1., 1., 2., etc.), keeping their labels.
- Examples (MARC fields such as `650 #0 $a Taxation $z California $z San Francisco.`)
  go in fenced code blocks, one field per line, **copied exactly** including `$a`/`$x`/
  `$y`/`$z`/`$v`, indicators, punctuation, and bracketed glosses such as
  `[not 650 #0 $a ...]`. Keep "Title:" lines and "LC practice:" labels inside the block.
- Tables (e.g. the H 830 "Heading / Subdivision usage" table, the H 1146 chart, the
  subdivision tables in H 1095) become Markdown tables.
- Heading and subdivision names that the PDF renders in italics (extracted as `*...*`)
  stay wrapped in `*...*`. Old-template sheets use `B` (a broken en-dash glyph) where
  `--` is meant, e.g. `BIn literature` means `--In literature`; fix those to `--`.
- Cross-references like "see H 1095" stay as plain text.

## 2. List files: `rules/lists/<FILE>.json`

```json
{
  "sheet": "H 1095",
  "title": "Free-floating Subdivisions",
  "kind": "general-free-floating",
  "scope": "Form and topical subdivisions of general application; one-line statement of which headings the list applies under",
  "pattern_headings": [],
  "pattern_category": "",
  "general_notes": ["Any notes/endnotes that apply to the list as a whole, verbatim"],
  "entries": [
    {
      "subdivision": "--Ability testing",
      "subfield": "x",
      "type": "topical",
      "may_subd_geog": true,
      "use_under": "topical headings for tests and testing of native aptitude or acquired proficiency in a particular topic",
      "notes": "Do not subdivide geographically under names of individual space vehicles.",
      "see_also": ["--Testing"],
      "consult": ["H 2186"],
      "endnote": ""
    }
  ]
}
```

- `kind`: `general-free-floating`, `classes-of-persons`, `ethnic-groups`,
  `corporate-bodies`, `names-of-persons`, `names-of-families`, `names-of-places`,
  `bodies-of-water`, `pattern`, `free-floating-phrases` (H 362), `pattern-chart` (H 1146).
- `subdivision`: with the leading `--`, exact wording and capitalization, including
  multi-level subdivisions such as `--Accidents--Investigation` and multiples such as
  `--Translations into French, [German, etc.]`.
- `subfield`: `x`, `v`, `y`, or `z` as given on the list. If the list gives a subdivision
  twice (once as `$x` topical and once as `$v` form), emit two entries.
- `type`: `topical`, `form`, `chronological`, `geographic`.
- `may_subd_geog`: true if the list marks it "(May Subd Geog)" / "Yes"; false otherwise.
- `use_under`: the usage statement, verbatim minus the leading "Use under".
- `notes`, `see_also`, `consult`, `endnote`: verbatim text; empty string / list if none.
- For H 362 phrase patterns, use `"pattern"` instead of `"subdivision"` (e.g.
  `"[name of city] Metropolitan Area ([geographic qualifier])"`) plus `"examples"` and
  `"exceptions"`.
- For H 1146's chart: entries of `{"category", "pattern_headings", "sheet"}`.

Every entry on the printed list must appear. Count them and state the count in your
report.

## 3. Index: `rules/index/shm_index.json`

`{"entries": [{"term": "Abbreviations", "sheets": ["H 1095", "Appendix A"], "note": ""}]}`
— one entry per index line; sub-entries become `"term": "Abbreviations -- in headings"`.
