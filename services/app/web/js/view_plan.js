/* view_plan.js — план ТО: «горизонт × тип канала» + заявки по направлениям */
window.Views = window.Views || {};
Views.plan = (() => {
  const { el, esc, ic, fmt } = UI;
  const Q = [
    { key: "текущий квартал", cls: "high", hint: "exp < 7 дней — выезд в этом квартале" },
    { key: "следующий квартал", cls: "mid", hint: "exp 7–21 день" },
    { key: "плановый год", cls: "low", hint: "exp ≥ 21 дня" },
    { key: "плановый", cls: "low", hint: "без выраженного срока" },
  ];
  let quarter = "";

  async function render(main, state, silent) {
    const F = UI.stage();               // сборка offscreen — план не «пропадает» на время запросов
    UI.quiet(main, silent);
    const task = state.task || "wear";
    const data = await API.get(`/maintenance-plan?task=${task}`).catch(() => ({ rows: [] }));
    const tickets = await API.get("/maintenance/summary").catch(() => ({ by_task: {}, by_status: {} }));
    const rows = (data.rows || []).filter(r => !quarter || r.plan === quarter);
    const maxScore = Math.max(1, ...rows.map(r => r.score_сумма || 0));
    const tot = rows.reduce((a, r) => a + (r["каналов"] || 0), 0);
    const risky = rows.filter(r => (r["риск_средний"] || 0) >= .5).reduce((a, r) => a + (r["каналов"] || 0), 0);
    const canRun = ["dispatcher", "central"].includes(API.store.user && API.store.user.role);

    const head = el(`<div class="page-head">
      <div><div class="h1">План превентивного ТО</div>
        <div class="sub">«горизонт × тип канала» · <b>${esc(API.TASK_META[task].label)}</b> ·
          ${fmt(tot, 0)} каналов · <b style="color:var(--bad)">${fmt(risky, 0)}</b> со средним риском ≥ 0.5</div></div>
      <div class="grow"></div>
      <div class="row wrap">${canRun ? `<button class="btn sm" id="auto" title="Открыть превентивные заявки по каналам с риском выше порога автоформирования (по текущему направлению). Дубли не создаются.">${ic("sparkles", "s")} Сформировать заявки</button>` : ""}</div></div>`);

    const qcards = el(`<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(210px,1fr))"></div>`);
    Q.forEach((q, i) => {
      const rs = (data.rows || []).filter(r => r.plan === q.key);
      const n = rs.reduce((a, r) => a + (r["каналов"] || 0), 0);
      const sc = rs.reduce((a, r) => a + (r.score_сумма || 0), 0);
      const c = el(`<div class="kpi rv ${quarter === q.key ? "on" : ""}" style="--i:${i}" data-q="${esc(q.key)}">
        <div class="kglow"></div><div class="t">${ic("calendar")} ${esc(q.key)}</div>
        <div class="v" data-cnt="${n}">0<small>каналов</small></div>
        <div class="rw"><span>Σ score <b>${fmt(sc, 1)}</b></span><span>типов <b>${rs.length}</b></span></div>
        <div class="faint" style="margin-top:8px;font-size:11px">${esc(q.hint)}</div></div>`);
      c.onclick = () => { quarter = quarter === q.key ? "" : q.key; render(main, state, true); };
      qcards.appendChild(c);
    });

    const card = el(`<div class="card flat"><table class="tbl"><thead><tr>
      <th>Горизонт</th><th>Тип канала</th><th>Каналов</th><th>Ср. риск</th>
      <th>Σ score</th><th>Медиана ожидания</th><th></th></tr></thead><tbody></tbody></table></div>`);
    const tb = card.querySelector("tbody");
    if (!rows.length) tb.appendChild(el(`<tr><td colspan="7">${UI.emptyState("нет данных — запустите прогнозный цикл или снимите фильтр", "calendar")}</td></tr>`));
    rows.forEach((r, i) => {
      const q = Q.find(x => x.key === r.plan) || { cls: "" };
      const tr = el(`<tr class="rv-row" style="--i:${Math.min(i, 20)}">
        <td><span class="badge ${q.cls}">${esc(r.plan)}</span></td>
        <td><b>${esc(r["тип_датчика"])}</b></td>
        <td class="num">${r["каналов"]}</td>
        <td class="num" style="color:${UI.riskColor(r["риск_средний"])}">${fmt(r["риск_средний"], 3)}</td>
        <td class="num">${fmt(r.score_сумма, 2)}</td>
        <td class="num">${fmt(r.exp_days_медиана, 1)} дн</td>
        <td><div class="rbar" style="width:140px;margin:0"><i data-w="${(r.score_сумма || 0) / maxScore * 100}"></i></div></td></tr>`);
      tr.onclick = () => state.navigate("forecasts");
      tb.appendChild(tr);
    });

    const tkRow = Object.entries(tickets.by_task || {}).map(([t, st]) => {
      const open = (st.suggested || 0) + (st.assigned || 0) + (st.in_progress || 0);
      const m = API.TASK_META[t] || { icon: "info", short: t };
      return `<div class="stat"><div class="l">${ic(m.icon, "s")} ${esc(m.short)}</div>
        <div class="v">${open}<small style="font-size:12px;color:var(--text-dim)"> открыто</small></div>
        <div class="faint" style="font-size:11px">выполнено ${st.done || 0} · отменено ${st.cancelled || 0}</div></div>`;
    }).join("");
    const tkCard = el(`<div class="card"><div class="ct">${ic("wrench", "s")} Заявки по направлениям
      <span class="grow"></span><button class="btn xs ghost" id="gt">канбан заявок →</button></div>
      <div class="stats">${tkRow || UI.emptyState("заявок пока нет", "wrench")}</div>
      <div class="note">заявки формируются автоматически на каждом сим-тике (risk30 ≥ порога) либо решением диспетчера
        «профилактика» в карточке прогноза; дубли по каналу не создаются</div></div>`);
    tkCard.querySelector("#gt").onclick = () => state.navigate("tickets");

    const autoB = head.querySelector("#auto");
    if (autoB) autoB.onclick = async e => {
      const b = e.currentTarget;
      b.classList.add("loading");
      try {
        const r = await UI.autoGenerate({ task: state.task || task });
        if (r) render(main, state, true);
      } finally { b.classList.remove("loading"); }
    };

    F.appendChild(head); F.appendChild(qcards); F.appendChild(card);
    F.appendChild(el(`<div style="margin-top:16px"></div>`));
    F.appendChild(scheduleCard(state, main));
    F.appendChild(el(`<div style="margin-top:16px"></div>`));
    F.appendChild(tkCard);
    UI.mount(main, F, { merge: !!main.dataset.mounted, quiet: silent });
    main.dataset.mounted = "1";
    main.querySelectorAll("[data-cnt]").forEach(n => UI.countUp(n, +n.dataset.cnt, { d: 0 }));
    FX.bars(main);
    UI.stagger(main, ".rv-row");
    return true;
  }
  /* График обслуживания: все заявки по дате выезда (объекты, датчики, направления).
     host — живой контейнер раздела: асинхронная отрисовка идёт в него, поэтому
     тик/мягкое обновление не оставляет таблицу устаревшей. */
  function scheduleCard(state, host) {
    const { el, esc, ic, fmt, dt } = UI;
    let range = localStorage.getItem("mc_sched_range") || "30";
    let openOnly = localStorage.getItem("mc_sched_open") !== "0";
    const card = el(`<div class="card spot" data-key="sched"><div class="ct">${ic("calendar", "s")} График обслуживания
      <span class="grow"></span>
      <div class="seg" id="schrng">${[["7", "7 дней"], ["30", "30 дней"], ["90", "90 дней"], ["0", "всё"]]
        .map(([v, l]) => `<button data-r="${v}" class="${v === range ? "on" : ""}">${l}</button>`).join("")}</div>
      <label class="chk"><input type="checkbox" id="schopen" ${openOnly ? "checked" : ""}> только открытые</label>
      <button class="btn xs ghost" id="schcsv">${ic("download", "s")} CSV</button></div>
      <div class="chart-body" id="sched-body" data-keep></div></div>`);
    let rows = [];
    const bodyOf = () => (host && host.querySelector("#sched-body")) || card.querySelector("#sched-body");
    const draw = async () => {
      const body = bodyOf();
      if (!body.querySelector("table")) {        // скелетон — только когда таблицы ещё нет
        body.innerHTML = "";
        body.appendChild(UI.skeleton(1, 160));
      }
      const [data, clk] = await Promise.all([
        API.get("/maintenance/tickets?order=due&limit=800").catch(() => ({ items: [] })),
        API.get("/meta/clock").catch(() => null),
      ]);
      const simNow = clk && clk.sim_now ? new Date(clk.sim_now) : new Date();
      const days = +range;
      rows = (data.items || []).filter(t => {
        if (openOnly && !["suggested", "assigned", "in_progress"].includes(t.status)) return false;
        if (!days) return true;
        const p = t.plan_at || t.due_to;
        if (!p) return false;
        const d = new Date(p), diff = (d - simNow) / 86400000;
        return diff >= -1 && diff <= days || (diff < 0 && t.overdue);
      });
      body.innerHTML = "";
      if (!rows.length) {
        body.appendChild(el(UI.emptyState(`в ближайшие ${days || "любые"} дней заявок на обслуживание нет`, "calendar")));
        return;
      }
      /* группировка по дате выезда */
      const byDay = new Map();
      rows.forEach(t => {
        const p = t.plan_at || t.due_to;
        const day = p ? p.slice(0, 10) : "без даты";
        if (!byDay.has(day)) byDay.set(day, []);
        byDay.get(day).push(t);
      });
      const wrap = el(`<div class="stack" style="gap:14px"></div>`);
      [...byDay.keys()].sort().forEach(day => {
        const list = byDay.get(day);
        const closed = list.filter(t => !["suggested", "assigned", "in_progress"].includes(t.status)).length;
        wrap.appendChild(el(`<div>
          <div class="row" style="margin-bottom:6px"><b class="num">${esc(day === "без даты" ? day : dt(day + "T09:00:00"))}</b>
            <span class="badge ${day === "без даты" ? "" : "info"}">${list.length} заявок</span>
            ${closed ? `<span class="faint" style="font-size:11.5px">${closed} уже закрыто/отменено</span>` : ""}</div>
          <table class="tbl"><thead><tr><th>Объект</th><th>Датчик / канал</th><th>Направление</th>
            <th>Статус</th><th>Приоритет</th><th>Исполнитель</th><th>№</th></tr></thead><tbody>
            ${list.map(t => `<tr class="rrow" data-id="${t.id}">
              <td><b>${esc(t.object_name || t.object_id)}</b>
                <div class="faint" style="font-size:11px">${esc(t.district || "")}</div></td>
              <td class="muted">${esc(t.sensor_name || t.channel_id)}</td>
              <td>${esc(t.task_desc)}</td>
              <td><span class="badge ${t.status === "done" ? "low" : t.status === "cancelled" ? "" :
                t.status === "in_progress" ? "mid" : "info"}">${esc(t.status_ru)}</span>
                ${t.overdue ? '<span class="badge high">просрочено</span>' : ""}</td>
              <td class="muted">${esc(t.priority)}</td>
              <td class="muted">${esc(t.assignee || "—")}</td>
              <td class="num faint">#${t.id}</td></tr>`).join("")}
          </tbody></table></div>`));
      });
      body.appendChild(wrap);
      body.querySelectorAll("tr[data-id]").forEach(tr => tr.onclick = () =>
        Views.tickets.openCard(+tr.dataset.id, state));
      body.appendChild(el(`<div class="faint" style="font-size:11.5px;margin-top:10px">
        всего в графике: ${rows.length} · отсчёт от сим-времени ${dt(simNow.toISOString())}
        (даты выезда назначает диспетчер в карточке заявки)</div>`));
    };
    FX.seg(card.querySelector("#schrng"), b => {
      range = b.dataset.r; localStorage.setItem("mc_sched_range", range); draw();
    });
    card.querySelector("#schopen").onchange = e => {
      openOnly = e.target.checked; localStorage.setItem("mc_sched_open", openOnly ? "1" : "0"); draw();
    };
    card.querySelector("#schcsv").onclick = () => Views.forecasts.exportCsv(
      rows.map(t => ({
        id: t.id, object_id: t.object_id, название_объекта: t.object_name, район: t.district,
        название_датчика: t.sensor_name, тип_датчика: t.task_desc, p24: t.p24, p72: "",
        risk30: t.risk, risk30_cal: "", exp_days: t.exp_days, score: t.score, plan: t.status_ru,
        event_flag: "", bucket_ts: (t.plan_at || t.due_to || "").slice(0, 10),
      })), "schedule");
    draw();
    return card;
  }

  return { render, name: "План ТО", icon: "calendar" };
})();
