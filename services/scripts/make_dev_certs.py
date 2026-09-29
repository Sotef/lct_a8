# -*- coding: utf-8 -*-
"""Самоподписанный TLS-сертификат для профиля `tls` (демо/тест).

Создаёт `deploy/certs/tls.crt` и `deploy/certs/tls.key` (SAN: localhost, 127.0.0.1) —
ровно те имена, которые монтирует контейнер `proxy` (см. `deploy/certs/README.md`).
Без сертификатов `docker compose --profile tls up -d` уходит в рестарт-луп
(`nginx: cannot load certificate "/etc/nginx/certs/tls.crt"`).

Запуск (из каталога `services/`; нужен пакет `cryptography` — он уже приходит
вместе с `python-jose[cryptography]`):

    .venv\\Scripts\\python.exe scripts\\make_dev_certs.py
    .venv\\Scripts\\python.exe scripts\\make_dev_certs.py --days 30 --force
    .venv\\Scripts\\python.exe scripts\\make_dev_certs.py --out deploy/certs

SAN = localhost, 127.0.0.1 и все LAN-адреса хоста — чтобы работал тест с телефона
по `https://<IP>:8443` (иначе браузер ругается на несоответствие имени).
Свои адреса/имена: `--host 192.168.1.50` (можно несколько раз), авто-LAN — `--no-lan`.

Для прода — корпоративный сертификат (см. deploy/certs/README.md), не этот.
"""
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import pathlib
import socket
import sys

try:  # консоль Windows бывает cp1251 — не падаем на «→» и русском тексте
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_OUT = HERE.parent / "deploy" / "certs"


def lan_ipv4() -> list[str]:
    """IPv4-адреса хоста в локальной сети (без loopback и link-local).

    Нужны для теста с телефона/планшета: `https://<LAN-IP>:8443` требует,
    чтобы адрес был в SAN сертификата, иначе браузер ругается на имя.
    """
    ips: list[str] = []
    try:                                  # основной адрес: udp-connect пакеты не шлёт
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:                                  # плюс всё, что знает резолвер имени хоста
        ips += list(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    out: list[str] = []
    for ip in ips:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.is_loopback or a.is_link_local or a.is_unspecified:
            continue
        if str(a) not in out:
            out.append(str(a))
    return out



def make_cert(out: pathlib.Path, days: int, cn: str, force: bool,
              extra_hosts: list[str] | None = None,
              include_lan: bool = True) -> int:
    crt, key = out / "tls.crt", out / "tls.key"
    if (crt.exists() or key.exists()) and not force:
        print("сертификаты уже есть: %s, %s (перезаписать — --force)"
              % (crt, key))
        return 1
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("нет пакета cryptography — установите: pip install cryptography")
        return 1

    san: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    seen = {"localhost", "127.0.0.1"}
    for host in (extra_hosts or []):
        host = host.strip()
        if not host or host in seen:
            continue
        seen.add(host)
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            san.append(x509.DNSName(host))
    if include_lan:
        for ip in lan_ipv4():
            if ip in seen:
                continue
            seen.add(ip)
            san.append(x509.IPAddress(ipaddress.ip_address(ip)))

    out.mkdir(parents=True, exist_ok=True)
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(priv.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(priv, hashes.SHA256())
    )
    key.write_bytes(priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    print("готово: %s (%d б), %s (%d б)"
          % (crt, crt.stat().st_size, key, key.stat().st_size))
    print("срок: %d дн., CN=%s" % (days, cn))
    print("SAN: " + ", ".join(str(g.value) for g in san))
    print("дальше: docker compose --profile tls up -d  →  "
          "https://localhost:8443/  (и https://<LAN-IP>:8443 с телефона,")
    print("если сертификат установлен как доверенный на устройстве)")
    print("(файлы в .gitignore — приватный ключ в репозиторий не попадает)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Самоподписанный сертификат для TLS-профиля (демо/тест)")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="каталог для tls.crt/tls.key (по умолчанию services/deploy/certs)")
    ap.add_argument("--days", type=int, default=365, help="срок действия, дней")
    ap.add_argument("--cn", default="moscollector.local", help="Common Name")
    ap.add_argument("--host", action="append", default=[], metavar="IP|ИМЯ",
                    help="дополнительный адрес или имя для SAN (можно несколько раз); "
                         "LAN-адреса хоста добавляются автоматически")
    ap.add_argument("--no-lan", action="store_true",
                    help="не добавлять LAN-адреса хоста в SAN")
    ap.add_argument("--force", action="store_true", help="перезаписать существующие")
    args = ap.parse_args()
    return make_cert(pathlib.Path(args.out), args.days, args.cn, args.force,
                     extra_hosts=args.host, include_lan=not args.no_lan)


if __name__ == "__main__":
    raise SystemExit(main())
