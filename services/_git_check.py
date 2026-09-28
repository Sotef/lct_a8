# -*- coding: utf-8 -*-
"""Отчёт: что уже в git, что нужно добавить, что правильно игнорируется."""
import pathlib
import subprocess

ROOT = pathlib.Path(r"d:\Downloads_D\lct_a8")


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


NEED = [
    "services/MOBILE_PLAN.md", "services/FRONTEND.md", "services/.dockerignore",
    "services/.env.docker.example", "services/Dockerfile", "services/docker-compose.yml",
    "services/scripts/docker-entrypoint.sh", "services/scripts/wait_for_db.py",
    "services/scripts/verify_deploy.py", "services/deploy/nginx/nginx.conf",
    "services/deploy/certs/README.md", "services/app/web/sw.js",
    "services/app/web/manifest.webmanifest", "services/app/web/css/mobile.css",
    "services/app/web/js/view_alerts.js", "services/app/web/js/mobile/offline.js",
    "services/app/web/js/mobile/push.js", "services/app/web/js/mobile/photo.js",
    "services/app/web/js/mobile/shell.js", "services/app/web/__probe.html",
    "services/app/web/__mprobe.html", "services/app/web/icons/icon-192.svg",
    "services/app/api/alerts.py", "services/app/api/push.py",
    "services/app/workers/alerts.py", "services/app/services/push_service.py",
    "services/app/services/attachment_service.py", "services/app/services/idempotency.py",
    "services/tests/front_static_check.mjs", "services/tests/_routes.json",
    "services/tests/web_smoke.ps1", "README.md", "ARCHITECTURE.md", ".gitignore",
]
HEAVY = [
    "services/data/app.db", "services/data/raw/buckets_2026.parquet",
    "services/data/panels/subdaily_panel_fire6h_2026.csv", "services/logs/app.log",
    "services/deploy/certs/tls.key", "services/deploy/certs/tls.crt",
]

out = []
out.append("=== нужные файлы: наличие в git ===")
for f in NEED:
    rc, _ = git("ls-files", "--error-unmatch", f)
    out.append(("TRACKED    " if rc == 0 else "NOT-IN-GIT ") + f)

out.append("")
out.append("=== нужные файлы: не игнорируются ли .gitignore ===")
rc, txt = git("check-ignore", "--no-index", "-v", *NEED)
ignored = {l.split("\t")[-1] for l in txt.strip().splitlines() if l.strip()}
for f in NEED:
    out.append(("IGNORED!! " if f in ignored else "OK        ") + f)

out.append("")
out.append("=== тяжёлые/секретные пути: должны быть проигнорированы ===")
for f in HEAVY:
    rc, _ = git("check-ignore", "--no-index", "-q", f)
    out.append(("IGNORED   " if rc == 0 else "!!! IN REPO") + " " + f)

pathlib.Path(ROOT / "services/data/_git_check.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
