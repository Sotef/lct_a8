/* charts3.js — «когда ожидать событие» (квантили из S(t)) и SHAP-факторы */
Object.assign(Charts, (() => {
  const { el, esc, fmt, fmtPct } = UI;
  const DAY = { "6ч": .25, "12ч": .5, "24ч": 1, "48ч": 2, "3д": 3, "7д": 7, "14д": 14, "21д": 21, "30д": 30 };

  function eta(surv, labels) {
    const host = el(`<div class="card"><div class="ct">${UI.ic("clock", "s")} Когда ожидать событие</div></div>`);
    if (!surv || surv.length < 2) { host.appendChild(el(UI.emptyState("нет кривой выживаемости"))); return host; }
    const days = labels.map(l => DAY[l] !== undefined ? DAY[l] : 1);
    const F = surv.map(s => 1 - Math.max(0, Math.min(1, s)));
    const q = p => {
      if (p <= F[0]) return days[0] * p / Math.max(F[0], 1e-9);
      for (let i = 1; i < F.length; i++) if (p <= F[i]) {
        const f0 = F[i - 1], span = Math.max(F[i] - f0, 1e-9);
        return days[i - 1] + (days[i] - days[i - 1]) * (p - f0) / span;
      }
      return null;
    };
    const [q10, q25, med, q75, q90] = [.1, .25, .5, .75, .9].map(q);
    if (med === null) {
      host.appendChild(el(`<div class="empty">${UI.ic("check")}<div>Медиана за пределами 30 дней:
        P(событие ≤ 30д) = <b>${fmtPct(F[F.length - 1], 1)}</b> — в течение месяца событие маловероятно</div></div>`));
      return host;
    }
    const w = 620, X = d => 40 + (Math.min(d, 30) / 30) * (w - 70);
    let s = `<svg viewBox="0 0 ${w} 96" style="width:100%">`;
    for (let d = 0; d <= 30; d += 5) s += `<line x1="${X(d)}" x2="${X(d)}" y1="26" y2="62" stroke="var(--border)"/>
      <text x="${X(d)}" y="82" font-size="9.5" fill="var(--text-faint)" text-anchor="middle">${d}д</text>`;
    const a = q10 !== null ? X(q10) : X(0), b = q90 !== null ? X(q90) : X(30);
    const bw = Math.max(3, X(q75 === null ? 30 : q75) - X(q25));
    s += `<line x1="${a}" x2="${b}" y1="44" y2="44" stroke="var(--text-faint)" stroke-width="1.5"/>
      <rect x="${X(q25)}" y="34" height="20" rx="6" width="${bw}" fill="var(--accent-2)" opacity=".3" stroke="var(--accent-2)"
        style="transform-box:fill-box;transform-origin:left;animation:growX 1s cubic-bezier(.16,1,.3,1) both"/>
      <line x1="${X(med)}" x2="${X(med)}" y1="28" y2="60" stroke="var(--accent)" stroke-width="3" stroke-linecap="round"/>
      <text x="${X(med)}" y="20" font-size="11" font-weight="700" fill="var(--text)" text-anchor="middle">медиана ≈ ${fmt(med, 1)} дн</text></svg>`;
    host.appendChild(el(s));
    host.appendChild(el(`<div class="note">бокс — квартили q25–q75, усы — 10–90%. С вероятностью 50% событие произойдёт до медианы.</div>`));
    return host;
  }

  function factors(list, topn = 10) {
    const host = el(`<div></div>`);
    if (!list || !list.length || list.every(f => f.shap === null || f.shap === undefined)) {
      host.appendChild(el(UI.emptyState("факторы не сохранены для этого прогноза", "info"))); return host;
    }
    const top = list.slice(0, topn), mx = Math.max(...top.map(f => Math.abs(f.shap || 0))) || 1;
    top.forEach(f => {
      const s = f.shap || 0, neg = s < 0;
      host.appendChild(el(`<div class="fbar"><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(f.feature)}">${esc(f.feature)}</span>
        <span style="color:${neg ? "var(--ok)" : "var(--bad)"}">${s > 0 ? "+" : ""}${fmt(s, 3)}</span>
        <div class="b"><i data-w="${Math.abs(s) / mx * 100}" style="background:${neg ? "var(--ok)" : "linear-gradient(90deg,var(--warn),var(--bad))"}"></i></div></div>`));
    });
    host.appendChild(el(`<div class="note">вклад признака (SHAP) в вероятность на текущем шаге:
      <b style="color:var(--bad)">+</b> повышает риск, <b style="color:var(--ok)">−</b> понижает</div>`));
    FX.bars(host);
    return host;
  }
  /* донат: parts = [{label, value, color}] */
  function donut(parts, size = 150, center = "") {
    const tot = parts.reduce((a, p) => a + (p.value || 0), 0) || 1, r = 52, c = 2 * Math.PI * r;
    let off = 0;
    const arcs = parts.map((p, i) => {
      const len = (p.value || 0) / tot * c;
      const s = `<circle cx="70" cy="70" r="${r}" fill="none" stroke="${p.color}" stroke-width="16"
        stroke-dasharray="0 ${c}" stroke-dashoffset="${-off}" transform="rotate(-90 70 70)" data-len="${len}"
        style="transition:stroke-dasharray 1.1s ${i * 0.12}s cubic-bezier(.16,1,.3,1)"><title>${esc(p.label)}: ${p.value}</title></circle>`;
      off += len; return s;
    }).join("");
    const node = el(`<div style="width:${size}px;position:relative;flex:0 0 ${size}px"><svg viewBox="0 0 140 140" style="width:100%">
      <circle cx="70" cy="70" r="${r}" fill="none" stroke="var(--bg-2)" stroke-width="16"/>${arcs}</svg>
      <div style="position:absolute;inset:0;display:grid;place-items:center;text-align:center">${center}</div></div>`);
    requestAnimationFrame(() => requestAnimationFrame(() => node.querySelectorAll("circle[data-len]")
      .forEach(ci => ci.setAttribute("stroke-dasharray", `${ci.dataset.len} ${c}`))));
    return node;
  }
  return { eta, factors, donut };
})());
