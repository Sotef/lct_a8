/* charts2.js — gauge риска, кривая F(t) */
Object.assign(Charts, (() => {
  const { el, esc, fmt, fmtPct, riskColor } = UI;
  const { nid, smooth, tip, drawLines } = Charts;

  /* полукольцевой gauge: анимированная дуга + стрелка + число */
  function gauge(value, label = "риск 30 дней", size = 170) {
    const v = Math.max(0, Math.min(1, +value || 0)), c = Math.PI * 70, id = nid("gg");
    const node = el(`<div style="position:relative;width:${size}px;text-align:center">
      <svg viewBox="0 0 170 104" style="width:100%">
        <defs><linearGradient id="${id}" x1="0" x2="1"><stop offset="0" stop-color="var(--ok)"/>
          <stop offset=".5" stop-color="var(--warn)"/><stop offset="1" stop-color="var(--bad)"/></linearGradient></defs>
        <path d="M15 90 A70 70 0 0 1 155 90" fill="none" stroke="var(--bg-2)" stroke-width="13" stroke-linecap="round"/>
        <path class="arc" d="M15 90 A70 70 0 0 1 155 90" fill="none" stroke="url(#${id})" stroke-width="13"
          stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c}"
          style="transition:stroke-dashoffset 1.4s cubic-bezier(.16,1,.3,1)"/>
        <g class="needle" style="transform-origin:85px 90px;transform:rotate(-90deg);transition:transform 1.4s cubic-bezier(.34,1.56,.64,1)">
          <line x1="85" y1="90" x2="85" y2="32" stroke="var(--text)" stroke-width="2.4" stroke-linecap="round"/>
          <circle cx="85" cy="90" r="5" fill="var(--text)"/></g>
      </svg>
      <div style="margin-top:-12px"><div class="gv num" style="font-size:30px;font-weight:800;color:${riskColor(v)}">0%</div>
      <div class="faint" style="font-size:10.5px;text-transform:uppercase;letter-spacing:.1em">${esc(label)}</div></div></div>`);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      node.querySelector(".arc").style.strokeDashoffset = c * (1 - v);
      node.querySelector(".needle").style.transform = `rotate(${-90 + v * 180}deg)`;
      UI.countUp(node.querySelector(".gv"), v * 100, { d: 0, ms: 1400, suffix: "%" });
    }));
    return node;
  }

  /* кривая вероятности события F(t) = 1 − S(t) по горизонтам */
  function survival(surv, labels, w = 620, h = 190) {
    const host = el(`<div class="card"><div class="ct">${UI.ic("activity", "s")} Вероятность события по горизонту
      <span class="grow"></span><span class="faint" style="text-transform:none;letter-spacing:0;font-weight:500">P(событие ≤ t) = 1 − S(t)</span></div></div>`);
    if (!surv || !surv.length) { host.appendChild(el(UI.emptyState("нет кривой выживаемости", "info"))); return host; }
    const F = surv.map(s => 1 - Math.max(0, Math.min(1, s)));
    const L = 34, R = 14, T = 16, B = 28, n = F.length;
    const X = i => L + i * (w - L - R) / Math.max(n - 1, 1), Y = v => T + (1 - v) * (h - T - B);
    const pts = F.map((v, i) => [X(i), Y(v)]), id = nid("sv");
    let g = "";
    [0, .25, .5, .75, 1].forEach(v => g += `<line x1="${L}" x2="${w - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--border)" stroke-dasharray="2 4"/>
      <text x="${L - 6}" y="${Y(v) + 3}" font-size="9" fill="var(--text-faint)" text-anchor="end">${v * 100}%</text>`);
    const dots = pts.map((p, i) => `<g class="svp" data-i="${i}" style="cursor:pointer">
      <circle cx="${p[0]}" cy="${p[1]}" r="12" fill="transparent"/>
      <circle cx="${p[0]}" cy="${p[1]}" r="4.5" fill="var(--panel-solid)" stroke="${riskColor(F[i])}" stroke-width="2.4"
        style="animation:pop .5s ${0.6 + i * 0.08}s both cubic-bezier(.34,1.56,.64,1);transform-box:fill-box;transform-origin:center"/>
      <text x="${p[0]}" y="${h - 8}" font-size="10" fill="var(--text-faint)" text-anchor="middle">${esc(labels[i] || "")}</text></g>`).join("");
    const svg = el(`<svg viewBox="0 0 ${w} ${h}" style="width:100%;overflow:visible">
      <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--bad)" stop-opacity=".35"/>
        <stop offset="1" stop-color="var(--accent-2)" stop-opacity="0"/></linearGradient></defs>${g}
      <path d="${smooth(pts)} L${pts[n - 1][0]} ${h - B} L${pts[0][0]} ${h - B} Z" fill="url(#${id})" style="animation:fadeIn 1.2s both"/>
      <path class="drawline" d="${smooth(pts)}" fill="none" stroke="var(--accent-2)" stroke-width="2.4"/>${dots}</svg>`);
    host.appendChild(svg);
    svg.querySelectorAll(".svp").forEach(gp => {
      gp.addEventListener("mouseenter", () => {
        const i = +gp.dataset.i, r = svg.getBoundingClientRect();
        tip(`<div class="faint">горизонт ${esc(labels[i])}</div><div>P(событие) <b>${fmtPct(F[i], 1)}</b></div>
          <div class="faint">S(t) = ${fmt(surv[i], 3)}</div>`, r.left + pts[i][0] * r.width / w, r.top + pts[i][1] * r.height / h);
      });
      gp.addEventListener("mouseleave", () => tip(null));
    });
    drawLines(svg);
    return host;
  }
  return { gauge, survival };
})());
