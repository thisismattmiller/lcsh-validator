"""Turn-based validation agent: Claude Haiku 5.5 reasons over the deterministic facts and consults the rules via tools."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field

import anthropic

from .analysis import Analyzer
from .audit import CitationAuditor, audit_place_claims, audit_usage, pushback_message, scrub_unknown_sheets
from .db import LCSHDB
from .freefloating import FreeFloating
from .parse import parse_heading
from .rules import Rules

MODEL = "claude-haiku-5-5"

CORE_SHEETS = ["H 1075", "H 1095", "H 830", "H 1146", "H 620", "H 362", "Appendix D"]

SYSTEM_PROMPT = """You are an expert Library of Congress subject cataloger acting as a validator for Library of Congress Subject Headings (LCSH) subject heading strings. Your job: decide whether a supplied heading string is a validly constructed LCSH heading under the rules of the Subject Headings Manual (SHM) and the conventions of the LCSH authority file, and explain precisely why, citing instruction sheets (H numbers / appendices).

You are given, in the first user message, a FACTS report produced by deterministic lookups against the full LCSH authority file (MADS/RDF, 2026), LC's name authority file (id.loc.gov), LC's free-floating subdivisions list (April 2026) and the SHM lists. Treat the facts as ground truth about what is *established*; use your tools to read the governing rules before concluding.

A heading string is VALID when all of these hold:
1. The main heading is an authorized LCSH heading (150/151/155), an authorized name heading (LCNAF: 100/110/111/130/151 jurisdictions), a free-floating phrase heading constructed per H 362 / H 1917.5, or an established precoordinated string.
2. Every subdivision is either (a) established under that exact heading/prefix in the authority file, or (b) a free-floating subdivision whose usage statement authorizes it under this *type* of heading (H 1095 general; H 1100 classes of persons; H 1103 ethnic groups; H 1105 corporate bodies; H 1110 persons; H 1120 families; H 1140 places; H 1145.5 bodies of water; pattern lists H 1147–H 1200 for headings belonging to the pattern category), or (c) a geographic subdivision allowed because the preceding element is coded (May Subd Geog), in the authorized $z form (direct for countries/first-order divisions of Canada, Great Britain and the U.S.; otherwise indirect through the country/state/province; at most two levels; qualifiers deleted per H 830 sec. C.6), or (d) a chronological subdivision that is established under the heading or authorized as free-floating (century subdivisions under --History per H 620 / H 1647; period subdivisions after --Politics and government, --Economic conditions, etc. only when established).
3. The elements are in a prescribed order (H 1075 sec. D): [topic]--[place]--[topic]--[period]--[form] or [topic]--[topic]--[place]--[period]--[form] or [place]--[topic]--[period]--[form]; form subdivisions last; a subdivision may be further subdivided by place only if it is itself (May Subd Geog) (H 860).
4. No conflict with an established heading (phrase heading vs. subdivision form, UF references, deprecated/cancelled headings, H 1095 sec. E.2) and the subdivision is not already implied by the heading (H 1095 sec. E.3).
5. The literal form is right: exact wording and capitalization of the authorized forms, '--' between elements, parenthetical qualifiers and inverted forms as established, no terminal punctuation issues (Appendices B, C, D).

Element-separator syntax (spaces around '--', a spaced single hyphen, em/en dashes, non-breaking hyphens) is normalized to '--' BEFORE validation; when the facts carry a "Separator syntax normalized" note, mention it as severity "note" only and judge the normalized string. Other surface-form defects — wrong capitalization, misspellings, wrong qualifier punctuation, missing periods in 'etc.' — make the supplied string "invalid" (severity "error"), with the corrected form in normalized_string. A terminal period is NOT a defect (MARC strings end with one); never add one to normalized_string. Severity "warning" is for usage doubts that do not by themselves invalidate the string; "note" is informational.

Headings not found in any authority file may still be valid free-floating phrase headings: H 362 authorizes "[city] Metropolitan Area ([qualifier])", "[city] Region (...)", "[city] Suburban Area (...)", "[geographic feature or river] Region (...)" built on an established name (with an extra comma after an inverted base heading), and H 1917.5 authorizes music form headings with medium-of-performance qualifiers. When the facts report a "free_floating_phrase_candidate", verify the base heading and the pattern rather than rejecting the string for being unestablished. An established precoordinated string in the authority file (whole_string_established) is valid as established even if a free-floating list would not have authorized it.

