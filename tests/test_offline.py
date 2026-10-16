"""Offline tests (no API, no network): parser, free-floating list, rules, analyzer against the local DB."""
import json

import pytest

from lcsh_validator.parse import parse_heading, normalize_label


def test_parse_plain():
    p = parse_heading("Tacos--History--20th century.")
    assert p.main == "Tacos"
    assert [c.text for c in p.subdivisions] == ["History", "20th century"]
    assert p.string == "Tacos--History--20th century"


def test_parse_marc():
    p = parse_heading("650 _0 $a Taxation $z France $z Paris.")
    assert p.tag == "650"
    assert [(c.code, c.text) for c in p.subdivisions] == [("z", "France"), ("z", "Paris")]


def test_parse_name_marc():
    p = parse_heading("600 10 $a Shakespeare, William, $d 1564-1616 $x Criticism and interpretation.")
    assert p.main == "Shakespeare, William, 1564-1616"
    assert p.subdivisions[0].role == "topical"


def test_normalize():
    assert normalize_label("Taxation — France") == "taxation--france"
    assert normalize_label("Comic books, strips, etc.") == "comic books, strips, etc."


@pytest.fixture(scope="module")
def db():
    from lcsh_validator.db import LCSHDB
    return LCSHDB(online=False)


def test_db_lookup(db):
    h = db.lookup_exact("Tacos")[0]
    assert h["kind"] == "topic" and h["may_subd_geog"] == 1


def test_db_variant(db):
    assert db.lookup_variant("Mormon handcart companies")[0]["label"] == "Latter Day Saint handcart companies"


def test_established_under(db):
    nxt = {e["next_element"] for e in db.established_under("United States--History")}
    assert "Civil War, 1861-1865" in nxt


def test_free_floating():
    from lcsh_validator.freefloating import FreeFloating
    ff = FreeFloating()
    r = ff.lookup("History")
    assert any("topical" in e["types"] for e in r["free_floating_list"])
    assert "H 1095" in [c["sheet"] for c in r["controlling_sheets"]]


def test_rules():
    from lcsh_validator.rules import Rules
    r = Rules()
    assert r.get("H 1075")["title"] == "Subdivisions"
    assert r.validation_rules("H 830")
    assert r.get("H1145_5") is not None
    assert r.index_lookup("Metropolitan areas")


def test_analyzer_offline(db):
    from lcsh_validator.analysis import Analyzer
    from lcsh_validator.freefloating import FreeFloating
    a = Analyzer(db, FreeFloating())
    rep = a.analyze(parse_heading("Tacos--History--20th century"))
    assert rep["main_heading"]["lcsh_exact"][0]["label"] == "Tacos"
    assert rep["subdivisions"][0]["classified_as"] == "topical"
    assert rep["subdivisions"][1]["classified_as"] == "chronological"
    json.dumps(rep, default=str)


@pytest.fixture(scope="module")
def analyzer(db):
    from lcsh_validator.analysis import Analyzer
    from lcsh_validator.freefloating import default_ff
    return Analyzer(db, default_ff())


def _checks(analyzer, heading):
    return [(c["rule"], c["severity"]) for c in analyzer.analyze(parse_heading(heading))["rule_checks"]]


def test_rule_check_h1647_sec9(analyzer):
    assert ("H 1647 sec. 9", "error") in _checks(analyzer, "Lima (Peru)--Social conditions--History--17th century")
    assert _checks(analyzer, "Japan--Population--History") == []


def test_rule_check_h1642(analyzer):
    assert ("H 1642 sec. 1-2", "error") in _checks(analyzer, "Agriculture--Government policy--India")
    assert _checks(analyzer, "Smart cities--Government policy") == []


def test_rule_check_phrase_conflict(analyzer):
    assert ("H 1095 sec. E.2", "error") in _checks(analyzer, "Social justice--In motion pictures")
    # the phrase form was cancelled for this deity, so the subdivision form is the current one
    assert _checks(analyzer, "Dionysus (Greek deity)--In literature") == []


