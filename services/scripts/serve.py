# -*- coding: utf-8 -*-
"""Запуск сервиса для доступа из локальной сети (плюс подсказки по адресам и firewall).

По умолчанию слушает все интерфейсы (`0.0.0.0:8000`), поэтому сервис доступен
с других машин по IP или имени хоста:  http://<IP>:8000  /  http://<имя-машины>:8000
(SPA и API отдаются одним origin — отдельный домен не нужен).

Запуск:
  services\\.venv\\Scripts\\python.exe scripts\\serve.py                     # 0.0.0.0:8000
  services\\.venv\\Scripts\\python.exe scripts\\serve.py --host 127.0.0.1    # только локально
  services\\.venv\\Scripts\\python.exe scripts\\serve.py --port 8080
  services\\.venv\\Scripts\\python.exe scripts\\serve.py --firewall          # открыть порт (нужны права админа)
"""
from __future__ import annotations

import argparse
import pathlib
import socket
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def local_ips() -> list[str]:
    """IPv4-адреса машины, пригодные для локальной сети (без 169.254/loopback)."""
    ips: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    # UDP-трюк: адрес «наружу» — реальный интерфейс, даже если getaddrinfo молчит
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips and not ip.startswith("127."):
            ips.insert(0, ip)
    except OSError:
        pass
    return ips


def vpn_like(ip: str) -> bool:
    """Адреса виртуальных адаптеров (Hyper-V/WSL/VPN) — для локальной сети не годятся."""
    return ip.startswith(("172.1", "172.2", "172.3", "10.", "192.168.56."))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = доступ из сети, 127.0.0.1 = только локально")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--firewall", action="store_true", help="добавить правило брандмауэра (нужны права админа)")
    ap.add_argument("--no-reload", action="store_true", help="не следить за изменениями файлов")
    args = ap.parse_args()

    host = args.host
    ips = [ip for ip in local_ips() if not vpn_like(ip)] or local_ips()
    P = lambda *a: print(*a, flush=True)  # noqa: E731
    print("=" * 68)
    print("Москоллектор · предиктивный сервис ОДС")
    print(f"  локально:   http://127.0.0.1:{args.port}/")
    if host == "0.0.0.0":
        if ips:
            print(f"  в сети:     http://{ips[0]}:{args.port}/        (по IP — надёжнее всего)")
        print(f"  по имени:   http://{socket.gethostname()}:{args.port}/        (если в сети разрешаются имена)")
        if len(ips) > 1:
            print(f"  другие IP:  {', '.join('http://%s:%d/' % (ip, args.port) for ip in ips[1:])}")
        print(f"  Swagger:    http://127.0.0.1:{args.port}/docs")
    else:
        print("  ВНИМАНИЕ: слушаем только localhost — с других машин сервис недоступен.")
        print("            Для сети запустите без --host (по умолчанию 0.0.0.0).")
    print("=" * 68, flush=True)

    if args.firewall:
        rule = f"LCT Predictive {args.port}"
        cmd = (f'netsh advfirewall firewall add rule name="{rule}" dir=in action=allow '
               f'protocol=TCP localport={args.port}')
        print("→ брандмауэр:", cmd, flush=True)
        res = subprocess.run(cmd, shell=True, check=False, capture_output=True, text=True)
        if res.returncode != 0:
            print("  не удалось добавить правило — нужны права администратора.", flush=True)
            print("  Запустите PowerShell «от имени администратора» и выполните ту же команду,", flush=True)
            print("  либо:  Start-Process powershell -Verb RunAs -ArgumentList '-Command',", flush=True)
            print(f"         \"{cmd}\"", flush=True)
    elif host == "0.0.0.0":
        print("Если Windows блокирует порт — выполните от администратора:")
        print(f'  netsh advfirewall firewall add rule name="LCT Predictive {args.port}" '
              f'dir=in action=allow protocol=TCP localport={args.port}')
        print("или просто запустите этот скрипт с флагом --firewall (нужно подтверждение UAC).")
    import uvicorn
    # приложение читает HOST/PORT из config — прокидываем через окружение
    import os
    os.environ["HOST"], os.environ["PORT"] = host, str(args.port)
    uvicorn.run("app.main:app", host=host, port=args.port, workers=args.workers,
                reload=not args.no_reload and args.workers == 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
