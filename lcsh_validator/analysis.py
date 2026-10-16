"""Deterministic analysis of a parsed heading: lookups, classification, literal checks.

Produces a JSON-serializable "facts" report that the Haiku agent reasons over.
"""
from __future__ import annotations

import json
from pathlib import Path

import re

from .db import LCSHDB
from .freefloating import FreeFloating
from .parse import ParsedHeading, normalize_label

CHRONO_RE = re.compile(
    r"^(To \d{1,4}( B\.C\.)?|\d{1,4}( B\.C\.)?-(\d{1,4}( A\.D\.)?)?|\d{1,2}(st|nd|rd|th) century( B\.C\.)?|"
    r"\d{3,4}|.+, \d{3,4}(-\d{1,4})?|.+, \d{1,4} B\.C\.(-\d{1,4}( A\.D\.)?)?|\d{4}-\d{4}|\d{4}-|.*\(\d{4}-\d{4}\)|\d{1,2}(st|nd|rd|th)-\d{1,2}(st|nd|rd|th) centur(y|ies))$"
)
LOWER_OK = {"e-mail", "iPhone", "iPad", "eBay", "pH", "mRNA", "p-adic", "de", "van", "von"}


def _prefer_context(forms: list[dict], context: list[str] | None, text: str) -> list[dict]:
    """Among several 181 forms for one label, put first the one whose chain equals the chain given."""
    if not forms or not context:
        return forms
    want = normalize_label("--".join(list(context) + [text]))
    return sorted(forms, key=lambda f: normalize_label(f["form"]) != want)


# phrases by which a usage statement names a whole type of heading rather than a specific category
GENERAL_CLAUSES = {
    "topical": ["topical headings", "subjects of all types", "all types of headings", "headings of all types", "under subjects", "all subjects", "any subject"],
    "geographic": ["names of countries, cities, etc.", "names of places", "under places", "geographic headings", "names of countries"],
    "personal name": ["names of individual persons", "names of persons", "individual persons"],
    "corporate name": ["names of individual corporate bodies", "individual corporate bodies"],
    "class of persons": ["classes of persons"],
    "ethnic group": ["ethnic groups"],
}
_NEGATED = re.compile(r"\b(not|except|rather than|instead of)\b[^.;]{0,40}$", re.I)


def usage_coverage(heading_types: list[str], ffi: dict, main: str) -> dict:
    """Quote the clause of a free-floating subdivision's usage statement(s) that names the main heading's type, if any."""
    texts = [u for e in ffi.get("free_floating_list") or [] for u in (e.get("usage") or [])]
    texts += [str(e.get("use_under") or "") for e in ffi.get("shm_list_entries") or [] if e.get("use_under")]
    out: dict = {"heading_types": heading_types, "general_clause": None, "phrase": None}
    for t in heading_types:
        for phrase in GENERAL_CLAUSES.get(t, []):
            for text in texts:
                low = text.lower()
                i = low.find(phrase)
                while i >= 0:
                    if not _NEGATED.search(low[max(0, i - 40):i]):
                        # the sentence around the phrase, trimmed
                        start = max(low.rfind(". ", 0, i) + 2, 0)
                        end = low.find(".", i + len(phrase))
                        clause = text[start:end + 1 if end > 0 else len(text)].strip()
                        if len(clause) > 260:
                            clause = "..." + text[max(start, i - 120):min(len(text), i + len(phrase) + 120)].strip() + "..."
                        out.update({"heading_type": t, "phrase": phrase, "general_clause": clause,
                                    "note": f"The usage statement names this heading's type ('{phrase}'); the subdivision is authorized under {main} on that clause unless a 'Do not use ...' note, a scope restriction or the governing special sheet excludes this heading."})
                        return out
                    i = low.find(phrase, i + 1)
    out["heading_type"] = heading_types[0] if heading_types else None
    out["note"] = (f"No clause of the usage statement names {main}'s type by a general phrase; it names specific categories. Decide whether {main} belongs to one of them and quote the clause."
                   if texts else "No usage statement available.")
    return out


def _summ(h: dict) -> dict:
    """Compact record summary for the report."""
    return {k: h.get(k) for k in ("id", "label", "kind_label", "authorized", "deprecated", "may_subd_geog", "scope_note", "history_note",
                                  "example_note", "editorial_note", "deletion_note", "pattern_collections", "use_instead", "earlier_forms", "gac") if h.get(k) not in (None, "", [], 0)}



def _pattern_matches(pattern: str, norm_elements: list[str]) -> bool:
    parts = [normalize_label(p) for p in pattern.split("--")]
    if not parts or len(parts) > len(norm_elements) or all(p.startswith("[") for p in parts):
        return False  # a template with no literal element ("[Nationality]--[Foreign country]") would match everything

    def one(p: str, e: str) -> bool:
        m = re.fullmatch(r"\[[^\]]*\]\s*(.*)", p)
        if m:
            tail = m.group(1).strip()
            return True if not tail else e.endswith(" " + tail) or e == tail
        return p == e

    for start in range(len(norm_elements) - len(parts) + 1):
        if all(one(p, norm_elements[start + k]) for k, p in enumerate(parts)):
            return True
    return False


