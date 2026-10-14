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
