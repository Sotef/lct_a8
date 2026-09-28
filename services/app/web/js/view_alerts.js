/* view_alerts.js — экран «Алерты»: лента недельного риска (MOBILE_PLAN §4.3).
   Данные — GET /alerts (серверный alert_log); если журнал пуст, сервер отдаёт
   «живых» кандидатов по текущему бакету (fallback=true). */
window.Views = window.Views || {};
Views.alerts = (() => {
  const { el, esc, ic, fmt, riskLevel, ago } = UI;
  let filterTask = "";

  const p7 = it => (it.p7d !== undefined && it.p7d !== null) ? it.p7d : it.risk_used;
  const title = it => it.object_name || ("объект " + (it.object_id || "—"));
  const sensor = it => it.sensor_type || it.sensor_name || it.channel_id || "—";

  function openItem(it, state, refresh) {
    if (it.id) Cards.forecast.open(+it.id, { onDecided: refresh });
    else if (it.object_id) Cards.object.open(it.object_id, { state, task: it.task || state.task });
  }

  function renderHead(state, data, items) {
    const role = (API.store.user && API.store.user.role) || "";
    const head = el(`<div class="page-head">
      <div><div class="h1">Алерты риска</div>
        <div class="sub">${items.length} сигналов · порог P(≤7д) ≥ ${fmt(data.min_p7d, 2)} ·
          ${data.fallback ? "живые кандидаты (журнал пуст)" : "журнал алертов"} · ${esc(API.ROLE_RU[role] || role)}</div></div>
      <div class="grow"></div>
      <div class="row wrap">
        <button class="btn ghost sm" id="rf">${ic("refresh", "s")} обновить</button>
        <button class="btn ghost sm m-only inline" id="mn">${ic("menu", "s")} Ещё</button>
      </div></div>`);
    const tools = el(`<div class="toolrow m-search">
      <select id="ft"><option value="">все направления</option>${API.TASKS.map(t =>
        `<option value="${t}" ${filterTask === t ? "selected" : ""}>${esc(API.TASK_META[t].label)}</option>`).join("")}</select>
      <span class="grow"></span><span class="faint">${items.length} записей</span></div>`);
    tools.querySelector("#ft").onchange = e => {
      filterTask = e.target.value;
      render(state.box || document.getElementById("pagebox"), state, true);
    };
    head.querySelector("#rf").onclick = () => {
      API.invalidate("/alerts");
      render(state.box || document.getElementById("pagebox"), state, true);
    };
    head.querySelector("#mn").onclick = () => { if (window.MOBILE && MOBILE.openMore) MOBILE.openMore(); };
    const wrap = el(`<div></div>`);
    wrap.append(head, tools);
    return wrap;
  }

  function itemActions(it, state, refresh) {
    const role = (API.store.user && API.store.user.role) || "";
    const canDecide = ["dispatcher", "central"].includes(role);
    const row = el(`<div class="m-item-actions"></div>`);
    const bObj = el(`<button class="btn ghost sm">${ic("map", "s")} Объект</button>`);
    bObj.onclick = () => Cards.object.open(it.object_id, { state, task: it.task || state.task });
    row.appendChild(bObj);
    if (it.id) {
      const bFc = el(`<button class="btn sm">${ic("target", "s")} Прогноз</button>`);
      bFc.onclick = () => Cards.forecast.open(+it.id, { onDecided: refresh });
      row.appendChild(bFc);
    }
    if (canDecide && it.id) {
      const bConf = el(`<button class="btn dang sm">${ic("alert", "s")} Подтвердить</button>`);
      bConf.onclick = () => decide(it, "confirm", refresh);
      row.appendChild(bConf);
      const bRej = el(`<button class="btn good sm">${ic("x", "s")} Отклонить</button>`);
      bRej.onclick = () => decide(it, "reject", refresh);
      row.appendChild(bRej);
    }
    return row;
  }

  async function decide(it, decision, refresh) {
    try {
      const r = await API.post(`/forecasts/${it.id}/decision`,
        { decision, responsible: API.store.user && API.store.user.username });
      UI.toast(API.queued(r) ? "решение поставлено в очередь (офлайн)" : "решение сохранено",
        "ok", { title: decision === "confirm" ? "подтверждено" : "отклонено" });
      API.invalidate("/alerts"); API.invalidate("/audit");
      if (refresh) refresh();
    } catch (e) { UI.toast(e.message, "err"); }
  }

  function renderMobile(F, items, state, data, refresh) {
    if (!items.length) { F.appendChild(el(UI.emptyState("нет сигналов выше порога", "check"))); return; }
    const list = el(`<div class="m-list"></div>`);
    items.forEach(it => {
      const lv = riskLevel(p7(it));
      const tm = API.TASK_META[it.task] || {};
      const card = el(`<div class="m-item">
        <div class="m-item-top">
          <div style="min-width:0">
            <div class="m-item-title">${esc(title(it))}</div>
            <div class="m-item-sub">${ic(tm.icon || "info", "s")} ${esc(tm.short || it.task || "")} · ${esc(sensor(it))}</div>
          </div>
          <div class="m-item-side">
            <span class="badge ${lv.cls}">${fmt(p7(it), 2)}</span>
            <div class="faint" style="font-size:10.5px;margin-top:4px">${it.sent_at ? ago(it.sent_at) : "сейчас"}</div>
          </div>
        </div>
        <div class="rbar"><i data-w="${Math.min(100, (p7(it) || 0) * 100)}"
          style="background:${UI.riskColor(p7(it) || 0)}"></i></div>
      </div>`);
      card.appendChild(itemActions(it, state, refresh));
      card.onclick = e => { if (!e.target.closest("button")) openItem(it, state, refresh); };
      list.appendChild(card);
    });
    F.appendChild(list);
    FX.bars(F);
  }

  function renderDesktop(F, items, state, data, refresh) {
    const card = el(`<div class="card spot"><div class="ct">${ic("bell", "s")} Сигналы недельного риска
      <span class="grow"></span><span class="faint">${items.length}</span></div>
      <div class="rlist"></div></div>`);
    const list = card.querySelector(".rlist");
    if (!items.length) {
      list.appendChild(el(UI.emptyState("нет сигналов выше порога", "check")));
      F.appendChild(card);
      return;
    }
    items.forEach((it, i) => {
      const lv = riskLevel(p7(it));
      const tm = API.TASK_META[it.task] || {};
      const row = el(`<div class="ritem rv" style="--i:${i}">
        <span class="rank">${i + 1}</span>
        <div class="mid">
          <div class="obj"><span class="nm">${ic(tm.icon || "info", "s")} ${esc(title(it))}</span>
            <span class="badge ${lv.cls}">${fmt(p7(it), 2)}</span></div>
          <div class="sen">${esc(sensor(it))} · ${it.sent_at ? ago(it.sent_at) : "текущий бакет"}</div>
        </div>
        <div class="pr"><b>${fmt(p7(it), 2)}</b>P ≤ 7д</div>
        <span class="go">${ic("chevron")}</span></div>`);
      row.onclick = () => openItem(it, state, refresh);
      list.appendChild(row);
    });
    F.appendChild(card);
    UI.stagger(list, ".ritem");
  }

  async function render(main, state, silent) {
    if (!main) return;
    UI.quiet(main, silent);
    const F = UI.stage();
    const qp = new URLSearchParams({ limit: "120" });
    if (filterTask) qp.set("task", filterTask);
    const data = await API.get("/alerts?" + qp).catch(() => ({ items: [], min_p7d: 0.2 }));
    const items = (data.items || []).slice();
    const refresh = () => render(main, state, true);
    F.appendChild(renderHead(state, data, items));
    if (window.MOBILE && MOBILE.is()) renderMobile(F, items, state, data, refresh);
    else renderDesktop(F, items, state, data, refresh);
    UI.mount(main, F, { merge: !!main.dataset.mounted, quiet: silent });
    main.dataset.mounted = "1";
    UI.live(() => render(main, state, true), 30000);
  }

  return { render, name: "Алерты", icon: "bell" };
})();

