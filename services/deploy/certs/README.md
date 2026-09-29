# Сертификаты TLS для профиля `tls` (reverse-proxy nginx)

В этот каталог кладутся два файла:

```
deploy/certs/tls.crt   # сертификат (цепочка)
deploy/certs/tls.key   # приватный ключ (без пароля)
```

Каталог монтируется в контейнер `proxy` как `/etc/nginx/certs` (read-only).

## Вариант 0. Одной командой (самоподписанный, для демо/теста)

**Если есть локальный venv (Windows):**
```powershell
cd services
.\.venv\Scripts\python.exe scripts\make_dev_certs.py     # создаст tls.crt + tls.key на 365 дней
docker compose --profile tls up -d
# https://127.0.0.1:8443/  (браузер покажет предупреждение о самоподписанном сертификате)
```

**Только через Docker (venv не нужен)** — каталог `deploy/certs` смонтирован в `api`:
```powershell
cd services
docker compose up -d --build                                          # api уже поднят
docker compose exec -T api python scripts/make_dev_certs.py           # пишет прямо на хост в deploy/certs
docker compose --profile tls up -d                                    # поднять proxy
```

> ⚠️ Запускать генератор нужно с хоста (через venv) или через `docker compose exec` — если запустить
> `python scripts/make_dev_certs.py` **внутри** контейнера вручную (`docker exec ... sh`), файлы
> попадут в контейнер и `proxy` их не увидит (он монтирует `./deploy/certs` с хоста).
>
> Порядок важен: сначала сертификаты, потом `--profile tls up -d`. Если `proxy` уже успел
> поубиваться без сертификатов, он останется в бэк-оффе — после генерации сделайте
> `docker compose restart proxy` (или `docker compose --profile tls up -d --force-recreate`).

Скрипту нужен только пакет `cryptography` (приходит с `python-jose[cryptography]`), `openssl` не требуется.
Существующие сертификаты не перезаписываются (`--force`), срок — `--days`, каталог — `--out`.

> Важно: **без** сертификатов контейнер `proxy` уходит в рестарт-луп
> (`nginx: cannot load certificate "/etc/nginx/certs/tls.crt"`), а API по HTTP продолжает работать.

## Вариант 1. Корпоративный сертификат
Скопируйте выданные файлы сюда под именами `tls.crt` / `tls.key`.

## Вариант 2. Самоподписанный (демо/тест, браузер покажет предупреждение)
PowerShell (если есть `openssl` из Git for Windows):

```powershell
openssl req -x509 -newkey rsa:2048 -nodes -days 365 `
  -keyout deploy/certs/tls.key -out deploy/certs/tls.crt `
  -subj "/CN=moscollector.local" `
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

WSL / bash:

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout deploy/certs/tls.key -out deploy/certs/tls.crt \
  -subj "/CN=moscollector.local" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

Если `openssl` нет — сгенерируйте сертификат в любом другом окружении и
скопируйте `tls.crt`/`tls.key` сюда, либо запустите сервис без профиля `tls`
(TLS-терминация на внешнем балансировщике/AD-инфраструктуре).

**Не коммитьте приватный ключ в репозиторий.**
