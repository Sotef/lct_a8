/* view_dashboard.js — пульт: KPI по направлениям, тренд, топ-риски, заявки, лента действий */
window.Views = window.Views || {};
Views.dashboard = (() => {
  const { el, esc, ic, fmt, dt, riskLevel, riskColor } = UI;
  let horizon = "72h", topMode = "objects";
  const HZ = {
    "24h": { btn: "24 ч", field: "p24", cap: "P ≤ 24 ч" },
    "72h": { btn: "72 ч", field: "p72", cap: "P ≤ 72 ч" },
    "30d": { btn: "30 дн", field: "risk_used", cap: "P ≤ 30 дн" },
  };
  const grab = (p, fb) => API.get(p).catch(() => fb);

  async function render(main, state, silent) {
    const task = state.task || "wear";
    /* сборка идёт в offscreen-фрагмент: живой раздел остаётся на экране,
       пока грузятся данные, а затем обновляется мягко (тик/фильтр — только поля) */
    const F = UI.stage();
    UI.quiet(main, silent);
    const [summary, tickets, top, topObj] = await Promise.all([
      grab("/meta/summary", {}),
      grab("/maintenance/summary", { by_status: {}, open: 0 }),
      grab(`/top-risks?task=${task}&k=14&horizon=${horizon}`, { items: [] }),
      topMode === "objects" ? grab(`/top-objects?task=${task}&k=8&horizon=${horizon}`, { items: [] }) : { items: [] },
    ]);
    const hz = HZ[horizon];

    F.appendChild(renderHead(main, state, task));

    /* --- KPI по направлениям --- */
    const kpis = el(`<div class="kpis"></div>`);
    API.TASKS.forEach((t, i) => {
      const s = summary[t] || {}, m = API.TASK_META[t], on = t === task, avg = s.avg_risk;
      const k = el(`<div class="kpi ${on ? "on" : ""} rv" data-tilt data-t="${t}" style="--i:${i};--kc:${m.color}">
        <div class="kglow"></div>
        <div class="t">${ic(m.icon)} ${esc(m.label)}${s.bucket ? "" : '<span class="tag badge">нет данных</span>'}</div>
        <div class="v" data-cnt="${s.n || 0}">0<small>каналов</small></div>
        <div class="rw"><span>риск ср. <b>${fmt(avg, 2)}</b></span><span>p24 <b>${fmt(s.avg_p24, 3)}</b></span></div>
        <div class="rw"><span>высоких <b style="color:var(--bad)">${s.high || 0}</b></span>
          <span>критичных <b style="color:var(--bad)">${s.critical || 0}</b></span>
          <span>событий <b style="color:var(--accent-2)">${s.active || 0}</b></span></div>
        <div class="bar"><i data-w="${Math.min(100, (avg || 0) * 100)}" style="background:${riskColor(avg || 0)}"></i></div>
        <div class="faint" style="margin-top:8px;font-size:11px">${s.bucket ? "бакет " + dt(s.bucket) : "ожидает расчёта"}</div></div>`);
      k.onclick = () => switchTask(t, state);
      kpis.appendChild(k);
    });
    F.appendChild(kpis);

    const topCard = renderTop(main, state, task, hz, top, topObj);
    const tkCard = renderTickets(state, tickets);
    const trendCard = renderTrend(main, state, task);
    const factCard = renderFacts(main, state);

    const g1 = el(`<div class="grid2 rv"><div class="stack"></div><div class="stack"></div></div>`);
    g1.children[0].appendChild(trendCard);
    g1.children[0].appendChild(tkCard);
    g1.children[1].appendChild(topCard);
    F.appendChild(g1);
    const g2 = el(`<div class="grid2 rv"><div class="stack" data-key="facts"></div><div class="stack"></div></div>`);
    g2.children[0].appendChild(factCard);
    F.appendChild(g2);

    UI.mount(main, F, { merge: !!main.dataset.mounted, quiet: silent });
    main.dataset.mounted = "1";
    /* счётчики и полосы — уже по живым узлам (после постановки) */
    main.querySelectorAll("[data-cnt]").forEach(n => UI.countUp(n, +n.dataset.cnt, { d: 0 }));
    const opn = main.querySelector("[data-open]");
    if (opn) UI.countUp(opn, +opn.dataset.open, { d: 0 });
    FX.bars(main);
    loadActivity(main, state);
    UI.live(() => render(main, state, true), 25000);
    return true;
  }

  /* Реальные происшествия (журнал) против прогнозов: что произошло и когда это предсказали.

     Карточка грузит данные сама (как тренд), но, в отличие от первой версии, рисует в ЖИВОЙ
     узел и хранит последний ответ в кэше — панель не «пропадает» при перерисовке пульта
     на каждом тике и не требует ручного «обновить». Происшествия за последние 24 ч
     сим-времени помечены (бейдж «24 ч») и показываются постоянно. */
  let factGen = 0;
  const factCache = {};                       // task -> последний ответ /meta/events
  function renderFacts(main, state) {
    const task = state.task || "wear";
    const card = el(`<div class="card spot rv" id="factcard"><div class="ct">${ic("activity", "s")}
      Реальные происшествия и прогнозы
      <span class="grow"></span>
      <span class="faint" id="fact-thr" style="font-size:11px"></span>
      <button class="btn ghost xs" id="fact-rf">${ic("refresh", "s")} обновить</button></div>
      <div class="row wrap" id="fact-sum" style="gap:8px;margin:8px 0"></div>
      <div class="tscroll" id="fact-body" style="max-height:360px"></div>
      <div class="faint" id="fact-note" style="font-size:11px;margin-top:6px"></div></div>`);
    /* пишем и в новый узел, и в живой (мягкое обновление пульта может подменить узел) */
    const targets = () => {
      const live = main && main.querySelector("#factcard");
      return (live && live !== card) ? [live, card] : [card];
    };
    const paint = d => {
      const s = d.summary;
      const pct = v => v === null || v === undefined ? "—" : Math.round(v * 100) + "%";
      targets().forEach(h => {
        const thr = h.querySelector("#fact-thr"), sum = h.querySelector("#fact-sum");
        const body = h.querySelector("#fact-body"), note = h.querySelector("#fact-note");
        if (!body) return;
        thr.textContent = `порог p24 ≥ ${d.threshold} · ${d.fact_kind}`;
        sum.innerHTML = [
          ["событий", s.events, ""],
          [`предсказано`, `${s.predicted} (${pct(s.recall)})`, s.recall >= 0.5 ? "low" : "mid"],
          ["за 24 ч", s.recent != null ? s.recent : "—", s.recent ? "info" : "faint"],
          ["алертов", s.alerts, ""], ["попаданий", `${s.hits} (${pct(s.precision)})`, ""],
          ["упреждение", s.median_lead_h === null ? "—" : s.median_lead_h + " ч", ""],
          ["ППР (искл.)", s.planned_ppr, "faint"],
        ].map(([l, v, cls]) => `<span class="badge ${cls}">${esc(l)}: <b>${esc(String(v))}</b></span>`).join("");
        const it = d.items || [];
        body.innerHTML = it.length ? `<table class="tbl"><thead><tr>
            <th>произошло</th><th>что именно</th><th>класс</th><th>предсказано</th></tr></thead><tbody>
          ${it.slice(0, 60).map(x => `<tr data-pid="${x.prediction_id || ""}" data-fpid="${x.прогноз_prediction_id || ""}"
              style="cursor:pointer">
            <td class="num">${esc(x.произошло)}${x.свежее ? ' <span class="badge high">24 ч</span>' : ""}
              <div class="faint" style="font-size:10px">${esc(x.событий_в_бакете || 0)} соб.</div></td>
            <td><b>${esc(x.тип_датчика || "—")}</b>${x.название_датчика ? ` · ${esc(x.название_датчика)}` : ""}
              <div class="faint" style="font-size:10.5px">объект ${esc(x.object_id)}${x.object_name ? " · " + esc(x.object_name) : ""}
              ${x.похоже_на_ППР ? ' · <span class="badge faint">ППР</span>' : ""}</div></td>
            <td>${x.группа_события ? `<span class="badge ${x.класс_события === "авария" ? "high" : "mid"}">${esc(x.группа_события)}</span>` : "—"}</td>
            <td>${x.предсказано
              ? `<span class="badge low">${esc(x.прогноз_бакет)}</span>
                 <div class="faint" style="font-size:10.5px">за ${x.предсказано_за_ч} ч · p24=${x.прогноз_p24}</div>`
              : '<span class="badge high">пропущено моделью</span>'}</td></tr>`).join("")}
        </tbody></table>` : UI.emptyState("в текущем круге реплея происшествий пока нет", "activity");
        body.querySelectorAll("[data-fpid],[data-pid]").forEach(tr => tr.onclick = () => {
          const pid = +tr.dataset.fpid || +tr.dataset.pid;
          if (pid) Cards.forecast.open(pid, { onDecided: () => reload() });
        });
        note.textContent = d.note || "";
        const rf = h.querySelector("#fact-rf");
        if (rf) rf.onclick = reload;
      });
    };
    const reload = async () => {
      const my = ++factGen;
      if (factCache[task]) paint(factCache[task]);     // сразу показываем прошлые данные
      const d = await API.get(`/meta/events?task=${task}&n=60`).catch(() => null);
      if (my !== factGen) return;                      // ответ устаревшего запроса не рисуем
      if (!d || !d.summary) return;                    // ошибка сети — оставляем прежнюю картину
      factCache[task] = d;
      paint(d);
    };
    card.querySelector("#fact-rf").onclick = reload;
    reload();
    return card;
  }


  const MEAS = [["p24", "1 день"], ["p72", "3 дня"], ["p7d", "7 дней"], ["risk30", "30 дней"]];
  /* Сглаживание среднего: в бакете от 16 до 1146 активных каналов, поэтому сырое среднее
     «пилит» и на каждом тике график выглядит новым. По умолчанию 24 ч (4 бакета). */
  const SMOOTH = [[1, "6 ч"], [4, "24 ч"], [12, "3 сут"]];
  const MIN_N = 20;                    // бакеты с меньшим числом каналов помечаем как ненадёжные
  /* Тренд риска: свой выбор горизонта (1/3/7/30 дней) и режима «средний/максимум».
     Карточка сама грузит данные — переключение не перерисовывает весь пульт.

     Важно: пульт перерисовывается на каждом тике сим-часов и по live-таймеру, поэтому
     в полёте могут оказаться несколько запросов (например, за старый горизонт или за
     прежний объект). Ответ устаревшего запроса НЕ должен перетирать актуальный график —
     для этого служит счётчик поколений trendGen: рисует только самый свежий запрос. */
  let trendGen = 0;
  function renderTrend(main, state, task) {
    const { el, esc, ic } = UI;
    let measure = localStorage.getItem("mc_trend_measure") || "risk30";
    let showMax = localStorage.getItem("mc_trend_max") !== "0";
    let smooth = +localStorage.getItem("mc_trend_smooth") || 4;
    const card = el(`<div class="card spot" data-key="trend"><div class="ct">${ic("activity", "s")} Тренд риска ·
      ${esc(API.TASK_META[task].label)}
      <span class="grow"></span>
      <div class="seg" id="tseg">${MEAS.map(([m, l]) =>
        `<button data-m="${m}" class="${m === measure ? "on" : ""}">${l}</button>`).join("")}</div>
      <label class="faint" style="font-size:11px;gap:6px">сглаживание
        <span class="seg" id="tsm">${SMOOTH.map(([v, l]) =>
          `<button data-v="${v}" class="${v === smooth ? "on" : ""}">${l}</button>`).join("")}</span></label>
      <label class="chk" title="Показывать худший канал — иногда он «прибит» к 100% и зашумляет средний">
        <input type="checkbox" id="tmax" ${showMax ? "checked" : ""}> максимум</label></div>
      <div class="chart-body" id="trend-body" data-keep></div></div>`);
    /* Отрисовка идёт в ЖИВОЙ узел карточки (при мягком обновлении карточка не пересобирается),
       а прошлая кривая остаётся на месте, пока не придут новые данные — без «пропадания». */
    const bodyOf = () => (main && main.querySelector("#trend-body")) || card.querySelector("#trend-body");
    const draw = async () => {
      const my = ++trendGen;                    // наш номер поколения
      const body = bodyOf();
      if (!body) return;
      if (!body.querySelector("svg")) {         // скелетон — только когда показывать нечего
        body.innerHTML = "";
        body.appendChild(UI.skeleton(1, 200));
      }
      const q = `/meta/risk-history?task=${task}&n=120&measure=${measure}`
        + `&smooth=${smooth}&min_n=${MIN_N}`;
      const d = await API.get(q, 20000).catch(() => ({ rows: [] }));
      if (my !== trendGen) return;              // запущен более свежий запрос — этот ответ устарел
      const live = bodyOf();                    // узел мог быть подменён морфингом при перерисовке
      if (!live) return;                        // ушли с раздела — рисовать некуда
      live.innerHTML = "";
      const rows = d.rows || [];
      live.appendChild(Charts.trend(rows, { showMax, h: 250 }));
      /* Подпись: для полного ряда — выбранный горизонт и число точек; для короткого
         (сразу после «Заново с января») — понятное объяснение, что происходит и когда
         ждать данные, иначе кажется, что график «сломался». */
      const clk = state.clock || {};
      const simNow = clk.sim_now ? String(clk.sim_now).slice(0, 16).replace("T", " ") : "—";
      const nextTick = (clk.next_tick_in_sec !== null && clk.next_tick_in_sec !== undefined)
        ? ` · следующий тик ~${clk.next_tick_in_sec} с` : "";
      const smRu = ({ 1: "6 ч", 4: "24 ч", 12: "3 сут" })[smooth] || `${smooth * 6} ч`;
      const ns = rows.map(r => r.n || 0);
      const thin = (d.total || rows.length) - (d.n_valid === undefined ? rows.length : d.n_valid);
      const hint = rows.length >= 2
        ? `${d.measure_ru || ""} · сглажено ${smRu} · ${rows.length} точек`
          + ` · по постоянным каналам${d.cohort_n ? ` (когорта ${d.cohort_n})` : ""}`
          + ` · каналов в бакете ${ns.length ? Math.min(...ns) + "…" + Math.max(...ns) : "—"}`
          + (thin > 0 ? ` · тонких бакетов (n<${MIN_N}): ${thin}` : "")
        : `точек пока ${rows.length} — история накапливается по 6ч-бакету за тик (сим-время ${simNow}${nextTick}). `
          + "После «Заново с января» первый прогноз появляется через ~один тик, кривая растёт дальше сама";
      live.appendChild(el(`<div class="faint" id="trend-hint" style="font-size:11.5px;margin-top:2px">${esc(hint)}</div>`));
    };
    FX.seg(card.querySelector("#tseg"), b => {
      measure = b.dataset.m; localStorage.setItem("mc_trend_measure", measure); draw();
    });
    FX.seg(card.querySelector("#tsm"), b => {
      smooth = +b.dataset.v; localStorage.setItem("mc_trend_smooth", String(smooth)); draw();
    });
    card.querySelector("#tmax").onchange = e => {
      showMax = e.target.checked; localStorage.setItem("mc_trend_max", showMax ? "1" : "0"); draw();
    };
    draw();
    return card;
  }

  function renderHead(main, state, task) {
    const { el, esc, ic } = UI;
    const u = (API.store.user || {}).username || "";
    const hh = new Date().getHours();
    const greet = hh < 6 ? "Доброй ночи" : hh < 12 ? "Доброе утро" : hh < 18 ? "Добрый день" : "Добрый вечер";
    const head = el(`<div class="page-head">
      <div><div class="h1">${greet}, <span class="gt">${esc(u.split(".")[0] || "диспетчер")}</span></div>
        <div class="sub">Пульт предиктивной аналитики · горизонт до 30 дней · журнал СМВУ в режиме реплея
        ${state.clock && state.clock.sim_now ? `· сим-время ${esc(state.clock.sim_now.slice(0, 16).replace("T", " "))}` : ""}</div></div>
      <div class="grow"></div>
      <div class="row wrap">
        <button class="btn ghost sm" id="rf">${ic("refresh", "s")} Обновить</button>
        ${["dispatcher", "central"].includes(API.store.user && API.store.user.role)
          ? `<button class="btn sm" id="mk" title="Открыть превентивные заявки по каналам с высоким риском (risk30 выше порога автоформирования). Дубли не создаются — существующая заявка просто назначается.">${ic("sparkles", "s")} Сформировать заявки</button>` : ""}
      </div></div>`);
    head.querySelector("#rf").onclick = () => { API.invalidate(); render(main, state); UI.toast("данные обновлены", "ok"); };
    const mk = head.querySelector("#mk");
    if (mk) mk.onclick = async () => {
      mk.classList.add("loading");
      try {
        const r = await UI.autoGenerate({ task: state.task });
        if (r) render(main, state, true);
      } finally { mk.classList.remove("loading"); }
    };
    return head;
  }

  function renderTop(main, state, task, hz, top, topObj) {
    const { el, esc, ic, fmt, riskLevel, riskColor } = UI;
    const card = el(`<div class="card spot"><div class="ct">${ic("alert", "s")} Топ-риски · ${esc(API.TASK_META[task].label)}
      <span class="grow"></span>
      <div class="seg" id="seghz">${Object.keys(HZ).map(h =>
        `<button data-h="${h}" class="${h === horizon ? "on" : ""}">${HZ[h].btn}</button>`).join("")}</div>
      <div class="seg" id="segmode">
        <button data-m="objects" class="${topMode === "objects" ? "on" : ""}">объекты</button>
        <button data-m="channels" class="${topMode === "channels" ? "on" : ""}">датчики</button></div></div>
      <div class="rlist"></div></div>`);
    FX.seg(card.querySelector("#seghz"), () => {
      horizon = card.querySelector("#seghz button.on").dataset.h; render(main, state, true); });
    FX.seg(card.querySelector("#segmode"), () => {
      topMode = card.querySelector("#segmode button.on").dataset.m; render(main, state, true); });
    const rl = card.querySelector(".rlist");
    const items = topMode === "objects" ? topObj.items : top.items;
    if (!items || !items.length) {
      rl.appendChild(el(UI.emptyState("прогнозы для текущего бакета ещё не рассчитаны — дождитесь ближайшего тика сим-времени", "clock")));
      return card;
    }
    if (topMode === "objects") {
      rl.appendChild(el(`<div class="faint" style="font-size:11.5px">вклад объекта = Σ (severity канала × P события за ${esc(hz.btn)}) · клик — карточка топ-канала</div>`));
      topObj.items.forEach((o, i) => {
        const mx = o["риск_макс"] || 0, lv = riskLevel(mx);
        const row = el(`<div class="ritem rv-row" style="--i:${i}">
          <div class="rank">${i + 1}</div>
          <div class="mid">
            <div class="obj"><span class="nm">${esc(o["название_объекта"] || "объект " + o.object_id)}</span>
              <span class="badge ${lv.cls}">макс ${fmt(mx, 2)}</span></div>
            <div class="sen">${esc(o["тип_объекта"] || "")} · район ${esc(o["район"] || "—")} · каналов ${o["каналов"]}</div>
            <div class="rbar"><i data-w="${Math.min(100, mx * 100)}" style="background:${riskColor(mx)}"></i></div></div>
          <div class="pr"><b>${fmt(o["вклад"], 2)}</b>Σ вклад</div>
          <span class="go">${ic("chevron")}</span></div>`);
        row.onclick = () => (o.top_channels && o.top_channels.length)
          ? Cards.forecast.open(o.top_channels[0].prediction_id, { onDecided: () => render(main, state, true) })
          : Cards.object.open(o.object_id, { state, task });
        rl.appendChild(row);
      });
    } else {
      top.items.forEach((it, i) => {
        const ph = hz.field === "risk_used" ? UI.riskOf(it) : (it[hz.field] || 0);
        const r30 = UI.riskOf(it), lv = riskLevel(r30), tm = API.TASK_META[it.task] || API.TASK_META[task];
        const row = el(`<div class="ritem rv-row" style="--i:${i}">
          <div class="rank">${i + 1}</div>
          <div class="mid">
            <div class="obj"><span class="nm">${esc(it["название_объекта"] || "объект " + it.object_id)}</span>
              <span class="badge ${lv.cls}">риск30 ${fmt(r30, 2)}</span>
              ${it.event_flag ? '<span class="badge active pulse">событие</span>' : ""}</div>
            <div class="sen">${ic(tm.icon, "s")} ${esc(it["тип_датчика"] || "—")} · ${esc(it["название_датчика"] || it["ид_канала_данных"])}
              · score ${fmt(it.score, 2)}</div>
            <div class="rbar"><i data-w="${Math.min(100, ph * 100)}" style="background:${riskColor(ph)}"></i></div></div>
          <div class="pr"><b>${fmt(ph, 2)}</b>${esc(hz.cap)}</div>
          <span class="go">${ic("chevron")}</span></div>`);
        row.onclick = () => Cards.forecast.open(it.id, { onDecided: () => render(main, state, true) });
        rl.appendChild(row);
      });
    }
    return card;
  }

  function renderTickets(state, tickets) {
    const { el, ic } = UI;
    const bs = tickets.by_status || {};
    const donut = Charts.donut([
      { label: "предложено", value: bs.suggested || 0, color: "var(--accent-2)" },
      { label: "назначено", value: bs.assigned || 0, color: "var(--info)" },
      { label: "в работе", value: bs.in_progress || 0, color: "var(--warn)" },
      { label: "выполнено", value: bs.done || 0, color: "var(--ok)" },
      { label: "отменено", value: bs.cancelled || 0, color: "var(--text-faint)" },
    ], 140, `<div><div style="font-size:24px;font-weight:800" data-open="${tickets.open || 0}">0</div>
      <div class="faint" style="font-size:10.5px;text-transform:uppercase;letter-spacing:.08em">открыто</div></div>`);
    const card = el(`<div class="card spot"><div class="ct">${ic("wrench", "s")} Превентивные заявки
      <span class="grow"></span><button class="btn xs ghost" id="gt">все заявки →</button></div>
      <div class="row" style="gap:18px;align-items:center;flex-wrap:wrap"></div></div>`);
    const row = card.querySelector(".row");
    row.appendChild(donut);
    const legend = el(`<div style="flex:1;min-width:170px"></div>`);
    [["suggested", "предложено", "var(--accent-2)"], ["assigned", "назначено", "var(--info)"],
     ["in_progress", "в работе", "var(--warn)"], ["done", "выполнено", "var(--ok)"],
     ["cancelled", "отменено", "var(--text-faint)"]].forEach(([k, l, c]) => {
      legend.appendChild(el(`<div class="row" style="justify-content:space-between;font-size:12.5px;padding:3px 0">
        <span class="muted"><i style="display:inline-block;width:9px;height:9px;border-radius:3px;background:${c};margin-right:7px"></i>${l}</span>
        <b class="num">${bs[k] || 0}</b></div>`));
    });
    row.appendChild(legend);
    card.querySelector("#gt").onclick = () => state.navigate("tickets");
    return card;
  }

  /* лента журнала действий (не для техника: он видит только свой район) */
  let activityGen = 0;
  async function loadActivity(main, state) {
    const { el, esc, ic } = UI;
    const role = API.store.user && API.store.user.role;
    if (role === "tech") return;
    const my = ++activityGen;                       // защита от устаревших ответов
    const data = await API.get("/audit?size=9").catch(() => ({ items: [] }));
    if (my !== activityGen || !main.isConnected) return;   // пришёл ответ прошлого вызова
    const card = el(`<div class="card spot" id="activity" data-keep style="margin-top:16px"><div class="ct">${ic("activity", "s")} Лента действий
      <span class="grow"></span><button class="btn xs ghost" id="ga">журнал аудита →</button></div>
      <div class="alog" style="margin:-12px -18px -12px"></div></div>`);
    const list = card.querySelector(".alog");
    const cls = a => a.startsWith("auth.login_failed") || a.startsWith("client") ? "warn"
      : a.startsWith("auth.login") || a.startsWith("auth.logout") ? "good" : "";
    const icn = a => a.includes("decision") ? "target" : a.includes("ticket") ? "wrench"
      : a.includes("login") ? "user" : a.includes("client") ? "alert" : a.includes("reload") ? "refresh" : "info";
    if (!data.items.length) list.appendChild(el(UI.emptyState("пока нет записей", "info")));
    data.items.forEach(a => list.appendChild(el(`<div class="aitem ${cls(a.action)}">
      <span class="ai">${ic(icn(a.action), "s")}</span>
      <div><div class="at"><b>${esc(a.action_ru)}</b>${a.username ? ` · ${esc(a.username)}` : ""}</div>
        <div class="ad">${esc(a.entity_type || "")} ${esc(a.entity_id || "")}
          ${a.detail && a.detail.comment ? `· «${esc(a.detail.comment)}»` : ""}
          ${a.detail && a.detail.decision ? `· ${esc(a.detail.decision)}` : ""}</div></div>
      <div class="aw">${UI.ago(a.created_at)}</div></div>`)));
    card.querySelector("#ga").onclick = () => state.navigate("audit");
    const old = main.querySelector("#activity");
    if (old) old.replaceWith(card); else main.appendChild(card);
    UI.stagger(list, ".aitem");
  }

  function switchTask(t, state) {
    state.setTask(t);
    const chips = document.querySelector(".chips");
    if (chips) {
      chips.querySelectorAll(".chip").forEach(x => x.classList.toggle("on", x.dataset.t === t));
      FX.slider(chips, ".chip-ind", ".chip.on");
    }
    const box = state.box || document.getElementById("pagebox");
    if (box) render(box, state);
  }

  return { render, name: "Пульт", icon: "dashboard" };
})();
