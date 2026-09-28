/* view_graph.js — граф связности: объекты ↔ пикеты инженерных систем (тег p3), force-layout, подсветка */
window.Views = window.Views || {};
Views.graph = (() => {
  const { el, esc, ic, fmt, riskHex, riskLevel } = UI;

  async function render(main, state) {
    const F = UI.stage();               // сборка offscreen (граф переукладывается целиком)
    const data = await API.get("/objects/graph");
    const hubs = [...(data.hubs || [])].sort((a, b) => b.count - a.count).slice(0, 20);
    const hubIds = new Set(hubs.map(h => h.id));
    const objIds = new Set();
    hubs.forEach(h => (h.objects || []).forEach(o => objIds.add(o)));
    const nodes = (data.nodes || []).filter(n => objIds.has(n.id));

    const head = el(`<div class="page-head">
      <div><div class="h1">Граф систем</div>
        <div class="sub">${hubs.length} пикетов-хабов (тег p3) · ${nodes.length} объектов ·
          цвет = <b>P(событие ≤ 7 дней)</b> по направлению «${esc(API.TASK_META[state.task].label)}»
          (максимум по каналам за последние 3 суток прогнозов; направление переключается ползунком в шапке),
          размер — число связей</div></div>
      <div class="grow"></div>
      <div class="row wrap">
        <label class="chk" title="Подписи не наслаиваются: если места нет, подпись появится при наведении">
          <input type="checkbox" id="glab" ${localStorage.getItem("mc_graph_labels") !== "0" ? "checked" : ""}> подписи объектов</label>
        <button class="btn ghost sm" id="rf">${ic("refresh", "s")} Переуложить</button>
        <button class="btn ghost sm" id="rs">${ic("target", "s")} Сброс зума</button></div></div>`);
    const legend = el(`<div class="glegend">
      <span><i style="background:var(--accent-2)"></i>пикет (ПК)</span>
      <span><i style="background:${UI.riskHex(0)}"></i>низкий P(≤7д)</span>
      <span><i style="background:${UI.riskHex(0.3)}"></i>средний</span>
      <span><i style="background:${UI.riskHex(0.7)}"></i>высокий</span>
      <span class="faint">перетаскивание — сдвиг · колесо — зум · клик по объекту — карточка объекта со статистикой ·
        пустая точка = по объекту нет прогнозов за 7 дней</span></div>`);

    const W = 1200, H = 680;
    const host = el(`<div class="graph-host"></div>`);
    F.appendChild(head); F.appendChild(legend); F.appendChild(host);

    const P = [], M = new Map();
    hubs.forEach((h, i) => {
      const a = (i / hubs.length) * 2 * Math.PI - Math.PI / 2;
      const p = { id: h.id, label: h.label, count: h.count,
        x: W / 2 + 170 * Math.cos(a), y: H / 2 + 170 * Math.sin(a) };
      P.push(p); M.set(h.id, p);
    });
    nodes.forEach((n, i) => {
      const a = (i / Math.max(1, nodes.length)) * 2 * Math.PI - Math.PI / 2;
      const p = { id: n.id, name: n.name, risk: n.risk || {}, risk7d: n.risk7d || {},
        hubs: n.hubs || [],
        x: W / 2 + 300 * Math.cos(a), y: H / 2 + 490 * Math.sin(a) };
      P.push(p); M.set(n.id, p);
    });
    const L = [];
    (data.links || []).forEach(l => {
      if (hubIds.has(l.source) && M.has(l.target)) L.push({ s: l.source, t: l.target, w: l.weight || .3 });
    });

    layout(P, M, L, W, H);
    draw(host, hubs, nodes, L, M, W, H, main, state, head);
    UI.mount(main, F, { merge: false });      // граф: атомарная замена (оживляет layout и зум)
    return true;
  }

  /* force-layout: отталкивание узлов + пружины рёбер (без библиотек) */
  function layout(P, M, L, W, H) {
    const ITER = 240;
    for (let it = 0; it < ITER; it++) {
      const k = 1 - it / ITER;
      P.forEach(p => { p.fx = 0; p.fy = 0; });
      for (let i = 0; i < P.length; i++)
        for (let j = i + 1; j < P.length; j++) {
          const a = P[i], b = P[j];
          let dx = b.x - a.x, dy = b.y - a.y, d2 = dx * dx + dy * dy;
          if (d2 < 1) d2 = 1;
          const d = Math.sqrt(d2), f = Math.min(2200, 26000 / d2);
          dx /= d; dy /= d;
          a.fx -= dx * f; a.fy -= dy * f; b.fx += dx * f; b.fy += dy * f;
        }
      L.forEach(l => {
        const a = M.get(l.s), b = M.get(l.t);
        if (!a || !b) return;
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.max(1, Math.hypot(dx, dy));
        const want = 120 + 120 * (1 - Math.min(1, l.w * 6));
        const f = (d - want) * .035;
        a.fx += dx / d * f; a.fy += dy / d * f; b.fx -= dx / d * f; b.fy -= dy / d * f;
      });
      P.forEach(p => {
        p.x += p.fx * k * .9; p.y += p.fy * k * .9;
        p.x = Math.max(40, Math.min(W - 40, p.x)); p.y = Math.max(40, Math.min(H - 40, p.y));
      });
    }
  }
  function draw(host, hubs, nodes, L, M, W, H, main, state, head) {
    const { el, esc, ic, fmt, riskHex, riskLevel } = UI;
    let svg = `<svg viewBox="0 0 ${W} ${H}"><g class="vp">`;
    L.forEach((l, i) => {
      const a = M.get(l.s), b = M.get(l.t);
      svg += `<line class="glink ${i % 3 === 0 ? "flowline" : ""}" data-s="${esc(l.s)}" data-t="${esc(l.t)}"
        x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}"
        stroke-width="${Math.max(.5, Math.min(3, l.w * 12)).toFixed(2)}"/>`;
    });
    hubs.forEach(h => {
      const p = M.get(h.id);
      svg += `<g class="gnode" data-id="${esc(h.id)}" data-kind="hub">
        <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${(5 + Math.min(10, Math.sqrt(h.count) * 1.3)).toFixed(1)}"
          fill="var(--accent-2)" opacity=".9"/>
        <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${(9 + Math.min(10, Math.sqrt(h.count) * 1.3)).toFixed(1)}"
          fill="none" stroke="var(--accent-2)" opacity=".2"/>
        <text x="${p.x.toFixed(1)}" y="${(p.y - 12).toFixed(1)}" text-anchor="middle">${esc(p.label)}</text>
        <title>${esc(p.label)} · объектов: ${p.count}</title></g>`;
    });
    /* подписи объектов: не наслаиваются друг на друга (проверка на пересечение боксов) */
    const showLabels = localStorage.getItem("mc_graph_labels") !== "0";
    const placed = [];
    const fits = (x, y, w2, h2) => !placed.some(r =>
      Math.abs(x - r.x) < (w2 + r.w) / 2 && Math.abs(y - r.y) < (h2 + r.h) / 2);

    nodes.forEach(n => {
      const p = M.get(n.id);
      /* риск за 7 дней по выбранному направлению (из /objects/graph -> risk7d).
         Если по объекту данных нет — рисуем «полую» точку, а не подставляем чужой риск. */
      const r7 = p.risk7d || {};
      const has7 = Object.keys(r7).length > 0;
      const risk = has7 ? (r7[state.task] !== undefined && r7[state.task] !== null
        ? r7[state.task] : 0) : null;
      const r = 6 + Math.min(11, Math.sqrt((p.hubs || []).length) * 2.6);
      const name = (p.name || n.id);
      let label = "";
      if (showLabels) {
        const w2 = Math.min(name.length, 18) * 5.2, h2 = 11;
        const tries = [[p.x, p.y + r + 12], [p.x, p.y - r - 5], [p.x + r + 6, p.y + 3]];
        const spot = tries.find(([lx, ly]) => fits(lx, ly, w2, h2));
        if (spot) {
          placed.push({ x: spot[0], y: spot[1], w: w2, h: h2 });
          label = `<text x="${spot[0].toFixed(1)}" y="${(spot[1] + 3.5).toFixed(1)}" text-anchor="middle"
            font-size="9.5">${esc(name.slice(0, 18))}</text>`;
        }
      }
      svg += `<g class="gnode" data-id="${esc(n.id)}" data-kind="obj">
        <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${r.toFixed(1)}"
          fill="${risk === null ? "transparent" : riskHex(risk)}"
          stroke="${risk === null ? "var(--text-faint)" : risk >= 0.5 ? riskHex(risk) : "var(--border-strong)"}"
          stroke-width="${risk !== null && risk >= 0.5 ? 2 : 1.2}"
          stroke-dasharray="${risk === null ? "3 2" : "none"}"/>
        ${label}
        <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${Math.max(10, r + 2)}" fill="transparent"
          style="cursor:pointer"/>
        <title>${esc(name)} · ${risk === null ? "нет данных за 7 дней" : `${esc(API.TASK_META[state.task].label)}: P(≤7д) = ${fmt(risk, 3)}`}
· пикетов ${(p.hubs || []).length} — клик: карточка объекта со статистикой</title></g>`;
    });
    svg += `</g></svg>`;
    const box = el(`<div style="position:absolute;inset:0">${svg}</div>`);
    host.appendChild(box);
    const vp = box.querySelector(".vp");
    vp.style.transformOrigin = "50% 50%";

    let zoom = 1, pan = { x: 0, y: 0 }, drag = null;
    const apply = () => vp.style.transform = `scale(${zoom}) translate(${pan.x}px, ${pan.y}px)`;
    host.addEventListener("wheel", e => {
      e.preventDefault();
      zoom = Math.max(.5, Math.min(3.5, zoom * (e.deltaY < 0 ? 1.12 : .9))); apply();
    }, { passive: false });
    host.addEventListener("pointerdown", e => {
      drag = e.target.closest(".gnode") ? null : { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y };
    });
    addEventListener("pointermove", e => {
      if (!drag) return;
      pan = { x: drag.px + (e.clientX - drag.x), y: drag.py + (e.clientY - drag.y) }; apply();
    });
    addEventListener("pointerup", () => { drag = null; });

    const links = box.querySelectorAll(".glink"), gNodes = box.querySelectorAll(".gnode");
    const near = (a, b) => L.some(l => (l.s === a && l.t === b) || (l.t === a && l.s === b));
    gNodes.forEach(node => {
      node.addEventListener("mouseenter", () => {
        const id = node.dataset.id;
        links.forEach(l => {
          const on = l.dataset.s === id || l.dataset.t === id;
          l.classList.toggle("hl", on); l.classList.toggle("dim", !on);
        });
        gNodes.forEach(n => n.classList.toggle("dim", n.dataset.id !== id && !near(id, n.dataset.id)));
      });
      node.addEventListener("mouseleave", () => {
        links.forEach(l => l.classList.remove("hl", "dim"));
        gNodes.forEach(n => n.classList.remove("dim"));
      });
      node.addEventListener("click", () => {
        if (node.dataset.kind === "obj") Cards.object.open(node.dataset.id, { state, task: state.task });
      });
    });
    const rf = head.querySelector("#rf"); if (rf) rf.onclick = () => render(main, state);
    const rs = head.querySelector("#rs"); if (rs) rs.onclick = () => { zoom = 1; pan = { x: 0, y: 0 }; apply(); };
    const gl = head.querySelector("#glab");
    if (gl) gl.onchange = e => {
      localStorage.setItem("mc_graph_labels", e.target.checked ? "1" : "0");
      render(main, state);
    };
    main.appendChild(el(`<div class="note">${ic("info", "s")} Граф построен из тегов инженерных систем («p3» — пикет):
      объекты связаны, если их датчики относятся к одному пикету. Цвет — прогноз <b>P(событие ≤ 7 дней)</b>
      по выбранному направлению (ползунок в шапке), размер — число связей. Клик по объекту открывает его
      карточку: риски по всем направлениям, датчики, заявки и график работ по объекту.</div>`));
  }
  return { render, name: "Граф систем", icon: "graph" };
})();