Distinguish four outcomes:
- "valid": every criterion above holds.
- "invalid": reserve this for defects that the facts or the rule text establish outright: a surface-form defect; an element found nowhere (not in LCSH, not in LCNAF, not in any free-floating or pattern list, not established under the prefix); an explicit prohibition ("Do not use under ...", a scope note, a UF/see reference to a different form, a deprecated or cancelled heading, H 1095 sec. E.2/E.3 conflicts); a geographic chain that contradicts the authorized 781 subdivision form or H 830; a prescribed-order violation; a place following a subdivision that is not (May Subd Geog). Report these with severity "error".
- "questionable": every element is authorized somewhere and nothing explicitly forbids the combination, but no clause of the applicable usage statement names this heading's type, or the pattern-category membership is inferred rather than established, or the combination is unusual enough that a cataloger should check it. Report the doubt with severity "warning", never "error". A usage statement that names "topical headings" (or "subjects", "subjects of all types") covers any topical (150) heading, including headings for ethnic groups, classes of persons, organizations, activities, materials, etc., unless the governing special sheet or list explicitly excludes it: that is authorization, not a reason for doubt. Do not stretch an inference ("ethnic-group headings have their own list, so a general H 1095 subdivision is barred") into an "invalid".
- "uncertain": the string could be valid only under an interpretation you could not confirm with the tools (e.g. a name heading you could not verify).
Also distinguish general LCSH validity from current *LC practice*: since 2025/2026 LC catalogers do not assign form subdivisions ($v) and use LCGFT instead, but form subdivisions remain valid LCSH for other institutions — a string with a correctly used form subdivision is "valid" with an LC-practice note, not "invalid".

