# web_smoke — браузерный (headless Edge/Chrome) прогон SPA: все разделы, карточки, DnD, палитра, карта.
# Запуск: powershell -File services\tests\web_smoke.ps1   (сервис должен быть запущен на 127.0.0.1:8000)
param(
  [string]$Base = "http://127.0.0.1:8000",
  [switch]$WithTimers
)
$ErrorActionPreference = "Stop"
$candidates = @(
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ }
if (-not $candidates) { Write-Host "не найден Edge/Chrome для headless-прогона"; exit 2 }
$browser = @($candidates)[0]

$url = "$Base/__probe.html" + $(if ($WithTimers) { "?timers=1" } else { "" })
$tmp = Join-Path $env:TEMP ("probe_" + [guid]::NewGuid().ToString("N") + ".html")
# Edge пишет служебные предупреждения в stderr — не считаем их ошибкой скрипта
$ErrorActionPreference = "Continue"
& $browser --headless=new --disable-gpu --no-sandbox --hide-scrollbars `
  --virtual-time-budget=60000 --dump-dom $url 2>$null | Out-File -Encoding utf8 $tmp
$ErrorActionPreference = "Stop"

$html = Get-Content $tmp -Raw
$title = ([regex]::Match($html, "<title>([^<]*)</title>")).Groups[1].Value
$body = ([regex]::Match($html, '(?s)<pre id="probe-out"[^>]*>(.*?)</pre>')).Groups[1].Value
$body = $body -replace '&lt;', '<' -replace '&gt;', '>' -replace '&amp;', '&'
Remove-Item $tmp -Force

Write-Host $body
$fails = @()
if ($title -ne "PROBE OK") { $fails += "title=$title" }
if ($body -match "FAIL") { $fails += "в отчёте есть FAIL" }
if ($body -notmatch "TOTAL ERRORS: 0") { $fails += "есть JS-ошибки" }
foreach ($v in "dashboard","forecasts","objects","graph","plan","tickets","audit","sys","users") {
  if ($body -notmatch "VIEW ${v}: ") { $fails += "раздел $v не отчитался" }
}
if ($fails.Count) { Write-Host ("=== WEB SMOKE: FAIL :: " + ($fails -join "; ")) ; exit 1 }
Write-Host "=== WEB SMOKE: ALL OK (headless $([System.IO.Path]::GetFileName($browser))) ==="
exit 0
