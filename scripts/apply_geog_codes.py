"""Add the MARC 008/06 geographic-subdivision code to data/derived/lcsh.sqlite (column headings.geog_code).

The MADS/RDF bulk data only says which headings are in collection_SubdivideGeographically (008/06 'i' or 'd').
It cannot tell a record LC explicitly coded "not subdivided geographically" (008/06 blank, e.g. United States--History--
Civil War, 1861-1865--Regimental histories) from one LC never evaluated (008/06 '|', e.g. Art, Modern--19th century and
the 2008-2010 validation records). The codes come from the LC MDSConnect "2016" MARC files (a 2015-12-29 snapshot) via
scripts/extract_marc_008.py, completed by scripts/fetch_marc_008.py (per-record MARCXML from id.loc.gov for the records
created or changed since). Several files may be given; a later file overrides an earlier one. Codes '-' (record not
found) and '?' (fetch failed) are ignored. Geographic-subdivision rows derived from a 151 record (id ending -781)
inherit the record's code.

usage: uv run scripts/apply_geog_codes.py data/derived/geog_code_008_06.tsv data/derived/geog_code_008_06_idloc.tsv
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data/derived/lcsh.sqlite"


def main():
    files = [Path(a) for a in sys.argv[1:]] or [ROOT / "data/derived/geog_code_008_06.tsv", ROOT / "data/derived/geog_code_008_06_idloc.tsv"]
    codes: dict[str, str] = {}
    for tsv in files:
        if not tsv.exists():
            print(f"{tsv} missing, skipped")
            continue
        for line in open(tsv, encoding="utf-8"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[1] not in ("-", "?"):
                codes[parts[0]] = parts[1]
    con = sqlite3.connect(DB)
    cols = [r[1] for r in con.execute("pragma table_info(headings)")]
    if "geog_code" not in cols:
        con.execute("alter table headings add column geog_code text")
    con.execute("update headings set geog_code=null")
    con.executemany("update headings set geog_code=? where id=?", [(c, i) for i, c in codes.items()])
    con.execute("update headings set geog_code=(select p.geog_code from headings p where p.id=headings.generated_from) where id like '%-781'")
    con.commit()
    n = con.execute("select count(*) from headings where geog_code is not null").fetchone()[0]
    print(f"geog_code set on {n} of {con.execute('select count(*) from headings').fetchone()[0]} headings")


if __name__ == "__main__":
    main()