def test_rule_check_h1100_social_class(analyzer):
    assert ("H 1100 sec. D", "error") in _checks(analyzer, "Nobility--Social life and customs")
    # --Political activity's usage names classes of persons, corporate bodies etc., not topical headings in general
    assert ("H 1100 sec. D", "error") in _checks(analyzer, "Nobility--Political activity--Poland")


def test_rule_check_century_conflict(analyzer):
    # Peru--Politics and government has established periods (…, 1980-, 2000-): a free-floating century conflicts
    assert ("H 1647 sec. 2.b (H 1140 note)", "error") in _checks(analyzer, "Peru--Politics and government--21st century")
    assert _checks(analyzer, "Technology--France--History--20th century") == []


def test_free_floating_strings(analyzer):
    r = analyzer.analyze(parse_heading("Horsemanship--History--To 1500"))
    assert [f["string"] for f in r["free_floating_strings"]] == ["History--To 1500"]


def test_rule_check_juvenile_last(analyzer):
    assert ("H 1690 sec. 1; H 1075 sec. C.4", "error") in _checks(analyzer, "Women--Juvenile literature--Employment")
    assert _checks(analyzer, "Women--Employment--Juvenile literature") == []


def test_rule_check_place_before_geog_subdivision(analyzer):
    assert ("H 860 sec. 2; H 1075 sec. D.2", "error") in _checks(analyzer, "Art--Mongolia--Study and teaching")
    assert _checks(analyzer, "Art--Study and teaching--Mongolia") == []
    assert _checks(analyzer, "Education--United States--Finance") == []  # established in this order


def test_rule_check_in_literature_under_topic(analyzer):
    assert any(r.startswith("H 1095 (usage of --In literature)") for r, _ in _checks(analyzer, "Friendship--In literature"))
    assert _checks(analyzer, "Shakespeare, William, 1564-1616--In literature") == []
    # Outer space is a 151: --In literature is free-floating under places (85 established [place]--In literature strings)
    assert not [r for r, _ in _checks(analyzer, "Outer space--In literature") if "In literature" in r]


def test_multiple_not_matched_when_slot_is_a_subdivision():
    from lcsh_validator.freefloating import default_ff
    ff = default_ff()
    assert ff.lookup("Study and teaching--History")["matched_pattern"] is None
    assert ff.lookup("Paraphrases, French")["matched_pattern"] == "Paraphrases, English, [French, German, etc.]"


def test_rule_check_place_after_non_geog_heading(analyzer):
    assert ("H 830 sec. A; H 1075 sec. C.2", "error") in _checks(analyzer, "Authors--United States--Biography")
    assert ("H 830 sec. A; H 1075 sec. C.2", "error") in _checks(analyzer, "Commerce--Indonesia")
    assert _checks(analyzer, "Taxation--France--Paris") == []


def test_rule_check_place_after_non_geog_subdivision(analyzer):
    assert ("H 1095 sec. E.5; H 1075 sec. D.2", "error") in _checks(analyzer, "Caregivers--Social conditions--United States")
    assert _checks(analyzer, "Caregivers--United States--Social conditions") == []


def test_rule_check_chain_contradicts_781(analyzer):
    assert ("H 830 sec. C.1, C.5, C.6", "error") in _checks(analyzer, "Taxation--Germany--Paris (France)")


def test_rule_check_bare_century_after_place(analyzer):
    assert ("H 620 sec. 3.d; H 1647 sec. 2.b", "error") in _checks(analyzer, "Travel writing--Germany--21st century--History and criticism")
    assert _checks(analyzer, "Art, Chinese--China--20th century") == []


def test_region_heading_keeps_its_own_781(analyzer):
    # 'Andes Region' (sh87002893) has its own 181 'Andes Region'; the one generated from 'Andes Region (Venezuela)' must not win
    assert _checks(analyzer, "Indigenous women--Abuse of--Andes Region") == []
    assert analyzer.db.geographic_subdivision_form("Andes Region")[0]["form"] == "Andes Region"


