# Сертификаты TLS для профиля `tls` (reverse-proxy nginx)

В этот каталог кладутся два файла:

```
deploy/certs/tls.crt   # сертификат (цепочка)
deploy/certs/tls.key   # приватный ключ (без пароля)
```

Каталог монтируется в контейнер `proxy` как `/etc/nginx/certs` (read-only).

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
