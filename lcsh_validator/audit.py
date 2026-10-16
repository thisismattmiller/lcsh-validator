"""Mechanical checks on the model's verdict: do the rules it cites exist, is a subdivision cited to a list it is on,
and did a usage doubt ignore a clause of the usage statement that names the heading's type?

Each check returns a list of problem dicts. The agent sends them back to the model once; whatever is still wrong
afterwards is scrubbed (a cataloger must never be sent to a sheet that does not exist)."""
from __future__ import annotations

import re

from .freefloating import FreeFloating
from .parse import normalize_label
from .rules import Rules, sheet_key

SHEET_RE = re.compile(r"\bH\s?(\d{2,4}(?:\.\d+)?)\b")
APPENDIX_RE = re.compile(r"\bAppendix\s+([A-H])\b", re.I)
SUBDIV_RE = re.compile(r"--([A-Z][^;.()\"\[\]]*)")

# fields of the verdict that carry citations, with a path for the report
_TEXT_FIELDS = ("explanation",)


def _cited_texts(verdict: dict):
    for i, iss in enumerate(verdict.get("issues") or []):
        if isinstance(iss, dict):
            yield f"issues[{i}].rule", str(iss.get("rule") or "")
            yield f"issues[{i}].problem", str(iss.get("problem") or "")
    for i, el in enumerate(verdict.get("elements") or []):
        if isinstance(el, dict):
            yield f"elements[{i}].basis", str(el.get("basis") or "")
    for f in _TEXT_FIELDS:
        yield f, str(verdict.get(f) or "")
    for i, n in enumerate(verdict.get("lc_practice_notes") or []):
        yield f"lc_practice_notes[{i}]", str(n)


def sheets_in(text: str) -> list[str]:
    out = [sheet_key("H " + m) for m in SHEET_RE.findall(text)]
    out += [f"Appendix {m.upper()}" for m in APPENDIX_RE.findall(text)]
    return out


class CitationAuditor:
    def __init__(self, rules: Rules, ff: FreeFloating):
        self.rules = rules
        self.ff = ff
        # sheet -> normalized subdivision labels on that SHM list
        self.list_members: dict[str, set[str]] = {}
        for sheet, d in ff.lists.items():
            self.list_members[sheet] = {normalize_label((e.get("subdivision") or e.get("pattern") or "").lstrip("-")) for e in d.get("entries", [])} - {""}
        # from LC's free-floating list proper: subdivision -> controlling sheets
        for n, entries in ff.by_norm.items():
            for e in entries:
                if e.get("reference"):
                    continue
                for s in e.get("sheets", []):
                    self.list_members.setdefault(s, set()).add(n)
        self.known: set[str] = set(ff.by_norm) | set(ff.list_by_norm)

    def sheet_exists(self, sheet: str) -> bool:
        return self.rules.get(sheet) is not None or self.ff.sheet_entries(sheet) is not None

    def lists_with(self, norm: str) -> list[str]:
        return sorted(s for s, members in self.list_members.items() if norm in members)

    _NEG = re.compile(r"\b(not|no|neither|nor|never|exclud\w*|without|lacks?|missing|absent)\b", re.I)

    def _subdivisions_cited_to(self, clause: str, cited_lists: list[str]) -> list[str]:
        """Known subdivisions that the clause ties to a cited list: written as a free-standing --X (not the tail of a
        heading string like Housing--Finance or a template like [part of the body]--Diseases), within 90 characters of
        the sheet token, with no negation in between ('H 1164 (--Popular works is not on it)' is not a citation)."""
        sheet_spans = [(m.start(), m.end()) for m in SHEET_RE.finditer(clause) if sheet_key("H " + m.group(1)) in cited_lists]
        out = []
        for m in SUBDIV_RE.finditer(clause):
            if m.start() > 0 and not clause[m.start() - 1].isspace() and clause[m.start() - 1] not in "(\"'":
                continue
            words = [w.strip("'\"’‘“”") for w in m.group(1).strip().split()]
            words = [w for w in words if w]
            norm = None
            for k in range(min(7, len(words)), 0, -1):
                cand = normalize_label(" ".join(words[:k]).rstrip(" ,-"))
                if cand in self.known:
                    norm = cand
                    break
            if not norm:
                continue
            for a, b in sheet_spans:
                gap = m.start() - b if b <= m.start() else a - m.end()
                window = clause[min(a, m.start()):max(b, m.end()) + 40]
                if gap <= 90 and not self._NEG.search(window):
                    out.append(norm)
                    break
        return out

    def audit(self, verdict: dict) -> list[dict]:
        problems: list[dict] = []
        seen: set[tuple] = set()
        for where, text in _cited_texts(verdict):
            for sheet in sheets_in(text):
                if not self.sheet_exists(sheet) and ("unknown_sheet", sheet) not in seen:
                    seen.add(("unknown_sheet", sheet))
                    problems.append({"kind": "unknown_sheet", "sheet": sheet, "where": where})
            if not where.endswith((".rule", ".basis")):
                continue  # list-membership check only on the citation fields, where sheet and subdivision are tied
            for clause in re.split(r";", text):
                cited_lists = [s for s in sheets_in(clause) if s in self.list_members]
                if not cited_lists:
                    continue
                for norm in self._subdivisions_cited_to(clause, cited_lists):
                    on = self.lists_with(norm)
                    if on and not any(norm in self.list_members[s] for s in cited_lists):
                        key = ("not_on_list", norm, tuple(cited_lists))
                        if key not in seen:
                            seen.add(key)
                            problems.append({"kind": "not_on_list", "subdivision": "--" + norm, "cited": cited_lists, "on_lists": on, "where": where})
        return problems