def test_apostrophe_like_characters_fold_in_lookup(analyzer):
    assert [h["label"] for h in analyzer.db.lookup_exact("Shīʿah")] == ["Shīʻah"]
    notes = analyzer.analyze(parse_heading("Shīʿah--Doctrines"))["surface_checks"]
    assert any("authorized spelling is 'Shīʻah'" in n for n in notes)


def test_spaced_hyphen_before_year_is_a_date_not_a_separator():
    p = parse_heading("Weaver, Cheryl, - 2005--Health.")
    assert p.main == "Weaver, Cheryl, - 2005" and [c.text for c in p.subdivisions] == ["Health"]
    p = parse_heading("Art - France - History")
    assert p.main == "Art" and [c.text for c in p.subdivisions] == ["France", "History"]


def test_literature_headings_get_h1156_hint_and_period_order_check(analyzer):
    hints = {h["sheet"] for h in analyzer.db.category_hints(analyzer.db.lookup_exact("Turkish poetry", subdivisions=False)[0]["id"])}
    assert "H 1156" in hints
    assert ("H 1156 sec. B, E.1; H 1075 sec. D", "error") in _checks(analyzer, "Turkish poetry--History and criticism--21st century")
    assert _checks(analyzer, "Turkish poetry--21st century--History and criticism") == []


def test_rule_check_prefix_is_a_uf_reference(analyzer):
    assert ("H 373; H 1095 sec. E.2", "error") in _checks(analyzer, "Science--Research--Technological innovations")
    assert ("H 373; H 1095 sec. E.2", "error") in _checks(analyzer, "Public administration--Law and legislation")
    assert _checks(analyzer, "Education--Research--United States") == []


def test_bare_place_with_several_781s_takes_the_chain_given(analyzer):
    assert _checks(analyzer, "Quechua Indians--Peru--Sierra") == []
    assert _checks(analyzer, "Quechua Indians--Ecuador--Sierra") == []
    assert ("H 830 sec. C.1, C.5, C.6", "error") in _checks(analyzer, "Quechua Indians--Bolivia--Sierra")


def test_hyphenation_near_match_is_reported(analyzer):
    mh = analyzer.analyze(parse_heading("Water supply--Ethiopia"))["main_heading"]
    assert [h["label"] for h in mh.get("lcsh_near_match", [])] == ["Water-supply"]


def test_label_form_category_hints(analyzer):
    sheets = lambda lab: {h["sheet"] for h in analyzer.db.category_hints(analyzer.db.lookup_exact(lab, subdivisions=False)[0]["id"])}
    assert "H 1148" in sheets("Art, Arab")
    assert "H 1160" in sheets("Music") and "H 1160" in sheets("Popular music")
    assert ("H 1160 (order: place, period, topic, form); H 1075 sec. D", "error") in _checks(analyzer, "Music--Indonesia--History and criticism--21st century")
    assert _checks(analyzer, "Art, Arab--Oman--20th century") == []


def test_established_string_matched_only_after_case_folding_is_noted(analyzer):
    notes = analyzer.analyze(parse_heading("Korea--History--Japanese invasions, 1592-1598"))["surface_checks"]
    assert any("Japanese Invasions, 1592-1598" in n for n in notes)
    assert analyzer.analyze(parse_heading("Korea--History--Japanese Invasions, 1592-1598"))["surface_checks"] == []


def test_h1100_sec_d_is_a_warning_when_lc_applies_the_list_in_practice(analyzer):
    # Intellectuals: BT Persons and BT Social classes; LC established Intellectuals--Interviews and Intellectuals--Biography
    checks = analyzer.analyze(parse_heading("Intellectuals--India--Tamil Nadu--Interviews"))["rule_checks"]
    assert [(c["rule"], c["severity"]) for c in checks] == [("H 1100 sec. D", "note")]
    assert "Intellectuals--Interviews" in checks[0]["established_strings_using_this_subdivision"]
    # --Obituaries: no established string, but Intellectuals is also BT Persons -> a warning, not an error
    assert ("H 1100 sec. D", "warning") in _checks(analyzer, "Intellectuals--Yugoslavia--Obituaries")
    # Working class is an explicit H 1100 sec. D example with no other BT path and no established string: still an error
    assert ("H 1100 sec. D", "error") in _checks(analyzer, "Working class--Ecuador--Guayaquil--Social conditions")


