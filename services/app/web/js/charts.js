/* charts.js — лёгкие SVG-графики без зависимостей */
window.Charts = (() => {
  const { el, esc, fmt } = UI;

  function _path(pts) {
    return pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  }
  function _scale(vals, w, h, pad = 4) {
    const mn = Math.min(...vals), mx = Math.max(...vals);
    const rng = (mx - mn) || 1;
    return vals.map((v, i) => [
      pad + i * (w - 2 * pad) / Math.max(vals.length - 1, 1),
      h - pad - ((v - mn) / rng) * (h - 2 * pad),
    ]);
  }

  /* Спарклайн: одна линия + заполнение */
  function spark(vals, w = 120, h = 34, color = "var(--accent-2)") {
    if (!vals || vals.length < 2) return el(`<div class="muted" style="padding:8px">—</div>`);
    const pts = _scale(vals, w, h);
    const line = _path(pts);
    const area = line + ` L ${pts[pts.length - 1][0]} ${h} L ${pts[0][0]} ${h} Z`;
    return el(`<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">
      <path d="${area}" fill="${color}" opacity=".14"/>
      <path d="${line}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round"/>
      <circle cx="${pts[pts.length - 1][0]}" cy="${pts[pts.length - 1][1]}" r="2.6" fill="${color}"/>
    </svg>`);
  }

  /* Тренд по бакетам: честная шкала 0..max, сетка, тултипы, маркер «сейчас» */
  function trend(rows, w = 640, h = 190) {
    const host = el(`<div class="card"><div class="ct">Тренд риска по бакетам
      <span class="muted" style="font-weight:400;font-size:11px">· средний и максимальный risk30 всех каналов задачи на каждый 6ч-бакет</span></div></div>`);
    if (!rows || rows.length < 2) {
      host.appendChild(el(`<div class="empty">история накапливается: сервис живёт в режиме реплея
        с 01.01.2026 — по мере тиков сим-времени здесь растёт кривая риска</div>`));
      return host;
    }
    const avg = rows.map(r => r.avg_risk), mx = rows.map(r => r.max_risk);
    const vmax = Math.max(0.05, ...mx) * 1.08;         /* честная шкала от нуля */
    const pad = 10, pw = w - 34;
    const X = i => 30 + i * (pw - 6) / Math.max(rows.length - 1, 1);
    const Y = v => h - pad - (Math.min(v, vmax) / vmax) * (h - 2 * pad);
    const pa = avg.map((v, i) => [X(i), Y(v)]), pm = mx.map((v, i) => [X(i), Y(v)]);
    const area = _path(pa) + ` L ${pa[pa.length - 1][0]} ${h - pad} L ${pa[0][0]} ${h - pad} Z`;

    let grid = "";
    for (let g = 0; g <= 4; g++) {
      const v = vmax * g / 4, y = Y(v);
      grid += `<line x1="30" y1="${y}" x2="${30 + pw - 6}" y2="${y}" stroke="var(--border)" stroke-width="1" opacity=".5"/>
        <text x="26" y="${y + 3}" fill="var(--text-faint)" font-size="9" text-anchor="end">${fmt(v, 2)}</text>`;
    }
    let tips = "";
    rows.forEach((r, i) => {
      tips += `<circle cx="${X(i)}" cy="${Y(avg[i])}" r="9" fill="transparent">
        <title>${esc(r.bucket_ts.slice(0, 16).replace("T", " "))} · ср. ${fmt(r.avg_risk, 3)} · макс ${fmt(r.max_risk, 3)} · каналов ${r.n}</title></circle>`;
    });
    const step = Math.max(1, Math.ceil(rows.length / 6));
    let xl = "";
    rows.forEach((r, i) => {
      if (i % step === 0 || i === rows.length - 1)
        xl += `<text x="${X(i)}" y="${h + 14}" fill="var(--text-faint)" font-size="9.5" text-anchor="middle">${esc(r.bucket_ts.slice(5, 10))}</text>`;
    });
    const last = pa[pa.length - 1];
    const svg = `<svg viewBox="0 0 ${w} ${h + 20}" style="width:100%">
      <defs><linearGradient id="tg" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="var(--accent)"/><stop offset="1" stop-color="var(--accent-2)"/>
      </linearGradient></defs>
      ${grid}
      <path d="${area}" fill="url(#tg)" opacity=".16"/>
      <path d="${_path(pm)}" fill="none" stroke="var(--bad)" stroke-width="1.2" opacity=".7" stroke-dasharray="3 3"/>
      <path class="drawline" style="--len:4000" d="${_path(pa)}" fill="none" stroke="url(#tg)" stroke-width="2.4" stroke-linejoin="round"/>
      <circle cx="${last[0]}" cy="${last[1]}" r="4" fill="var(--accent-2)"><title>сейчас: ${esc(rows[rows.length - 1].bucket_ts.slice(0, 16).replace("T", " "))}</title></circle>
      <text x="${Math.min(last[0] + 6, w - 46)}" y="${last[1] - 8}" fill="var(--text-dim)" font-size="9.5">сейчас</text>
      ${xl}${tips}</svg>`;
    host.appendChild(el(svg));
    host.appendChild(el(`<div class="glegend">
      <span><i style="background:var(--accent-2)"></i>средний risk30</span>
      <span><i style="background:var(--bad)"></i>максимум по каналам</span>
      <span class="muted">шкала 0–${fmt(vmax, 2)} · наведите на точку для деталей</span></div>`));
    return host;
  }

  /* Боксплот ожидания события: распределение времени до события из S(t). */
  function boxplotTime(surv, labels, w = 560, h = 100) {
    const host = el(`<div class="card"><div class="ct">Когда ожидать событие
      <span class="muted" style="font-weight:400;font-size:11px">· распределение времени до события из кривой S(t)</span></div></div>`);
    const DAY = { "6ч": 0.25, "12ч": 0.5, "24ч": 1, "48ч": 2, "3д": 3, "7д": 7,
                  "14д": 14, "21д": 21, "30д": 30 };
    if (!surv || surv.length < 2) {
      host.appendChild(el(`<div class="empty">нет кривой выживаемости</div>`));
      return host;
    }
    const days = labels.map(l => DAY[l] !== undefined ? DAY[l] : 1);
    const F = surv.map(s => 1 - Math.max(0, Math.min(1, s)));   /* P(событие ≤ t_i) */
    const q = (p) => {
      if (p <= F[0]) return days[0] * p / Math.max(F[0], 1e-9);
      for (let i = 1; i < F.length; i++) {
        if (p <= F[i]) {
          const f0 = Math.max(F[i - 1], 1e-9), span = Math.max(F[i] - f0, 1e-9);
          return days[i - 1] + (days[i] - days[i - 1]) * (p - f0) / span;
        }
      }
      return null;  /* медиана за пределами горизонта */
    };
    const q10 = q(0.10), q25 = q(0.25), med = q(0.50), q75 = q(0.75), q90 = q(0.90);
    const p30 = F[F.length - 1];
    if (med === null) {
      host.appendChild(el(`<div class="empty">медиана за пределами 30 дней:
        P(событие ≤ 30д) = ${fmt(p30, 2)} — событие на горизонте месяца маловероятно</div>`));
      return host;
    }
    const xmax = 30, pw = w - 90, y0 = 30, bh = 16;
    const X = d => 62 + (Math.min(d, xmax) / xmax) * pw;
    let s = `<svg viewBox="0 0 ${w} ${h}" style="width:100%">`;
    for (let d = 0; d <= 30; d += 5) {
      s += `<line x1="${X(d)}" y1="${y0 - 8}" x2="${X(d)}" y2="${y0 + bh + 8}" stroke="var(--border)" opacity=".5"/>
        <text x="${X(d)}" y="${y0 + bh + 20}" fill="var(--text-faint)" font-size="9" text-anchor="middle">${d}д</text>`;
    }
    const w0 = q10 !== null ? X(q10) : X(0), w1 = q90 !== null ? X(q90) : X(xmax);
    s += `<line class="bxq" x1="${w0}" y1="${y0 + bh / 2}" x2="${w1}" y2="${y0 + bh / 2}"/>`;
    if (q10 !== null) s += `<line class="bxq" x1="${w0}" y1="${y0 + 2}" x2="${w0}" y2="${y0 + bh - 2}"/>`;
    if (q90 !== null) s += `<line class="bxq" x1="${w1}" y1="${y0 + 2}" x2="${w1}" y2="${y0 + bh - 2}"/>`;
    s += `<rect x="${X(q25)}" y="${y0}" width="${Math.max(2, X(q75) - X(q25))}" height="${bh}" rx="4"
        fill="var(--accent-2)" opacity=".28" stroke="var(--accent-2)"/>
      <line x1="${X(med)}" y1="${y0 - 3}" x2="${X(med)}" y2="${y0 + bh + 3}" stroke="var(--accent)" stroke-width="2.4"/>
      <text x="${X(med)}" y="${y0 - 10}" fill="var(--text)" font-size="10.5" text-anchor="middle" font-weight="700">медиана ${fmt(med, 1)} дн</text>
      <text x="${X(q25)}" y="${y0 + bh + 20}" fill="var(--text-faint)" font-size="8.5" text-anchor="middle">q25 ${q25 !== null ? fmt(q25, 1) : "—"}</text>
      <text x="${X(q75)}" y="${y0 + bh + 20}" fill="var(--text-faint)" font-size="8.5" text-anchor="middle">q75 ${q75 !== null ? fmt(q75, 1) : "—"}</text>
      </svg>`;
    host.appendChild(el(s));
    host.appendChild(el(`<div class="note">P(событие ≤ 30д) = ${fmt(p30, 2)} · бокс — q25–q75,
      усы — 10–90%; к медиане событие ожидается с вероятностью 50%.</div>`));
    return host;
  }

  /* Кривая выживаемости S(t): точки [6ч..30д] */
  function survival(surv, labels, w = 560, h = 170) {
    const host = el(`<div class="card"><div class="ct">Вероятность БЕЗ события по горизонту S(t)</div></div>`);
    if (!surv || !surv.length) return host;
    const pts = _scale(surv, w, h, 12);
    const area = _path(pts) + ` L ${pts[pts.length - 1][0]} ${h} L ${pts[0][0]} ${h} Z`;
    let grid = "";
    pts.forEach((p, i) => {
      grid += `<circle cx="${p[0]}" cy="${p[1]}" r="3" fill="var(--accent-2)"/>
        <text x="${p[0]}" y="${h + 16}" font-size="9.5" fill="var(--text-faint)" text-anchor="middle">${esc(labels[i] || "")}</text>
        <text x="${p[0]}" y="${p[1] - 8}" font-size="9" fill="var(--text-dim)" text-anchor="middle">${fmt(surv[i], 2)}</text>`;
    });
    host.appendChild(el(`<svg viewBox="0 0 ${w} ${h + 22}" style="width:100%">
      <path d="${area}" fill="var(--accent-2)" opacity=".1"/>
      <path d="${_path(pts)}" fill="none" stroke="var(--accent-2)" stroke-width="2.2"/>
      ${grid}</svg>`));
    return host;
  }

  /* SHAP-факторы: горизонтальные бары */
  function factors(list, topn = 8) {
    const host = el(`<div><div class="ct" style="margin-bottom:8px">Почему модель так решила (SHAP)</div></div>`);
    if (!list || !list.length) {
      host.appendChild(el(`<div class="empty">факторы не сохранены для этого прогноза</div>`));
      return host;
    }
    const mx = Math.max(...list.slice(0, topn).map(f => Math.abs(f.shap || 0))) || 1;
    list.slice(0, topn).forEach(f => {
      const s = f.shap || 0, neg = s < 0;
      const row = el(`<div class="fbar">
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(f.feature)}</span>
        <span style="color:${neg ? "var(--warn)" : "var(--accent-2)"}">${s > 0 ? "+" : ""}${fmt(s, 3)}</span>
        <div class="b"><i style="width:${Math.abs(s) / mx * 100}%;${neg ? "background:var(--warn)" : ""}"></i></div>
      </div>`);
      host.appendChild(row);
    });
    host.appendChild(el(`<div class="note">вклад признака в вероятность на текущем шаге; положительный — повышает риск, отрицательный — понижает</div>`));
    return host;
  }

  return { spark, trend, survival, factors, boxplotTime };
})();
