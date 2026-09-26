/* view_graph.js — граф систем: объекты ↔ пикеты (тег p3) из /objects/graph */
window.Views = window.Views || {};
Views.graph = (() => {
  const { el, esc, fmt, riskHex } = UI;

  async function render(main, state) {
    main.innerHTML = `<div class="spin"></div>`;
    const data = await API.get("/objects/graph");

    /* берём топ-хабы по числу объектов и только связанные с ними объекты */
    const hubs = [...data.hubs].sort((a, b) => b.count - a.count).slice(0, 18);
    const hubIds = new Set(hubs.map(h => h.id));
    const objIds = new Set();
    hubs.forEach(h => h.objects.forEach(o => objIds.add(o)));
    const nodes = data.nodes.filter(n => objIds.has(n.id));

    const head = el(`<div class="topbar">
      <div><div class="h1">Граф систем</div>
      <div class="sub">${hubs.length} пикетов-хабов (тег p3) · ${nodes.length} связанных объектов ·
      связь = общий пикет инженерной системы</div></div></div>`);
    main.innerHTML = "";
    main.appendChild(head);

    const legend = el(`<div class="glegend">
      <span><i style="background:var(--accent-2)"></i>пикет (ПК)</span>
      <span><i style="background:var(--accent)"></i>объект</span>
      <span>размер/цвет объекта — максимальный risk30 по задачам</span></div>`);
    main.appendChild(legend);

    const W = 1100, H = 620, cx = W / 2, cy = H / 2;
    const R1 = 130, R2 = 265;   /* радиусы: хабы внутрь, объекты наружу */
    let svg = `<svg viewBox="0 0 ${W} ${H}">`;

    const hubPos = hubs.map((h, i) => {
      const a = (i / hubs.length) * 2 * Math.PI - Math.PI / 2;
      return { ...h, x: cx + R1 * Math.cos(a), y: cy + R1 * Math.sin(a) };
    });
    const pos = new Map(hubPos.map(h => [h.id, h]));
    const objNodes = nodes.map((n, i) => {
      const a = (i / nodes.length) * 2 * Math.PI - Math.PI / 2;
      const p = { ...n, x: cx + R2 * Math.cos(a), y: cy + R2 * Math.sin(a) };
      pos.set(n.id, p);
      return p;
    });

    /* рёбра */
    data.links.forEach(l => {
      if (!hubIds.has(l.source) || !pos.has(l.target)) return;
      const s = pos.get(l.source), t = pos.get(l.target);
      if (!s || !t) return;
      svg += `<line class="glink" data-s="${l.source}" data-t="${l.target}"
        x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}" stroke-width="${Math.max(0.6, l.weight * 14)}"/>`;
    });

    /* хабы */
    hubPos.forEach(h => {
      const r = 5 + Math.min(9, Math.sqrt(h.count) * 1.4);
      svg += `<g class="gnode" data-id="${h.id}">
        <circle cx="${h.x}" cy="${h.y}" r="${r}" fill="var(--accent-2)" opacity=".9"/>
        <text x="${h.x}" y="${h.y - r - 5}" text-anchor="middle">${esc(h.label)}</text></g>`;
    });

    /* объекты */
    objNodes.forEach(o => {
      const vals = Object.values(o.risk || {});
      const risk = vals.length ? Math.max(0, ...vals.map(v => +v || 0)) : 0;
      const r = 6 + Math.min(10, Math.sqrt((o.hubs || []).length) * 2.5);
      svg += `<g class="gnode" data-id="${o.id}">
        <circle cx="${o.x}" cy="${o.y}" r="${r}" fill="${riskHex(risk)}"
          stroke="var(--border-strong)" stroke-width="1.2"/>
        <text x="${o.x}" y="${o.y + r + 12}" text-anchor="middle">${esc((o.name || "").slice(0, 22))}</text></g>`;
    });
    svg += `</svg>`;

    const box = el(`<div class="ghost">${svg}</div>`);
    main.appendChild(box);

    /* подсветка соседей при наведении */
    box.querySelectorAll(".gnode").forEach(g => {
      g.addEventListener("mouseenter", () => {
        const id = g.dataset.id;
        box.querySelectorAll(".glink").forEach(l => {
          const on = l.dataset.s === id || l.dataset.t === id;
          l.classList.toggle("hl", on);
        });
        g.classList.add("hl");
      });
      g.addEventListener("mouseleave", () => {
        box.querySelectorAll(".glink.hl").forEach(l => l.classList.remove("hl"));
        g.classList.remove("hl");
      });
      g.addEventListener("click", () => {
        if (g.dataset.id && !g.dataset.id.startsWith("h_")) {
          Views.forecasts.openObject(g.dataset.id, state);
        }
      });
    });

    main.appendChild(el(`<div class="note">Граф построен из тегов инженерных систем
      (пикеты «p3»): объекты связаны, если их датчики принадлежат одному пикету. Ссылка
      топологическая (кто с кем делит участок коллектора), географических координат в данных нет.</div>`));
  }

  return { render, name: "Граф систем", icon: "⬡" };
})();