def test_literary_author_groups_get_h1155_2_hint_by_label_form(analyzer):
    sheets = lambda lab: {h["sheet"] for h in analyzer.db.category_hints(analyzer.db.lookup_exact(lab, subdivisions=False)[0]["id"])}
    assert "H 1155.2" in sheets("Authors, Urdu") and "H 1155.2" in sheets("Poets, Urdu")
    # H 1155.2: no period subdivision after a geographic subdivision under a group of literary authors
    assert ("H 1155.2 (Period subdivisions note)", "error") in _checks(analyzer, "Authors, Urdu--Pakistan--20th century--Biography")
    assert _checks(analyzer, "Authors, Urdu--20th century--Biography") == []


def test_untraced_reference_and_deletion_note_are_surfaced(analyzer):
    mh = analyzer.analyze(parse_heading("Districts"))["main_heading"]
    assert mh["lcsh_exact"] == [] and mh["lcsh_untraced_reference"][0]["id"] == "sh2001000458"
    assert all(s["label"] != "Districts" for s in mh.get("suggestions", []))
    dep = analyzer.analyze(parse_heading("Kings, queens, rulers, etc.--Fiction"))["main_heading"]["lcsh_deprecated"]
    assert '"sj" prefix' in dep[0]["deletion_note"]


def test_bt_with_subdivision_still_reaches_a_category_root(analyzer):
    hid = analyzer.db.lookup_exact("Dalits", subdivisions=False)[0]["id"]
    assert "H 1103" in {h["sheet"] for h in analyzer.db.category_hints(hid)}


def test_established_prefix_reports_its_geographic_coding(analyzer):
    rep = analyzer.analyze(parse_heading("Murder--Investigation--Brazil--Alagoas--Case studies"))
    assert rep["longest_established_prefix"]["may_subd_geog"] is True and rep["rule_checks"] == []
    # Law--Philosophy (sh85075193) is coded 008/06 '|' (never evaluated): None, and the list coding of --Philosophy decides
    rep = analyzer.analyze(parse_heading("Law--Philosophy--France"))
    assert rep["longest_established_prefix"]["may_subd_geog"] is None
    assert ("H 1095 sec. E.5; H 1075 sec. D.2", "error") in [(c["rule"], c["severity"]) for c in rep["rule_checks"]]
    # a validation record ending in a place carries no such note: the next place continues the chain
    assert "note" not in analyzer.analyze(parse_heading("Education--Thailand--Narathiwat (Province)"))["longest_established_prefix"]


def test_history_under_nationally_qualified_art_heading_is_an_error(analyzer):
    assert ("H 1647 sec. 1; H 1250 sec. D.1", "error") in _checks(analyzer, "Art, Mexican--History--20th century")
    assert _checks(analyzer, "Art, Mexican--20th century") == []
    assert _checks(analyzer, "Art, Modern--20th century--History") == []  # style qualifier, and the string is established


def test_phrase_subdivision_is_allowed_under_a_geographic_main_heading(analyzer):
    # Antarctica is a 151: --On television is free-floating under places (H 1095), so no H 1627 error
    rep = analyzer.analyze(parse_heading("Antarctica--On television--History"))
    assert not [c for c in rep["rule_checks"] if "H 1627" in c["rule"]]
    rep = analyzer.analyze(parse_heading("Astronomy--On television"))
    assert [c for c in rep["rule_checks"] if "H 1627" in c["rule"] and c["severity"] == "error"]


def test_established_prefix_coded_may_subd_geog_allows_a_place_after_a_list_subdivision(analyzer):
    # Copyright--Art (sh85032450) is coded (May Subd Geog) although the H 1095 list entry for --Art is not
    rep = analyzer.analyze(parse_heading("Copyright--Art--Australia"))
    assert not [c for c in rep["rule_checks"] if c["severity"] == "error"]
    rep = analyzer.analyze(parse_heading("Corruption--Prevention--Brazil"))
    assert [c for c in rep["rule_checks"] if "H 1095 sec. E.5" in c["rule"] and c["severity"] == "error"]



