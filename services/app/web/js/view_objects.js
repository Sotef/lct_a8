/* view_objects.js — объекты: список / карта-радар (офлайн SVG), риски L2 */
window.Views = window.Views || {};
Views.objects = (() => {
  const { el, esc, ic, fmt, riskHex, riskColor, riskLevel } = UI;
  let mode = "list", q = "", distFilter = "", riskFilter = 0, sortMode = "risk";
  let lastState = null;

  async function render(main, state, silent) {
    lastState = state;
    const F = UI.stage();               // сборка offscreen — список/карта не «пропадают»
    UI.quiet(main, silent);
    const tree = await API.get("/objects");
    const objs = (tree.tree || []).filter(o => o.level >= 2);
    const districts = [...new Set(objs.map(o => o.district).filter(Boolean))].sort();
    if (!mode) mode = "list";

    const max7 = o => Math.max(0, ...Object.values(o.risk7d || {}).map(v => +v || 0));
    const has7 = o => Object.keys(o.risk7d || {}).length > 0;
    let list = objs.filter(o => {
      const r = max7(o);
      if (riskFilter && r < riskFilter) return false;
      if (distFilter && o.district !== distFilter) return false;
      if (!q) return true;
      const t = q.toLowerCase();
      return [o.name, o.type, o.district, o.object_id].some(v => (v || "").toLowerCase().includes(t));
    });
    if (sortMode === "risk") list = [...list].sort((a, b) => max7(b) - max7(a));
    if (sortMode === "name") list = [...list].sort((a, b) => (a.name || "").localeCompare(b.name || "", "ru"));
    if (sortMode === "channels") list = [...list].sort((a, b) =>
      Math.max(0, ...Object.values(b.risks || {}).map(r => r.channel_count || 0)) -
      Math.max(0, ...Object.values(a.risks || {}).map(r => r.channel_count || 0)));
    const hi = objs.filter(o => max7(o) >= 0.5).length;

    const head = el(`<div class="page-head">
      <div><div class="h1">Объекты <span class="gt">инфраструктуры</span></div>
        <div class="sub">${objs.length} объектов уровня 2 · риск = <b>максимум P(событие ≤ 7 дней)</b> по каналам
          (прогноз, за последние 3 суток сим-времени) ·
          <b style="color:var(--bad)">${hi}</b> с недельным риском ≥ 0.5</div></div>
      <div class="grow"></div>
      <div class="seg" id="segmode">
        <button data-m="list" class="${mode === "list" ? "on" : ""}">${ic("list", "s")} Список</button>
        <button data-m="map" class="${mode === "map" ? "on" : ""}">${ic("map", "s")} Карта-радар</button>
      </div></div>`);
    FX.seg(head.querySelector("#segmode"), b => { mode = b.dataset.m; render(main, state, true); });
    F.appendChild(head);

    const tools = el(`<div class="toolrow">
      <input type="search" id="q" placeholder="Поиск: название, район, тип, id…" value="${esc(q)}">
      <select id="dist"><option value="">все районы</option>${districts.map(d =>
        `<option value="${esc(d)}" ${d === distFilter ? "selected" : ""}>район ${esc(d)}</option>`).join("")}</select>
      <select id="risk"><option value="0">любой риск</option>
        <option value="0.2" ${riskFilter === 0.2 ? "selected" : ""}>P(≤7д) ≥ 0.2</option>
        <option value="0.5" ${riskFilter === 0.5 ? "selected" : ""}>P(≤7д) ≥ 0.5</option></select>
      <select id="sort"><option value="risk" ${sortMode === "risk" ? "selected" : ""}>сортировка: риск ↓</option>
        <option value="name" ${sortMode === "name" ? "selected" : ""}>по названию</option>
        <option value="channels" ${sortMode === "channels" ? "selected" : ""}>по числу каналов</option></select>
      <span class="grow"></span><span class="faint">показано ${list.length} из ${objs.length}</span></div>`);
    tools.querySelector("#q").oninput = UI.debounce(e => { q = e.target.value; render(main, state, true); }, 280);
    tools.querySelector("#dist").onchange = e => { distFilter = e.target.value; render(main, state, true); };
    tools.querySelector("#risk").onchange = e => { riskFilter = +e.target.value; render(main, state, true); };
    tools.querySelector("#sort").onchange = e => { sortMode = e.target.value; render(main, state, true); };
    F.appendChild(tools);

    if (mode === "list") renderList(F, list, state, max7, has7);
    else renderMap(F, list, state, max7, has7);
    /* список — мягко (морфинг значений), карту-радар пересобираем целиком:
       зум/перетаскивание держат ссылки на конкретный узел SVG */
    const canMerge = mode === "list" && !!main.dataset.mounted;
    UI.mount(main, F, { merge: canMerge, quiet: silent });
    main.dataset.mounted = "1";
    UI.stagger(main, ".rv-row");
    return true;
  }

  /* полоски по направлениям: значения — недельный прогноз P(≤7д), в подсказке и L2 risk30 */
  function riskStrip(risks, risk7d) {
    return API.TASKS.map(t => {
      const v = +((risk7d || {})[t] || 0);
      const r = (risks || {})[t];
      const known = (risk7d || {})[t] !== undefined || !!r;
      return `<span title="${esc(API.TASK_META[t].label)}: P(≤7д) ${risk7d && risk7d[t] !== undefined
        ? fmt(risk7d[t], 2) : "нет данных"}${r ? ` · L2 risk30 ${fmt(r.risk30_max, 2)}` : ""}"
        style="width:30px;height:7px;border-radius:4px;display:inline-block;background:${riskHex(v)};opacity:${known ? 1 : .15}"></span>`;
    }).join(" ");
  }

  function renderList(host, list, state, max7, has7) {
    const card = el(`<div class="card flat tscroll"><table class="tbl"><thead><tr>
      <th>Объект</th><th>Район</th><th>Каналы</th><th>P(≤7д) по направлениям</th><th>Макс. P(≤7д)</th><th></th>
    </tr></thead><tbody></tbody></table></div>`);
    const tb = card.querySelector("tbody");
    if (!list.length) tb.appendChild(el(`<tr><td colspan="6">${UI.emptyState("ничего не найдено", "search")}</td></tr>`));
    const chOf = o => Math.max(0, ...Object.values(o.risks || {}).map(r => r.channel_count || 0));
    list.forEach((o, i) => {
      const r = max7(o), known = has7(o), lv = riskLevel(known ? r : null);
      const tr = el(`<tr class="rrow rv-row" data-id="${esc(o.object_id)}" style="--i:${Math.min(i, 20)}">
        <td><b>${esc(o.name || o.object_id)}</b>${known ? "" : ' <span class="badge">нет недельных прогнозов</span>'}
          <div class="faint" style="font-size:11.5px">${esc(o.type || "")} · id ${esc(o.object_id)}</div></td>
        <td class="muted">${esc(o.district || "—")}</td>
        <td class="num">${chOf(o) || "—"}</td>
        <td>${riskStrip(o.risks, o.risk7d)}</td>
        <td><span class="badge ${known ? lv.cls : ""}">${known ? fmt(r, 2) : "—"}</span></td>
        <td class="faint">${ic("chevron", "s")}</td></tr>`);
      tr.onclick = () => Cards.object.open(tr.dataset.id, { state, task: state.task });
      tb.appendChild(tr);
    });
    host.appendChild(card);
  }
  /* ---------- карта-радар: схематичная раскладка по районам (координат в данных нет) ---------- */
  function renderMap(host, list, state, max7, has7) {
    const W = 1000, H = 640, cx = W / 2, cy = H / 2;
    const byDist = {};
    list.forEach(o => { (byDist[o.district || "—"] = byDist[o.district || "—"] || []).push(o); });
    const districts = Object.keys(byDist).sort();

    const ahead = el(`<div class="note" style="margin:0 0 12px">
      ${ic("info", "s")} Географических координат в источниках нет: раскладка <b>схематичная</b> — районы-секторы,
      внутри сектора объекты стоят по индексу. Цвет — <b>P(событие ≤ 7 дней)</b> (максимум по каналам),
      размер — число каналов, пульсация — высокий недельный риск. Это визуальная кластеризация очереди риска,
      а не карта коллекторов.</div>`);
    const host2 = el(`<div class="maphost" id="mh"></div>`);
    const ctrl = el(`<div class="map-ctrl">
      <button class="icbtn" data-z="in" title="приблизить">${ic("plus")}</button>
      <button class="icbtn" data-z="out" title="отдалить">${ic("minus")}</button>
      <button class="icbtn" data-z="reset" title="сбросить">${ic("target")}</button></div>`);
    host2.appendChild(ctrl);
    host2.appendChild(el(`<div class="map-legend">
      <span><i style="background:var(--ok)"></i>низкий</span><span><i style="background:var(--warn)"></i>средний</span>
      <span><i style="background:var(--bad)"></i>высокий</span>
      <span class="faint">колесо — зум · перетаскивание — сдвиг</span></div>`));
    host.appendChild(ahead); host.appendChild(host2);
    const g = buildMapSvg(host2, districts, byDist, max7, has7, { W, H, cx, cy });
    if (g) bindMapInteractions(host2, g);
  }

  function buildMapSvg(host, districts, byDist, max7, has7, { W, H, cx, cy }) {
    const N = Math.max(1, districts.length);
    let svg = `<svg viewBox="0 0 ${W} ${H}" id="mpsvg">`;
    for (let gx = 0; gx <= W; gx += 60)
      svg += `<line x1="${gx}" y1="0" x2="${gx}" y2="${H}" stroke="var(--border)" opacity=".3"/>`;
    for (let gy = 0; gy <= H; gy += 60)
      svg += `<line x1="0" y1="${gy}" x2="${W}" y2="${gy}" stroke="var(--border)" opacity=".3"/>`;
    for (let r = 90; r <= 300; r += 70)
      svg += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--border-strong)"
        stroke-dasharray="${(r / 30).toFixed(0)} ${(r / 20).toFixed(0)}" opacity=".28"/>`;
    svg += `<defs><linearGradient id="sweepg" x1="0" x2="1"><stop offset="0" stop-color="var(--accent-2)" stop-opacity="0"/>
      <stop offset="1" stop-color="var(--accent-2)" stop-opacity=".9"/></linearGradient>
      <radialGradient id="sweepf"><stop offset="0" stop-color="var(--accent-2)" stop-opacity=".16"/>
      <stop offset="1" stop-color="var(--accent-2)" stop-opacity="0"/></radialGradient></defs>
      <g style="transform-origin:${cx}px ${cy}px;animation:spin 10s linear infinite">
      <line x1="${cx}" y1="${cy}" x2="${cx + 300}" y2="${cy}" stroke="url(#sweepg)" stroke-width="2"/>
      <path d="M${cx} ${cy} L${cx + 300} ${cy} A300 300 0 0 1 ${cx + 300 * Math.cos(-0.4)} ${cy + 300 * Math.sin(-0.4)} Z"
        fill="url(#sweepf)"/></g>
      <circle cx="${cx}" cy="${cy}" r="4" fill="var(--accent)"/>
      <circle cx="${cx}" cy="${cy}" r="10" fill="none" stroke="var(--accent)" opacity=".5" class="halo"/>
      <text x="${cx}" y="${cy - 20}" text-anchor="middle" fill="var(--text-dim)" font-size="12" font-weight="800">ЦЕНТР ОДС</text>`;

    districts.forEach((d, di) => {
      const a0 = (di / N) * 2 * Math.PI - Math.PI / 2;
      const items = byDist[d];
      svg += `<line x1="${cx + 55 * Math.cos(a0)}" y1="${cy + 55 * Math.sin(a0)}"
        x2="${cx + 292 * Math.cos(a0)}" y2="${cy + 292 * Math.sin(a0)}" stroke="var(--border-strong)" opacity=".3"/>
        <text x="${cx + 324 * Math.cos(a0)}" y="${cy + 324 * Math.sin(a0)}" text-anchor="middle"
          fill="var(--text-faint)" font-size="11" font-weight="700">Р-Н ${esc(d)}</text>`;
      items.forEach((o, i) => {
        const ring = 115 + (i % 3) * 58 + ((di % 2) ? 26 : 0);
        const da = (i / Math.max(1, items.length)) * (2 * Math.PI / N) * .92 - (Math.PI / N) * .44;
        const a = a0 + da;
        const x = cx + ring * Math.cos(a) * 1.16, y = cy + ring * Math.sin(a);
        const r = max7(o), chn = Math.max(1, ...Object.values(o.risks || {}).map(v => v.channel_count || 0));
        const has = has7(o);
        const rad = has ? Math.min(16, 5 + Math.sqrt(chn) * 1.5) : 4.5;
        svg += `<g class="omap" data-oid="${esc(o.object_id)}">
          ${has && r >= .5 ? `<circle class="halo" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(rad + 6).toFixed(1)}"
            fill="${riskHex(r)}" opacity=".2"/>` : ""}
          <circle class="dot" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${rad.toFixed(1)}"
            fill="${has ? riskHex(r) : "transparent"}" stroke="${has ? "var(--border-strong)" : "var(--text-faint)"}"
            stroke-width="${has ? 1.2 : 1.4}" stroke-dasharray="${has ? "none" : "3 2"}"/>
          ${has ? `<text x="${x.toFixed(1)}" y="${(y + 3.5).toFixed(1)}" text-anchor="middle"
            font-size="${Math.min(10, rad).toFixed(0)}" fill="#0b0d12" font-weight="800">${chn > 999 ? "1k" : chn}</text>` : ""}
          <text class="lbl" x="${x.toFixed(1)}" y="${(y + rad + 13).toFixed(1)}" text-anchor="middle" font-size="10"
            fill="var(--text)">${esc((o.name || o.object_id).slice(0, 26))}</text>
          <title>${esc(o.name || o.object_id)} · ${esc(o.type || "")} · район ${esc(o.district || "—")} ·
            P(≤7д) ${has ? fmt(r, 2) : "нет данных"} · каналов ${chn}</title></g>`;
      });
    });
    svg += `</svg>`;
    host.appendChild(el(`<div style="position:absolute;inset:0">${svg}</div>`));
    return host.querySelector("#mpsvg");
  }
  function bindMapInteractions(host, g) {
    let zoom = 1, pan = { x: 0, y: 0 };
    g.style.transformOrigin = "50% 50%";
    g.style.transition = "transform .3s cubic-bezier(.16,1,.3,1)";
    const apply = () => g.style.transform = `scale(${zoom}) translate(${pan.x}px, ${pan.y}px)`;
    host.querySelectorAll("[data-z]").forEach(b => b.onclick = () => {
      const z = b.dataset.z;
      if (z === "in") zoom = Math.min(3, zoom * 1.25);
      else if (z === "out") zoom = Math.max(.6, zoom / 1.25);
      else { zoom = 1; pan = { x: 0, y: 0 }; }
      host.classList.toggle("zoomed", zoom > 1.4);
      apply();
    });
    host.addEventListener("wheel", e => {
      e.preventDefault();
      zoom = Math.max(.6, Math.min(3, zoom * (e.deltaY < 0 ? 1.12 : .9)));
      host.classList.toggle("zoomed", zoom > 1.4);
      apply();
    }, { passive: false });
    let drag = null, moved = false;
    host.addEventListener("pointerdown", e => {
      if (e.target.closest(".map-ctrl")) return;
      drag = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y };
      moved = false; host.classList.add("drag");
    });
    addEventListener("pointermove", e => {
      if (!drag) return;
      moved = true;
      pan = { x: drag.px + (e.clientX - drag.x), y: drag.py + (e.clientY - drag.y) };
      apply();
    });
    addEventListener("pointerup", () => { if (drag) { drag = null; host.classList.remove("drag"); } });
    g.querySelectorAll(".omap").forEach(n => n.addEventListener("click", () => {
      if (moved) { moved = false; return; }
      Cards.object.open(n.dataset.oid, { state: lastState, task: lastState && lastState.task });
    }));
  }
  return { render, name: "Объекты", icon: "map" };
})();