Method (turn by turn):
- Read the facts. Identify the heading type (topical, geographic/jurisdiction, personal/corporate name, uniform title, class of persons, ethnic group, pattern category member, etc.).
- For each subdivision decide which of (a)-(d) applies; when it is free-floating, confirm with lookup_subdivision / get_rule that the usage statement covers this heading type and read any "Do not use ..." restrictions; consult the special instruction sheet for that subdivision when one exists (sheets_for_subdivision / shm_index).
- Read every usage statement to its end before judging it. Usage statements list several types of headings joined by "and under ..."; a heading is covered if ANY clause names its type, and the last clause is often the general one ("... and topical headings for individual directories ..."). The facts give each free-floating subdivision a "usage_coverage" block: when its "general_clause" is set, the statement names this heading's type and the usage is satisfied on that clause (check only the entry's notes and the governing special sheet for an explicit exclusion); when it is null, the statement names specific categories only, and your issue must quote the clause you tested the heading against. Never write "the usage statement names X, not topical headings" without having read the whole statement.
- Write for a cataloger: refer to "the usage statement", "the facts" or "the authority record", never to the facts' field names (general_clause, usage_coverage, whole_string_established).
- Cite only instruction sheets that exist and that you have read in this session (get_rule, search_rules, the facts, or the core rules above). A citation to a sheet that does not exist, or of a subdivision to a list it is not on, is sent back to you for correction, and anything left is struck from the verdict.
- The facts' "rule_checks" are explicit prohibitions tested mechanically (H 1647 sec. 9; H 1647 sec. 2.b century subdivisions that overlap established periods; H 1642; H 1095 sec. E.2; H 1100 sec. D). Report each error-level rule check as an error-severity issue citing that rule, unless "whole_string_established" shows LC established the exact string; never call the string valid while silently ignoring one.
- For subdivisions restricted to persons in the fine arts, literature, music or performing arts (--Criticism and interpretation, --Appreciation, --Catalogs raisonnés, --Fictional works, --Themes, motives), decide from the name record's "occupation", "field_of_activity", "entity_type" and "sources_670" in the facts; if the record carries none of these, say the occupation is unrecorded and use "questionable", never "valid".
- When the facts report "merged_main_heading", the authorized name itself contains '--' (e.g. Bà Rịa--Vũng Tàu (Vietnam)); validate the string with that merged heading as the main heading and do not treat the split as an error.
- Under Music and musical-composition headings (H 1160) the fixed chronological subdivisions (--To 500, --500-1400, --16th century ... --21st century) are free-floating and follow the geographic subdivision (H 1160 order: place, period, topic, form): Music--France--18th century--History and criticism.
- A name-title heading for a work ("Canetti, Elias, 1905-1994. Masse und Macht") is valid when LCNAF holds the work only as language-qualified expressions ("... Masse und Macht. English"): those records are built on exactly that work heading, so the unqualified form is confirmed, not uncertain.
- [place]--Relations--[place] (H 1996) is a valid string in its own right; whether a particular work would instead take --Foreign relations is an assignment question. Never report it as "questionable" on that ground.
- A name heading found in LCNAF is usable as a subject (H 430) unless the record itself says otherwise; do not doubt a string because the facts omit 008 coding values.
- A rule check that lists "established_strings_using_this_subdivision" (LC itself established e.g. Intellectuals--Interviews) is a note: LC practice settles the usage, so the string is "valid" on that point, not "questionable".
- H 955 sec. 1 bars --History and --Politics and government only under England itself as the main heading (use Great Britain--History); as a geographic subdivision England follows the topic directly and may be followed by --History (H 955 sec. 2.b; Theater--Great Britain--History; 158 established [topic]--England--History strings). Never fault [topic]--England--History on H 955.
- A geographic heading (151) takes the place-only subdivisions (--In literature, --In art, --On television, --In motion pictures ...) whatever kind of place it is: LC established Moon--In literature, Sun--In literature and 85 [place]--In literature strings, so Outer space--In literature or Antarctica--On television is a valid construction, not a doubt; H 1140's exclusion of celestial bodies concerns the H 1140 list, not these H 1095 phrase subdivisions.
- A main heading reported under "lcsh_untraced_reference" is not a heading at all (an untraced-reference record): the string is "invalid"; suggest the headings its notes point to.
- A deprecated record whose "deletion_note" says it was redistributed as a juvenile ("sj") heading is a Children's and Young Adults' (CYAC) heading, usable only in a 6XX with second indicator 1, not in LCSH proper: report "questionable" and say so.
- A string that consists solely of an authorized LCNAF name (no subdivisions) is "valid": whether a given work is about that person, and how thinly the record is documented, are assignment matters, not defects of the string.
- A personal, family or corporate name, place name, or work title that is not found in LCNAF (and is not a variant of a record that was found) is "uncertain", not "invalid": the file is not complete and the name may be newly established; report "invalid" only when its form breaks Appendix D / RDA conventions (missing comma before dates, wrong punctuation) or the dateless/qualified candidate in the facts shows the supplied dates or qualifier are wrong.
- Restrictions that depend on the work being cataloged, not on the string — H 1023 (Soviet Union only for works limited to 1917-1991), H 1996/H 1629 (--Relations vs. --Foreign relations, both are authorized), H 1430 setting provisions, scope notes about what a work must cover — are assignment advice: mention them as severity "note" and do not downgrade an otherwise valid string to "questionable" for them.
- A place used as the main heading keeps its full authorized name with qualifier (Naranja de Tapia (Michoacán de Ocampo, Mexico)); indirect subdivision through the country (H 830) applies only when the place is a $z subdivision.
- A geographic subdivision needs no free-floating list entry: any authorized place or region (America, Europe, Mediterranean Region) may follow an element coded (May Subd Geog) in its authorized $z form.
- may_subd_geog on an established string is three-valued: true = coded (May Subd Geog); false = LC coded it 'not subdivided geographically' (008/06 blank), or it is a single-element heading without the coding; null = LC never evaluated the string (008/06 '|', as on the 2008-2010 validation records), so the free-floating coding of its last subdivision governs. Never read null as a bar. A country followed by a locality (Brazil--Rio Grande do Sul (State); Poland--Warsaw) is one indirect place; a record for [string]--[country] never bars the locality.
- A part of the Bible is formulated, not established: Bible. [Book as in the NAF], [chapter(s) in Roman numerals], [verses in Arabic] (Bible. Mark, XVI, 1-8; Bible. Genesis, IX, 18-29; Bible. Exodus, XIX-XXXVI; Bible. Romans, XII) follows RDA 6.23.2.9.5 and the LC-PCC policy statement and needs no authority record of its own. Judge its form (comma after the book, Roman chapter, Arabic verses: 'Bible. Luke, 1: 26-38' and 'Bible. Samuel 1st' are defects), not its absence from the file, and the H 1188 sacred-works subdivisions (--Criticism, interpretation, etc.; --Sermons; --Commentaries) are free-floating under such parts.
- Usage statements that say "under subjects" (--Congresses, --Bibliography, --Periodicals, --Indexes, ...) cover every kind of heading used as a subject, including names of persons and corporate bodies.
- A string supplied without subfield coding is not "questionable" merely because an element could be read as $x or as $v (Karnataka (India)--Folklore, Sign language--Textbooks): if either reading is authorized the string is valid; say which coding each reading takes in the notes.
- A topical heading stays a topical heading after geographic subdivision: a usage statement naming "topical headings" covers [topic]--[place]--[subdivision] (e.g. Justice, Administration of--China, Northwest--History--To 1500), and one naming "classes of persons" covers [class]--[place]--[subdivision]. Do not treat "reached through a place subdivision" as a reason for doubt.
- H 1629: [place 1]--Foreign relations--[place 2] is used for relations between two countries or two regions, and a region made up of several countries (Balkan Peninsula, South Asia, Persian Gulf States) is a valid [place 2]; only relations with three or more separately named countries take the unsubdivided --Foreign relations.
- Some free-floating list entries are strings of two or three subdivisions (e.g. "--History--To 1500", "--Study and teaching--Audio-visual aids", "--Law and legislation--Compliance costs"). The facts report these under "free_floating_strings" and mark each covered element with "part_of_free_floating_string"; judge the run by that entry's usage statement, not by the usage statements of its individual elements.
- --Fiction, --Drama, --Poetry, --Juvenile fiction, --Comic books, strips, etc., --Humor and --Anecdotes are form subdivisions whose usage statements end "...and under topical headings for collections of [stories/plays/poems/...] on those subjects": that clause authorizes them under any topical heading (H 1790, H 1780), e.g. Drugs--Overdose--Fiction and Investigations--Fiction are valid.
- When a run of subdivisions matches a multi-element list entry whose usage is narrower than the heading at hand (e.g. "Biography--Anecdotes" listed under places), also test the elements one by one: --Anecdotes is free-floating under classes of persons on its own, so Architects--...--Biography--Anecdotes is not barred by the pair entry.
- List entries written as multiples, e.g. "--Paraphrases, English, [French, German, etc.]" or "--Films for French, [Spanish, etc.] speakers", authorize any language, name or term in that slot; "--Paraphrases, French" is therefore on the list. When a lookup reports "matched_pattern", treat the string as that list entry.
- For geographic subdivisions, verify the chain against the authorized subdivision form (781) reported in the facts and H 830.
- When something is not found, use search_headings / established_under to find what *is* established and suggest the correct form.
- Do not guess rule content from memory when a tool can show it; cite the sheet and section you relied on. Keep tool calls purposeful (typically 3–10 calls).