def test_music_form_heading_recognised_through_its_broader_term(analyzer):
    # Musicals has no "music" in its label; its BT Dramatic music makes it an H 1160 music form, which takes
    # the H 1160 order geographic, chronological, topical (sec. 7) and the free-floating century subdivisions (sec. 4)
    rep = analyzer.analyze(parse_heading("Musicals--Australia--21st century--History and criticism"))
    assert "H 1160" in {h["sheet"] for h in rep["main_heading"]["category_hints"]}
    assert not [c for c in rep["rule_checks"] if "H 620 sec. 3.d" in c["rule"]]
    rep = analyzer.analyze(parse_heading("Music theory--Germany--20th century"))
    assert [c for c in rep["rule_checks"] if "H 620 sec. 3.d" in c["rule"]]


def test_place_after_an_uncoded_established_string_under_a_name_main_heading_does_not_crash(analyzer):
    # United States is a name heading (no LCSH record), and United States--History--Civil War, 1861-1865--Regimental histories
    # (sh85140267) is not coded (May Subd Geog) although the H 1200 list entry is: a warning, not a crash
    rep = analyzer.analyze(parse_heading("United States--History--Civil War, 1861-1865--Regimental histories--Missouri"))
    checks = [c for c in rep["rule_checks"] if "H 830 sec. A" in c["rule"]]
    assert checks and checks[0]["severity"] == "warning"


def test_geographic_coding_is_three_valued(analyzer):
    # 008/06 'i': True; blank: False; '|' (never evaluated) on an established string: None; a single-element heading without the coding: False
    assert analyzer.db.lookup_exact("Copyright--Art")[0]["may_subd_geog"] is True
    assert analyzer.db.lookup_exact("United States--History--Civil War, 1861-1865--Regimental histories")[0]["may_subd_geog"] is False
    assert analyzer.db.lookup_exact("Art, Modern--19th century")[0]["may_subd_geog"] is None
    assert analyzer.db.lookup_exact("Technocracy")[0]["may_subd_geog"] is False
    # coded blank after the 2015 snapshot (sh85072414 changed 2019): the per-record backfill from id.loc.gov carries it
    assert analyzer.db.lookup_exact("Kings and rulers--Abdication")[0]["may_subd_geog"] is False
    assert analyzer.db.lookup_exact("Kings and rulers--Abdication")[0]["geog_code"] == " "
    rep = analyzer.analyze(parse_heading("Dementia--Patients--Care--India"))
    e = rep["subdivisions"][1]["established_under_prefix"]
    assert e["may_subd_geog"] is None and "never coded" in e["may_subd_geog_note"]
    assert not [c for c in rep["rule_checks"] if c["severity"] == "error"]


def test_country_then_locality_is_one_place_after_a_validation_record(analyzer):
    # World War, 1939-1945--Jewish resistance--Poland (sh2008113968) is a validation record coded '|'; --Warsaw continues the chain Poland--Warsaw
    rep = analyzer.analyze(parse_heading("World War, 1939-1945--Jewish resistance--Poland--Warsaw--Biography"))
    e = rep["subdivisions"][1]["established_under_prefix"]
    assert e["may_subd_geog"] is None and "continues the indirect geographic chain Poland--Warsaw" in e["next_element_note"]
    assert not [c for c in rep["rule_checks"] if c["severity"] == "error"]