def audit_usage(verdict: dict, facts: dict) -> list[dict]:
    """A warning/error about a free-floating subdivision whose usage statement names the heading's type by a general
    clause (e.g. '... and topical headings ...') that the issue text does not acknowledge."""
    problems = []
    cov = {}
    for s in facts.get("subdivisions") or []:
        c = s.get("usage_coverage")
        if c and c.get("general_clause"):
            cov[normalize_label(s["text"])] = (s["text"], c)
    for i, iss in enumerate(verdict.get("issues") or []):
        if not isinstance(iss, dict) or iss.get("severity") not in ("warning", "error"):
            continue
        el = normalize_label(str(iss.get("element") or "").lstrip("-").split("--")[-1])
        if el not in cov:
            continue
        text, c = cov[el]
        blob = (str(iss.get("problem") or "") + " " + str(iss.get("rule") or "")).lower()
        if not re.search(r"usage|names? (only )?(types|names|individual|corporate|classes|activities|categor)|does not (clearly )?(name|cover|include)|not clearly|pattern categor", blob):
            continue
        phrase = c["phrase"].lower()
        if phrase in blob and re.search(r"\b(covers|names|includes|authoriz)", blob):
            continue  # the model saw the clause and still doubts for another reason: let it stand
        problems.append({"kind": "usage_clause_ignored", "element": text, "heading_type": c["heading_type"], "clause": c["general_clause"], "where": f"issues[{i}]"})
    return problems


_PLACE_CLAIM = re.compile(r"may subd geog|subdivided geographically|geographic subdivision|(?:cannot|can not|may not|must not|not allowed to|is not permitted to) (?:follow|be placed|come|appear)|place (?:cannot|may not|can not)|not .{0,30}coded", re.I)


def audit_place_claims(verdict: dict, facts: dict) -> list[dict]:
    """An error/warning that says a place may not stand where it is, when the facts' geographic chain shows the
    place follows an element coded (May Subd Geog) in its authorized form."""
    problems = []
    for chain in facts.get("geographic_chains") or []:
        if not (chain.get("preceding_element_may_subd_geog") and chain.get("matches_authorized_form")):
            continue
        place = chain["given"][0]
        prev = chain.get("preceded_by")
        for i, iss in enumerate(verdict.get("issues") or []):
            if not isinstance(iss, dict) or iss.get("severity") not in ("warning", "error"):
                continue
            blob = str(iss.get("element") or "") + " " + str(iss.get("problem") or "")
            if place.lower() in blob.lower() and _PLACE_CLAIM.search(blob):
                problems.append({"kind": "place_claim_contradicts_facts", "place": place, "preceded_by": prev, "where": f"issues[{i}]"})
    return problems


def pushback_message(problems: list[dict]) -> str:
    lines = ["Before this verdict is accepted, correct the following. Re-check with get_rule / lookup_subdivision as needed and then return the complete corrected JSON verdict (same shape)."]
    for p in problems:
        if p["kind"] == "unknown_sheet":
            lines.append(f"- You cite {p['sheet']} ({p['where']}). There is no such sheet in the Subject Headings Manual. Cite only a sheet you have read with get_rule or search_rules, or remove the citation. Never send a cataloger to a sheet that does not exist.")
        elif p["kind"] == "not_on_list":
            lines.append(f"- You cite {', '.join(p['cited'])} for {p['subdivision']} ({p['where']}), but that subdivision has no entry on {'that list' if len(p['cited']) == 1 else 'those lists'}. It is listed on {', '.join(p['on_lists'])}. Cite the list it is actually on and re-read that entry's usage statement.")
        elif p["kind"] == "place_claim_contradicts_facts":
            lines.append(f"- Your {p['where']} says the place {p['place']} may not stand where it is. The facts' geographic_chains show that {p['place']} directly follows --{p['preceded_by']}, which is coded (May Subd Geog), and that it is in its authorized subdivision form. Re-read the element order; if you keep the issue, name the element the place actually follows and quote the coding fact that bars it.")
        elif p["kind"] == "usage_clause_ignored":
            lines.append(f"- Your {p['where']} doubts --{p['element']} on its usage statement, but that statement also says: \"{p['clause']}\". The main heading is a {p['heading_type']} heading, so that clause names its type. Read the whole usage statement; if the clause covers this heading and no 'Do not use' note or special sheet excludes it, drop the doubt and judge the string valid on that point. If you still doubt it, quote the words of the usage statement or special sheet that exclude this heading.")
    return "\n".join(lines)


def scrub_unknown_sheets(verdict: dict, problems: list[dict]) -> list[str]:
    """Remove citations to sheets that do not exist from every text field; returns the sheets removed."""
    bad = [p["sheet"] for p in problems if p["kind"] == "unknown_sheet"]
    if not bad:
        return []
    pat = re.compile(r"\b(" + "|".join(re.escape(b).replace(r"H\ ", r"H\s?") for b in bad) + r")(\s*(?:sec(?:tion)?\.?\s*[\w.()-]+))?", re.I)

    def fix(s):
        return pat.sub(lambda m: f"[citation to {sheet_key(m.group(1))} removed: no such SHM sheet]", s) if isinstance(s, str) else s

    for iss in verdict.get("issues") or []:
        if isinstance(iss, dict):
            for k in ("rule", "problem", "fix"):
                iss[k] = fix(iss.get(k))
    for el in verdict.get("elements") or []:
        if isinstance(el, dict):
            el["basis"] = fix(el.get("basis"))
    verdict["explanation"] = fix(verdict.get("explanation"))
    verdict["lc_practice_notes"] = [fix(n) for n in verdict.get("lc_practice_notes") or []]
    return bad