When done, reply with ONLY a JSON object (no prose before or after) with this shape:
{
  "verdict": "valid" | "invalid" | "questionable" | "uncertain",
  "confidence": 0.0-1.0,
  "normalized_string": "the heading as it should be written if valid (or best correction), elements joined by -- with no terminal period",
  "heading_type": "short description",
  "elements": [ {"element": "...", "role": "main|topical|geographic|chronological|form", "status": "authorized|established-under-prefix|free-floating|name-authority|invalid|uncertain", "basis": "one sentence with citation"} ],
  "issues": [ {"element": "...", "severity": "error|warning|note", "problem": "...", "rule": "H nnnn sec. X", "fix": "..."} ],
  "lc_practice_notes": ["..."],
  "suggested_alternatives": ["..."],
  "explanation": "3-8 sentences for a cataloger, citing sheets"
}
"""


VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["valid", "invalid", "questionable", "uncertain"]},
        "confidence": {"type": "number"},
        "normalized_string": {"type": "string"},
        "heading_type": {"type": "string"},
        "elements": {"type": "array", "items": {"type": "object", "properties": {
            "element": {"type": "string"}, "role": {"type": "string"}, "status": {"type": "string"}, "basis": {"type": "string"}},
            "required": ["element", "role", "status", "basis"], "additionalProperties": False}},
        "issues": {"type": "array", "items": {"type": "object", "properties": {
            "element": {"type": "string"}, "severity": {"type": "string", "enum": ["error", "warning", "note"]},
            "problem": {"type": "string"}, "rule": {"type": "string"}, "fix": {"type": "string"}},
            "required": ["element", "severity", "problem", "rule", "fix"], "additionalProperties": False}},
        "lc_practice_notes": {"type": "array", "items": {"type": "string"}},
        "suggested_alternatives": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
    },
    "required": ["verdict", "confidence", "normalized_string", "heading_type", "elements", "issues", "lc_practice_notes", "suggested_alternatives", "explanation"],
    "additionalProperties": False,
}


# USD per million tokens: (input, 5-minute cache write, cache read, output). Prompts here are well
# under the 100k-token tier boundary. Source: platform.claude.com/docs/en/about-claude/pricing (2026-10).
PRICING = {
    "claude-haiku-5-5": (0.10, 0.125, 0.01, 0.50),
    "claude-haiku-4-5": (1.00, 1.25, 0.10, 5.00),
    "claude-sonnet-5-5": (3.00, 3.75, 0.30, 15.00),
    "claude-opus-5-5": (5.00, 6.25, 0.50, 25.00),
}


def estimate_cost(usage: dict, model: str) -> dict | None:
    """Cost of one validation in USD from the summed usage counters; None for an unknown model."""
    rates = next((r for k, r in PRICING.items() if model.startswith(k)), None)
    if not rates:
        return None
    parts = {
        "input": usage.get("input_tokens", 0) * rates[0] / 1e6,
        "cache_write": usage.get("cache_creation_input_tokens", 0) * rates[1] / 1e6,
        "cache_read": usage.get("cache_read_input_tokens", 0) * rates[2] / 1e6,
        "output": usage.get("output_tokens", 0) * rates[3] / 1e6,
    }
    return {"usd": round(sum(parts.values()), 6), "breakdown": {k: round(v, 6) for k, v in parts.items()},
            "model": model, "rates_per_mtok": {"input": rates[0], "cache_write": rates[1], "cache_read": rates[2], "output": rates[3]}}


@dataclass
class ValidationResult:
    heading: str
    verdict: dict
    facts: dict
    transcript: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    turns: int = 0
    model: str = MODEL

    @property
    def cost(self) -> dict | None:
        return estimate_cost(self.usage, self.model)

    def tools_used(self) -> list[str]:
        return [t["tool"] for t in self.transcript if t.get("type") == "tool"]

    def to_dict(self):
        return {"heading": self.heading, "verdict": self.verdict, "turns": self.turns, "usage": self.usage}

    def full_dict(self):
        """Everything, for the web UI: verdict, facts, transcript (model text + tool calls/results), usage."""
        return {"heading": self.heading, "verdict": self.verdict, "facts": self.facts, "transcript": self.transcript,
                "turns": self.turns, "usage": self.usage, "cost": self.cost}


class Validator:
    def __init__(self, db: LCSHDB | None = None, ff: FreeFloating | None = None, rules: Rules | None = None,
                 model: str = MODEL, effort: str = "medium", max_turns: int = 20, verbose: bool = False, client=None):
        self.db = db or LCSHDB()
        self.ff = ff or FreeFloating()
        self.rules = rules or Rules()
        self.analyzer = Analyzer(self.db, self.ff)
        self.model = model
        self.effort = effort
        self.max_turns = max_turns
        self.verbose = verbose
        self.transcript_result_chars = 20000  # how much of each tool result to keep in the transcript
        self.client = client or anthropic.Anthropic()
        self._system = None
        self.auditor = CitationAuditor(self.rules, self.ff)
        self.pushback_rounds = int(os.environ.get("LCSH_PUSHBACK_ROUNDS", "1"))

    # ------------------------------------------------------------------ prompt assembly
    def system_blocks(self) -> list[dict]:
        if self._system is None:
            core = []
            for sh in CORE_SHEETS:
                vr = self.rules.validation_rules(sh)
                if vr:
                    core.append(f"### {sh} — {self.rules.get(sh)['title']}\n{vr}")
            toc = "\n".join(f"- {t['sheet']}: {t['title']} [{t['relevance']}]" for t in self.rules.toc() if t["relevance"] in ("high", "medium"))
            text = SYSTEM_PROMPT + "\n\n# Core validation rules (distilled from the SHM; read the full sheets with get_rule when needed)\n\n" + "\n\n".join(core)
            text += "\n\n# Instruction sheets available via get_rule (relevance high/medium)\n" + toc
            self._system = [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
        return self._system

    # ------------------------------------------------------------------ tools
    def tool_defs(self) -> list[dict]:
        return [
            {"name": "lookup_heading", "description": "Look up a heading string in the LCSH authority file (exact label, UF/variant references, deprecated records with their replacements), the LC name authority file, plus category hints from the BT hierarchy and a sample of established strings under it.",
             "input_schema": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}},
            {"name": "search_headings", "description": "Full-text search of LCSH authorized labels for candidates when an exact lookup fails (returns up to 10 with kind and May-Subd-Geog flag).",
             "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}},
            {"name": "established_under", "description": "List the next elements that are established in the authority file directly under a heading or prefix, e.g. 'United States--History' -> the established period subdivisions. Use to see which subdivisions/periods exist under a heading.",
             "input_schema": {"type": "object", "properties": {"prefix": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["prefix"]}},
            {"name": "lookup_subdivision", "description": "Everything known about a subdivision string: free-floating list entry (types, controlling SHM sheets, usage statement, May Subd Geog, UF/BT/NT), the LCSH subdivision authority records (180/181/182/185 with pattern collections), the SHM list entries that mention it, and which special instruction sheets govern it.",
             "input_schema": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]}},
            {"name": "lookup_place", "description": "Resolve a place name: LCSH geographic heading (151) and/or LC name authority jurisdiction, with its authorized geographic subdivision form (781 $z chain). Pass `context` (the $z elements given before it) to disambiguate bare names like 'Buffalo'.",
             "input_schema": {"type": "object", "properties": {"label": {"type": "string"}, "context": {"type": "array", "items": {"type": "string"}}}, "required": ["label"]}},
            {"name": "get_rule", "description": "Read an SHM instruction sheet (or appendix / LCSH introduction) in its LLM-friendly form. Optionally restrict to a section (e.g. 'Validation rules', 'C.5', 'Full text').",
             "input_schema": {"type": "object", "properties": {"sheet": {"type": "string", "description": "e.g. 'H 1095', 'H 1145.5', 'Appendix B', 'LCSH-Main-intro'"}, "section": {"type": "string"}}, "required": ["sheet"]}},
            {"name": "search_rules", "description": "Full-text search across all SHM sheets; returns matching sections with sheet numbers.",
             "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}},
            {"name": "shm_index", "description": "Look a term up in the SHM's own index to find which sheets discuss it (e.g. 'Biography', 'Dictionaries', 'Metropolitan areas').",
             "input_schema": {"type": "object", "properties": {"term": {"type": "string"}}, "required": ["term"]}},
            {"name": "sheets_for_subdivision", "description": "Which instruction sheets specifically govern a given subdivision (from each sheet's subdivisions_governed metadata).",
             "input_schema": {"type": "object", "properties": {"subdivision": {"type": "string"}}, "required": ["subdivision"]}},
            {"name": "pattern_list", "description": "The free-floating subdivisions controlled by a pattern heading sheet (e.g. 'H 1147' animals), from the SHM list and from the subdivision authority records tagged for that pattern. Large; use `filter` to restrict to entries containing a word.",
             "input_schema": {"type": "object", "properties": {"sheet": {"type": "string"}, "filter": {"type": "string"}}, "required": ["sheet"]}},
            {"name": "broader_terms", "description": "BT ancestor chains for an LCSH heading id or label (to judge pattern-category membership, e.g. is X an animal / a language / a disease).",
             "input_schema": {"type": "object", "properties": {"heading": {"type": "string"}}, "required": ["heading"]}},
        ]

    def run_tool(self, name: str, inp: dict):
        db, ff, rules, an = self.db, self.ff, self.rules, self.analyzer
        if name == "lookup_heading":
            return an.main_heading(inp["label"], None)
        if name == "search_headings":
            return [{"label": h["label"], "kind": h["kind_label"], "may_subd_geog": h["may_subd_geog"], "scope_note": h["scope_note"]} for h in db.search(inp["query"], limit=inp.get("limit", 10))]
        if name == "established_under":
            return db.established_under(inp["prefix"], limit=inp.get("limit", 80))
        if name == "lookup_subdivision":
            r = ff.lookup(inp["label"])
            r["lcsh_subdivision_records"] = [{"label": h["label"], "tag": h["tag"], "may_subd_geog": h["may_subd_geog"], "note": h["scope_note"], "pattern_collections": [c for c in h["collections"] if "Pattern" in c], "example_note": h["example_note"]} for h in db.lookup_exact(inp["label"], subdivisions=True)]
            r["governing_sheets"] = rules.sheets_for_subdivision(inp["label"])
            r["shm_index"] = rules.index_lookup(inp["label"].lstrip("-"), limit=6)
            return r
        if name == "lookup_place":
            return an.resolve_place(inp["label"], inp.get("context") or [])
        if name == "get_rule":
            r = rules.get(inp["sheet"], inp.get("section"), max_chars=30000)
            return r or {"error": f"no sheet {inp['sheet']!r}; use the toc in the system prompt"}
        if name == "search_rules":
            return rules.search(inp["query"], limit=inp.get("limit", 6))
        if name == "shm_index":
            return rules.index_lookup(inp["term"])
        if name == "sheets_for_subdivision":
            return rules.sheets_for_subdivision(inp["subdivision"])
        if name == "pattern_list":
            sheet = inp["sheet"]
            d = ff.sheet_entries(sheet) or {}
            entries = d.get("entries", [])
            recs = db.pattern_subdivisions(sheet)
            flt = (inp.get("filter") or "").lower()
            if flt:
                entries = [e for e in entries if flt in json.dumps(e).lower()]
                recs = [r for r in recs if flt in json.dumps(r).lower()]
            return {"sheet": sheet, "pattern_headings": d.get("pattern_headings"), "pattern_category": d.get("pattern_category"), "general_notes": d.get("general_notes"),
                    "shm_list_entries": entries[:150], "authority_record_subdivisions": recs[:150]}
        if name == "broader_terms":
            h = inp["heading"]
            hid = h if re.match(r"^sh\d+", h) else next((x["id"] for x in db.lookup_exact(h) if x["authorized"]), None)
            if not hid:
                return {"error": "heading not found"}
            return {"id": hid, "label": db.label_of(hid), "paths": [" > ".join(p) for p in db.broader_chain(hid)], "category_hints": db.category_hints(hid)}
        return {"error": f"unknown tool {name}"}

    # ------------------------------------------------------------------ API call
    _structured_ok: bool | None = None

    def _create(self, messages):
        """messages.create with the verdict schema enforced when the API allows it alongside tools; otherwise plain."""
        base = dict(model=self.model, max_tokens=8000, system=self.system_blocks(), tools=self.tool_defs(), messages=messages)
        if self._structured_ok is not False:
            try:
                resp = self.client.messages.create(**base, output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": VERDICT_SCHEMA}})
                self._structured_ok = True
                return resp
            except anthropic.BadRequestError as e:
                if self.verbose:
                    print(f"  [structured output unavailable with tools: {e.message[:120]}]", file=sys.stderr)
                self._structured_ok = False
        return self.client.messages.create(**base, output_config={"effort": self.effort})

    # ------------------------------------------------------------------ loop
    def validate(self, heading: str, stabilize: bool | None = None, _second_pass: bool = False) -> ValidationResult:
        parsed = parse_heading(heading)
        facts = self.analyzer.analyze(parsed)
        # point the model at the special instruction sheets that govern each subdivision
        for sub in facts.get("subdivisions", []):
            gov = self.rules.sheets_for_subdivision(sub["text"])
            idx = [e for e in self.rules.index_lookup(sub["text"], limit=4) if e.get("sheets")]
            if gov or idx:
                sub["governing_sheets"] = {"from_sheet_metadata": gov, "from_shm_index": idx}
        user = ("Validate this LCSH subject heading string.\n\nHEADING: " + heading +
                "\n\nFACTS (deterministic lookups):\n```json\n" + json.dumps(facts, ensure_ascii=False, default=str) + "\n```")
        messages = [{"role": "user", "content": user}]
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        transcript = []
        final_text, turns = self._loop(messages, usage, transcript, 0, self.max_turns)
        verdict = _extract_json(final_text)
        verdict = self._repair_json(verdict, messages, usage)
        # guardrails: rules that do not exist, subdivisions cited to the wrong list, usage clauses read only in part
        problems = self.auditor.audit(verdict) + audit_usage(verdict, facts) + audit_place_claims(verdict, facts)
        rounds = 0
        if problems:
            verdict["guardrails"] = {"pushback": problems}
        while problems and rounds < self.pushback_rounds and not verdict.get("parse_error"):
            rounds += 1
            messages.append({"role": "user", "content": pushback_message(problems)})
            transcript.append({"type": "text", "turn": turns, "text": "[guardrail pushback]\n" + pushback_message(problems), "final": False})
            text2, turns = self._loop(messages, usage, transcript, turns, turns + 8)
            v2 = self._repair_json(_extract_json(text2), messages, usage)
            if v2.get("parse_error"):
                break
            v2["guardrails"] = verdict["guardrails"]
            verdict = v2
            problems = self.auditor.audit(verdict) + audit_usage(verdict, facts) + audit_place_claims(verdict, facts)
        if "guardrails" in verdict:
            verdict["guardrails"]["rounds"] = rounds
            verdict["guardrails"]["unresolved"] = problems
            removed = scrub_unknown_sheets(verdict, problems)
            if removed:
                verdict["guardrails"]["citations_removed"] = removed
            kinds = sorted({p["kind"] for p in verdict["guardrails"]["pushback"]})
            verdict["verdict_note"] = (f"guardrail pushback on {', '.join(kinds)}" + (f"; unresolved: {len(problems)}" if problems else "; resolved")
                                       + (f"; citations removed: {', '.join(removed)}" if removed else ""))
        verdict = _reconcile(verdict, facts)
        result = ValidationResult(heading=heading, verdict=verdict, facts=facts, transcript=transcript, usage=usage, turns=turns, model=self.model)
        return self._stabilize(result, heading, facts, stabilize, _second_pass)

    def _loop(self, messages: list, usage: dict, transcript: list, turns: int, max_turns: int) -> tuple[str, int]:
        """Run the tool-use loop until the model answers without tool calls; returns (final text, turns)."""
        final_text = ""
        while turns < max_turns:
            turns += 1
            resp = self._create(messages)
            for k in usage:
                usage[k] += getattr(resp.usage, k, 0) or 0
            if resp.stop_reason == "refusal":
                final_text = json.dumps({"verdict": "uncertain", "confidence": 0, "explanation": "model refused"})
                break
            messages.append({"role": "assistant", "content": resp.content})
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            texts = [b.text for b in resp.content if b.type == "text"]
            if texts:
                final_text = "\n".join(texts)
                transcript.append({"type": "text", "turn": turns, "text": final_text, "final": not tool_uses})
            if not tool_uses:
                break
            results = []
            for tu in tool_uses:
                t0 = time.time()
                try:
                    out = self.run_tool(tu.name, tu.input)
                    content = json.dumps(out, ensure_ascii=False, default=str)
                    is_error = False
                except Exception as e:  # noqa: BLE001
                    content = f"tool error: {e}"
                    is_error = True
                if len(content) > 60000:
                    content = content[:60000] + "\n[truncated]"
                transcript.append({"type": "tool", "turn": turns, "tool": tu.name, "input": tu.input, "chars": len(content),
                                   "secs": round(time.time() - t0, 2), "is_error": is_error,
                                   "result": content[:self.transcript_result_chars], "truncated": len(content) > self.transcript_result_chars})
                if self.verbose:
                    print(f"  [turn {turns}] {tu.name}({json.dumps(tu.input, ensure_ascii=False)}) -> {len(content)} chars", file=sys.stderr)
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": content, "is_error": is_error})
            messages.append({"role": "user", "content": results})
        return final_text, turns

    def _repair_json(self, verdict: dict, messages: list, usage: dict) -> dict:
        if verdict.get("parse_error"):
            # repair pass: ask for the JSON object alone, schema-constrained
            try:
                rep = self.client.messages.create(
                    model=self.model, max_tokens=6000, system=self.system_blocks(),
                    messages=messages + [{"role": "user", "content": "Your previous reply was not valid JSON. Return the same verdict as a single JSON object matching the required shape, nothing else."}],
                    output_config={"effort": "low", "format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
                )
                for k in usage:
                    usage[k] += getattr(rep.usage, k, 0) or 0
                verdict = _extract_json("\n".join(b.text for b in rep.content if b.type == "text"))
            except anthropic.APIError as e:  # noqa: BLE001
                verdict["repair_error"] = str(e)
        return verdict

    def _stabilize(self, result: "ValidationResult", heading: str, facts: dict, stabilize: bool | None, _second_pass: bool) -> "ValidationResult":
        verdict = result.verdict
        if stabilize is None:
            stabilize = os.environ.get("LCSH_STABILIZE", "") not in ("", "0", "false")
        rule_errors = [c for c in (facts.get("rule_checks") or []) if c.get("severity") == "error"] if not facts.get("whole_string_established") else []
        backed = verdict.get("verdict") == "invalid" and any(
            _cites(c["rule"], (i or {}).get("rule", "")) for c in rule_errors for i in (verdict.get("issues") or []) if (i or {}).get("severity") == "error")
        if backed:
            verdict["verdict_note"] = "invalid on a deterministic rule check; no second pass needed"
        if stabilize and not _second_pass and not backed and verdict.get("verdict") in ("valid", "invalid") and float(verdict.get("confidence") or 0) < STABILIZE_BELOW:
            # borderline: a second independent pass must agree, otherwise the heading needs a human
            again = self.validate(heading, stabilize=False, _second_pass=True)
            for k in result.usage:
                result.usage[k] += again.usage.get(k, 0)
            result.turns += again.turns
            result.transcript.append({"type": "text", "turn": result.turns, "text": "[second pass]\n" + json.dumps(again.verdict, ensure_ascii=False), "final": True})
            if again.verdict.get("verdict") != verdict.get("verdict") and rule_errors and "invalid" in (verdict.get("verdict"), again.verdict.get("verdict")):
                # one pass applied the mechanical check and the other did not: the check wins
                inv = verdict if verdict.get("verdict") == "invalid" else again.verdict
                verdict["second_pass"] = {k: again.verdict.get(k) for k in ("verdict", "confidence", "explanation", "issues")}
                verdict.update({k: inv.get(k) for k in ("verdict", "confidence", "issues", "explanation", "normalized_string") if k in inv})
                verdict["verdict_note"] = (f"two independent passes disagreed ('{verdict['verdict']}' vs '{again.verdict.get('verdict')}'); the facts carry an error-level rule check "
                                           f"({', '.join(c['rule'] for c in rule_errors)}), so the 'invalid' pass is reported")
            elif again.verdict.get("verdict") != verdict.get("verdict"):
                verdict["verdict_note"] = (f"two independent passes disagreed ('{verdict['verdict']}' at {verdict.get('confidence')} vs '{again.verdict.get('verdict')}' at {again.verdict.get('confidence')}); "
                                           "reported as questionable")
                verdict["second_pass"] = {k: again.verdict.get(k) for k in ("verdict", "confidence", "explanation", "issues")}
                verdict["verdict"] = "questionable"
                verdict["confidence"] = min(float(verdict.get("confidence") or 0), float(again.verdict.get("confidence") or 0))
            else:
                verdict["verdict_note"] = f"confirmed by a second independent pass ({again.verdict.get('confidence')})"
        return result


def _extract_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    cand = m.group(1) if m else text
    start = cand.find("{")
    end = cand.rfind("}")
    if start >= 0 and end > start:
        cand = cand[start:end + 1]
    for attempt in (cand, _fix_escapes(cand)):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue
    return {"verdict": "uncertain", "confidence": 0.0, "explanation": text, "parse_error": True}


def _fix_escapes(s: str) -> str:
    r"""Models sometimes write \$ or other invalid escapes inside JSON strings; drop the backslash of any invalid escape."""
    return re.sub(r"\\(?![\"\\/bfnrtu])", "", s)


STABILIZE_BELOW = float(os.environ.get("LCSH_STABILIZE_BELOW", "0.8"))


def _cites(check_rule: str, issue_rule: str) -> bool:
    """Does an issue's rule citation name any sheet of a rule check ('H 373; H 1095 sec. E.2' vs 'H 1095 sec. E.2; H 373 (UF references)')?"""
    sheets = set(re.findall(r"H \d+(?:\.\d+)?", check_rule))
    return bool(sheets & set(re.findall(r"H \d+(?:\.\d+)?", issue_rule or "")))