class Analyzer:
    ART_STYLE_QUALIFIERS = {"Modern", "Medieval", "Ancient", "Abstract", "Baroque", "Renaissance", "Gothic", "Romanesque", "Primitive", "Prehistoric",
                            "Classical", "Rococo", "Victorian", "Colonial", "Byzantine", "Early Christian", "Outsider", "Naive", "Erotic", "Psychedelic",
                            "Conceptual", "Kinetic", "Decorative", "Municipal", "Public", "Popular", "Street", "Visionary", "Optical", "Computer", "Video",
                            "Performance", "Environmental", "Mail", "Digital", "Minimal", "Pop", "Op", "Tribal", "Folk", "Immigrant", "Lesbian", "Gay",
                            "Children's", "Students'", "Prisoners'", "Mentally ill", "Women's", "Artistic", "Mannerism", "Commercial", "Fantastic"}

    def __init__(self, db: LCSHDB, ff: FreeFloating):
        self.db = db
        self.ff = ff
        # dated LC decisions on SACO proposals (Summaries of Decisions) tied to a subdivision, heading or pattern
        self.lc_decisions_notes: list[dict] = []
        path = Path(__file__).resolve().parent.parent / "rules/lc_decisions.json"
        if path.exists():
            try:
                self.lc_decisions_notes = json.loads(path.read_text(encoding="utf-8")).get("notes", [])
            except (OSError, ValueError):
                self.lc_decisions_notes = []

    # ------------------------------------------------------------------ main heading
    def main_heading(self, text: str, tag: str | None) -> dict:
        out: dict = {"text": text}
        exact = [h for h in self.db.lookup_exact(text, subdivisions=False)]
        auth = [h for h in exact if h["authorized"] and not h["deprecated"]]
        dep = [h for h in exact if h["deprecated"]]
        out["lcsh_exact"] = [_summ(h) for h in auth]
        out["lcsh_deprecated"] = [dict(_summ(h), use_instead_labels=[self._replacement_label(u) for u in h.get("use_instead", [])]) for h in dep]
        untraced = [h for h in exact if not h["authorized"] and not h["deprecated"] and any("UntracedReference" in str(c) for c in (h.get("collections") or []))]
        if untraced:
            # e.g. "Districts": an untraced-reference record that exists in the file but is not a usable heading
            out["lcsh_untraced_reference"] = [dict(_summ(h), note="This record is an untraced reference (collection UntracedReference), not an authorized heading: the term may not be used as a heading. See its scope/editorial notes for the headings to use instead.") for h in untraced]
        variants = self.db.lookup_variant(text)
        out["lcsh_variant_of"] = [dict(_summ(h), matched_variant=h["matched_variant"]) for h in variants if not h["is_complex"]]
        if not auth and not dep and not variants:
            near = self.db.lookup_loose(text)
            if near:
                out["lcsh_near_match"] = [dict(_summ(h), note=f"differs from the supplied form only in hyphenation or spacing; the authorized spelling is '{h['label']}'") for h in near[:3]]
        if auth:
            h = auth[0]
            out["category_hints"] = self.db.category_hints(h["id"])
            out["broader_terms"] = [self.db.label_of(b) for b in h.get("broader", []) if not str(b).startswith("label:")][:6]
            out["established_strings_under_heading_sample"] = [e["example"] for e in self.db.established_under(h["label"], limit=25)]
        # Name authority file (jurisdictions, persons, corporate bodies, titles, named entities)
        moved_to_naf = any(str(u).startswith("n") for h in dep for u in h.get("use_instead", []))
        want_name = tag in ("600", "610", "611", "630", "651") or not (auth or dep or variants) or moved_to_naf
        if want_name:
            nm = self.db.lookup_name(text)
            if nm.get("found") or nm.get("candidates"):
                out["name_authority"] = {k: v for k, v in nm.items() if k in ("found", "id", "label", "kind", "geographic_subdivision_form", "notes", "entity_type", "matched_as", "candidates", "gac", "place_associated", "occupation", "field_of_activity", "sources_670", "geog_subdiv_code_008_06")}
                if nm.get("found") and nm.get("variants"):
                    out["name_authority"]["variants_sample"] = nm["variants"][:5]
        if not (auth or dep or variants or out.get("name_authority", {}).get("found")):
            phrase = self.phrase_candidate(text)
            if phrase:
                out["free_floating_phrase_candidate"] = phrase
            online = self.db.lookup_subject_online(text)
            if online.get("found"):
                out["lcsh_online_only"] = online
            out["suggestions"] = [{"label": h["label"], "kind": h["kind_label"]} for h in self.db.search(text, limit=8) if not h["is_complex"] and h.get("authorized")][:8]
        return out

    @staticmethod
    def heading_types(mh: dict) -> list[str]:
        """The kinds of heading a main heading is, in the vocabulary of the usage statements (a 150 for a group of
        people is both a 'topical' heading and a 'class of persons')."""
        types: list[str] = []
        ex = (mh.get("lcsh_exact") or [{}])[0]
        kl = str(ex.get("kind_label") or "")
        if kl.startswith("topical"):
            types.append("topical")
        elif kl.startswith("geographic"):
            types.append("geographic")
        elif kl.startswith("personal"):
            types.append("personal name")
        elif kl.startswith(("corporate", "conference")):
            types.append("corporate name")
        nm = mh.get("name_authority") or {}
        if nm.get("found"):
            k = str(nm.get("kind") or "")
            if k.startswith("geographic"):
                types.append("geographic")
            elif k.startswith("personal"):
                types.append("personal name")
            elif k.startswith(("corporate", "conference")):
                types.append("corporate name")
        for h in mh.get("category_hints") or []:
            if h.get("sheet") == "H 1100" and not h.get("excluded"):
                types.append("class of persons")
            elif h.get("sheet") == "H 1103":
                types.append("ethnic group")
        return list(dict.fromkeys(types))

    PHRASE_RE = re.compile(r"^(?P<base>.+?),?\s+(?P<term>Metropolitan Area|Suburban Area|Region)(?:\s+\((?P<qual>[^()]*)\))?$")

    def phrase_candidate(self, text: str) -> dict | None:
        """H 362 free-floating phrase headings: [city] Metropolitan Area/Region/Suburban Area (qualifier), [feature] Region."""
        m = self.PHRASE_RE.match(text.strip())
        if not m:
            return None
        base, term, qual = m.group("base").strip(), m.group("term"), m.group("qual")
        res = {"pattern": f"[base heading] {term} ([geographic qualifier])", "term": term, "base_as_written": base, "qualifier": qual, "sheet": "H 362"}
        # the base may be a city (name authority, qualifier moved to the end) or an established geographic feature (LCSH 151)
        cands = []
        if qual:
            cands.append(f"{base} ({qual})")
        cands.append(base)
        for c in cands:
            lc = [h for h in self.db.lookup_exact(c, subdivisions=False) if h["kind"] == "geographic" and h["authorized"]]
            if lc:
                res["base_heading"] = {"source": "LCSH", "label": lc[0]["label"], "id": lc[0]["id"]}
                break
            nm = self.db.lookup_name(c)
            if nm.get("found") and str(nm.get("kind", "")).startswith("geographic"):
                res["base_heading"] = {"source": "LCNAF", "label": nm["label"], "id": nm["id"], "entity_type": nm.get("entity_type", "")}
                break
        if "base_heading" not in res:
            res["base_heading"] = None
        res["base_is_inverted"] = "," in base
        res["no_qualifier_exceptions"] = ["Jerusalem", "New York", "Washington"]
        return res

    # ------------------------------------------------------------------ subdivisions
    def subdivision(self, text: str, code: str | None, position: int, prefix: str, is_last: bool) -> dict:
        out: dict = {"position": position, "text": text, "subfield_given": code}
        ffi = self.ff.lookup(text)
        out["free_floating"] = ffi if (ffi["free_floating_list"] or ffi["use_instead"] or ffi["shm_list_entries"]) else None
        recs = [h for h in self.db.lookup_exact(text, subdivisions=True)]
        out["lcsh_subdivision_records"] = [dict(_summ(h), tag=h["tag"], collections=[c for c in h["collections"] if "Pattern" in c]) for h in recs][:6]
        # also a heading? (names of places/topics used as $x or $z)
        heads = [h for h in self.db.lookup_exact(text, subdivisions=False) if h["authorized"] and not h["is_complex"]]
        out["also_an_lcsh_heading"] = [_summ(h) for h in heads][:3]
        # established as next element under the prefix?
        under = self.db.established_under(prefix, limit=400)
        n = normalize_label(text)
        hit = next((u for u in under if normalize_label(u["next_element"]) == n), None)
        out["established_under_prefix"] = {"prefix": prefix, "established": bool(hit), "example": hit["example"] if hit else None}
        if hit:
            whole = [h for h in self.db.lookup_exact(f"{prefix}--{text}", subdivisions=False) if h["authorized"]]
            if whole:  # the string up to and including this element is itself an authority record: report its geographic coding
                out["established_under_prefix"]["record_id"] = whole[0]["id"]
                msg = self.db.fill_geog_code(whole[0]).get("may_subd_geog")
                out["established_under_prefix"]["may_subd_geog"] = msg
                if msg is None:
                    out["established_under_prefix"]["may_subd_geog_note"] = f"LC never coded this string for geographic subdivision (008/06 '|'); the coding of --{text} on the free-floating list or its subdivision record governs whether a place may follow."
                elif msg is False:
                    out["established_under_prefix"]["may_subd_geog_note"] = "LC coded this string 'not subdivided geographically' (008/06 blank)."
        comp_type = ""
        if hit:
            comps = self.db.complex_components(hit["id"])
            if len(comps) > position:
                comp_type = comps[position]["component_type"]
                out["established_under_prefix"]["component_type"] = comp_type
        if not hit and not out["free_floating"] and not recs:
            out["established_next_elements_sample"] = [u["next_element"] for u in under[:40]]
        # classification
        # authority records (180/182/185) are the primary evidence of a subdivision's type; the printed list is secondary
        types = {({"180": "topical", "181": "geographic", "182": "chronological", "185": "form"}.get(h["tag"], "")) for h in recs}
        types.discard("")
        if not types:
            for e in (ffi["free_floating_list"] or []):
                types.update(e["types"])
        if code in ("x", "y", "z", "v"):
            cls = {"x": "topical", "y": "chronological", "z": "geographic", "v": "form"}[code]
        elif CHRONO_RE.match(text) or "chronological" in types:
            cls = "chronological"
        elif "topical" in types and "form" in types:
            cls = "form" if is_last else "topical"
        elif types:
            cls = sorted(types)[0]
        elif heads and heads[0]["kind"] == "geographic":
            cls = "geographic"
        elif comp_type == "Geographic":
            cls = "geographic"
        elif comp_type == "Temporal":
            cls = "chronological"
        elif comp_type in ("Topic", "GenreForm") and not heads:
            cls = "topical" if comp_type == "Topic" else "form"
        else:
            cls = "unknown"
        if cls in ("unknown", "geographic") and code in (None, "z") and not out["free_floating"]:
            place = self.resolve_place(text)
            if place.get("name_authority") or place.get("lcsh_geographic_heading") or place.get("authorized_subdivision_form"):
                out["place_resolution"] = place
                if place.get("name_authority", {}).get("kind", "").startswith("geographic") or place.get("lcsh_geographic_heading") or place.get("authorized_subdivision_form"):
                    cls = "geographic"
                elif place.get("name_authority"):
                    out["name_authority_note"] = "This element is a name heading, not a place; name headings are not used as subdivisions except in a few established patterns."
        out["classified_as"] = cls
        out["known_types"] = sorted(types)
        return out

    def _replacement_label(self, hid: str) -> str:
        lab = self.db.label_of(hid)
        if lab == hid and str(hid).startswith("n"):
            rec = self.db.name_record(hid)
            if rec.get("label"):
                return f"{rec['label']} (LCNAF {hid})"
        return lab

    # ------------------------------------------------------------------ geography
    def resolve_place(self, text: str, context: list[str] | None = None) -> dict:
        """Resolve a place name; `context` is the chain of geographic elements given before it (for disambiguating bare names)."""
        res: dict = {"text": text}
        context = context or []
        lc = [h for h in self.db.lookup_exact(text, subdivisions=False) if h["kind"] == "geographic" and h["authorized"]]
        if lc:
            res["lcsh_geographic_heading"] = _summ(lc[0])
            forms = self.db.geographic_subdivision_form(lc[0]["label"])
            own = [f for f in forms if f.get("generated_from") == lc[0]["id"]] or forms
            own = _prefer_context(own, context, text)
            if own:
                res["authorized_subdivision_form"] = own[0]["form"]
        nm = self.db.lookup_name(text)
        if nm.get("found") and not str(nm.get("kind", "")).startswith("geographic"):
            res["name_authority_non_place"] = {"label": nm.get("label"), "kind": nm.get("kind")}
            nm = {"found": False}
        if nm.get("found"):
            res["name_authority"] = {k: v for k, v in nm.items() if k in ("id", "label", "kind", "geographic_subdivision_form", "entity_type", "matched_as", "gac")}
            if nm.get("geographic_subdivision_form"):
                res.setdefault("authorized_subdivision_form", nm["geographic_subdivision_form"])
        if "(" not in text and not context and res.get("authorized_subdivision_form"):
            # a bare name such as 'Rome' resolves to the record for ancient Rome ($z Rome); the modern city is 'Rome (Italy)' -> Italy--Rome
            seen = {normalize_label(res["authorized_subdivision_form"])}
            others = []
            for c in self.db.place_candidates(text, limit=40):
                f = c.get("geographic_subdivision_form")
                if f and normalize_label(f) not in seen:
                    seen.add(normalize_label(f))
                    others.append({"label": c.get("label"), "authorized_subdivision_form": f})
            if others:
                # simplest qualifiers first: 'Rome (Italy)' before 'Rome (Bradford County, Pa. : Township)'
                others.sort(key=lambda o: (len(re.findall(r"[,:]", o["label"])), len(o["label"])))
                res["other_places_with_this_name"] = others[:6]
                res["ambiguity_note"] = "The bare name matches this record; differently qualified places of the same name take other $z forms (listed)."

        # 181 record by its own label (e.g. "Washington (D.C.)" used directly); a bare name with several 181s
        # ('Sierra': Ecuador--Sierra, Peru--Sierra) takes the one that fits the chain given
        if "authorized_subdivision_form" not in res:
            forms = _prefer_context(self.db.geographic_subdivision_form(text), context, text)
            if forms:
                res["authorized_subdivision_form"] = forms[0]["form"]
                if len(forms) > 1:
                    res["other_authorized_forms"] = [f["form"] for f in forms[1:6]]
        # H 362: '[city] Region', '[city] Metropolitan Area', '[feature] Region' are free-floating phrase headings and may be
        # used as $z in the base place's chain: Czech Republic--Prague Region
        if "authorized_subdivision_form" not in res:
            pm = self.PHRASE_RE.match(text.strip())
            if pm and not pm.group("qual"):
                base, term = pm.group("base").strip(), pm.group("term")
                cands = [c for c in self.db.place_candidates(base, limit=40) if c.get("geographic_subdivision_form")]
                if context:
                    first = normalize_label(context[0])
                    cands = [c for c in cands if normalize_label(c["geographic_subdivision_form"]).startswith(first + "--") or normalize_label(c["geographic_subdivision_form"]) == first]
                # the city itself ('Derventa (Bosnia and Herzegovina)') before a district of the same name ('Derventa (Opština)')
                cands.sort(key=lambda c: ("(" in c["geographic_subdivision_form"].split("--")[-1], len(c["geographic_subdivision_form"])))
                lc_base = [h for h in self.db.lookup_exact(base, subdivisions=False) if h["kind"] == "geographic" and h["authorized"]]
                base_form = cands[0]["geographic_subdivision_form"] if cands else (self.db.geographic_subdivision_form(lc_base[0]["label"]) or [{}])[0].get("form") if lc_base else None
                if base_form:
                    res["authorized_subdivision_form"] = f"{base_form} {term}"
                    res["free_floating_phrase"] = {"sheet": "H 362", "pattern": f"[base] {term}", "base": cands[0]["label"] if cands else lc_base[0]["label"],
                                                   "note": f"'{text}' is not an authority record; it is the H 362 free-floating phrase built on the established base, used as $z in the base's chain: {base_form} {term}."}
        # bare name without qualifier (e.g. "Buffalo"): find qualified candidates and pick the one whose 781 form fits the chain
        if "authorized_subdivision_form" not in res or (context and not normalize_label(res["authorized_subdivision_form"]).startswith(normalize_label("--".join(context)))):
            cands = self.db.place_candidates(text)
            if cands:
                want = normalize_label("--".join(context + [text])) if context else None
                best = next((c for c in cands if c.get("geographic_subdivision_form") and want and normalize_label(c["geographic_subdivision_form"]) == want), None)
                res["qualified_candidates"] = cands
                if best:
                    res["authorized_subdivision_form"] = best["geographic_subdivision_form"]
                    res["resolved_candidate"] = best
                elif context:
                    # same first-level place (country/state) but a different chain: report the authorized form so the chain can be compared
                    first = normalize_label(context[0])
                    near = [c for c in cands if c.get("geographic_subdivision_form") and normalize_label(c["geographic_subdivision_form"]).startswith(first + "--")]
                    if len(near) == 1:
                        res["authorized_subdivision_form"] = near[0]["geographic_subdivision_form"]
                        res["resolved_candidate"] = near[0]
                        res["note"] = "Resolved by matching the first-level place; the given chain differs from the authorized form."
        return res

    def geographic_chains(self, elements: list[str], subs: list[dict]) -> list[dict]:
        """For each run of consecutive geographic elements, compare to the authorized $z form of the final place."""
        chains = []
        i = 0
        while i < len(subs):
            if subs[i]["classified_as"] == "geographic":
                j = i
                while j + 1 < len(subs) and subs[j + 1]["classified_as"] == "geographic":
                    j += 1
                run = [s["text"] for s in subs[i:j + 1]]
                last = self.resolve_place(run[-1], run[:-1])
                chain: dict = {"given": run, "preceded_by": elements[i], "final_place": last}
                form = last.get("authorized_subdivision_form")
                if form:
                    chain["expected_chain"] = form.split("--")
                    chain["matches_authorized_form"] = normalize_label("--".join(run)) == normalize_label(form)
                # is the element before the run authorized for geographic subdivision?
                prev_text = elements[i]
                if i == 0:
                    prev = [h for h in self.db.lookup_exact(prev_text, subdivisions=False) if h["authorized"]]
                else:
                    prev = [h for h in self.db.lookup_exact(prev_text, subdivisions=True)]
                    ffi = self.ff.lookup(prev_text)
                    if ffi["free_floating_list"]:
                        chain["preceding_subdivision_may_subd_geog"] = any(e["may_subd_geog"] for e in ffi["free_floating_list"])
                if prev:
                    chain["preceding_element_may_subd_geog"] = self.db.fill_geog_code(prev[0])["may_subd_geog"]
                chains.append(chain)
                i = j + 1
            else:
                i += 1
        return chains

    # ------------------------------------------------------------------ literal checks
    @staticmethod
    def surface_checks(parsed: ParsedHeading) -> list[str]:
        issues = list(parsed.notes)
        elems = [parsed.main] + [c.text for c in parsed.subdivisions]
        raw = parsed.raw
        if re.search(r"--\s|\s--", raw):
            issues.append("Spaces around '--': LCSH strings are written with no spaces around the double hyphen.")
        if re.search(r"\s{2,}", raw.strip()):
            issues.append("Double spaces found.")
        for e in elems:
            if not e:
                issues.append("Empty element (consecutive delimiters).")
                continue
            if e[0].islower() and e.split()[0] not in LOWER_OK and not re.match(r"^\d", e):
                issues.append(f"Element '{e}' begins with a lowercase letter; LCSH elements are capitalized (Appendix B).")
            if e.count("(") != e.count(")"):
                issues.append(f"Unbalanced parentheses in '{e}'.")
            if re.search(r"\betc\b(?!\.)", e):
                issues.append(f"'etc' without period in '{e}' (LCSH writes 'etc.').")
            if re.search(r"\s[,;:]", e):
                issues.append(f"Space before punctuation in '{e}'.")
            if "(May Subd Geog)" in e or "(Not Subd Geog)" in e:
                issues.append("The '(May Subd Geog)' legend is a display convention in the LCSH list, not part of the heading string.")
            if re.search(r"\(\s|\s\)", e):
                issues.append(f"Space inside parentheses in '{e}'.")
        return issues

    # ------------------------------------------------------------------ whole string
    def analyze(self, parsed: ParsedHeading) -> dict:
        elements = [parsed.main] + [c.text for c in parsed.subdivisions]
        report: dict = {"input": parsed.to_dict(), "surface_checks": self.surface_checks(parsed)}
        report["main_heading"] = self.main_heading(parsed.main, parsed.tag)
        # a few authorized names contain '--' themselves (Bà Rịa--Vũng Tàu (Vietnam)); when the first element is unknown,
        # test whether the first two elements together are one established heading
        mh = report["main_heading"]
        # matched only after normalization (case, diacritics, ayn/alif characters): tell the model the exact authorized spelling
        for h in (mh.get("lcsh_exact") or [])[:1]:
            if h.get("label") and h["label"] != parsed.main and h["label"].rstrip(".") != parsed.main.rstrip("."):
                report["surface_checks"].append(f"'{parsed.main}' matches the authorized heading '{h['label']}' only after folding case, diacritics or apostrophe-like characters (ʻ ʼ ʿ ʾ ’); the authorized spelling is '{h['label']}'.")
        if parsed.subdivisions and not (mh.get("lcsh_exact") or mh.get("lcsh_deprecated") or mh.get("lcsh_variant_of") or (mh.get("name_authority") or {}).get("found")):
            merged = parsed.main + "--" + parsed.subdivisions[0].text
            m_lc = [h for h in self.db.lookup_exact(merged, subdivisions=False) if h["authorized"] and not h["is_complex"]]
            m_nm = self.db.lookup_name(merged) if not m_lc else {}
            if m_lc or m_nm.get("found"):
                report["merged_main_heading"] = {
                    "label": m_lc[0]["label"] if m_lc else m_nm["label"], "source": "LCSH" if m_lc else "LCNAF",
                    "id": m_lc[0]["id"] if m_lc else m_nm.get("id"),
                    "geographic_subdivision_form": (self.db.geographic_subdivision_form(m_lc[0]["label"]) or [{}])[0].get("form") if m_lc else m_nm.get("geographic_subdivision_form"),
                    "note": "The authorized label itself contains '--': the first two parsed elements are one heading, and the remaining elements are its subdivisions."}
                parsed.subdivisions.pop(0)
                parsed.main = merged
                parsed.notes.append(f"First two elements merged into the established heading {merged!r} (its label contains '--').")
                elements = [parsed.main] + [c.text for c in parsed.subdivisions]
                report["input"] = parsed.to_dict()
                report["main_heading"] = self.main_heading(parsed.main, parsed.tag)
        # whole string / longest established prefix
        whole = [h for h in self.db.lookup_exact(parsed.string) if h["authorized"]]
        report["whole_string_established"] = [_summ(h) for h in whole][:2]
        longest = None
        for k in range(len(elements), 1, -1):
            pref = "--".join(elements[:k])
            hits = [h for h in self.db.lookup_exact(pref) if h["authorized"]]
            if hits:
                self.db.fill_geog_code(hits[0])
                longest = {"prefix": pref, "id": hits[0]["id"], "elements_covered": k, "remaining_free_floating_candidates": elements[k:],
                           "may_subd_geog": hits[0].get("may_subd_geog")}
                comps = self.db.complex_components(hits[0]["id"])
                if not comps or comps[-1].get("component_type") != "Geographic":  # the coding matters when the prefix ends in a topic
                    msg = hits[0].get("may_subd_geog")
                    longest["note"] = ("This established string is coded (May Subd Geog): a place may follow it directly." if msg
                                       else "LC never coded this string for geographic subdivision (008/06 '|'): whether a place may follow it is decided by the coding of its last element on the free-floating list or its subdivision record." if msg is None
                                       else "LC coded this string 'not subdivided geographically' (008/06 blank), so a place may not follow it directly; if the last element's free-floating list entry is (May Subd Geog), treat the record's coding as a doubt rather than a bar.")
                # 'Korea--History--Japanese invasions, 1592-1598' matches the established string only after folding case
                if hits[0]["label"].rstrip(".") != pref.rstrip(".") and normalize_label(hits[0]["label"]) == normalize_label(pref):
                    report["surface_checks"].append(f"'{pref}' matches the established string '{hits[0]['label']}' only after folding case, diacritics or apostrophe-like characters; the authorized spelling is '{hits[0]['label']}'.")
                break
        report["longest_established_prefix"] = longest
        subs = []
        for i, c in enumerate(parsed.subdivisions):
            prefix = "--".join(elements[: i + 1])
            subs.append(self.subdivision(c.text, c.code, i + 1, prefix, is_last=(i == len(parsed.subdivisions) - 1)))
        # second pass: an unknown element right after a geographic element may be a bare locality (Buffalo, Erie County)
        for i, s in enumerate(subs):
            if s["classified_as"] == "unknown" and i > 0 and subs[i - 1]["classified_as"] == "geographic" and s["subfield_given"] in (None, "z"):
                ctx = []
                j = i - 1
                while j >= 0 and subs[j]["classified_as"] == "geographic":
                    ctx.insert(0, subs[j]["text"])
                    j -= 1
                place = self.resolve_place(s["text"], ctx)
                if place.get("authorized_subdivision_form") or place.get("qualified_candidates"):
                    s["place_resolution"] = place
                    s["classified_as"] = "geographic"
        report["subdivisions"] = subs
        # does each free-floating subdivision's usage statement name this heading's type by a general clause?
        htypes = self.heading_types(report["main_heading"])
        for s in subs:
            if s.get("free_floating"):
                s["usage_coverage"] = usage_coverage(htypes, s["free_floating"], parsed.main)
        # multi-element free-floating strings (877 list entries such as --History--To 1500, --Study and teaching--Audio-visual aids)
        ff_strings = []
        for i in range(len(subs)):
            for span in (3, 2):
                if i - span + 1 < 0:
                    continue
                run = [s["text"] for s in subs[i - span + 1 : i + 1]]
                joined = "--".join(run)
                info = self.ff.lookup(joined)
                if info["free_floating_list"] or info["shm_list_entries"]:
                    ff_strings.append({"elements": run, "positions": list(range(i - span + 2, i + 2)), "string": joined,
                                       "free_floating_list": info["free_floating_list"], "shm_list_entries": info["shm_list_entries"][:4],
                                       "controlling_sheets": info["controlling_sheets"], "matched_pattern": info["matched_pattern"]})
                    for s in subs[i - span + 1 : i + 1]:
                        s["part_of_free_floating_string"] = joined
                    break
        report["free_floating_strings"] = ff_strings
        report["geographic_chains"] = self.geographic_chains(elements, subs)
        report["element_pattern"] = " > ".join(["main"] + [s["classified_as"] for s in subs])
        # order heuristics (H 1075)
        order_notes = []
        roles = [s["classified_as"] for s in subs]
        if "form" in roles:
            last_form = len(roles) - 1 - roles[::-1].index("form")
            if any(r in ("topical", "geographic", "chronological") for r in roles[last_form + 1:]):
                order_notes.append("A form subdivision is followed by a non-form subdivision; form subdivisions are normally last (H 1075 sec. C.4), unless the form element is really topical ($x).")
        if "chronological" in roles:
            first_chrono = roles.index("chronological")
            if first_chrono > 0 and roles[first_chrono - 1] == "geographic":
                order_notes.append("Chronological subdivision directly follows a geographic subdivision: check that the period is established under [topic]--[place] or that the pattern [topic]--[place]--[period] is authorized (H 1075 sec. D, H 620).")
            if first_chrono == 0 and report["main_heading"].get("lcsh_exact"):
                order_notes.append("Chronological subdivision directly follows the main heading: valid only when the period is established under the heading, or for inherently historical headings/art, literature and music form headings (H 620, H 1647).")
        report["order_notes"] = order_notes
        # a country followed by a locality is one indirect place (H 830): the record for [string]--[country] does not govern the locality
        texts_all = [s["text"] for s in subs]
        for ch in report.get("geographic_chains") or []:
            given = ch.get("given") or []
            if len(given) > 1 and ch.get("matches_authorized_form") and given[0] in texts_all:
                e = subs[texts_all.index(given[0])].get("established_under_prefix") or {}
                if e.get("established") and e.get("record_id"):
                    e["next_element_note"] = f"--{given[1]} continues the indirect geographic chain {'--'.join(given)} (one place, H 830 sec. C); the geographic coding of {e['record_id']} does not bar it."
        report["rule_checks"] = self.rule_checks(parsed, report, subs)
        report["lc_decisions"] = self.lc_decisions(elements)
        return report

    # ------------------------------------------------------------------ explicit prohibitions (deterministic)
    H1647_SEC9 = {normalize_label(x) for x in [
        "Annexation to", "Anniversaries, etc.", "Antiquities", "Art", "Centennial celebrations, etc.", "Chronology", "Church history",
        "Civilization", "Commercial policy", "Cultural policy", "Description and travel", "Discovery and exploration", "Economic conditions",
        "Economic policy", "Environmental conditions", "Foreign economic relations", "Foreign relations", "Genealogy", "Geography",
        "Gold discoveries", "Historical geography", "Historiography", "History", "History, Local", "History, Military", "History, Naval",
        "History of doctrines", "Illustrations", "Intellectual life", "Kings and rulers", "Military policy", "Military relations",
        "Moral conditions", "Origin", "Politics and government", "Population policy", "Portraits", "Queens", "Relations", "Religion",
        "Religious life and customs", "Rural conditions", "Social conditions", "Social life and customs", "Social policy"]}
    PHRASE_SUBDIVS = {"in literature": "in literature", "in art": "in art", "in motion pictures": "in motion pictures", "in mass media": "in mass media",
                      "in music": "in music", "in popular culture": "in popular culture", "on television": "on television",
                      "on postage stamps": "on postage stamps", "in the bible": "in the Bible", "in the press": "in the press"}

    LC_DECISIONS_MAX = 6

    def lc_decisions(self, elements: list[str]) -> list[dict]:
        """Summaries-of-Decisions notes whose subdivision, heading or pattern occurs in this string. A pattern is
        a '--'-joined template: a literal element must match exactly, '[Topic]' matches any element and
        '[Field] applications' matches an element ending in those words; the template's elements must be consecutive."""
        norm = [normalize_label(e) for e in elements]
        out = []
        for n in self.lc_decisions_notes:
            matched = []
            kind = n.get("kind")
            # a decision about specific headings attaches only to those headings; one about a pattern only by the pattern
            if kind not in ("heading", "pattern"):
                for sub in n.get("subdivisions") or []:
                    k = normalize_label(sub.lstrip("-"))
                    if k in norm[1:]:
                        matched.append(sub)
            if kind != "pattern":
                for h in n.get("headings") or []:
                    if normalize_label(h) == norm[0] or normalize_label(h) == normalize_label("--".join(elements[:2])):
                        matched.append(h)
            if kind in ("pattern", None, "other"):
                for pat in n.get("patterns") or []:
                    if _pattern_matches(pat, norm):
                        matched.append(pat)
            if matched:
                heading_hit = any(not m.startswith("--") and "--" not in m for m in matched)
                out.append({"matched_on": matched, "date": n.get("date"), "source": n.get("source_id"), "url": n.get("url"),
                            "kind": n.get("kind"), "decision": n.get("decision"), "shm_cited": n.get("shm_cited") or [], "note": n.get("note"),
                            "_rank": (heading_hit, len(matched), n.get("date") or "")})
        # a common subdivision (--History) carries dozens of decisions: keep the most specific and recent few
        out.sort(key=lambda x: x["_rank"], reverse=True)
        kept = out[:self.LC_DECISIONS_MAX]
        for x in kept:
            x.pop("_rank")
        if len(out) > len(kept):
            kept.append({"note": f"{len(out) - len(kept)} further decisions on these subdivisions not shown (older or less specific).", "omitted": len(out) - len(kept)})
        return kept

    def rule_checks(self, parsed: ParsedHeading, report: dict, subs: list[dict]) -> list[dict]:
        """Explicit prohibitions from the SHM that can be tested mechanically. Each hit is a finding the model must address;
        an established whole string overrides them (reported in 'whole_string_established')."""
        out: list[dict] = []
        main = parsed.main
        texts = [s["text"] for s in subs]
        norms = [normalize_label(t) for t in texts]
        main_is_topical = (bool(report["main_heading"].get("lcsh_exact")) and not report["main_heading"].get("name_authority", {}).get("found")
                           and "151" not in (report["main_heading"].get("lcsh_exact") or [{}])[0].get("kind_label", ""))  # a 151 (Antarctica, Arab countries) is a place, not a topic
        # H 1647 sec. 9: --History (or --History--[century]) after a subdivision that is itself historical
        for i, n in enumerate(norms):
            if n == "history" and i > 0 and norms[i - 1] in self.H1647_SEC9 and not norms[i - 1].startswith("annexation"):
                out.append({"rule": "H 1647 sec. 9", "severity": "error", "elements": [texts[i - 1], texts[i]],
                            "finding": f"--History may not follow --{texts[i - 1]}: that subdivision is on the H 1647 sec. 9 list of subdivisions never further subdivided by --History (or --History--[century]). Period subdivisions, where authorized, follow --{texts[i - 1]} directly."})
            if n == "history" and i > 0 and norms[i - 1].startswith("annexation to"):
                out.append({"rule": "H 1647 sec. 9", "severity": "error", "elements": [texts[i - 1], texts[i]],
                            "finding": "--History may not follow --Annexation to [...] (H 1647 sec. 9)."})
        # H 1629 sec. 1-2: --Foreign relations takes only editorially established period subdivisions (no free-floating century,
        # no interposed --History); [place 1]--Foreign relations--[place 2] takes no period subdivision and no --History at all
        century = re.compile(r"^\d{1,2}(?:st|nd|rd|th) century$")
        for i, n in enumerate(norms):
            if i > 0 and norms[i - 1] == "foreign relations" and century.match(n) and not subs[i].get("established_under_prefix", {}).get("established"):
                out.append({"rule": "H 1629 sec. 1", "severity": "error", "elements": [texts[i - 1], texts[i]],
                            "finding": f"--Foreign relations is not further subdivided by free-floating century subdivisions; only period subdivisions LC has editorially established under {main}--Foreign relations may follow it (none for --{texts[i]}). Bring out the period with an additional heading."})
            if i > 1 and norms[i - 2] == "foreign relations" and subs[i - 1]["classified_as"] == "geographic" and (n == "history" or century.match(n) or subs[i]["classified_as"] == "chronological"):
                out.append({"rule": "H 1629 sec. 2", "severity": "error", "elements": [texts[i - 2], texts[i - 1], texts[i]],
                            "finding": f"{main}--Foreign relations--{texts[i - 1]} names the relations between two places; H 1629 sec. 2 says not to subdivide such a heading by period (or by --History). Assign additional headings of the type [place]--Foreign relations--[established period] to bring out the time."})
        # H 1642: --Government policy is not used where a phrase heading [topic] and state / [topic] policy is established
        for i, n in enumerate(norms):
            if n == "government policy" and i == 0:
                for cand in (f"{main} and state", f"{main} policy"):
                    hits = [h for h in self.db.lookup_exact(cand, subdivisions=False) if h["authorized"] and not h["deprecated"]]
                    via = [h for h in self.db.lookup_variant(cand) if not h["is_complex"]]
                    if hits:
                        out.append({"rule": "H 1642 sec. 1-2", "severity": "error", "elements": [main, texts[i]],
                                    "finding": f"The phrase heading '{hits[0]['label']}' is established, so --Government policy is not used under {main}; use the phrase heading (H 1642 sec. 2).",
                                    "established_heading": hits[0]["label"]})
                        break
                    if via:
                        out.append({"rule": "H 1642 sec. 1-2", "severity": "error", "elements": [main, texts[i]],
                                    "finding": f"'{cand}' is a UF reference to the established heading '{via[0]['label']}', which already expresses government policy on this topic; use it instead of --Government policy (H 1642 sec. 2).",
                                    "established_heading": via[0]["label"]})
                        break
        # H 1095 sec. E.2: a free-floating subdivision is not used where an established phrase heading expresses the same relationship
        for i, n in enumerate(norms):
            if i == 0 and n in self.PHRASE_SUBDIVS:
                cand = f"{main} {self.PHRASE_SUBDIVS[n]}"
                hits = [h for h in self.db.lookup_exact(cand, subdivisions=False) if h["authorized"] and not h["deprecated"]]
                if hits:
                    out.append({"rule": "H 1095 sec. E.2", "severity": "error" if main_is_topical else "warning", "elements": [main, texts[i]],
                                "finding": f"The phrase heading '{hits[0]['label']}' is established for this relationship, so the subdivision form conflicts with an established heading (H 1095 sec. E.2). "
                                           + ("Use the established phrase heading." if main_is_topical else "Under names of persons, deities and places the subdivision form is the free-floating pattern; check which form LC uses for this heading."),
                                "established_heading": hits[0]["label"]})
        # H 1100 sec. D: the classes-of-persons list does not apply to social classes
        hints = report["main_heading"].get("category_hints") or []
        if any(h.get("excluded") for h in hints):
            for i, t in enumerate(texts):
                ffi = subs[i].get("free_floating") or {}
                sheets = {c["sheet"] for c in ffi.get("controlling_sheets", [])}
                usage = " ".join(u for e in ffi.get("free_floating_list", []) for u in (e.get("usage") or [])).lower()
                if sheets & {"H 1100", "H 1103"} and "topical headings" not in usage and not subs[i].get("established_under_prefix", {}).get("established"):
                    finding = f"--{t} is free-floating under classes of persons (and the other categories its usage statement names), not under topical headings in general, and {main} is a social class or collective social grouping, to which H 1100 sec. D says the classes-of-persons list does not apply."
                    mixed = next((h for h in hints if h.get("excluded") and h.get("mixed")), None)
                    used = self.db.strings_using_subdivision(main, t)
                    check = {"rule": "H 1100 sec. D", "severity": "error", "elements": [main, t], "finding": finding}
                    if used or mixed:
                        # LC itself applies the subdivision under this heading, or the heading is also a class of persons by another BT path:
                        # the exclusion is a doubt for the cataloger, not a deterministic bar (Intellectuals--Interviews is established).
                        check["severity"] = "warning"
                        if used:
                            # LC's own established strings outweigh a BT-derived category guess: a note, not a doubt
                            check["severity"] = "note"
                            check["established_strings_using_this_subdivision"] = used
                            check["finding"] += f" However, LC has established {', '.join(used[:3])} under this heading, so LC applies --{t} here; the H 1100 sec. D exclusion does not bar this string."
                        if mixed:
                            check["finding"] += f" {main} is also a class of persons by another BT path ({mixed.get('also_classes_of_persons_via')})."
                    out.append(check)
        # H 830 sec. A / H 1075 sec. C.2 / H 475: a place may follow only an element coded (May Subd Geog), or an established [prefix]--[place]
        for ch in report.get("geographic_chains") or []:
            first_place = ch["given"][0]
            k = texts.index(first_place) if first_place in texts else -1
            if k < 0 or subs[k].get("established_under_prefix", {}).get("established") or subs[k].get("part_of_free_floating_string"):
                continue
            if k > 0 and subs[k - 1].get("established_under_prefix", {}).get("may_subd_geog") is False and subs[k - 1]["classified_as"] == "topical":
                est = "--".join([main] + texts[:k])
                prev = subs[k - 1]
                ffl = (prev.get("free_floating") or {}).get("free_floating_list") or []
                list_geog = any(e.get("may_subd_geog") for e in ffl)  # the free-floating list codes the subdivision (May Subd Geog) although LC's record does not
                out.append({"rule": "H 830 sec. A; H 1075 sec. C.2", "severity": "warning" if list_geog else "error", "elements": [texts[k - 1], first_place],
                            "finding": f"LC coded the established string {est} ({prev['established_under_prefix']['record_id']}) 'not subdivided geographically' (008/06 blank), so a place may not follow it. "
                                       + (f"The free-floating list entry for --{texts[k - 1]} is (May Subd Geog), so check which coding LC applies. " if list_geog else "")
                                       + (f"When the main heading allows geographic subdivision the place goes before the topical subdivision: {main}--{first_place}--{texts[k - 1]}." if (report["main_heading"].get("lcsh_exact") or [{}])[0].get("may_subd_geog") else "Express the place another way.")})
                continue
            if k == 0:
                mh = report["main_heading"]
                nm = mh.get("name_authority") or {}
                if report["main_heading"].get("lcsh_near_match"):
                    code = ""  # the NAF hit is a coincidence; the heading is really the LCSH form that differs only in hyphenation
                else:
                    code = str(nm.get("geog_subdiv_code_008_06") or "")
                if mh.get("lcsh_exact") and ch.get("preceding_element_may_subd_geog") is False:
                    out.append({"rule": "H 830 sec. A; H 1075 sec. C.2", "severity": "error", "elements": [main, first_place],
                                "finding": f"{main} is not coded (May Subd Geog), so a place may not follow it unless LC established {main}--{first_place}; it did not. Express the place another way (e.g. [place]--{main} if that pattern is established, a qualified heading, or a separate heading)."})
                elif nm.get("found") and code.startswith("n"):
                    out.append({"rule": "H 475 sec. 1-2; H 830 sec. A", "severity": "error", "elements": [main, first_place],
                                "finding": f"The name authority record for {main} is coded 008/06 'n' (not subdivided geographically), so --{first_place} may not follow it."})
            else:
                prev = subs[k - 1]
                if prev["classified_as"] != "topical":
                    continue
                ffl = (prev.get("free_floating") or {}).get("free_floating_list") or []
                recs = [r for r in (prev.get("lcsh_subdivision_records") or []) if r.get("tag") == "180"]
                if prev.get("established_under_prefix", {}).get("may_subd_geog") is True:
                    continue  # LC established [prefix]--[this subdivision] and coded it (May Subd Geog), e.g. Copyright--Art: the record outranks the list
                if (ffl or recs) and not any(e.get("may_subd_geog") for e in ffl) and not any(r.get("may_subd_geog") for r in recs):
                    out.append({"rule": "H 1095 sec. E.5; H 1075 sec. D.2", "severity": "error", "elements": [prev["text"], first_place],
                                "finding": f"--{prev['text']} is not coded (May Subd Geog), so a place may not follow it. When the main heading allows geographic subdivision the place goes before the topical subdivision: {main}--{first_place}--{prev['text']}."})
        # H 373 / H 1095 sec. E.2: a precoordinated prefix of the string that the authority file records as a UF (see-from) of another
        # heading, e.g. 'Science--Research' -> Research, 'Public administration--Law and legislation' -> Administrative law
        for k in range(1, len(texts) + 1):
            prefix = "--".join([main] + texts[:k])
            if self.db.lookup_exact(prefix, subdivisions=False):
                continue
            targets = [v for v in self.db.lookup_variant(prefix) if v.get("authorized") and not v.get("deprecated") and v.get("kind") != "subdivision_topical"]
            if targets:
                out.append({"rule": "H 373; H 1095 sec. E.2", "severity": "error", "elements": [main] + texts[:k],
                            "finding": f"'{prefix}' is a UF (see-from) reference to the established heading '{targets[0]['label']}' ({targets[0]['id']}); the authority file directs that form, so the string may not be built with '{prefix}'."})
                break
        # H 830 sec. C: the chain given must match the authorized 781 subdivision form of the final place
        for ch in report.get("geographic_chains") or []:
            if ch.get("matches_authorized_form") is False and ch.get("expected_chain"):
                fp = ch.get("final_place") or {}
                if fp.get("resolved_candidate") or fp.get("note"):
                    continue  # another authority record fits the given chain, or it was resolved by first-level place
                out.append({"rule": "H 830 sec. C.1, C.5, C.6", "severity": "error", "elements": list(ch["given"]),
                            "finding": f"The geographic chain {'--'.join(ch['given'])} does not match the authorized subdivision form of the final place, {'--'.join(ch['expected_chain'])} (781 field / H 830: interpose the country or first-order division, delete qualifiers). Use {'--'.join(ch['expected_chain'])}."})
        # H 620 sec. 3.d: a bare century subdivision right after a place is free-floating only under art, language, literary-author-group, literature and music headings
        art_sheets = {"H 1148", "H 1154", "H 1155.2", "H 1156", "H 1160"}
        hint_sheets = {h.get("sheet") for h in (report["main_heading"].get("category_hints") or [])}
        for i, n in enumerate(norms):
            if i > 0 and re.match(r"^\d{1,2}(?:st|nd|rd|th) century$", n) and subs[i - 1]["classified_as"] == "geographic" and main_is_topical:
                if subs[i].get("established_under_prefix", {}).get("established") or hint_sheets & art_sheets:
                    continue
                if any(c for c in out if c["rule"].startswith("H 1647 sec. 2.b") and texts[i] in c["elements"]):
                    continue
                out.append({"rule": "H 620 sec. 3.d; H 1647 sec. 2.b", "severity": "error", "elements": [texts[i - 1], texts[i]],
                            "finding": f"--{texts[i]} directly after the place --{texts[i - 1]} is not established under {'--'.join([main] + texts[:i])}, and a bare century subdivision is free-floating only under art, language, literary-author-group, literature and musical-composition headings; {main} shows no such category. Under a topical heading the century follows --History: {'--'.join([main] + texts[:i])}--History--{texts[i]}."})
        # H 1155.2 (Period subdivisions note): no period subdivision under a group-of-literary-authors heading that has a geographic subdivision
        if "H 1155.2" in hint_sheets:
            for i, n in enumerate(norms):
                if i > 0 and subs[i - 1]["classified_as"] == "geographic" and re.match(r"^(\d{1,2}(?:st|nd|rd|th) century|old english, ca\. 450-1100|middle english, 1100-1500|early modern, 1500-1700)$", n) \
                        and not subs[i].get("established_under_prefix", {}).get("established"):
                    out.append({"rule": "H 1155.2 (Period subdivisions note)", "severity": "error", "elements": [texts[i - 1], texts[i]],
                                "finding": f"Period subdivisions are not used under a heading for a group of literary authors that has a geographic subdivision ({main}--{texts[i - 1]}); drop the period or the place: {'--'.join([main] + [t for j, t in enumerate(texts) if j != i])} or {'--'.join([main] + [t for j, t in enumerate(texts) if j != i - 1])}."})
        # H 1647 sec. 1 / H 1250 sec. D.1: --History is not used under art genre headings qualified by a national, ethnic or religious group
        # (Art, Mexican--20th century, not Art, Mexican--History--20th century); style/period qualifiers (Art, Modern) are not groups
        m_art = re.match(r"^(?:Art|Arts|Painting|Sculpture|Drawing|Prints|Engraving|Decorative arts|Pottery|Ceramics|Jewelry|Mosaics|Folk art|Calligraphy|Wood-carving), ([A-Z][^,()]+)$", main)
        if "H 1148" in hint_sheets and m_art and m_art.group(1).strip() not in self.ART_STYLE_QUALIFIERS and "history" in norms:
            i = norms.index("history")
            if not subs[i].get("established_under_prefix", {}).get("established"):
                rest = [t for j, t in enumerate(texts) if j != i]
                out.append({"rule": "H 1647 sec. 1; H 1250 sec. D.1", "severity": "error", "elements": [main, texts[i]],
                            "finding": f"--History is not used under art genre headings qualified by a national, ethnic or religious group ({main}); period subdivisions follow the heading directly. Use {'--'.join([main] + rest)}."})
        # H 1156 sec. B, E.1: under literatures and literary genres the period subdivision comes directly after the heading, before --History and criticism
        if hint_sheets & {"H 1156", "H 1160"}:
            lit = "H 1156" in hint_sheets
            for i, n in enumerate(norms):
                if i > 0 and norms[i - 1] == "history and criticism" and (re.match(r"^\d{1,2}(?:st|nd|rd|th) century$", n) or re.match(r"^(to \d+|.*\b\d{3,4}-\d{3,4})$", n)):
                    out.append({"rule": "H 1156 sec. B, E.1; H 1075 sec. D" if lit else "H 1160 (order: place, period, topic, form); H 1075 sec. D", "severity": "error", "elements": [texts[i - 1], texts[i]],
                                "finding": f"Under a {'literature' if lit else 'music'} heading the period subdivision comes before --History and criticism: {'--'.join([main] + texts[:i - 1] + [texts[i], texts[i - 1]])}, not {'--'.join([main] + texts[:i + 1])}."})
        # H 860 sec. 2 / H 1075 sec. D.2: a topical subdivision that is itself (May Subd Geog) takes the place after it, not before it
        for i, sub in enumerate(subs):
            if i == 0 or sub["classified_as"] != "topical" or subs[i - 1]["classified_as"] != "geographic":
                continue
            if sub.get("established_under_prefix", {}).get("established") or sub.get("part_of_free_floating_string"):
                continue
            ffl = (sub.get("free_floating") or {}).get("free_floating_list") or []
            recs = sub.get("lcsh_subdivision_records") or []
            msg = any(e.get("may_subd_geog") for e in ffl) or any(r.get("tag") == "180" and r.get("may_subd_geog") for r in recs)
            if not msg or not (ffl or recs):
                continue
            # the preceding run of places must sit directly after the main heading (or after a non-geographic element that is not itself the issue)
            j = i - 1
            while j >= 0 and subs[j]["classified_as"] == "geographic":
                j -= 1
            places = [t["text"] for t in subs[j + 1:i]]
            out.append({"rule": "H 860 sec. 2; H 1075 sec. D.2", "severity": "error", "elements": places + [sub["text"]],
                        "finding": f"--{sub['text']} is itself authorized for geographic subdivision, so the place follows it: {'--'.join([main] + texts[:j + 1] + [sub['text']] + places)}. Putting the place before a (May Subd Geog) topical subdivision is the prescribed-order error of H 860 sec. 2 / H 1075 sec. D.2, unless LC established the string in this order."})
        # H 1095 usage: --In literature, --In art, --In motion pictures ... are used under names (persons, places, bodies, deities...), not under plain topical headings
        if main_is_topical and norms and norms[0] in self.PHRASE_SUBDIVS and not any(c for c in (report["main_heading"].get("category_hints") or [])):
            if not any(k in (report["main_heading"].get("lcsh_exact") or [{}])[0].get("label", "").lower() for k in ("deity", "legendary character", "fictitious character", "mythology")):
                t = texts[0]
                out.append({"rule": "H 1095 (usage of --" + t + "); H 1627", "severity": "error", "elements": [main, t],
                            "finding": f"--{t} is free-floating only under names of persons, families, corporate bodies, places, deities, legendary and fictitious characters and sacred works; {main} is a plain topical heading. For a topic the relationship is expressed by a phrase heading ('{main} {self.PHRASE_SUBDIVS[norms[0]]}'), which must be established, not by the subdivision."})
        # H 1690 / H 1075 sec. C.4: juvenile form subdivisions are the last element (only another juvenile form may follow)
        juvenile = {"juvenile literature", "juvenile fiction", "juvenile drama", "juvenile poetry", "juvenile films", "juvenile sound recordings",
                    "juvenile software", "juvenile humor"}
        for i, n in enumerate(norms):
            if n in juvenile and i < len(norms) - 1 and norms[i + 1] not in juvenile:
                out.append({"rule": "H 1690 sec. 1; H 1075 sec. C.4", "severity": "error", "elements": [texts[i], texts[i + 1]],
                            "finding": f"--{texts[i]} is a form subdivision for juvenile materials and is the final element of a string; --{texts[i + 1]} may not follow it. Put the topical and geographic subdivisions before the juvenile form subdivision."})
        # H 1647 sec. 2.b / H 1140 note: free-floating century subdivisions only where they do not conflict with established period subdivisions
        for i, n in enumerate(norms):
            mc = re.match(r"^(\d{1,2})(?:st|nd|rd|th) century$", n)
            if not mc or i == 0:
                continue
            prefix = "--".join([main] + texts[:i])
            if subs[i].get("established_under_prefix", {}).get("established"):
                continue
            c = int(mc.group(1))
            lo, hi = 100 * (c - 1) + 1, 100 * c
            conflicts = []
            for u in self.db.established_under(prefix, limit=400):
                e = u["next_element"].strip()
                ms = re.match(r"^(?:ca\. )?(\d{3,4})-(\d{3,4})?$", e)
                mt = re.match(r"^To (\d{3,4})$", e)
                mcent = re.match(r"^(\d{1,2})(?:st|nd|rd|th) century$", e)
                if ms:
                    a, b = int(ms.group(1)), int(ms.group(2)) if ms.group(2) else 9999
                elif mt:
                    a, b = 0, int(mt.group(1))
                elif mcent:
                    continue  # another century established directly: no conflict, the pattern is in use
                else:
                    continue
                if a <= hi and b >= lo:
                    conflicts.append(e)
            if conflicts:
                out.append({"rule": "H 1647 sec. 2.b (H 1140 note)", "severity": "error", "elements": [texts[i - 1], texts[i]],
                            "finding": f"The free-floating century subdivision --{texts[i]} overlaps period subdivisions already established under {prefix} ({', '.join(conflicts[:6])}); H 1647 sec. 2.b assigns free-floating century subdivisions only where there is no conflict with established chronological subdivisions. Use the established period.",
                            "established_periods": conflicts[:10]})
        return out
