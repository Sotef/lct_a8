# Стадия 1. Распаковка журналов .7z → dataset/extracted/
import time

import py7zr

if REBUILD:
    ex_dir = DATASET / "extracted"
    ex_dir.mkdir(exist_ok=True)
    for z7 in sorted(DATASET.glob("ext-journal-*.7z")):
        year = z7.name.split("-")[2].split(".")[0]
        out = ex_dir / f"ext-journal-{year}.csv"
        if out.exists():
            print(f"SKIP {year}")
            continue
        t0 = time.perf_counter()
        with py7zr.SevenZipFile(z7, "r") as z:
            z.extractall(path=ex_dir)
        print(f"DONE {year}: {out.stat().st_size / 1e6:.1f} MB, {time.perf_counter() - t0:.0f} с")
else:
    print("REBUILD=False — распакованные журналы (текущее состояние):")
    for fp in sorted((DATASET / "extracted").glob("ext-journal-*.csv")):
        print("  ", fp.name, f"{(fp.stat().st_size / 1e6):,.0f} MB")