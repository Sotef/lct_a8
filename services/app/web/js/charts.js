/* charts.js — SVG-графики без зависимостей: база + интерактивный тренд с crosshair */
window.Charts = (() => {
  const { el, esc, fmt } = UI;
  let uid = 0;
  const nid = p => p + (++uid);
  const path = pts => pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  /* сглаженная кривая (catmull-rom -> bezier) */
  function smooth(pts) {
    if (pts.length < 3) return path(pts);
    let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
      const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
      d += ` C${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
    }
    return d;
  }
  let tipEl = null;
  function tip(html, x, y) {
    if (!tipEl) { tipEl = el(`<div class="ctip"></div>`); document.body.appendChild(tipEl); }
    if (html === null) { tipEl.classList.remove("on"); return; }
    tipEl.innerHTML = html; tipEl.style.left = x + "px"; tipEl.style.top = y + "px"; tipEl.classList.add("on");
  }
  const drawLines = svg => requestAnimationFrame(() => svg.querySelectorAll(".drawline").forEach(p => {
    try { p.style.setProperty("--len", Math.ceil(p.getTotalLength()) + 2); } catch (e) {}
  }));

  function spark(vals, color = "var(--accent-2)", w = 240, h = 46) {
    if (!vals || vals.length < 2) return "";
    const mn = Math.min(...vals), mx = Math.max(...vals), rng = (mx - mn) || 1;
    const pts = vals.map((v, i) => [i * w / (vals.length - 1), h - 4 - ((v - mn) / rng) * (h - 10)]);
    const id = nid("sg");
    return `<svg class="spk" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".5"/>
      <stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
      <path d="${smooth(pts)} L${w} ${h} L0 ${h} Z" fill="url(#${id})"/>
      <path d="${smooth(pts)}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
  }

  function trend(rows, opt = {}) {
    const o = Object.assign({ h: 240, showMax: true, unit: "%" }, opt);
    const w = o.w || 820, h = o.h, showMax = o.showMax;
    /* возвращает САМ график (svg + легенда): заголовок и переключатели рисует карточка-хозяин */
    const host = el(`<div></div>`);
    const body = host;
    if (!rows || rows.length < 2) {
      body.appendChild(el(UI.emptyState("история накапливается: сим-время идёт шагами по 6 ч — кривая растёт в реальном времени", "clock")));
      return host;
    }
    /* линия «средний» рисуется по сглаженному среднему, если оно есть: сырые бакеты
       несопоставимы (в бакете от 16 до 1146 активных каналов) */
    const sm = rows.some(r => r.avg_risk_smooth !== undefined
      && r.avg_risk_smooth !== null && r.avg_risk_smooth !== r.avg_risk);
    const avg = rows.map(r => (r.avg_risk_smooth !== undefined && r.avg_risk_smooth !== null)
      ? r.avg_risk_smooth : (r.avg_risk || 0));
    const mx = rows.map(r => r.max_risk || 0);
    /* шкала по максимуму показываемых линий, «круглыми» делениями и никогда выше 100% */
    const peak = Math.max(0.02, ...(showMax ? mx : avg));
    const NICE = [0.05, 0.1, 0.2, 0.25, 0.5, 1];
    let vstep = 0.05;
    for (const s of NICE) { vstep = s; if (peak / s <= 4.5) break; }
    let vmax = Math.ceil(peak / vstep) * vstep;
    if (vmax < vstep * 2) vmax = vstep * 2;
    vmax = Math.min(1, +vmax.toFixed(4));          // потолок ровно 100%
    const L = 44, R = 12, T = 12, B = 26;
    const X = i => L + i * (w - L - R) / (rows.length - 1);
    const Y = v => T + (1 - Math.min(v, vmax) / vmax) * (h - T - B);
    const pa = avg.map((v, i) => [X(i), Y(v)]), pm = mx.map((v, i) => [X(i), Y(v)]);
    const id = nid("tg");
    let grid = "", xl = "";
    for (let v = 0; v <= vmax + 1e-9; v += vstep) {
      const y = Y(v);
      grid += `<line x1="${L}" y1="${y}" x2="${w - R}" y2="${y}" stroke="var(--border)" stroke-dasharray="2 4"/>
        <text x="${L - 6}" y="${y + 3}" fill="var(--text-faint)" font-size="9.5" text-anchor="end">${fmt(v * 100, 0)}${esc(o.unit)}</text>`;
    }
    const step = Math.max(1, Math.ceil(rows.length / 7));
    rows.forEach((r, i) => {
      if (i % step === 0 || i === rows.length - 1)
        xl += `<text x="${X(i)}" y="${h - 6}" fill="var(--text-faint)" font-size="9.5" text-anchor="middle">${esc(r.bucket_ts.slice(5, 10))}</text>`;
    });
    const last = pa[pa.length - 1];
    const svg = el(`<svg viewBox="0 0 ${w} ${h}" style="width:100%;overflow:visible">
      <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--accent)" stop-opacity=".42"/>
        <stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></linearGradient>
        <linearGradient id="${id}l" x1="0" x2="1"><stop offset="0" stop-color="var(--accent)"/><stop offset="1" stop-color="var(--accent-2)"/></linearGradient></defs>
      ${grid}
      <path d="${smooth(pa)} L${last[0]} ${h - B} L${pa[0][0]} ${h - B} Z" fill="url(#${id})" style="animation:fadeIn 1.4s both"/>
      ${showMax ? `<path class="drawline" d="${smooth(pm)}" fill="none" stroke="var(--bad)" stroke-width="1.3" opacity=".65"/>` : ""}
      <path class="drawline" d="${smooth(pa)}" fill="none" stroke="url(#${id}l)" stroke-width="2.6" stroke-linecap="round"/>
      <circle cx="${last[0]}" cy="${last[1]}" r="8" fill="var(--accent-2)" opacity=".3" class="halo"/>
      <circle cx="${last[0]}" cy="${last[1]}" r="4" fill="var(--accent-2)"/>
      ${xl}
      <g class="xh" style="opacity:0;transition:opacity .15s"><line y1="${T}" y2="${h - B}" stroke="var(--text-faint)" stroke-dasharray="3 3"/>
        <circle r="5" fill="var(--accent-2)" stroke="var(--bg)" stroke-width="2"/><circle r="4" fill="var(--bad)" stroke="var(--bg)" stroke-width="2"/></g>
      <rect x="${L}" y="0" width="${w - L - R}" height="${h}" fill="transparent" class="hit"/></svg>`);
    body.appendChild(svg);
    const xh = svg.querySelector(".xh"), ln = xh.querySelector("line"), cs = xh.querySelectorAll("circle");
    const hit = svg.querySelector(".hit");
    hit.addEventListener("mousemove", e => {
      const r = svg.getBoundingClientRect(), sx = (e.clientX - r.left) * w / r.width;
      const i = Math.max(0, Math.min(rows.length - 1, Math.round((sx - L) / ((w - L - R) / (rows.length - 1)))));
      xh.style.opacity = 1;
      ln.setAttribute("x1", X(i)); ln.setAttribute("x2", X(i));
      cs[0].setAttribute("cx", X(i)); cs[0].setAttribute("cy", Y(avg[i]));
      cs[1].setAttribute("cx", X(i)); cs[1].setAttribute("cy", Y(mx[i]));
      const rr = rows[i];
      const raw = rr.avg_risk_raw !== undefined ? rr.avg_risk_raw : rr.avg_risk;
      tip(`<div class="faint">${esc(rr.bucket_ts.slice(0, 16).replace("T", " "))}</div>
        <div><span class="sw" style="background:var(--accent-2)"></span>средний <b>${fmt(avg[i], 3)}</b>${
          sm && raw !== avg[i] ? ` <span class="faint">(в этом бакете ${fmt(raw, 3)})</span>` : ""}</div>
        <div><span class="sw" style="background:var(--bad)"></span>максимум <b>${fmt(rr.max_risk, 3)}</b></div>
        <div class="faint">каналов в бакете: ${rr.n}${rr.low_n ? " — мало, точка ненадёжна" : ""}</div>`, r.left + X(i) * r.width / w, r.top + Y(avg[i]) * r.height / h);
    });
    hit.addEventListener("mouseleave", () => { xh.style.opacity = 0; tip(null); });
    drawLines(svg);
    body.appendChild(el(`<div class="glegend" style="margin-top:8px">
      <span><i style="background:var(--accent-2)"></i>средний${sm ? " (сглажено)" : " по каналам"}</span>
      ${showMax ? '<span><i style="background:var(--bad)"></i>максимум</span>' : ""}
      <span class="faint">сейчас: ${fmt(avg[avg.length - 1], 3)}${showMax ? ` · макс ${fmt(mx[mx.length - 1], 3)}` : ""}
        · ${rows.length} бакетов · наведите для деталей</span></div>`));
    return host;
  }
  return { nid, path, smooth, tip, drawLines, spark, trend };
})();
