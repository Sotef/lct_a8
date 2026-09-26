/* view_forecasts.js — журнал прогнозов + карточка риска + карточка объекта */
window.Views = window.Views || {};
Views.forecasts = (() => {
  const { el, esc, fmt, dt, riskLevel, riskColor } = UI;
  const TASK_META = API.TASK_META;
  let task = "wear", page = 1, objFilter = "", activeOnly = false, jhz = "30d";
  const JHZ = { "24h": "24ч", "72h": "72ч", "30d": "30д" };

  /* ---------- карточка прогноза (drawer) ---------- */
  function closeDrawer() {
    document.querySelectorAll(".drawer, .drawer-veil").forEach(d => d.remove());
  }

  async function openCard(id, state, canDecide) {
    closeDrawer();
    canDecide = canDecide !== undefined ? canDecide
      : ["dispatcher", "central"].includes(API.store.user && API.store.user.role);
    document.body.appendChild(el(`<div class="drawer-veil" onclick="window.__dx()"></div>`));
    const d = el(`<div class="drawer"><div class="spin"></div></div>`);
    document.body.appendChild(d);
    window.__dx = closeDrawer;

    let c;
    try { c = await API.get(`/forecasts/${id}`); }
    catch (e) { d.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }

    const lv = riskLevel(c.probabilities);
    const ru = c.probabilities.risk_used !== undefined ? c.probabilities.risk_used : c.probabilities.risk30;
    const hist = (c.history || []).map(h => `
      <div class="hi"><b>${esc(h.decision)}</b> · ${esc(h.responsible || h.username || "—")}
      · ${dt(h.created_at)}${h.comment ? `<div class="muted">${esc(h.comment)}</div>` : ""}</div>`).join("");

    const lastEv = (c.last_events || []).map(e => `
      <tr><td class="num">${dt(e.bucket_ts)}</td>
      <td class="num">${fmt(e.risk30, 2)}</td><td class="num">${fmt(e.p24, 3)}</td></tr>`).join("");

    d.innerHTML = `
      <div class="dx"><div class="t">${esc(c.task_desc)} · канал ${esc(c.channel_id)}</div>
        <button onclick="window.__dx()">✕</button></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <span class="badge ${lv.cls}">риск: ${lv.text}</span>
        ${esc(c.sensor_type || "")} <span class="muted">·</span> ${esc(c.channel_name || "—")}
        ${c.tag ? `<span class="badge">ПК ${esc(c.tag)}</span>` : ""}
      </div>
      <div class="muted" style="margin-top:8px">
        📍 ${esc(c.object && c.object.name || c.object_id)} (${esc(c.object && c.object.type || "")}, район ${esc(c.object && c.object.district || "—")})
        ${c.system_type ? ` · система: ${esc(c.system_type)}` : ""}</div>

      <div class="dsec"><h4>Вероятности</h4><div class="pgrid">
        <div class="pbox"><div class="l">P(событие ≤ 24 ч)</div><div class="v">${fmt(c.probabilities.p24, 3)}</div></div>
        <div class="pbox"><div class="l">P(событие ≤ 72 ч)</div><div class="v">${fmt(c.probabilities.p72, 3)}</div></div>
        <div class="pbox"><div class="l">P(событие ≤ 30 д)</div><div class="v" style="color:${riskColor(ru)}">${fmt(ru, 3)}</div></div>
        <div class="pbox"><div class="l">ожидание, дней</div><div class="v">${fmt(c.rbam && c.rbam.exp_days !== undefined ? c.rbam.exp_days : c.exp_days, 1)}</div></div>
      </div></div>`;

    const labels = (c.horizon && c.horizon.labels) || ["6ч", "12ч", "24ч", "48ч", "3д", "7д", "14д", "30д"];
    d.appendChild(Charts.survival(c.horizon && c.horizon.surv_points, labels));
    d.appendChild(Charts.boxplotTime(c.horizon && c.horizon.surv_points, labels));

    const facWrap = el(`<div class="dsec"></div>`);
    facWrap.appendChild(Charts.factors(c.factors));
    d.appendChild(facWrap);

    d.appendChild(el(`<div class="dsec"><h4>Рекомендация</h4>
      <div class="card" style="padding:12px 14px">${esc(c.recommended_action || "—")}</div>
      ${c.preventive_order ? `<div class="note">${esc(c.preventive_order)}</div>` : ""}
      ${c.rbam && c.rbam.plan ? `<div class="note">план ТО: ${esc(c.rbam.plan)} · severity ${fmt(c.rbam.severity, 2)} · scale ${fmt(c.rbam.scale, 2)}</div>` : ""}</div>`));

    if (lastEv) d.appendChild(el(`<div class="dsec"><h4>Последние события канала</h4>
      <table class="tbl"><thead><tr><th>бакет</th><th>risk30</th><th>p24</th></tr></thead>
      <tbody>${lastEv}</tbody></table></div>`));

    if (canDecide) {
      const dc = el(`<div class="dsec"><h4>Решение диспетчера</h4>
        <input id="dc" placeholder="комментарий: например, выявлено задымление, направлена бригада"
          style="width:100%;padding:8px 12px;border-radius:var(--radius-s);border:1px solid var(--border);
          background:var(--bg-2);outline:none">
        <div class="decbtns">
          <button class="btn sm good" data-v="confirm">✓ Подтвердить</button>
          <button class="btn sm dang" data-v="reject">✕ Отклонить</button>
          <button class="btn sm ghost" data-v="preventive">🛠 Профилактика</button>
        </div>
        <div class="err" id="de"></div></div>`);
      dc.querySelectorAll(".decbtns button").forEach(b => {
        b.onclick = async () => {
          const err = dc.querySelector("#de");
          err.textContent = "";
          try {
            await API.post(`/forecasts/${id}/decision`, {
              decision: b.dataset.v,
              responsible: API.store.user && API.store.user.username,
              comment: dc.querySelector("#dc").value || null,
            });
            UI.toast("решение сохранено (audit_log) ✓");
            closeDrawer(); openCard(id, state, canDecide);
          } catch (e) { err.textContent = e.message; }
        };
      });
      d.appendChild(dc);
    }

    d.appendChild(el(`<div class="dsec"><h4>История решений</h4>
      <div class="hist">${hist || '<span class="muted">решений пока нет</span>'}</div></div>`));
    d.appendChild(el(`<div class="note">модель ${esc(c.model_version || "—")} · бакет ${dt(c.bucket_ts)} ·
      финальное решение принимает диспетчер, модель — только прогноз</div>`));
  }

  /* ---------- журнал прогнозов ---------- */
  async function render(main, state, silent) {
    if (!silent) main.innerHTML = `<div class="spin"></div>`;
    task = state.task || "wear";
    const qp = new URLSearchParams({ task, page, size: 25, horizon: jhz });
    if (objFilter) qp.set("object_id", objFilter);
    let data;
    try { data = await API.get(`/forecasts?${qp}`); }
    catch (e) { main.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
    let items = data.items;
    if (activeOnly) items = items.filter(i => i.event_flag);

    const head = el(`<div class="topbar">
      <div><div class="h1">Журнал прогнозов</div>
      <div class="sub">${data.total} прогнозов · нажмите строку — карточка, решение, факторы</div></div>
      <div class="grow"></div>
      <label class="sub" style="display:flex;gap:6px;align-items:center">
        <input type="checkbox" id="ao" ${activeOnly ? "checked" : ""}> только активные события</label></div>`);

    const tools = el(`<div class="toolrow">
      <input type="search" id="of" placeholder="object_id (например 5122)" value="${esc(objFilter)}">
      <select id="hz">${Object.keys(JHZ).map(h =>
        `<option value="${h}" ${h === jhz ? "selected" : ""}>сортировка: ${JHZ[h]}</option>`).join("")}</select>
      <select id="pg"></select>
      <button class="btn ghost sm" id="clr">сбросить фильтры</button></div>`);
    const pgSel = tools.querySelector("#pg");
    const pages = Math.max(1, Math.ceil(data.total / 25));
    for (let i = 1; i <= Math.min(pages, 200); i++) {
      pgSel.appendChild(el(`<option value="${i}" ${i === page ? "selected" : ""}>стр. ${i} / ${pages}</option>`));
    }
    pgSel.onchange = () => { page = +pgSel.value; render(main, state); };
    tools.querySelector("#hz").onchange = (e) => { jhz = e.target.value; render(main, state); };
    tools.querySelector("#clr").onclick = () => { objFilter = ""; page = 1; render(main, state); };
    tools.querySelector("#of").onchange = (e) => { objFilter = e.target.value.trim(); page = 1; render(main, state); };
    head.querySelector("#ao").onchange = (e) => { activeOnly = e.target.checked; render(main, state); };

    const card = el(`<div class="card" style="padding:6px 0">
      <table class="tbl"><thead><tr>
        <th>Объект / датчик</th><th>Задача</th><th>risk 30д</th><th>p72</th><th>p24</th>
        <th>exp, дн</th><th>score</th><th>план</th><th>бакет</th></tr></thead>
      <tbody></tbody></table></div>`);
    const tbody = card.querySelector("tbody");
    if (!items.length) tbody.appendChild(el(`<tr><td colspan="9" class="empty">нет прогнозов по фильтру</td></tr>`));
    items.forEach(it => {
      const lv = riskLevel(it);
      const tr = el(`<tr class="rrow">
        <td><b>${esc(it["название_объекта"] || it.object_id)}</b>
          <div class="muted" style="font-size:11.5px">${esc(it["название_датчика"] || it["ид_канала_данных"])}
          ${it.event_flag ? ' <span class="badge active">событие</span>' : ""}
          <span class="badge ${lv.cls}">${lv.text}</span></div></td>
        <td class="muted">${esc(TASK_META[it.task] ? TASK_META[it.task].short : it.task)}</td>
        <td class="num" style="color:${riskColor(it.risk_used !== undefined ? it.risk_used : it.risk30)}">${fmt(it.risk_used !== undefined ? it.risk_used : it.risk30, 2)}</td>
        <td class="num">${fmt(it.p72, 3)}</td>
        <td class="num">${fmt(it.p24, 3)}</td>
        <td class="num">${fmt(it.exp_days, 1)}</td>
        <td class="num">${fmt(it.score, 2)}</td>
        <td class="muted">${esc(it.plan || "—")}</td>
        <td class="muted">${dt(it.bucket_ts)}</td></tr>`);
      tr.onclick = () => openCard(it.id, state);
      tbody.appendChild(tr);
    });

    main.innerHTML = "";
    main.appendChild(head); main.appendChild(tools); main.appendChild(card);

    /* live: тихий рефреш каждые 30с */
    UI.live(() => render(main, state, true), 30000);
  }

  /* ---------- карточка объекта (drawer): датчики + свежие прогнозы ---------- */
  async function openObject(objectId, state) {
    closeDrawer();
    document.body.appendChild(el(`<div class="drawer-veil" onclick="window.__dx()"></div>`));
    const d = el(`<div class="drawer"><div class="spin"></div></div>`);
    document.body.appendChild(d);
    window.__dx = closeDrawer;
    state = state || { task: "wear" };

    let obj, risks;
    try {
      [obj, risks] = await Promise.all([
        API.get(`/objects/${objectId}`),
        API.get(`/objects/${objectId}/risks`),
      ]);
    } catch (e) { d.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }

    const o = obj.object;
    d.innerHTML = `
      <div class="dx"><div class="t">${esc(o.name || o.object_id)}</div>
        <button onclick="window.__dx()">✕</button></div>
      <div class="muted">${esc(o.type || "")} · id ${esc(o.object_id)} · район ${esc(o.district || "—")}
        ${o.parent_id ? ` · родитель ${esc(o.parent_id)}` : ""}</div>
      <div class="dsec"><h4>Риски по задачам (L2)</h4><div class="pgrid">
        ${["fire", "access", "sensor", "wear"].map(t => {
          const r = (risks.risks || []).find(x => x.task === t);
          return `<div class="pbox"><div class="l">${esc(TASK_META[t].short)}</div>
            <div class="v" style="color:${riskColor(r && r.risk30_max || 0)}">${r ? fmt(r.risk30_max, 2) : "—"}</div>
            <div class="muted" style="font-size:11px">${r ? r.channel_count + " кан." : "нет данных"}</div></div>`;
        }).join("")}</div></div>
      <div class="dsec"><h4>Датчики и каналы объекта (${(obj.channels || []).length})</h4>
      <input type="search" id="chq" placeholder="фильтр по типу/названию/тегу…" style="width:100%;
        padding:8px 12px;border-radius:var(--radius-s);border:1px solid var(--border);
        background:var(--panel);outline:none;margin-bottom:10px">
      <table class="tbl"><thead><tr><th>Датчик</th><th>Тип</th><th>Система</th><th>Тег (ПК)</th></tr></thead>
      <tbody id="chb"></tbody></table></div>`;

    const tbody = d.querySelector("#chb");
    function drawCh(q) {
      const term = (q || "").toLowerCase();
      const rows = (obj.channels || []).filter(ch => !term ||
        [ch.sensor_name, ch.sensor_type, ch.system_type, ch.tag, ch.channel_id]
          .some(v => (v || "").toLowerCase().includes(term)));
      tbody.innerHTML = "";
      rows.slice(0, 300).forEach(ch => {
        tbody.appendChild(el(`<tr><td><b>${esc(ch.sensor_name || ch.channel_id)}</b></td>
          <td class="muted">${esc(ch.sensor_type || "—")}</td>
          <td class="muted">${esc(ch.system_type || "—")}</td>
          <td class="num muted">${esc(ch.tag || "—")}</td></tr>`));
      });
      if (!rows.length) tbody.appendChild(el(`<tr><td colspan="4" class="empty">не найдено</td></tr>`));
    }
    d.querySelector("#chq").oninput = (e) => drawCh(e.target.value);
    drawCh("");

    d.appendChild(el(`<div class="dsec"><h4>Прогнозы по объекту</h4>
      <button class="btn sm" id="go">Открыть в журнале прогнозов →</button></div>`));
    d.querySelector("#go").onclick = () => {
      closeDrawer();
      objFilter = objectId;
      page = 1;
      if (state.navigate) state.navigate("forecasts");
    };
  }

  return { render, openCard, openObject, closeDrawer, name: "Журнал прогнозов", icon: "▤" };
})();