def test_bilateral_foreign_relations_takes_no_period(analyzer):
    # H 1629 sec. 2: [place 1]--Foreign relations--[place 2] is not subdivided by period or --History; sec. 1: no free-floating century after --Foreign relations
    assert ("H 1629 sec. 2", "error") in _checks(analyzer, "Great Britain--Foreign relations--Europe--History--17th century")
    assert ("H 1629 sec. 2", "error") in _checks(analyzer, "Great Britain--Foreign relations--Iraq--20th century")
    assert ("H 1629 sec. 1", "error") in _checks(analyzer, "Belarus--Foreign relations--21st century")
    assert not [c for c in _checks(analyzer, "Austria--Foreign relations--1918-1938") if c[0].startswith("H 1629")]
    assert not [c for c in _checks(analyzer, "Great Britain--Foreign relations--Argentina") if c[0].startswith("H 1629")]


def test_unknown_geographic_coding_is_completed_from_the_cached_marc_record(tmp_path):
    # a record created or changed after the bulk 008/06 backfill has geog_code NULL; online, the code is read from
    # the record's MARCXML on id.loc.gov and cached. Offline, or when the coding is already known, nothing changes.
    from lcsh_validator.db import LCSHDB
    import json
    db = LCSHDB(cache_path=tmp_path / "cache.sqlite", online=True)
    db.cache.execute("insert into names values (?,?,?)", ("geog:sh2099000001", 0, json.dumps(" ")))
    db.cache.execute("insert into names values (?,?,?)", ("geog:sh2099000002", 0, json.dumps("i")))
    db.cache.commit()
    blank = db.fill_geog_code({"id": "sh2099000001", "label": "Zebras--Breeding", "may_subd_geog": None, "geog_code": None})
    assert blank["may_subd_geog"] is False and blank["geog_code"] == " " and blank["geog_code_source"] == "id.loc.gov"
    coded = db.fill_geog_code({"id": "sh2099000002", "label": "Zebras--Breeding", "may_subd_geog": None, "geog_code": None})
    assert coded["may_subd_geog"] is True
    known = db.fill_geog_code({"id": "sh2099000001", "label": "Zebras--Breeding", "may_subd_geog": None, "geog_code": "|"})
    assert known["may_subd_geog"] is None and "geog_code_source" not in known
    off = LCSHDB(cache_path=tmp_path / "cache.sqlite", online=False)
    assert "geog_code_source" not in off.fill_geog_code({"id": "sh2099000001", "label": "Zebras--Breeding", "may_subd_geog": None, "geog_code": None})


# ---------------------------------------------------------------- guardrails: citations and usage-statement reading
@pytest.fixture(scope="module")
def auditor():
    from lcsh_validator.audit import CitationAuditor
    from lcsh_validator.freefloating import default_ff
    from lcsh_validator.rules import Rules
    return CitationAuditor(Rules(), default_ff())


def test_audit_flags_a_sheet_that_does_not_exist(auditor):
    v = {"issues": [{"element": "Biography", "severity": "warning", "problem": "x", "rule": "H 185 sec. 2; H 1095 sec. F", "fix": ""}], "explanation": "See H 1100."}
    probs = auditor.audit(v)
    assert [p["sheet"] for p in probs if p["kind"] == "unknown_sheet"] == ["H 185"]


def test_audit_accepts_real_citations(auditor):
    v = {"issues": [{"element": "Directories", "severity": "warning", "problem": "x", "rule": "H 1095 sec. F (--Directories); H 1558 sec. 2.b", "fix": ""}],
         "elements": [{"element": "Finance", "role": "topical", "status": "free-floating", "basis": "H 1095 --Finance; H 1624 sec. 1"}], "explanation": "Appendix D"}
    assert auditor.audit(v) == []


def test_audit_flags_a_subdivision_cited_to_a_list_it_is_not_on(auditor):
    v = {"issues": [{"element": "Reorganization", "severity": "warning", "problem": "x", "rule": "H 1095 sec. F (usage statement for --Reorganization)", "fix": ""}]}
    probs = auditor.audit(v)
    assert len(probs) == 1 and probs[0]["kind"] == "not_on_list"
    assert probs[0]["subdivision"] == "--reorganization" and "H 1105" in probs[0]["on_lists"] and "H 1095" not in probs[0]["on_lists"]


