
  /* ---------- КАРТА (офлайн SVG, без внешних CDN) ---------- */
  function renderMap(host, objs, state) {
    const W = 1000, H = 580, cx = 500, cy = 300;
    const noData = objs.filter(o => !Object.keys(o.risks || {}).length).length;

    const wrap = el(`<div></div>`);
    const note = el(`<div class="note" style="margin-bottom:12px">⚠ Координаты объектов в данных
      отсутствуют — позиции на карте <b>схематичные</b> (детерминированный разброс вокруг Москвы
      и области), цвет = максимальный risk30, размер = число каналов.
      ${noData ? `<b>${noData} объектов без данных</b> (серые полые точки — нет активных каналов задач прогнозирования).` : ""}
      Это визуальная кластеризация, а не реальная география.</div>`);
    const box = el(`<div class="maphost"></div>`);
    box.appendChild(el(`<div class="map-note">Нажмите на объект — карточка с датчиками и прогнозами · офлайн-карта (без CDN)</div>`));
    wrap.appendChild(note); wrap.appendChild(box); host.appendChild(wrap);

    /* детерминированные xy: сгущение к «Москве», разброс по «МО» */
    function xy(oid) {
      let h = 0;
      for (const ch of String(oid)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
      const a = (h % 360) * Math.PI / 180;
      const r = 40 + (h % 1000) / 1000 * 230;      /* 40..270 — ближе к центру */
      return [cx + r * Math.cos(a) * 1.35, cy + r * Math.sin(a) * 1.05];
    }

    let svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;border:1px solid var(--border);
      border-radius:var(--radius);background:var(--bg-2)">`;
    /* сетка */
    for (let gx = 0; gx <= W; gx += 50)
      svg += `<line x1="${gx}" y1="0" x2="${gx}" y2="${H}" stroke="var(--border)" opacity=".35"/>`;
    for (let gy = 0; gy <= H; gy += 50)
      svg += `<line x1="0" y1="${gy}" x2="${W}" y2="${gy}" stroke="var(--border)" opacity=".35"/>`;
    /* условные «кольцевые дороги» и центр */
    svg += `<circle cx="${cx}" cy="${cy}" r="90" fill="none" stroke="var(--border-strong)" opacity=".5" stroke-dasharray="6 5"/>
      <circle cx="${cx}" cy="${cy}" r="200" fill="none" stroke="var(--border-strong)" opacity=".35" stroke-dasharray="4 6"/>
      <circle cx="${cx}" cy="${cy}" r="300" fill="none" stroke="var(--border-strong)" opacity=".25" stroke-dasharray="3 7"/>
      <text x="${cx}" y="${cy - 8}" text-anchor="middle" fill="var(--text-dim)" font-size="13" font-weight="800">МОСКВА</text>
      <text x="${cx}" y="${cy + 10}" text-anchor="middle" fill="var(--text-faint)" font-size="10">центр диспетчеризации</text>`;

    objs.forEach(o => {
      const risks = o.risks || {};
      const vals = Object.values(risks);
      const maxR = vals.length ? Math.max(0, ...vals.map(r => r.risk30_max || 0)) : 0;
      const ch = vals.length ? Math.max(1, ...vals.map(r => r.channel_count || 0)) : 0;
      const has = vals.length > 0;
      const [x, y] = xy(o.object_id);
      const r = has ? Math.min(16, 5 + Math.sqrt(ch) * 1.6) : 4.5;
      const tasksHtml = Object.entries(risks).map(([t, rk]) =>
        `<span class="badge ${rk.risk30_max >= 0.5 ? "high" : rk.risk30_max >= 0.2 ? "mid" : "low"}"
          style="margin:2px">${TASK_META[t] ? TASK_META[t].short : t}: ${fmt(rk.risk30_max, 2)}</span>`).join(" ");
      svg += `<g class="omap" data-oid="${o.object_id}" style="cursor:pointer">
        ${has && maxR >= 0.5 ? `<circle cx="${x}" cy="${y}" r="${r + 6}" fill="${riskHex(maxR)}" opacity=".18"/>` : ""}
        <circle cx="${x}" cy="${y}" r="${r}"
          fill="${has ? riskHex(maxR) : "transparent"}"
          stroke="${has ? "var(--border-strong)" : "var(--text-faint)"}"
          stroke-width="${has ? 1.2 : 1.4}" stroke-dasharray="${has ? "none" : "3 2"}">
          <title>${esc(o.name || o.object_id)} · ${has ? "макс риск " + fmt(maxR, 2) + ", каналов " + ch : "нет данных по задачам прогнозирования"}</title></circle>
        ${has ? `<text x="${x}" y="${y + 3.5}" text-anchor="middle" font-size="${Math.min(10, r)}" fill="#0b0d12" font-weight="800">${ch > 999 ? "1k+" : ch}</text>` : ""}
        <text x="${x}" y="${y + r + 13}" text-anchor="middle" font-size="10"
          fill="var(--text-dim)">${esc((o.name || o.object_id).slice(0, 26))}</text>
        <circle class="ohit" cx="${x}" cy="${y}" r="${Math.max(r + 6, 14)}" fill="transparent">
          <title>${esc(o.name || o.object_id)} · ${esc(o.type || "")} · район ${esc(o.district || "—")}
${tasksHtml ? tasksHtml.replace(/<[^>]+>/g, " ") : "нет данных"}</title></circle>
      </g>`;
    });
    svg += `</svg>`;
    box.appendChild(el(svg));
    box.querySelectorAll(".omap").forEach(g => {
      g.addEventListener("click", () =>
        Views.forecasts.openObject(g.dataset.oid, state));
    });
  }

/* view_objects.js — объекты: список / офлайн-карта Москвы и области */
window.Views = window.Views || {};
Views.objects = (() => {
  const { el, esc, fmt, riskHex } = UI;
  const TASK_META = API.TASK_META;
  let mode = "list";

  function destroy() {}

  async function render(main, state) {
    main.innerHTML = `<div class="spin"></div>`;
    const tree = await API.get("/objects");
    const objs = tree.tree.filter(o => o.level >= 2);

    const head = el(`<div class="topbar">
      <div><div class="h1">Объекты</div>
      <div class="sub">${objs.length} объектов · риски L2 (максимум risk30 по каналам)</div></div>
      <div class="grow"></div>
      <div class="seg">
        <button data-m="list" class="${mode === "list" ? "on" : ""}">Список</button>
        <button data-m="map" class="${mode === "map" ? "on" : ""}">Карта</button>
      </div></div>`);
    head.querySelectorAll(".seg button").forEach(b => {
      b.onclick = () => { mode = b.dataset.m; render(main, state); };
    });

    main.innerHTML = "";
    main.appendChild(head);
    const host = el(`<div></div>`);
    main.appendChild(host);
    if (mode === "list") renderList(host, objs, state);
    else renderMap(host, objs, state);
  }

  /* ---------- СПИСОК ---------- */
  function renderList(host, objs, state) {
    const tools = el(`<div class="toolrow">
      <input type="search" placeholder="Поиск объекта, района, типа…">
      <select class="sort">
        <option value="risk">Сортировка: риск ↓</option>
        <option value="name">Сортировка: название</option>
        <option value="channels">Сортировка: каналы ↓</option>
      </select></div>`);
    const list = el(`<div class="card" style="padding:6px 0"><table class="tbl"><thead><tr>
      <th>Объект</th><th>Район</th><th>Каналы</th><th>Риск по задачам</th><th></th>
    </tr></thead><tbody></tbody></table></div>`);
    const tbody = list.querySelector("tbody");
    const q = tools.querySelector("input"), sortSel = tools.querySelector(".sort");

    function draw() {
      const term = q.value.toLowerCase();
      let rows = objs.filter(o =>
        !term || (o.name || "").toLowerCase().includes(term) ||
        (o.district || "").includes(term) || (o.type || "").toLowerCase().includes(term));
      const maxR = o => Math.max(0, ...Object.values(o.risks || {}).map(r => r.risk30_max || 0));
      const ch = o => Math.max(0, ...Object.values(o.risks || {}).map(r => r.channel_count || 0));
      if (sortSel.value === "risk") rows = [...rows].sort((a, b) => maxR(b) - maxR(a));
      if (sortSel.value === "name") rows = [...rows].sort((a, b) => (a.name || "").localeCompare(b.name || "", "ru"));
      if (sortSel.value === "channels") rows = [...rows].sort((a, b) => ch(b) - ch(a));
      tbody.innerHTML = "";
      let noData = 0;
      rows.forEach(o => {
        const empty = !Object.keys(o.risks || {}).length;
        if (empty) noData++;
        const tr = el(`<tr class="rrow">
          <td><b>${esc(o.name || o.object_id)}</b>
            ${empty ? '<span class="badge" title="нет активных каналов задач прогнозирования">нет данных</span>' : ""}
            <div class="muted" style="font-size:11.5px">${esc(o.type || "")}</div></td>
          <td class="muted">${esc(o.district || "")}</td>
          <td class="num">${ch(o) || "—"}</td>
          <td class="riskcells" style="display:flex;gap:6px"></td>
          <td class="num muted">${empty ? "—" : fmt(maxR(o), 2)}</td></tr>`);
        const cells = tr.querySelector(".riskcells");
        ["fire", "access", "sensor", "wear"].forEach(t => {
          const r = (o.risks || {})[t];
          const d = el(`<span title="${TASK_META[t].label}: ${r ? fmt(r.risk30_max, 2) : "нет данных"}"
            style="width:34px;height:6px;border-radius:3px;display:inline-block;background:${riskHex(r && r.risk30_max || 0)};opacity:${r ? 1 : .18}"></span>`);
          cells.appendChild(d);
        });
        tr.onclick = () => Views.forecasts.openObject(o.object_id, state);
        tbody.appendChild(tr);
      });
      if (!rows.length) tbody.appendChild(el(`<tr><td colspan="5" class="empty">ничего не найдено</td></tr>`));
      else if (noData) tbody.appendChild(el(`<tr><td colspan="5" class="muted" style="padding:10px 14px">
        ${noData} из ${rows.length} объектов без данных — нет активных каналов задач прогнозирования
        (датчики этих объектов не входят в журнал СМВУ или не срабатывали за период)</td></tr>`));
    }
    q.oninput = draw; sortSel.onchange = draw;
    host.appendChild(tools); host.appendChild(list);
    draw();
  }

  function destroy() { if (leaflet) { leaflet.remove(); leaflet = null; } }

  return { render, destroy, name: "Объекты", icon: "◫" };
})();
