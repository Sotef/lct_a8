<#
.SYNOPSIS
  Прогон «кнопочных» тестов сервиса: API (pytest) + интерфейс (headless Edge/Chrome).

.DESCRIPTION
  1) tests/test_buttons_api.py — роли, заявки (исполнитель/статусы), история комментариев и дат,
     вложения, идемпотентность офлайн-действий, алерты, часы и «Заново с января» + время операций;
  2) app/web/__e2e.html — «водитель» интерфейса: жмёт кнопки и печатает, что изменилось и за сколько мс;
  3) при -Reset дополнительно проверяется наполнение «Тренда риска» после сброса (реальное время).

.EXAMPLE
  powershell -File services\tests\run_buttons_e2e.ps1                                   # текущий стек на :8000
  powershell -File services\tests\run_buttons_e2e.ps1 -Base http://127.0.0.1:8040 -Reset -Project e2e
  powershell -File services\tests\run_buttons_e2e.ps1 -User dispatcher.alpha
  powershell -File services\tests\run_buttons_e2e.ps1 -Mobile
#>
param(
  [string]$Base = "http://127.0.0.1:8000",
  [string]$User = "central.operator",
  [switch]$Reset,
  [switch]$Mobile,
  [string]$Project = "",                 # docker-compose проект (чтобы скопировать __e2e.html в контейнер)
  [string]$Window = "1280,900",          # размер окна headless (мобильный профиль: -Window 420,900)
  [int]$TrendWaitSec = 200,              # ожидание наполнения тренда после сброса (реальное время)
  [int]$TimeoutSec = 600,                # жёсткий таймаут браузера (на случай «залипания» страницы)
  [switch]$Fast                          # перед прогоном включить быстрый расчёт (4×, без SHAP)
)
# docker/браузер пишут служебные сообщения в stderr — не превращаем их в исключения
$ErrorActionPreference = "Continue"
$svc = Split-Path $PSScriptRoot -Parent
$py = Join-Path $svc ".venv\Scripts\python.exe"
$rep = Join-Path $svc "data\e2e_report.md"
$out = @()

function Say($s) { Write-Host $s; $script:out += $s }

Say "== КНОПОЧНЫЕ ТЕСТЫ =="
Say "сервис: $Base · пользователь: $User · сброс: $($Reset.IsPresent) · мобильный: $($Mobile.IsPresent)"

# --- 1. API-набор ------------------------------------------------------------
Say ""
Say "== 1/3 API-набор (роли, заявки, комментарии/даты, вложения, часы, алерты) =="
$api = & $py -m pytest (Join-Path $svc "tests\test_buttons_api.py") -q 2>&1
$api = @($api)
$apiTail = ($api | Where-Object { $_ -match "passed|failed|error" } | Select-Object -Last 1)
Say ("  " + $apiTail)
($api | Select-Object -Last 25) | ForEach-Object { Say ("  " + $_) }