def test_scrub_removes_citations_to_unknown_sheets():
    from lcsh_validator.audit import scrub_unknown_sheets
    v = {"issues": [{"element": "x", "severity": "warning", "problem": "Per H 185 sec. 2 this fails", "rule": "H 185 sec. 2; H 1095 sec. F", "fix": None}],
         "elements": [], "explanation": "H185 says so.", "lc_practice_notes": []}
    removed = scrub_unknown_sheets(v, [{"kind": "unknown_sheet", "sheet": "H 185", "where": "issues[0].rule"}])
    assert removed == ["H 185"]
    assert v["issues"][0]["rule"] == "[citation to H 185 removed: no such SHM sheet]; H 1095 sec. F"
    assert "removed" in v["issues"][0]["problem"] and "removed" in v["explanation"]


def test_usage_coverage_quotes_the_general_clause(analyzer):
    facts = analyzer.analyze(parse_heading("Mentally ill--Care--Directories"))
    cov = facts["subdivisions"][1]["usage_coverage"]
    assert "topical" in cov["heading_types"] and "class of persons" in cov["heading_types"]
    assert cov["phrase"] == "topical headings" and "topical headings" in cov["general_clause"]
    facts = analyzer.analyze(parse_heading("Hearing--Physiological aspects"))
    cov = facts["subdivisions"][0]["usage_coverage"]
    assert cov["general_clause"] is None and "specific categories" in cov["note"]


def test_audit_usage_flags_a_doubt_that_ignores_the_general_clause(analyzer):
    from lcsh_validator.audit import audit_usage, pushback_message
    facts = analyzer.analyze(parse_heading("Mentally ill--Care--Directories"))
    v = {"issues": [{"element": "Directories", "severity": "warning", "rule": "H 1095 sec. F",
                     "problem": "The usage of --Directories under classes of persons is for lists of names; a directory after --Care does not fit.", "fix": ""}]}
    probs = audit_usage(v, facts)
    assert len(probs) == 1 and probs[0]["kind"] == "usage_clause_ignored" and probs[0]["element"] == "Directories"
    assert "topical headings" in pushback_message(probs)
    # the same doubt that quotes the clause and argues past it is left alone
    v["issues"][0]["problem"] = "The usage statement covers topical headings, but H 1558 sec. 2.c sends organizational directories elsewhere."
    assert audit_usage(v, facts) == []


class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Resp:
    def __init__(self, text):
        self.content, self.stop_reason = [_Block(text)], "end_turn"
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})()


class _FakeMessages:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kw):
        self.calls.append(kw)
        return _Resp(self.replies.pop(0))


class _FakeClient:
    def __init__(self, replies):
        self.messages = _FakeMessages(replies)


def _verdict(rule, verdict="questionable"):
    import json
    return json.dumps({"verdict": verdict, "confidence": 0.6, "normalized_string": "Hearing--Physiological aspects", "heading_type": "topical",
                       "elements": [{"element": "Hearing", "role": "main", "status": "authorized", "basis": "sh85059691"}],
                       "issues": [{"element": "Physiological aspects", "severity": "warning", "problem": "doubt", "rule": rule, "fix": ""}],
                       "lc_practice_notes": [], "suggested_alternatives": [], "explanation": f"See {rule}."})


def test_agent_pushes_back_on_a_nonexistent_sheet_and_accepts_the_correction(db):
    from lcsh_validator.agent import Validator
    client = _FakeClient([_verdict("H 185 sec. 2"), _verdict("H 1095 sec. F")])
    v = Validator(db=db, client=client)
    r = v.validate("Hearing--Physiological aspects", stabilize=False)
    assert len(client.messages.calls) == 2
    pushback = [m["content"] for m in client.messages.calls[1]["messages"] if m["role"] == "user" and isinstance(m["content"], str)][-1]
    assert "H 185" in pushback and "no such sheet" in pushback
    g = r.verdict["guardrails"]
    assert g["pushback"][0]["kind"] == "unknown_sheet" and g["unresolved"] == [] and g["rounds"] == 1
    assert r.verdict["issues"][0]["rule"] == "H 1095 sec. F" and r.verdict["verdict_note"].endswith("resolved")


