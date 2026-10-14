"""Extract text from every PDF under data/raw/* into data/text/* (one .txt per PDF).
Usage: uv run scripts/extract_pdf_text.py
"""
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
PAIRS = [(ROOT / "data/raw/shm", ROOT / "data/text/shm"), (ROOT / "data/raw/lcsh", ROOT / "data/text/lcsh")]

for src, dst in PAIRS:
    dst.mkdir(parents=True, exist_ok=True)
    for pdf in sorted(src.glob("*.pdf")):
        out = dst / (pdf.stem + ".txt")
        try:
            doc = pymupdf.open(pdf)
            pages = []
            for i, page in enumerate(doc):
                pages.append(f"\n\n<<<PAGE {i+1}>>>\n" + page.get_text("text"))
            out.write_text("".join(pages))
        except Exception as e:  # noqa: BLE001
            print(f"FAILED {pdf.name}: {e}", file=sys.stderr)
    print(f"{src.name}: {len(list(dst.glob('*.txt')))} files")