# --- 2. браузерный прогон ----------------------------------------------------
Say ""
Say "== 2/3 ИНТЕРФЕЙС (headless) =="
$browser = @(
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $browser) { Say "  headless Edge/Chrome не найден — шаг пропущен"; }
else {
  if ($Project) {
    $cid = (& docker compose -p $Project ps -q api | Out-String).Trim()
    if (-not $cid) { throw "контейнер api проекта '$Project' не найден — докер-стек не поднят?" }
    $driver = Join-Path $svc "app\web\__e2e.html"
    & docker cp $driver "${cid}:/workspace/services/app/web/__e2e.html" 2>&1 | Out-Null
    $inside = (& docker exec $cid sh -lc "wc -c < /workspace/services/app/web/__e2e.html" | Out-String).Trim()
    $local = (Get-Item $driver).Length
    Say "  __e2e.html в контейнере: $inside байт (локально $local)"
    if ([int]$inside -ne [int]$local) { throw "драйвер не скопировался в контейнер" }
  }
  $q = "user=$User" + $(if ($Reset) { "&reset=1" }) + $(if ($Mobile) { "&mobile=1" })
  if ($Fast) {
    $pwdF = if ($User -like "central*") { "central123" }
            elseif ($User -like "dispatcher*") { "alpha123" } else { "tech123" }
    $lb = @{ username = $User; password = $pwdF } | ConvertTo-Json
    $tk = (Invoke-RestMethod -Method Post -Uri "$Base/api/v1/auth/login" -ContentType 'application/json' -Body $lb).access_token
    $hh = @{ Authorization = "Bearer $tk" }
    try {
      $null = Invoke-RestMethod -Method Post -Uri "$Base/api/v1/admin/clock/speed" -Headers $hh `
              -ContentType 'application/json' -Body '{"level":4,"fast":true}'
      Say "  быстрый режим включён (4×, без SHAP-факторов)"
    } catch { Say "  быстрый режим включить не удалось: $($_.Exception.Message)" }
  }
  $url = "$Base/__e2e.html?$q"
  $tmp = Join-Path $env:TEMP ("e2e_" + [guid]::NewGuid().ToString("N") + ".html")
  Say "  открываю $url (таймаут $TimeoutSec с)"
  # быстрая проверка синтаксиса JS драйвера: опечатка в шагах иначе проявится только
  # как «прогон не завершился» (страница вообще не выполнит отчёт)
  $driverFile = Join-Path $svc "app\web\__e2e.html"
  $nodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
  if ($nodeExe) {
    $m = [regex]::Match((Get-Content -Raw -Encoding UTF8 $driverFile), '(?s)<script>(.*?)</script>')
    if ($m.Success) {
      $jsTmp = Join-Path $env:TEMP ("e2e_check_" + [guid]::NewGuid().ToString("N") + ".js")
      [IO.File]::WriteAllText($jsTmp, $m.Groups[1].Value, [Text.UTF8Encoding]::new($false))
      & $nodeExe --check $jsTmp 2>&1 | Out-Null
      $jsOk = ($LASTEXITCODE -eq 0)
      Remove-Item $jsTmp -Force -ErrorAction SilentlyContinue
      if (-not $jsOk) { throw "синтаксическая ошибка в app/web/__e2e.html — прогон остановлен (проверьте node --check)" }
      Say "  драйвер __e2e.html: синтаксис JS OK"
    }
  }
  $eargs = @("--headless=new", "--disable-gpu", "--no-sandbox", "--window-size=$Window",
            "--virtual-time-budget=2400000", "--dump-dom", $url)
  $p = Start-Process -FilePath $browser -ArgumentList $eargs -NoNewWindow -PassThru `
        -RedirectStandardOutput $tmp -RedirectStandardError (Join-Path $env:TEMP "e2e_err.txt")
  if (-not $p.WaitForExit($TimeoutSec * 1000)) {
    try { $p.Kill() } catch {}
    Say "  ⚠ браузер не завершился за $TimeoutSec с — отчёт ниже может быть неполным"
  }
  $html = if (Test-Path $tmp) { Get-Content $tmp -Raw } else { "" }
  Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  $title = ([regex]::Match($html, "<title>([^<]*)</title>")).Groups[1].Value
  $probe = ([regex]::Match($html, '(?s)<pre id="probe-out"[^>]*>(.*?)</pre>')).Groups[1].Value
  $md = ([regex]::Match($html, '(?s)<pre id="e2e-report"[^>]*>(.*?)</pre>')).Groups[1].Value
  $probe = $probe -replace '&lt;', '<' -replace '&gt;', '>' -replace '&amp;', '&'
  $md = $md -replace '&lt;', '<' -replace '&gt;', '>' -replace '&amp;', '&'
  Say ""
  ($probe -split "`n") | ForEach-Object { Say ("  " + $_) }
  Say ""
  if ($title -notlike "E2E*") {
    Say "  ⚠ прогон интерфейса не завершился (бюджет виртуального времени/таймаут): title=$title"
  }
  Say "  ИТОГ интерфейса: $title"
  if ($md) { $out += $md }
}

# --- 3. после сброса: наполняется ли тренд (реальное время) ------------------
$trendLine = ""
if ($Reset) {
  Say ""
  Say "== 3/3 ПОСЛЕ СБРОСА: наполнение «Тренда риска» (ждём 2 тика сим-часов, максимум $TrendWaitSec с) =="
  $pwd = if ($User -like "central*") { "central123" }
         elseif ($User -like "dispatcher*") { "alpha123" } else { "tech123" }
  $apiB = "$Base/api/v1"
  $loginBody = @{ username = $User; password = $pwd } | ConvertTo-Json
  $tok = (Invoke-RestMethod -Method Post -Uri "$apiB/auth/login" -ContentType 'application/json' -Body $loginBody).access_token
  $h = @{ Authorization = "Bearer $tok" }
  # состояние часов сразу после сброса: тик может длиться минуты (с SHAP), поэтому ждём
  # не по секундам, а по продвижению сим-времени — иначе проверка даёт ложную тревогу
  $c0 = Invoke-RestMethod -Uri "$apiB/meta/clock" -Headers $h
  $b0 = [int]$c0.bucket
  Say ("  после сброса: сим-время {0} · интервал тика {1} с · последний тик {2} с · быстрый режим: {3}" -f `
       $c0.sim_now, $c0.tick_sec, $c0.last_tick_sec, $c0.fast)
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $pts = 0; $adv = 0; $note = ""
  while ($sw.Elapsed.TotalSeconds -lt $TrendWaitSec) {
    try {
      $c = Invoke-RestMethod -Uri "$apiB/meta/clock" -Headers $h
      $adv = [int]$c.bucket - $b0
      $rh = Invoke-RestMethod -Uri "$apiB/meta/risk-history?task=wear&n=120&measure=risk30" -Headers $h
      $pts = @($rh.rows).Count
      $note = "сим-время {0}, тиков после сброса: {1}, последний тик {2} с" -f $c.sim_now, $adv, $c.last_tick_sec
    } catch { $pts = -1 }
    if ($pts -ge 2 -and $adv -ge 1) { break }
    Start-Sleep -Seconds 5
  }
  $sw.Stop()
  $trendLine = "точек тренда после сброса: $pts за $([int]$sw.Elapsed.TotalSeconds) с · $note (нужно ≥ 2 точки)"
  Say ("  " + $trendLine)
}

# --- итог и отчёт -----------------------------------------------------------
$apiOk = ($apiTail -match "passed") -and ($apiTail -notmatch "failed")
$uiOk = ($title -eq "E2E OK")
$trendOk = (-not $Reset) -or ($pts -ge 2)
$all = $apiOk -and $uiOk -and $trendOk

$head = @(
  "# Отчёт прогона «кнопочных» тестов", "",
  "- сервис: ``$Base``", "- пользователь: ``$User``",
  "- API-набор: $apiTail", "- интерфейс (headless): **$title**"
)
if ($trendLine) { $head += "- $trendLine" }
$head += "- итог: " + $(if ($all) { "**ALL OK**" } else { "**ЕСТЬ ПРОБЛЕМЫ**" })

$dir = Split-Path $rep -Parent
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
[IO.File]::WriteAllLines($rep, ($head + @("") + $out), [Text.UTF8Encoding]::new($false))

Say ""
Say "== ИТОГ: " + $(if ($all) { "ALL OK" } else { "ЕСТЬ ПРОБЛЕМЫ" }) + " =="
Say "отчёт: $rep"
if (-not $all) { exit 1 }