def test_agent_strikes_a_nonexistent_sheet_the_model_insists_on(db):
    from lcsh_validator.agent import Validator
    client = _FakeClient([_verdict("H 185 sec. 2"), _verdict("H 185 sec. 2")])
    r = Validator(db=db, client=client).validate("Hearing--Physiological aspects", stabilize=False)
    assert r.verdict["guardrails"]["citations_removed"] == ["H 185"]
    assert "H 185 sec. 2" not in r.verdict["issues"][0]["rule"] and "removed" in r.verdict["issues"][0]["rule"]
    assert "removed" in r.verdict["explanation"]


def test_audit_ignores_templates_heading_strings_and_negated_mentions(auditor):
    v = {"elements": [{"element": "Popular works", "role": "form", "status": "free-floating",
                       "basis": "H 1095 names medical disciplines, individual diseases and [part of the body]--Diseases; Housing--Finance is established"}],
         "issues": [{"element": "x", "severity": "warning", "problem": "p", "rule": "H 1164 pattern list (--Popular works is not on it); H 1095 sec. F (--Popular works)", "fix": ""},
                    {"element": "y", "severity": "note", "problem": "p", "rule": "H 1095 Section G form entry '--Juvenile literature' ($v), usage 'Use as a form subdivision under subjects'", "fix": ""}]}
    assert auditor.audit(v) == []


def test_audit_place_claim_that_contradicts_the_chain(analyzer):
    from lcsh_validator.audit import audit_place_claims, pushback_message
    facts = analyzer.analyze(parse_heading("Housing--Finance--Government policy--United States"))
    v = {"issues": [{"element": "Finance--United States", "severity": "error", "rule": "H 830",
                     "problem": "Placing United States after Housing--Finance is not allowed because --Finance is not May Subd Geog.", "fix": ""}]}
    probs = audit_place_claims(v, facts)
    assert len(probs) == 1 and probs[0]["preceded_by"] == "Government policy"
    assert "Government policy" in pushback_message(probs)
    v["issues"][0]["problem"] = "Housing policy is an established phrase heading (H 1642)."
    assert audit_place_claims(v, facts) == []


# ---------------------------------------------------------------- rule popups for the web UI
def test_rules_json_export_matches_the_corpus():
    import json, subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    subprocess.run([sys.executable, str(root / "scripts/export_rules_json.py")], check=True, capture_output=True)
    idx = json.loads((root / "docs/rules/index.json").read_text(encoding="utf-8"))
    assert idx["H 1095"]["file"] == "H1095" and "Appendix D" in idx and "H 185" not in idx
    h1095 = json.loads((root / "docs/rules/H1095.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in h1095["sections"]][:3] == ["A", "B", "C"] and "E.3" in [s["id"] for s in h1095["sections"]]
    assert "topical headings" in h1095["list"]["entries"]["--directories"][0]["use_under"]
    h1558 = json.loads((root / "docs/rules/H1558.json").read_text(encoding="utf-8"))
    assert "2.b" in [s["id"] for s in h1558["sections"]] and h1558["validation_rules"]


def test_citation_parser_in_the_browser_script():
    import json, shutil, subprocess
    from pathlib import Path
    if not shutil.which("node"):
        pytest.skip("node not installed")
    root = Path(__file__).resolve().parent.parent
    js = ('require(%s); const R = globalThis.LcshRules;'
          'console.log(JSON.stringify(R.parseCitations("H 1095 sec. F (--Directories usage statement); H 1558 secs. 2.b, 2.c; see Appendix D and H1642 sec. 1.").filter(p => p.ref).map(p => [p.sheet, p.section, p.subdivision])))'
          % json.dumps(str(root / "docs/rules.js")))
    out = subprocess.run(["node", "-e", js], check=True, capture_output=True, text=True).stdout
    # a clause with no subdivision of its own inherits the first one named in the text
    assert json.loads(out) == [["H 1095", "F", "--directories"], ["H 1558", "2.b", "--directories"], ["Appendix D", None, "--directories"], ["H 1642", "1", "--directories"]]
