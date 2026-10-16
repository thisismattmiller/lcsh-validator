"""Extract id -> 008/06 (geographic subdivision code) from LC MDSConnect binary MARC authority files. Run with -I; paths as args."""
import gzip, sys, re
out = open(sys.argv[-1], "w", encoding="utf-8")
n = 0
for path in sys.argv[1:-1]:
    data = gzip.open(path, "rb").read()
    for rec in data.split(b"\x1d"):
        if len(rec) < 24:
            continue
        try:
            base = int(rec[12:17])
        except ValueError:
            continue
        directory = rec[24:base - 1]
        f001 = f008 = None
        for i in range(0, len(directory) - 11, 12):
            tag = directory[i:i + 3]; ln = int(directory[i + 3:i + 7]); st = int(directory[i + 7:i + 12])
            fld = rec[base + st: base + st + ln].rstrip(b"\x1e")
            if tag == b"001": f001 = fld.decode("utf-8", "replace")
            elif tag == b"008": f008 = fld.decode("utf-8", "replace")
        if f001 and f008 and len(f008) > 6:
            hid = re.sub(r"\s+", "", f001)
            out.write(f"{hid}\t{f008[6]}\n"); n += 1
print(n)
