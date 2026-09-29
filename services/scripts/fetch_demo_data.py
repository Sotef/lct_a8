# -*- coding: utf-8 -*-
"""Демо-данные 2026: получить из GitHub (Git LFS) или из архива релиза.

Что нужно сервису для демо-прогона (реплей 2026) и где это лежит:

| Данные                                             | Размер   | Хранение    |
|----------------------------------------------------|----------|-------------|
| `services/data/panels/subdaily_panel_*_2026.csv`    | ~319 МБ  | **Git LFS** |
| `services/data/raw/buckets_2026.parquet`            | ~1.1 МБ  | обычный git |
| `services/data/{z_stats_*,cat_codes_*,_features_schema.json,` `l2_object_risk.parquet,channel_first_seen.csv}` | <0.5 МБ | обычный git |
| `research/models/tte_*_discrete_hazard.cbm`, `calib30_access.pkl` | ~38 МБ | обычный git |
| `research/dataset/справочник_*.csv`                 | ~1.4 МБ  | обычный git |

Команды (из корня репозитория):

    python services/scripts/fetch_demo_data.py --check     # отчёт: что есть/чего нет
    python services/scripts/fetch_demo_data.py             # получить недостающее
    python services/scripts/fetch_demo_data.py --url <URL> # скачать архив demo-data-2026.zip
    python services/scripts/fetch_demo_data.py --pack       # собрать архив для публикации

Если LFS и архив недоступны — панель 6ч пересобирается из `raw/buckets_2026.parquet`
при первом запуске (дольше).
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = pathlib.Path(__file__).resolve().parent           # services/scripts
SERVICE = HERE.parent                                    # services
ROOT = SERVICE.parent                                    # lct_a8

# (путь от корня репо, обязателен?, человекочитаемое имя)
REQUIRED: list[tuple[str, bool, str]] = [
    ("services/data/panels/subdaily_panel_fire6h_2026.csv", True, "панель 6ч · fire"),
    ("services/data/panels/subdaily_panel_access6h_2026.csv", True, "панель 6ч · access"),
    ("services/data/panels/subdaily_panel_sensor6h_2026.csv", True, "панель 6ч · sensor"),
    ("services/data/panels/subdaily_panel_wear6h_2026.csv", True, "панель 6ч · wear"),
    ("services/data/raw/buckets_2026.parquet", True, "raw-бакеты 2026"),
    ("services/data/_features_schema.json", True, "схема признаков (X_cols)"),
    ("services/data/z_stats_fire.csv", True, "z-статистики · fire"),
    ("services/data/z_stats_access.csv", True, "z-статистики · access"),
    ("services/data/z_stats_sensor.csv", True, "z-статистики · sensor"),
    ("services/data/z_stats_wear.csv", True, "z-статистики · wear"),
    ("services/data/cat_codes_fire.json", True, "коды категорий · fire"),
    ("services/data/cat_codes_access.json", True, "коды категорий · access"),
    ("services/data/cat_codes_sensor.json", True, "коды категорий · sensor"),
    ("services/data/cat_codes_wear.json", True, "коды категорий · wear"),
    ("services/data/l2_object_risk.parquet", False, "L2-риск объектов"),
    ("services/data/channel_first_seen.csv", False, "возраст оборудования"),
    ("research/models/tte_fire_discrete_hazard.cbm", True, "модель · fire"),
    ("research/models/tte_access_discrete_hazard.cbm", True, "модель · access"),
    ("research/models/tte_sensor_discrete_hazard.cbm", True, "модель · sensor"),
    ("research/models/tte_wear_discrete_hazard.cbm", True, "модель · wear"),
    ("research/models/calib30_access.pkl", False, "калибровка risk30 · access"),
    ("research/dataset/справочник_каналов_датчиков.csv", True, "справочник каналов"),
    ("research/dataset/справочник_объектов_диспетчер.csv", True, "справочник объектов"),
]

LFS_PATTERN = "services/data/panels/*.csv"
ARCHIVE_NAME = "demo-data-2026.zip"


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} МБ"


def _hash(fp: pathlib.Path) -> str:
    h = hashlib.sha256()
    with fp.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def status() -> list[tuple[str, bool, str, int]]:
    out = []
    for rel, must, name in REQUIRED:
        fp = ROOT / rel
        size = fp.stat().st_size if fp.exists() else 0
        out.append((rel, must, name, size))
    return out


def cmd_check(verbose: bool = True) -> int:
    rows = status()
    miss = [r for r in rows if r[1] and r[3] == 0]
    if verbose:
        print("Демо-данные 2026 (корень: %s)\n" % ROOT)
        for rel, must, name, size in rows:
            mark = "OK " if size else ("НЕТ" if must else "—  ")
            print(f"  [{mark}] {name:34} {rel:58} {_mb(size) if size else ''}")
        print()
        print("Не хватает обязательных: %d." % len(miss) if miss
              else "Все обязательные данные на месте — можно запускать демо.")
    return 1 if miss else 0


def _run(cmd: list[str], cwd: pathlib.Path) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, f"команда не найдена: {cmd[0]}"


def lfs_available() -> bool:
    return _run(["git", "lfs", "version"], ROOT)[0] == 0


def git_has_remote() -> bool:
    code, out = _run(["git", "remote"], ROOT)
    return code == 0 and bool(out.strip())


def _panels_ok() -> bool:
    return all((ROOT / r).exists() and (ROOT / r).stat().st_size > 0
               for r, must, _n in REQUIRED if must and "/panels/" in r)


def pull_lfs() -> bool:
    """`git lfs pull` только для панелей. True — если файлы появились."""
    if not (lfs_available() and git_has_remote()):
        return False
    print("• git lfs pull --include=%s" % LFS_PATTERN)
    code, out = _run(["git", "lfs", "pull", "--include=" + LFS_PATTERN], ROOT)
    if code != 0:
        print("  не удалось: " + out.strip()[:300])
        return False
    return _panels_ok()


def fetch_url(url: str, sha256: str | None = None) -> bool:
    """Скачать архив демо-данных и распаковать в корень репозитория."""
    print("• скачивание архива: %s" % url)
    with tempfile.TemporaryDirectory(prefix="mc_demo_") as td:
        tmp = pathlib.Path(td) / ARCHIVE_NAME
        try:
            urllib.request.urlretrieve(url, tmp)
        except Exception as exc:  # noqa: BLE001
            print("  ошибка загрузки: %s" % exc)
            return False
        if sha256 and _hash(tmp) != sha256.lower():
            print("  ошибка: sha256 не совпал")
            return False
        print("  распаковка %s ..." % _mb(tmp.stat().st_size))
        root = ROOT.resolve()
        with zipfile.ZipFile(tmp) as z:
            for m in z.namelist():
                target = (ROOT / m).resolve()
                if not str(target).startswith(str(root)):      # без path traversal
                    print("  пропуск подозрительного пути: %s" % m)
                    continue
                if m.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(m) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    return True


def cmd_pack(out: pathlib.Path) -> int:
    """Собрать архив демо-данных (для GitHub Release) + sha256."""
    files = [(ROOT / rel, rel) for rel, _must, _n in REQUIRED if (ROOT / rel).exists()]
    if not files:
        print("нечего упаковывать: демо-данных нет")
        return 1
    total = sum(fp.stat().st_size for fp, _ in files)
    print("Упаковка %d файлов (%s) -> %s" % (len(files), _mb(total), out))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for fp, rel in files:
            z.write(fp, rel)
    digest = _hash(out)
    (out.parent / (out.name + ".sha256")).write_text(f"{digest}  {out.name}\n",
                                                     encoding="utf-8")
    print("\nГотово: %s (%s)" % (out, _mb(out.stat().st_size)))
    print("sha256: %s" % digest)
    print("\nКак опубликовать (любой вариант):")
    print("  1) Git LFS — файлы уже отслеживаются .gitattributes:")
    print("       git add services/data/panels && git push   # LFS-объекты уедут вместе с push")
    print("  2) Release — загрузить %s в GitHub Release с тегом `demo-data-2026`," % out.name)
    print("     затем получать данные: fetch_demo_data.py --url <URL ассета>")
    return 0


def cmd_default(url: str | None) -> int:
    if cmd_check(verbose=True) == 0:
        return 0
    if pull_lfs() and cmd_check(verbose=False) == 0:
        print("Готово: данные получены через Git LFS.")
        return 0
    if url and fetch_url(url) and cmd_check(verbose=False) == 0:
        print("Готово: данные получены из архива.")
        return 0
    print("\nНе удалось получить все данные автоматически. Варианты:")
    print("  • git lfs install && git lfs pull            # панели 6ч (~319 МБ)")
    print("  • fetch_demo_data.py --url <URL demo-data-2026.zip>")
    print("  • либо запустить сервис как есть: панель 6ч пересоберётся из")
    print("    raw/buckets_2026.parquet (дольше) — scripts/run_demo.py --recompute-panel")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Демо-данные 2026 из GitHub (LFS/Release)")
    ap.add_argument("--check", action="store_true", help="только отчёт о наличии")
    ap.add_argument("--url", default=None,
                    help="URL архива demo-data-2026.zip (GitHub Release asset)")
    ap.add_argument("--sha256", default=None, help="ожидаемая контрольная сумма архива")
    ap.add_argument("--pack", action="store_true", help="собрать архив для публикации")
    ap.add_argument("--out", default=str(SERVICE / "data" / ARCHIVE_NAME),
                    help="путь архива для --pack")
    args = ap.parse_args()

    if args.check:
        return cmd_check(verbose=True)
    if args.pack:
        return cmd_pack(pathlib.Path(args.out))
    if args.url:
        ok = fetch_url(args.url, args.sha256)
        return 0 if (ok and cmd_check(verbose=False) == 0) else 1
    return cmd_default(args.url)


if __name__ == "__main__":
    raise SystemExit(main())
