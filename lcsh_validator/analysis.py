"""Deterministic analysis of a parsed heading: lookups, classification, literal checks.

Produces a JSON-serializable "facts" report that the Haiku agent reasons over.
"""
from __future__ import annotations

import re

from .db import LCSHDB
from .freefloating import FreeFloating
from .parse import ParsedHeading, normalize_label

CHRONO_RE = re.compile(
    r"^(To \d{1,4}( B\.C\.)?|\d{1,4}( B\.C\.)?-(\d{1,4}( A\.D\.)?)?|\d{1,2}(st|nd|rd|th) century( B\.C\.)?|"
    r"\d{3,4}|.+, \d{3,4}(-\d{1,4})?|.+, \d{1,4} B\.C\.(-\d{1,4}( A\.D\.)?)?|\d{4}-\d{4}|\d{4}-|.*\(\d{4}-\d{4}\)|\d{1,2}(st|nd|rd|th)-\d{1,2}(st|nd|rd|th) centur(y|ies))$"
)
LOWER_OK = {"e-mail", "iPhone", "iPad", "eBay", "pH", "mRNA", "p-adic", "de", "van", "von"}


def _summ(h: dict) -> dict:
    """Compact record summary for the report."""
    return {k: h.get(k) for k in ("id", "label", "kind_label", "authorized", "deprecated", "may_subd_geog", "scope_note", "history_note",
                                  "example_note", "editorial_note", "pattern_collections", "use_instead", "earlier_forms", "gac") if h.get(k) not in (None, "", [], 0)}


class Analyzer:
    def __init__(self, db: LCSHDB, ff: FreeFloating):
        self.db = db
        self.ff = ff

    # ------------------------------------------------------------------ main heading
    def main_heading(self, text: str, tag: str | None) -> dict:
        out: dict = {"text": text}
        exact = [h for h in self.db.lookup_exact(text, subdivisions=False)]
        auth = [h for h in exact if h["authorized"] and not h["deprecated"]]
        dep = [h for h in exact if h["deprecated"]]
        out["lcsh_exact"] = [_summ(h) for h in auth]
        out["lcsh_deprecated"] = [dict(_summ(h), use_instead_labels=[self.db.label_of(u) for u in h.get("use_instead", [])]) for h in dep]
        variants = self.db.lookup_variant(text)
        out["lcsh_variant_of"] = [dict(_summ(h), matched_variant=h["matched_variant"]) for h in variants if not h["is_complex"]]
        if auth:
            h = auth[0]
            out["category_hints"] = self.db.category_hints(h["id"])
            out["broader_terms"] = [self.db.label_of(b) for b in h.get("broader", []) if not str(b).startswith("label:")][:6]
            out["established_strings_under_heading_sample"] = [e["example"] for e in self.db.established_under(h["label"], limit=25)]
        # Name authority file (jurisdictions, persons, corporate bodies, titles, named entities)
        want_name = tag in ("600", "610", "611", "630", "651") or not (auth or dep or variants)
        if want_name:
            nm = self.db.lookup_name(text)
            if nm.get("found") or nm.get("candidates"):
                out["name_authority"] = {k: v for k, v in nm.items() if k in ("found", "id", "label", "kind", "geographic_subdivision_form", "notes", "entity_type", "matched_as", "candidates", "gac", "place_associated")}
                if nm.get("found") and nm.get("variants"):
                    out["name_authority"]["variants_sample"] = nm["variants"][:5]
        if not (auth or dep or variants or out.get("name_authority", {}).get("found")):
            phrase = self.phrase_candidate(text)
            if phrase:
                out["free_floating_phrase_candidate"] = phrase
            online = self.db.lookup_subject_online(text)
            if online.get("found"):
                out["lcsh_online_only"] = online
            out["suggestions"] = [{"label": h["label"], "kind": h["kind_label"]} for h in self.db.search(text, limit=8) if not h["is_complex"]][:8]
        return out

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

    # ------------------------------------------------------------------ geography
    def resolve_place(self, text: str, context: list[str] | None = None) -> dict:
        """Resolve a place name; `context` is the chain of geographic elements given before it (for disambiguating bare names)."""
        res: dict = {"text": text}
        context = context or []
        lc = [h for h in self.db.lookup_exact(text, subdivisions=False) if h["kind"] == "geographic" and h["authorized"]]
        if lc:
            res["lcsh_geographic_heading"] = _summ(lc[0])
            forms = self.db.geographic_subdivision_form(lc[0]["label"])
            if forms:
                res["authorized_subdivision_form"] = forms[0]["form"]
        nm = self.db.lookup_name(text)
        if nm.get("found") and not str(nm.get("kind", "")).startswith("geographic"):
            res["name_authority_non_place"] = {"label": nm.get("label"), "kind": nm.get("kind")}
            nm = {"found": False}
        if nm.get("found"):
            res["name_authority"] = {k: v for k, v in nm.items() if k in ("id", "label", "kind", "geographic_subdivision_form", "entity_type", "matched_as", "gac")}
            if nm.get("geographic_subdivision_form"):
                res.setdefault("authorized_subdivision_form", nm["geographic_subdivision_form"])

        # 181 record by its own label (e.g. "Washington (D.C.)" used directly)
        if "authorized_subdivision_form" not in res:
            forms = self.db.geographic_subdivision_form(text)
            if forms:
                res["authorized_subdivision_form"] = forms[0]["form"]
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
                    chain["preceding_element_may_subd_geog"] = bool(prev[0]["may_subd_geog"])
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
        # whole string / longest established prefix
        whole = [h for h in self.db.lookup_exact(parsed.string) if h["authorized"]]
        report["whole_string_established"] = [_summ(h) for h in whole][:2]
        longest = None
        for k in range(len(elements), 1, -1):
            pref = "--".join(elements[:k])
            hits = [h for h in self.db.lookup_exact(pref) if h["authorized"]]
            if hits:
                longest = {"prefix": pref, "id": hits[0]["id"], "elements_covered": k, "remaining_free_floating_candidates": elements[k:]}
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
        return report
