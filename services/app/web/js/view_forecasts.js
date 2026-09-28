/* view_forecasts.js — журнал прогнозов: фильтры, сортировка по горизонту, пагинация, CSV */
window.Views = window.Views || {};
Views.forecasts = (() => {
  const { el, esc, ic, fmt, dt, riskLevel, riskColor } = UI;
  let page = 1, size = 25, hazard = "30d", activeOnly = false, plan = "", sortCol = null, sortDir = -1;
  let lastTotal = 0, lastItems = [];
  const HZ = { "24h": "24 ч", "72h": "72 ч", "30d": "30 дн" };
  const PLAN = ["текущий квартал", "следующий квартал", "плановый год", "плановый"];
  const grab = (p, fb) => API.get(p).catch(() => fb);
  const arrow = c => sortCol === c ? `<span class="arr">${sortDir < 0 ? "↓" : "↑"}</span>` : "";

  async function render(main, state, silent) {
    const task = state.task || "wear";
    const F = UI.stage();               // offscreen-сборка: раздел не «пропадает» на время запросов
    UI.quiet(main, silent);
    const qp = new URLSearchParams({ task, page, size, horizon: hazard });
    if (state.objFilter) qp.set("object_id", state.objFilter);
    if (plan) qp.set("status", plan);
    const data = await grab(`/forecasts?${qp}`, { items: [], total: 0 });
    let items = data.items || [];
    if (activeOnly) items = items.filter(i => i.event_flag);
    lastTotal = data.total || 0;
    lastItems = items;
    const pages = Math.max(1, Math.ceil(lastTotal / size));

    const head = el(`<div class="page-head">
      <div><div class="h1">Журнал прогнозов</div>
        <div class="sub">${fmt(data.total, 0)} прогнозов · <b>${esc(API.TASK_META[task].label)}</b>
          ${state.objFilter ? ` · фильтр по объекту <b>${esc(state.objFilter)}</b>` : ""} · клик по строке — карточка и решение</div></div>
      <div class="grow"></div>
      <div class="row wrap">
        <button class="btn ghost sm" id="csv">${ic("download", "s")} CSV</button>
        <button class="btn ghost sm" id="clr">${ic("x", "s")} Сбросить фильтры</button></div></div>`);

    const tools = el(`<div class="toolrow">
      <input type="search" id="of" placeholder="object_id (например 5122)" value="${esc(state.objFilter || "")}">
      <select id="hz">${Object.keys(HZ).map(h => `<option value="${h}" ${h === hazard ? "selected" : ""}>сортировка: ${HZ[h]}</option>`).join("")}</select>
      <select id="pl"><option value="">любой план</option>${PLAN.map(p =>
        `<option value="${esc(p)}" ${p === plan ? "selected" : ""}>${esc(p)}</option>`).join("")}</select>
      <label class="chk"><input type="checkbox" id="ao" ${activeOnly ? "checked" : ""}> только активные события</label>
      <span class="grow"></span>
      <button class="btn ghost sm" id="prev" ${page <= 1 ? "disabled" : ""}>${ic("left", "s")}</button>
      <span class="faint num" style="min-width:104px;text-align:center">стр. ${page} / ${pages}</span>
      <button class="btn ghost sm" id="next" ${page * size >= lastTotal ? "disabled" : ""}>${ic("chevron", "s")}</button></div>`);
    head.querySelector("#clr").onclick = () => {
      state.setObjFilter(""); page = 1; plan = ""; activeOnly = false; sortCol = null; render(main, state, true); };
    head.querySelector("#csv").onclick = () => exportCsv(lastItems, state.task || task);
    tools.querySelector("#of").onchange = e => { state.setObjFilter(e.target.value.trim()); page = 1; render(main, state, true); };
    tools.querySelector("#hz").onchange = e => { hazard = e.target.value; page = 1; render(main, state, true); };
    tools.querySelector("#pl").onchange = e => { plan = e.target.value; page = 1; render(main, state, true); };
    tools.querySelector("#ao").onchange = e => { activeOnly = e.target.checked; render(main, state, true); };
    tools.querySelector("#prev").onclick = () => { page = Math.max(1, page - 1); render(main, state, true); };
    tools.querySelector("#next").onclick = () => { page++; render(main, state, true); };

    const card = el(`<div class="card flat tscroll"><table class="tbl"><thead><tr>
      <th class="sortable" data-c="obj">Объект / датчик${arrow("obj")}</th><th>Направление</th>
      <th class="sortable" data-c="risk30">риск 30 дн${arrow("risk30")}</th>
      <th class="sortable" data-c="p72">p72${arrow("p72")}</th>
      <th class="sortable" data-c="p24">p24${arrow("p24")}</th>
      <th class="sortable" data-c="exp_days">ожид., дн${arrow("exp_days")}</th>
      <th class="sortable" data-c="score">score${arrow("score")}</th><th>план</th><th>бакет</th></tr></thead>
      <tbody></tbody></table></div>`);
    const tb = card.querySelector("tbody");
    const draw = () => {
      const rr = !sortCol ? items : [...items].sort((a, b) => {
        const g = o => sortCol === "obj" ? (o["название_объекта"] || "") : (o[sortCol] || 0);
        const x = g(a), y = g(b);
        return (typeof x === "string" ? x.localeCompare(y, "ru") : x - y) * sortDir;
      });
      tb.innerHTML = "";
      if (!rr.length) tb.appendChild(el(`<tr><td colspan="9">
        ${UI.emptyState("нет прогнозов по фильтру — измените условия или подождите тик сим-времени", "search")}</td></tr>`));
      rr.forEach((it, i) => {
        const lv = riskLevel(it), ru = UI.riskOf(it), tm = API.TASK_META[it.task] || {};
        const tr = el(`<tr class="rrow rv-row" data-id="${it.id}" style="--i:${Math.min(i, 18)}">
          <td><b>${esc(it["название_объекта"] || it.object_id)}</b>
            <div class="faint" style="font-size:11.5px">${esc(it["название_датчика"] || it["ид_канала_данных"])}
              ${it.event_flag ? ' <span class="badge active pulse">событие</span>' : ""}
              <span class="badge ${lv.cls}">${lv.text}</span></div></td>
          <td class="muted">${ic(tm.icon || "info", "s")} ${esc(tm.short || it.task)}</td>
          <td class="num" style="color:${riskColor(ru)}"><b>${fmt(ru, 2)}</b>
            <div class="rbar" style="width:56px;margin-top:3px"><i data-w="${Math.min(100, ru * 100)}" style="background:${riskColor(ru)}"></i></div></td>
          <td class="num">${fmt(it.p72, 3)}</td><td class="num">${fmt(it.p24, 3)}</td>
          <td class="num">${fmt(it.exp_days, 1)}</td><td class="num">${fmt(it.score, 2)}</td>
          <td class="muted" style="font-size:12px">${esc(it.plan || "—")}</td>
          <td class="faint num" style="font-size:11.5px">${dt(it.bucket_ts)}</td></tr>`);
        tr.onclick = () => Cards.forecast.open(+tr.dataset.id,
          { onDecided: () => render(main, state, true) });
        tb.appendChild(tr);
      });
      FX.bars(tb);
    };
    card.querySelectorAll("th.sortable").forEach(th => th.onclick = () => {
      const c = th.dataset.c;
      if (sortCol === c) sortDir *= -1; else { sortCol = c; sortDir = -1; }
      render(main, state, true);        // перерисовка из состояния: DOM остаётся на месте
    });
    draw();
    F.appendChild(head); F.appendChild(tools); F.appendChild(card);
    UI.mount(main, F, { merge: !!main.dataset.mounted, quiet: silent });
    main.dataset.mounted = "1";
    UI.stagger(main, ".rv-row");
    FX.bars(main);
    UI.live(() => render(main, state, true), 40000);
    return true;
  }

  function exportCsv(items, task) {
    if (!items || !items.length) { UI.toast("нечего экспортировать", "warn"); return; }
    const cols = ["id", "object_id", "название_объекта", "район", "название_датчика", "тип_датчика",
      "p24", "p72", "risk30", "risk30_cal", "exp_days", "score", "plan", "event_flag", "bucket_ts"];
    const csv = [cols.join(";")].concat(items.map(it => cols.map(c => {
      const v = it[c];
      return v === null || v === undefined ? "" : String(v).replace(/;/g, ",").replace(/\s+/g, " ");
    }).join(";"))).join("\r\n");
    const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `forecasts_${task}_p${page}_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
    UI.toast(`выгружено строк: ${items.length}`, "ok", { title: "CSV сформирован" });
  }
  return { render, name: "Журнал прогнозов", icon: "list", exportCsv };
})();
