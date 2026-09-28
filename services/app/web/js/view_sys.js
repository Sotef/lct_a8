/* view_sys.js — состояние сервиса: метрики, модели, сим-часы, live-хвост системного лога */
window.Views = window.Views || {};
Views.sys = (() => {
  const { el, esc, ic, fmt, fmtInt, dt } = UI;
  let tab = "overview", level = "", logger = "", q = "", paused = false, afterId = 0, lines = [];
  let timer = null;

  async function render(main, state) {
    stop();
    const role = API.store.user && API.store.user.role;
    if (role !== "central") { main.innerHTML = UI.emptyState("раздел доступен центральному диспетчеру", "lock"); return; }
    const F = UI.stage();               // сборка offscreen — панель не мигает на запросах
    const sys = await API.get("/admin/system").catch(() => null);
    const models = await API.get("/admin/models").catch(() => ({ models: [] }));
    const sources = await API.get("/admin/data/status").catch(() => ({ sources: [] }));
    if (!sys) { main.innerHTML = UI.emptyState("нет доступа к состоянию сервиса", "alert", "err-state"); return; }

    const head = el(`<div class="page-head">
      <div><div class="h1">Система</div>
        <div class="sub">состояние сервиса, модели, источники данных и живой хвост системного лога ·
          request-id каждого запроса виден в журнале</div></div>
      <div class="grow"></div>
      <div class="row wrap">
        <button class="btn ghost sm" id="rlm">${ic("refresh", "s")} Перезагрузить модели</button>
        <button class="btn ghost sm" id="dl">${ic("download", "s")} Скачать лог-файл</button></div></div>`);
    head.querySelector("#rlm").onclick = async e => {
      const b = e.currentTarget; b.classList.add("loading");
      try { const r = await API.post("/admin/models/reload"); UI.toast(`моделей перезагружено: ${(r.loaded || []).length}`, "ok"); }
      catch (err) { UI.toast(err.message, "err"); }
      finally { b.classList.remove("loading"); render(main, state); }
    };
    head.querySelector("#dl").onclick = () => downloadLog();

    const seg = el(`<div class="seg" id="tab" style="margin-bottom:16px">
      <button data-t="overview" class="${tab === "overview" ? "on" : ""}">${ic("server", "s")} Обзор</button>
      <button data-t="log" class="${tab === "log" ? "on" : ""}">${ic("terminal", "s")} Системный лог</button>
      <button data-t="models" class="${tab === "models" ? "on" : ""}">${ic("cpu", "s")} Модели и данные</button></div>`);
    FX.seg(seg, b => { tab = b.dataset.t; render(main, state, true); });

    F.appendChild(head); F.appendChild(seg);
    const host = el(`<div></div>`); F.appendChild(host);
    if (tab === "overview") renderOverview(host, sys, sources, main, state);
    else if (tab === "log") renderLog(host, main, state);
    else renderModels(host, models, sys);
    UI.mount(main, F, { merge: false });   // пересобираем целиком (живой лог держит ссылки на узлы)
    return true;
  }
  /* фон «сеть коллекторов»: скорость и отключение (сохраняется в браузере) */
  function bgCard() {
    const st = BGFX.state();
    const card = el(`<div class="card spot"><div class="ct">${ic("sparkles", "s")} Фон и анимации
      <span class="grow"></span><span class="faint" style="font-size:11.5px">сеть коллекторов за интерфейсом</span></div>
      <div class="row wrap" style="gap:12px;align-items:center">
        <div class="seg" id="bgsp">${BGFX.SPEEDS.map(v =>
          `<button data-v="${v}" class="${st.speed === v ? "on" : ""}">${BGFX.SPEED_RU[v]}</button>`).join("")}</div>
        <label class="chk"><input type="checkbox" id="bgpu" ${st.pulses ? "checked" : ""}> бегущие импульсы данных</label>
      </div>
      <div class="faint" style="font-size:11.5px;margin-top:10px">текущий режим: <b id="bgst">${esc(st.speed_ru)}</b>
        · настройка хранится в браузере и меняется из палитры команд: <b>Ctrl+K</b> → «Фон»</div>
      <div class="note">«Выкл» полностью останавливает отрисовку канваса (экономит батарею на ноутбуках),
        «Медленно» — фоновые частицы движутся спокойнее, «Быстро» — как в демо.</div></div>`);
    FX.seg(card.querySelector("#bgsp"), b => {
      BGFX.setSpeed(+b.dataset.v);
      const lbl = card.querySelector("#bgst");
      if (lbl) lbl.textContent = BGFX.SPEED_RU[BGFX.speed];
    });
    card.querySelector("#bgpu").onchange = e => BGFX.setPulses(e.target.checked);
    return card;
  }
  function renderOverview(host, sys, sources, main, state) {
    const c = sys.counts || {}, clk = sys.clock || {};
    const up = sys.uptime_sec || 0;
    const upStr = up > 86400 ? `${Math.floor(up / 86400)} д ${Math.floor(up % 86400 / 3600)} ч`
      : up > 3600 ? `${Math.floor(up / 3600)} ч ${Math.floor(up % 3600 / 60)} мин` : `${Math.floor(up / 60)} мин`;
    const stats = el(`<div class="stats"></div>`);
    [["прогнозов в БД", c.predictions], ["решений диспетчера", c.decisions], ["заявок", c.tickets],
     ["записей аудита", c.audit], ["пользователей", c.users], ["объектов / каналов", `${c.objects} / ${c.channels}`],
     ["uptime", upStr], ["лог-файл, байт", (sys.log && sys.log.size) || 0]].forEach(([l, v], i) => {
      stats.appendChild(el(`<div class="stat rv" style="--i:${i}"><div class="l">${esc(l)}</div>
        <div class="v num">${typeof v === "number" ? fmtInt(v) : esc(v)}</div></div>`));
    });
    const card = el(`<div class="card spot"><div class="ct">${ic("server", "s")} Контур</div>
      <div class="kv"><dt>Python</dt><dd>${esc(sys.python || "—")}</dd>
        <dt>Платформа</dt><dd>${esc((sys.platform || "").slice(0, 46))}</dd>
        <dt>БД</dt><dd>${esc(sys.db || "—")}</dd>
        <dt>уровень лога</dt><dd>${esc((sys.log && sys.log.level) || "—")} ${sys.log && sys.log.json ? "(JSON lines)" : ""}</dd>
        <dt>буфер логов</dt><dd>${fmtInt((sys.log && sys.log.buffer_last_id) || 0)} записей</dd></div>
      <div class="note" style="word-break:break-all">${esc((sys.log && sys.log.file) || "—")}</div></div>`);
    const clock = el(`<div class="card spot"><div class="ct">${ic("clock", "s")} Симулируемые часы (реплей 2026)
      <span class="grow"></span>
      ${clk.paused ? '<span class="badge mid pulse">пауза</span>' : '<span class="badge low">идёт</span>'}
      <span class="badge ${clk.loop ? "info" : ""}">${clk.loop ? "цикл включён" : "цикл выключен"}</span></div>
      <div class="kv"><dt>сим-время</dt><dd>${clk.sim_now ? esc(clk.sim_now.replace("T", " ")) : "—"}</dd>
        <dt>начало цикла</dt><dd>${clk.start_ts ? esc(clk.start_ts.replace("T", " ")) : "—"}</dd>
        <dt>конец данных</dt><dd>${clk.panel_max_ts ? esc(clk.panel_max_ts.replace("T", " ")) : "—"}</dd>
        <dt>бакет</dt><dd>${clk.bucket !== null && clk.bucket !== undefined ? clk.bucket : "—"}</dd>
        <dt>шаг</dt><dd>${clk.tick_sec || "—"} с реального времени = 6 ч сим-времени</dd>
        <dt>следующий тик</dt><dd>${clk.next_tick_in_sec !== null && clk.next_tick_in_sec !== undefined
          ? clk.next_tick_in_sec + " с" : (clk.paused ? "пауза" : "ожидание")}</dd>
        <dt>расчёт</dt><dd>${clk.computing ? "идёт…" : "свободен"}</dd></div>
      <div class="rbar" style="margin-top:10px"><i data-w="${Math.round((clk.progress || 0) * 100)}%"></i></div>
      <div class="faint" style="font-size:11px;margin-top:6px">пройдено ${Math.round((clk.progress || 0) * 100)}%
        периода; по достижении конца данных реплей начинается заново с 01.01.2026</div>
      <div style="margin-top:14px">
        <div class="faint" style="font-size:10.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px">
          Скорость демо-прокрута</div>
        <div class="row wrap">
          <div class="seg" id="c-speed">${[1, 2, 4, 8].map(l =>
            `<button data-l="${l}" class="${(clk.speed || 1) === l ? "on" : ""}">${l}×</button>`).join("")}</div>
          <span class="faint" style="font-size:11.5px">интервал ${clk.tick_sec || "—"} с ·
            ${clk.buckets_per_hour || "—"} бакетов/ч · полный проход ≈ ${clk.full_pass_hours || "—"} ч</span>
        </div>
        <div class="row wrap" style="margin-top:10px">
          <label class="chk" title="SHAP — самое дорогое место тика (~43 с на задачу). Без него тик идёт ~0.6 с; в карточках прогнозов будет «факторы не сохранены»">
            <input type="checkbox" id="c-fast" ${clk.fast ? "checked" : ""}>
            быстрый расчёт: без SHAP-факторов (тик ~×100 быстрее)</label>
          <label class="chk" title="Обычно не ускоряет: SHAP и так использует все ядра; помогает только в быстром режиме">
            <input type="checkbox" id="c-par" ${clk.parallel ? "checked" : ""}>
            параллельный расчёт задач</label>
          <span class="faint" style="font-size:11.5px">последний тик: ${clk.last_tick_sec !== null && clk.last_tick_sec !== undefined
            ? clk.last_tick_sec + " с" : "—"}</span>
        </div>
        ${!clk.fast && clk.last_tick_sec && clk.last_tick_sec > 20 ? `<div class="note">
          тик занимает ~${clk.last_tick_sec} с — почти всё время уходит на SHAP-факторы «почему».
          Включите «быстрый расчёт»: прокрут пойдёт в ~100 раз быстрее, а в карточках прогнозов
          вместо факторов появится честная надпись «факторы не сохранены».</div>` : ""}
      </div>
      <div class="row wrap" style="margin-top:12px">
        <button class="btn ghost sm" id="c-reset">${ic("refresh", "s")} Заново с января</button>
        <button class="btn ghost sm" id="c-pause">${ic(clk.paused ? "play" : "pause", "s")} ${clk.paused ? "Продолжить" : "Пауза"}</button>
        <button class="btn ghost sm" id="c-step">${ic("chevron", "s")} Шаг +6 ч</button></div>
      <div class="faint" style="font-size:11.5px;margin-top:8px">перезапуск круга касается только прогнозов:
        решения диспетчера, назначенные и выполненные заявки и журнал аудита сохраняются</div>
      ${clk.last_counts ? `<div class="note">последний тик: ${Object.entries(clk.last_counts)
        .map(([k, v]) => `${esc(k)}=${esc(v)}`).join(" · ")}</div>` : ""}
      ${clk.error ? `<div class="note" style="color:var(--bad)">${esc(String(clk.error)).slice(0, 300)}</div>` : ""}</div>`);
    const models = el(`<div class="card spot"><div class="ct">${ic("cpu", "s")} Модели ·
      ${esc(sys.auto_tickets && sys.auto_tickets.enabled ? "автозаявки включены" : "автозаявки выключены")}</div>
      <div class="stack">${API.TASKS.map(t => {
        const ok = (sys.models || {})[t] === "ok";
        return `<div class="row" style="justify-content:space-between">
          <span><b>${esc(API.TASK_META[t].label)}</b> <span class="faint num" style="font-size:11px">${esc(t)}</span></span>
          <span class="badge ${ok ? "low" : "high"}">${ic(ok ? "check" : "alert", "s")} ${ok ? "загружена" : esc(sys.models[t] || "нет")}</span></div>`;
      }).join("")}</div>
      ${sys.auto_tickets ? `<div class="note">порог автоформирования заявок: risk30 ≥ ${sys.auto_tickets.min_risk},
        не больше ${sys.auto_tickets.top_k} каналов за тик</div>` : ""}</div>`);
    const src = el(`<div class="card flat"><div class="ct" style="padding:0 0 12px">${ic("layers", "s")} Источники данных</div>
      <table class="tbl"><thead><tr><th>источник</th><th>тип</th><th>статус</th><th>строк</th><th>обновлён</th></tr></thead>
      <tbody>${(sources.sources || []).map(s => `<tr><td><b>${esc(s.name)}</b></td><td class="muted">${esc(s.kind)}</td>
        <td><span class="badge ${s.status === "ok" ? "low" : s.status === "error" ? "high" : ""}">${esc(s.status)}</span></td>
        <td class="num">${fmtInt(s.rows || 0)}</td><td class="faint">${s.last_load_end ? dt(s.last_load_end) : "—"}</td></tr>`).join("")
        || `<tr><td colspan="5">${UI.emptyState("источники ещё не загружались", "layers")}</td></tr>`}</tbody></table></div>`);
    const grid = el(`<div class="grid2" style="margin-top:16px"><div class="stack"></div><div class="stack"></div></div>`);
    grid.children[0].appendChild(card); grid.children[0].appendChild(models);
    grid.children[1].appendChild(clock); grid.children[1].appendChild(bgCard()); grid.children[1].appendChild(src);
    host.appendChild(stats); host.appendChild(grid);
    FX.bars(clock);

    /* управление реплеем: пауза / шаг / перезапуск с января / скорость */
    const call = async (path, btn, confirmText, opts) => {
      if (confirmText && !(await Overlay.confirm("Перезапустить реплей?", confirmText,
                                                 "Заново с января", "dang"))) return;
      btn.classList.add("loading");
      try {
        const r = await API.post(path, opts && opts.json);
        const c = r.clock || {};
        UI.toast(`сим-время ${(c.sim_now || "").replace("T", " ")}${c.paused ? " · пауза" : ""}`
          + (opts && opts.json && opts.json.level ? ` · ${c.speed}×` : ""), "ok",
          { title: "Реплей данных" });
        API.invalidate();
        if (main && state) await Views.sys.render(main, state); else location.reload();
      } catch (e) { UI.toast(e.message, "err"); btn.classList.remove("loading"); }
    };
    clock.querySelector("#c-reset").onclick = e => call("/admin/clock/reset", e.currentTarget,
      "Прогнозы будут пересчитаны заново с 01.01.2026. Решения диспетчера, назначенные/выполненные заявки "
      + "и журнал аудита СОХРАНЯЮТСЯ — удаляются только прогнозы и необработанные предложения автоформирования "
      + "(модель сформирует их заново на новом круге).");
    clock.querySelector("#c-pause").onclick = e => call(clk.paused ? "/admin/clock/resume" : "/admin/clock/pause",
      e.currentTarget);
    clock.querySelector("#c-step").onclick = e => call("/admin/clock/step?n=1", e.currentTarget);
    /* скорость прокрута: уровень 1×/2×/4×/8× + тумблеры расчёта */
    FX.seg(clock.querySelector("#c-speed"), b =>
      call("/admin/clock/speed", b, null, { json: { level: +b.dataset.l } }));
    clock.querySelector("#c-fast").onchange = e =>
      call("/admin/clock/speed", e.currentTarget, null, { json: { fast: e.target.checked } });
    clock.querySelector("#c-par").onchange = e =>
      call("/admin/clock/speed", e.currentTarget, null, { json: { parallel: e.target.checked } });
  }
  function renderLog(host, main, state) {
    const bar = el(`<div class="toolrow">
      <select id="lv"><option value="">все уровни</option>${["INFO", "WARNING", "ERROR", "DEBUG"].map(l =>
        `<option value="${l}" ${level === l ? "selected" : ""}>${l}+</option>`).join("")}</select>
      <select id="lg"><option value="">все логгеры</option>${["http", "audit", "maintenance", "main", "admin", "client", "simclock", "uvicorn"]
        .map(l => `<option value="${l}" ${logger === l ? "selected" : ""}>${l}</option>`).join("")}</select>
      <input type="search" id="lq" placeholder="подстрока в сообщении…" value="${esc(q)}">
      <label class="chk"><input type="checkbox" id="lp" ${paused ? "checked" : ""}> пауза</label>
      <span class="grow"></span>
      <span class="faint" id="lcnt">${lines.length} строк</span>
      <button class="btn ghost sm" id="lclr">${ic("x", "s")} очистить вид</button></div>`);
    const cons = el(`<div class="console"></div>`);
    host.appendChild(el(`<div class="note">${ic("terminal", "s")} Живой хвост системного лога (кольцевой буфер сервиса).
      Обновляется каждые 4 с; файл целиком — кнопкой «Скачать лог-файл». Клик по строке раскрывает детали.</div>`));
    host.appendChild(bar); host.appendChild(cons);
    bar.querySelector("#lv").onchange = e => { level = e.target.value; reload(cons, host); };
    bar.querySelector("#lg").onchange = e => { logger = e.target.value; reload(cons, host); };
    bar.querySelector("#lq").oninput = UI.debounce(e => { q = e.target.value.trim(); reload(cons, host); }, 350);
    bar.querySelector("#lp").onchange = e => { paused = e.target.checked; };
    bar.querySelector("#lclr").onclick = () => { lines = []; afterId = 0; cons.innerHTML = ""; paint(cons, host); };
    reload(cons, host);
    timer = setInterval(() => { if (!paused) poll(cons, host); }, 4000);
    paint(cons, host);
  }

  function paint(cons, host) {
    cons.innerHTML = "";
    lines.slice(-800).forEach((l, i) => cons.appendChild(line(l, i)));
    cons.scrollTop = cons.scrollHeight;
    const cnt = host.querySelector("#lcnt");
    if (cnt) cnt.textContent = `${lines.length} строк`;
  }

  function line(l, i) {
    const node = el(`<div class="lrow ${esc(l.level)}" style="--i:${Math.min(i, 30)}">
      <span class="lt">${esc((l.ts || "").slice(11, 19))}</span>
      <span class="lv">${esc(l.level)}</span>
      <span class="lg" title="${esc(l.logger)}">${esc(l.logger)}</span>
      <span class="lm">${esc(l.msg)}</span></div>`);
    node.onclick = () => {
      const ex = node.querySelector(".lx");
      if (ex) { ex.remove(); return; }
      node.appendChild(el(`<div class="lx"><pre class="json">${esc(JSON.stringify({
        ts: l.ts, level: l.level, logger: l.logger, request_id: l.request_id,
        user: l.user, ip: l.ip, data: l.data, exc: l.exc,
      }, null, 2))}</pre></div>`));
    };
    return node;
  }

  async function reload(cons, host) {
    lines = []; afterId = 0;
    await poll(cons, host);
  }

  async function poll(cons, host) {
    const qp = new URLSearchParams({ after_id: afterId, limit: 400 });
    if (level) qp.set("level", level);
    if (logger) qp.set("logger", logger);
    if (q) qp.set("q", q);
    const data = await API.get(`/admin/logs?${qp}`).catch(() => null);
    if (!data) return;
    if (data.items && data.items.length) {
      lines = lines.concat(data.items).slice(-1200);
      afterId = data.last_id;
      paint(cons, host);
    } else if (!lines.length) {
      cons.innerHTML = UI.emptyState("в буфере пока нет записей по фильтру", "terminal");
    }
  }

  async function downloadLog() {
    try {
      const text = await API.req("/admin/logs/file");
      const blob = new Blob([typeof text === "string" ? text : JSON.stringify(text)],
        { type: "text/plain;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `moscolllector-app-${new Date().toISOString().slice(0, 10)}.log`;
      a.click(); URL.revokeObjectURL(a.href);
      UI.toast("лог-файл выгружен", "ok");
    } catch (e) { UI.toast(e.message, "err"); }
  }

  function renderModels(host, data, sys) {
    const rows = data.models || [];
    const card = el(`<div class="card flat"><div class="ct" style="padding:0 0 12px">${ic("cpu", "s")} Реестр моделей
      <span class="grow"></span><span class="faint" style="text-transform:none">models_registry: версия, пути артефактов, метрики</span></div>
      <table class="tbl"><thead><tr><th>направление</th><th>версия</th><th>обучена на</th><th>активна</th>
        <th>модель</th><th>калибровка</th></tr></thead><tbody>${rows.map(r => `<tr>
        <td><b>${esc(API.TASK_META[r.task] ? API.TASK_META[r.task].label : r.task)}</b></td>
        <td class="num">${esc(r.version || "—")}</td><td class="muted">${esc(r.trained_on || "—")}</td>
        <td><span class="badge ${r.active ? "low" : ""}">${r.active ? "да" : "нет"}</span></td>
        <td class="num faint" style="font-size:11px;word-break:break-all">${esc((r.model_path || "").split(/[\\/]/).pop() || "—")}</td>
        <td class="num faint" style="font-size:11px">${esc((r.calib_path || "").split(/[\\/]/).pop() || "нет")}</td></tr>`).join("")
        || `<tr><td colspan="6">${UI.emptyState("реестр пуст — выполните scripts/seed.py", "cpu")}</td></tr>`}</tbody></table></div>`);
    host.appendChild(card);
    host.appendChild(el(`<div class="note">${ic("info", "s")} Модели перезагружаются без рестарта сервиса
      (кнопка «Перезагрузить модели»): активные артефакты читаются заново, прогнозы следующего тика считаются на новой версии.
      ${sys && sys.auto_tickets ? `Автоформирование заявок: risk30 ≥ ${sys.auto_tickets.min_risk}, top-${sys.auto_tickets.top_k} за тик.` : ""}</div>`));
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  return { render, destroy: stop, name: "Система", icon: "server" };
})();
