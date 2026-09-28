/* view_audit.js — журнал действий пользователей: фильтры, статистика, детали, экспорт */
window.Views = window.Views || {};
Views.audit = (() => {
  const { el, esc, ic, fmt, dtFull, ago } = UI;
  let page = 1, size = 40, action = "", q = "", hours = 24, total = 0, opened = null;
  const CLS = a => a.includes("login_failed") || a.startsWith("client") ? "warn" : a.startsWith("auth.") ? "good" : "";
  const ICN = a => a.includes("decision") ? "target" : a.includes("ticket") ? "wrench"
    : a.includes("login") ? "user" : a.includes("client") ? "alert"
    : a.includes("reload") ? "refresh" : a.includes("data") ? "server" : a.includes("admin") ? "shield" : "info";

  async function render(main, state) {
    const role = API.store.user && API.store.user.role;
    if (role === "tech") { main.innerHTML = UI.emptyState("раздел доступен диспетчеру и центральному диспетчеру", "lock"); return; }
    const qp = new URLSearchParams({ page, size });
    if (action) qp.set("action", action);
    if (q) qp.set("q", q);
    if (hours) qp.set("hours", hours);
    const [data, actions, stats] = await Promise.all([
      API.get(`/audit?${qp}`).catch(() => ({ items: [], total: 0 })),
      API.get("/audit/actions").catch(() => ({ actions: [] })),
      role === "central" ? API.get("/audit/stats?hours=24").catch(() => null) : Promise.resolve(null),
    ]);
    total = data.total || 0;
    const pages = Math.max(1, Math.ceil(total / size));

    const head = el(`<div class="page-head">
      <div><div class="h1">Журнал действий</div>
        <div class="sub">${fmt(total, 0)} записей ${role === "central" ? "по всем пользователям" : "— только ваши действия"} ·
          решения, заявки, входы и действия администратора фиксируются автоматически</div></div>
      <div class="grow"></div>
      <button class="btn ghost sm" id="csv">${ic("download", "s")} CSV</button></div>`);
    const tools = el(`<div class="toolrow">
      <input type="search" id="q" placeholder="поиск: пользователь, действие, объект…" value="${esc(q)}">
      <select id="ac"><option value="">все действия</option>
        <option value="auth.*" ${action === "auth.*" ? "selected" : ""}>только входы</option>
        <option value="forecast.*" ${action === "forecast.*" ? "selected" : ""}>прогнозы и решения</option>
        <option value="ticket.*" ${action === "ticket.*" ? "selected" : ""}>только заявки</option>
        <option value="admin.*" ${action === "admin.*" ? "selected" : ""}>администрирование</option>
        <option value="client.error" ${action === "client.error" ? "selected" : ""}>ошибки веб-интерфейса</option>
        ${(actions.actions || []).map(a => `<option value="${esc(a.action)}" ${action === a.action ? "selected" : ""}>${esc(a.action_ru)}</option>`).join("")}</select>
      <select id="hr"><option value="">весь период</option>
        <option value="1" ${hours === 1 ? "selected" : ""}>за час</option>
        <option value="24" ${hours === 24 ? "selected" : ""}>за сутки</option>
        <option value="168" ${hours === 168 ? "selected" : ""}>за неделю</option>
        <option value="720" ${hours === 720 ? "selected" : ""}>за месяц</option></select>
      <span class="grow"></span>
      <button class="btn ghost sm" id="prev" ${page <= 1 ? "disabled" : ""}>${ic("left", "s")}</button>
      <span class="faint num" style="min-width:104px;text-align:center">стр. ${page} / ${pages}</span>
      <button class="btn ghost sm" id="next" ${page * size >= total ? "disabled" : ""}>${ic("chevron", "s")}</button></div>`);
    tools.querySelector("#q").oninput = UI.debounce(e => { q = e.target.value.trim(); page = 1; render(main, state); }, 350);
    tools.querySelector("#ac").onchange = e => { action = e.target.value; page = 1; render(main, state); };
    tools.querySelector("#hr").onchange = e => { hours = +e.target.value; page = 1; render(main, state); };
    tools.querySelector("#prev").onclick = () => { page--; render(main, state); };
    tools.querySelector("#next").onclick = () => { page++; render(main, state); };
    head.querySelector("#csv").onclick = () => exportCsv(data.items || []);

    const card = el(`<div class="card flat" style="padding:0"><div class="alog"></div></div>`);
    const box = card.querySelector(".alog");
    if (!(data.items || []).length) box.appendChild(el(UI.emptyState("записей по фильтру нет", "search")));
    (data.items || []).forEach((a, i) => box.appendChild(aitem(a, i, main, state)));

    const F = UI.stage();
    F.appendChild(head);
    if (stats && stats.total) F.appendChild(statCard(stats));
    F.appendChild(tools); F.appendChild(card);
    UI.mount(main, F, { merge: false });
    UI.stagger(main, ".rv-row");
    return true;
  }

  function aitem(a, i, main, state) {
    const item = el(`<div class="aitem ${CLS(a.action)} rv-row" style="--i:${Math.min(i, 25)}">
      <span class="ai">${ic(ICN(a.action), "s")}</span>
      <div><div class="at"><b>${esc(a.action_ru)}</b>
          <span class="faint num" style="font-size:11px">${esc(a.action)}</span>
          ${a.username ? ` · ${esc(a.username)}` : ""}${a.role ? ` (${esc(API.ROLE_RU[a.role] || a.role)})` : ""}</div>
        <div class="ad">${esc(a.entity_type || "—")} ${esc(a.entity_id || "")}
          ${a.detail && a.detail.task ? ` · направление ${esc(a.detail.task)}` : ""}
          ${a.detail && a.detail.channel_id ? ` · канал ${esc(a.detail.channel_id)}` : ""}
          ${a.detail && a.detail.comment ? ` · «${esc(a.detail.comment)}»` : ""}</div>
        ${opened === a.id ? `<pre class="json">${esc(JSON.stringify(a.detail || {}, null, 2))}</pre>` : ""}</div>
      <div class="aw" title="${dtFull(a.created_at)}">${ago(a.created_at)}
        ${a.detail && a.detail.ip ? `<div class="faint">${esc(a.detail.ip)}</div>` : ""}
        ${a.detail && a.detail.request_id && a.detail.request_id !== "-"
          ? `<div class="faint" style="font-size:10px">rid ${esc(a.detail.request_id)}</div>` : ""}</div></div>`);
    item.onclick = () => { opened = opened === a.id ? null : a.id; render(main, state); };
    return item;
  }

  function statCard(stats) {
    const top = stats.by_action.slice(0, 6);
    const card = el(`<div class="card"><div class="ct">${ic("activity", "s")} Активность за ${stats.hours} ч
      <span class="grow"></span><span class="faint" style="text-transform:none;letter-spacing:0">всего действий: ${fmt(stats.total, 0)}</span></div>
      <div class="row wrap" style="gap:16px;align-items:flex-start"></div></div>`);
    const row = card.querySelector(".row");
    const palette = ["var(--accent)", "var(--accent-2)", "var(--ok)", "var(--warn)", "var(--bad)", "var(--text-faint)"];
    row.appendChild(Charts.donut(top.map((s, i) => ({ label: s.action_ru, value: s.n, color: palette[i] })), 140,
      `<div><div style="font-size:20px;font-weight:800">${fmt(stats.total, 0)}</div>
        <div class="faint" style="font-size:10px">действий</div></div>`));
    const legend = el(`<div style="flex:1;min-width:220px"></div>`);
    top.forEach(s => legend.appendChild(el(`<div class="row" style="justify-content:space-between;font-size:12.5px;padding:3px 0">
      <span class="muted">${esc(s.action_ru)}</span><b class="num">${fmt(s.n, 0)}</b></div>`)));
    if (stats.by_action.length > top.length) legend.appendChild(el(`<div class="faint" style="font-size:11.5px;margin-top:4px">
      ещё ${stats.by_action.length - top.length} типов действий</div>`));
    row.appendChild(legend);
    return card;
  }

  function exportCsv(items) {
    if (!items.length) { UI.toast("нечего экспортировать", "warn"); return; }
    const cols = ["id", "created_at", "action", "action_ru", "username", "role", "entity_type", "entity_id", "detail"];
    const csv = [cols.join(";")].concat(items.map(a => cols.map(c => {
      const v = c === "detail" ? JSON.stringify(a.detail || {}) : a[c];
      return v === null || v === undefined ? "" : String(v).replace(/;/g, ",").replace(/\s+/g, " ");
    }).join(";"))).join("\r\n");
    const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
    const aEl = document.createElement("a");
    aEl.href = URL.createObjectURL(blob);
    aEl.download = `audit_p${page}_${new Date().toISOString().slice(0, 10)}.csv`;
    aEl.click(); URL.revokeObjectURL(aEl.href);
    UI.toast(`выгружено записей: ${items.length}`, "ok", { title: "CSV журнала аудита" });
  }
  return { render, name: "Аудит", icon: "shield" };
})();