def _reconcile(verdict: dict, facts: dict | None = None) -> dict:
    """Keep the verdict consistent with the issues: any severity-'error' issue means the string as supplied is not valid.
    A deterministic rule check the model ignored keeps the string from being called plain 'valid'."""
    issues = verdict.get("issues") or []
    checks = [c for c in (facts or {}).get("rule_checks") or [] if c.get("severity") == "error"]
    if checks and verdict.get("verdict") == "valid" and not (facts or {}).get("whole_string_established"):
        cited = {str((i or {}).get("rule", "")) for i in issues}
        missed = [c for c in checks if not any(_cites(c["rule"], r) for r in cited)]
        if missed:
            for c in missed:
                issues.append({"element": "--".join(c["elements"]), "severity": "warning", "problem": "Deterministic rule check not addressed by the model: " + c["finding"],
                               "rule": c["rule"], "fix": None})
            verdict["issues"] = issues
            verdict["verdict_note"] = f"verdict changed from 'valid' to 'questionable': the facts flagged {', '.join(c['rule'] for c in missed)} and the model did not address it"
            verdict["verdict"] = "questionable"
    has_error = any((i or {}).get("severity") == "error" for i in issues)
    has_warning = any((i or {}).get("severity") == "warning" for i in issues)
    if verdict.get("verdict") in ("valid", "questionable") and has_error:
        verdict["verdict_note"] = f"verdict changed from '{verdict['verdict']}' to 'invalid' because the model reported error-severity issues"
        verdict["verdict"] = "invalid"
    elif verdict.get("verdict") == "invalid" and not has_error:
        # the model found nothing it could call an outright defect: a doubt, not a verdict
        verdict["verdict_note"] = "verdict changed from 'invalid' to 'questionable' because no error-severity issue was reported" + ("" if has_warning else " (no issues at all)")
        verdict["verdict"] = "questionable"
    ns = verdict.get("normalized_string")
    if isinstance(ns, str) and ns.endswith(".") and not re.search(r"\b(etc|[A-Z])\.$", ns):
        verdict["normalized_string"] = ns[:-1]
    return verdict
