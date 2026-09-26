/* view_dashboard.js — дашборд: KPI по задачам, тренд, топ-риски */
window.Views = window.Views || {};
Views.dashboard = (() => {
  const { el, esc, fmt, dt, riskColor } = UI;
  const TASK_META = API.TASK_META;
  let task = "wear", horizon = "72h", topMode = "objects";
  const HZ = {
    "24h": { btn: "24ч", field: "p24", cap: "P ≤24ч" },
    "72h": { btn: "72ч", field: "p72", cap: "P ≤72ч" },
    "30d": { btn: "30д", field: "risk_used", cap: "P ≤30д" },
  };

  async function render(main, state, silent) {
    if (!silent) main.innerHTML = `<div class="spin"></div>`;
    task = state.task || "wear";
    const [summary, hist, top, topObj] = await Promise.all([
      API.get("/meta/summary"),
      API.get(`/meta/risk-history?task=${task}&n=120`).catch(() => ({ rows: [] })),
      API.get(`/top-risks?task=${task}&k=12&horizon=${horizon}`)
        .catch(() => ({ items: [] })),
      API.get(`/top-objects?task=${task}&k=10&horizon=${horizon}`)
        .catch(() => ({ items: [] })),
    ]);
    const hz = HZ[horizon];

    /* --- KPI --- */
    const kpis = el(`<div class="kpis"></div>`);
    API.TASKS.forEach(t => {
      const s = summary[t] || {}, m = TASK_META[t];
      const k = el(`<div class="kpi ${t === task ? "danger" : ""}" data-task="${t}">
        <div class="t">${m.icon} ${esc(m.label)}</div>
        <div class="v">${s.n !== undefined ? s.n : 0}</div>
        <div class="row"><span>критичных <b>${s.critical !== undefined ? s.critical : 0}</b></span>
        <span>событий <b>${s.active !== undefined ? s.active : 0}</b></span>
        <span>ср. риск <b>${fmt(s.avg_risk, 2)}</b></span></div>
        <div class="sub" style="margin-top:6px">бакет: ${dt(s.bucket)}</div>
      </div>`);
      k.onclick = () => { state.setTask(t); task = t; render(main, state); };
      kpis.appendChild(k);
    });

    /* --- верхняя строка --- */
    const head = el(`<div class="topbar">
      <div><div class="h1">Дашборд рисков</div>
      <div class="sub">горизонт прогноза 30 дней · данные «поступают» в режиме реплея с 01.01.2026
      (сим-время в шапке) · обновляется автоматически</div></div>
      <div class="grow"></div></div>`);

    /* --- тренд --- */
    const trendCard = Charts.trend(hist.rows);

    /* --- топ: по объектам (Σ вес×вероятность) или по каналам --- */
    const topCard = el(`<div class="card"><div class="ct">Топ-риски · ${esc(TASK_META[task].label)}
      <span class="seg" style="margin-left:10px;display:inline-flex">
        ${Object.keys(HZ).map(h =>
          `<button data-h="${h}" class="${h === horizon ? "on" : ""}" style="padding:3px 10px">${HZ[h].btn}</button>`).join("")}
      </span>
      <span class="seg" style="margin-left:6px;display:inline-flex">
        <button data-m="objects" class="${topMode === "objects" ? "on" : ""}" style="padding:3px 10px">по объектам</button>
        <button data-m="channels" class="${topMode === "channels" ? "on" : ""}" style="padding:3px 10px">по датчикам</button>
      </span></div>
      <div class="rlist"></div></div>`);
    topCard.querySelectorAll(".seg button").forEach(b => {
      b.onclick = () => {
        if (b.dataset.h) horizon = b.dataset.h;
        if (b.dataset.m) topMode = b.dataset.m;
        render(main, state);
      };
    });
    const rl = topCard.querySelector(".rlist");

    if (topMode === "objects") {
      /* объекты: вклад = Σ (вес датчика × P(событие ≤ горизонт)) */
      rl.appendChild(el(`<div class="note" style="margin:2px 0 6px">вклад объекта =
        Σ (вес датчика × вероятность события за ${esc(hz.btn)}); клик — топ-канал объекта</div>`));
      if (!topObj.items.length) {
        rl.appendChild(el(`<div class="empty">нет прогнозов по задаче на текущем сим-бакете —
          ждите ближайший тик сим-времени</div>`));
      }
      topObj.items.forEach(o => {
        const lv = o["риск_макс"] >= 0.5 ? "high" : o["риск_макс"] >= 0.2 ? "mid" : "low";
        const row = el(`<div class="ritem">
          <div class="sc" style="color:${riskColor(o["риск_макс"])}">${fmt(o["вклад"], 2)}</div>
          <div class="mid">
            <div class="obj">${esc(o["название_объекта"] || "объект " + o.object_id)}
              <span class="badge ${lv}" style="margin-left:8px">макс P ${fmt(o["риск_макс"], 2)}</span></div>
            <div class="sen">${esc(o["тип_объекта"] || "")} · ${o["каналов"]} кан. · топ: ${esc((o.top_channels || [])
              .map(ch => ch.channel_id + " (" + fmt(ch["вклад"], 2) + ")").join(", "))}</div>
            <div class="rbar"><i style="width:${Math.min(100, o["риск_макс"] * 100)}%;background:${riskColor(o["риск_макс"])}"></i></div>
          </div>
          <div class="pr"><b>${fmt(o["вклад"], 2)}</b>Σ вклад</div>
        </div>`);
        if (o.top_channels && o.top_channels.length)
          row.onclick = () => Views.forecasts.openCard(o.top_channels[0].prediction_id, state);
        rl.appendChild(row);
      });
    } else {
      /* каналы: вероятность выбранного горизонта — главное число */
      if (!top.items.length) {
        rl.appendChild(el(`<div class="empty">нет прогнозов по задаче на текущем сим-бакете —
          ждите ближайший тик сим-времени</div>`));
      }
      top.items.forEach(it => {
        const ph = hz.field === "risk_used"
          ? (it.risk_used !== undefined && it.risk_used !== null ? it.risk_used : it.risk30)
          : (it[hz.field] !== undefined && it[hz.field] !== null ? it[hz.field] : 0);
        const r30 = it.risk_used !== undefined ? it.risk_used : it.risk30;
        const lv = r30 >= 0.5 ? "high" : r30 >= 0.2 ? "mid" : "low";
        const row = el(`<div class="ritem">
          <div class="sc" style="color:${riskColor(ph)}">${fmt(ph, 2)}</div>
          <div class="mid">
            <div class="obj">${esc(it["название_объекта"] || "объект " + it.object_id)}
              <span class="badge ${lv}" style="margin-left:8px" title="уровень по риску 30 дней">риск30: ${lv === "high" ? "высокий" : lv === "mid" ? "средний" : "низкий"}</span>
              ${it.event_flag ? '<span class="badge active">событие</span>' : ""}</div>
            <div class="sen">${esc(it["тип_датчика"] || "")} · ${esc(it["название_датчика"] || it["ид_канала_данных"])} · score ${fmt(it.score || 0, 2)}</div>
            <div class="rbar"><i style="width:${Math.min(100, ph * 100)}%;background:${riskColor(ph)}"></i></div>
          </div>
          <div class="pr"><b>${fmt(ph, 2)}</b>${esc(hz.cap)} · риск30 ${fmt(r30, 2)}</div>
        </div>`);
        row.onclick = () => Views.forecasts.openCard(it.id, state);
        rl.appendChild(row);
      });
    }

    main.innerHTML = "";
    main.appendChild(head);
    main.appendChild(kpis);
    const g = el(`<div class="grid2 fade-in" style="margin-top:14px"></div>`);
    g.appendChild(trendCard);
    g.appendChild(topCard);
    main.appendChild(g);

    /* live: тихий рефреш каждые 20с (данные текут из реплея) */
    UI.live(() => render(main, state, true), 20000);
  }

  return { render, name: "Дашборд", icon: "◈" };
})();
