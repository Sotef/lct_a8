/* ui.js — DOM-хелперы, форматирование, темы, тосты, счётчики */
window.UI = (() => {
  const THEMES = ["obsidian", "editorial", "terminal"];
  const THEME_NAMES = { obsidian: "Obsidian", editorial: "Editorial", terminal: "Terminal" };
  const THEME_SWATCH = {
    obsidian: "linear-gradient(135deg,#07080d 30%,#8b5cf6 70%,#22d3ee 100%)",
    editorial: "linear-gradient(135deg,#faf8f4 40%,#e3ddd1 60%,#b91c1c 100%)",
    terminal: "linear-gradient(135deg,#050807 45%,#0d9d63 80%,#16ff8a 100%)",
  };
  const ic = (n, c) => Icons.svg(n, c);
  const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  const esc = (s) => String((s === undefined || s === null) ? "" : s).replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const isNum = v => v !== null && v !== undefined && v !== "" && !isNaN(v);
  const fmt = (v, d = 3) => !isNum(v) ? "—" :
    (+v).toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmtPct = (v, d = 0) => !isNum(v) ? "—" : `${fmt(v * 100, d)}%`;
  const fmtInt = v => !isNum(v) ? "—" : Math.round(+v).toLocaleString("ru-RU");
  const dt = (iso) => iso ? new Date(iso).toLocaleString("ru-RU",
    { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
  const dtFull = (iso) => iso ? new Date(iso).toLocaleString("ru-RU") : "—";
  function ago(iso) {
    if (!iso) return "—";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 45) return "только что";
    if (s < 3600) return Math.round(s / 60) + " мин назад";
    if (s < 86400) return Math.round(s / 3600) + " ч назад";
    return Math.round(s / 86400) + " дн назад";
  }
  const riskOf = p => !p ? null : isNum(p.risk30_cal) ? p.risk30_cal : isNum(p.risk_used) ? p.risk_used : p.risk30;
  function riskLevel(pOrR) {
    const r = typeof pOrR === "number" ? pOrR : riskOf(pOrR);
    if (!isNum(r)) return { cls: "low", text: "—" };
    if (r >= 0.5) return { cls: "high", text: "высокий" };
    if (r >= 0.2) return { cls: "mid", text: "средний" };
    return { cls: "low", text: "низкий" };
  }
  const riskColor = r => r >= 0.5 ? "var(--bad)" : r >= 0.2 ? "var(--warn)" : "var(--ok)";
  const riskHex = r => r >= 0.5 ? "#f87171" : r >= 0.2 ? "#fbbf24" : "#34d399";
  const css = name => getComputedStyle(document.body).getPropertyValue(name).trim();

  /* --- темы: смена с круговым reveal через View Transitions --- */
  function theme() { return document.body.dataset.theme || localStorage.getItem("mc_theme") || "obsidian"; }
  function applyTheme(t) {
    document.body.dataset.theme = t;
    localStorage.setItem("mc_theme", t);
    document.querySelectorAll(".themeswitch button, .tprev button")
      .forEach(b => b.classList.toggle("on", b.dataset.t === t));
    window.dispatchEvent(new CustomEvent("themechange", { detail: t }));
  }
  function setTheme(t, ev) {
    if (!THEMES.includes(t)) t = "obsidian";
    if (t === theme()) return;
    if (!document.startViewTransition || matchMedia("(prefers-reduced-motion: reduce)").matches) { applyTheme(t); return; }
    const x = ev ? ev.clientX : innerWidth / 2, y = ev ? ev.clientY : 0;
    const r = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    const vt = document.startViewTransition(() => applyTheme(t));
    vt.ready.then(() => document.documentElement.animate(
      { clipPath: [`circle(0 at ${x}px ${y}px)`, `circle(${r}px at ${x}px ${y}px)`] },
      { duration: 700, easing: "cubic-bezier(.65,0,.35,1)", pseudoElement: "::view-transition-new(root)" }
    )).catch(() => {});
  }

  /* --- тосты (стек) --- */
  function toast(msg, kind = "info", opts = {}) {
    let host = document.querySelector(".toasts");
    if (!host) { host = el(`<div class="toasts"></div>`); document.body.appendChild(host); }
    const ms = opts.ms || (kind === "err" ? 6000 : 3200);
    const icon = { ok: "check", err: "alert", warn: "alert", info: "info" }[kind] || "info";
    const t = el(`<div class="toast ${kind}"><span class="ti">${ic(icon)}</span>
      <div class="tx">${opts.title ? `<b>${esc(opts.title)}</b>` : ""}${esc(msg)}</div>
      <button aria-label="закрыть">${ic("x", "s")}</button><i class="tl" style="animation-duration:${ms}ms"></i></div>`);
    const close = () => { t.classList.add("out"); setTimeout(() => t.remove(), 350); };
    t.querySelector("button").onclick = close;
    host.appendChild(t);
    while (host.children.length > 5) host.firstElementChild.remove();
    setTimeout(close, ms);
  }

  /* --- анимированный счётчик --- */
  function countUp(node, to, { d = 0, ms = 1100, suffix = "" } = {}) {
    if (!node) return;
    const from = +(node.dataset.v || 0);
    node.dataset.v = isNum(to) ? to : 0;
    if (!isNum(to)) { node.textContent = "—"; return; }
    const t0 = performance.now();
    const step = now => {
      const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 4);
      node.textContent = fmt(from + (to - from) * e, d) + suffix;
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  /* --- «Сформировать заявки»: сначала объясняем, что произойдёт, потом выполняем --- */
  async function autoGenerate(opts = {}) {
    const task = opts.task || null;
    const meta = task ? API.TASK_META[task] : null;
    const s = await API.get("/maintenance/summary").catch(() => null);
    const a = (s && s.auto) || {};
    const minR = a.min_risk !== undefined ? a.min_risk : 0.5;
    const cap = a.top_k || 15;
    const ok = await Overlay.confirm(
      "Сформировать превентивные заявки?",
      `Сервис откроет заявки на обслуживание по каналам, где прогноз риска (30 дней) ≥ ${minR}`
      + `${meta ? `, направление «${meta.label}»` : ", по всем направлениям"}. `
      + `За один запуск — не больше ${cap} каналов. Если по каналу заявка уже открыта, дубль не создаётся: `
      + `задача просто попадает в работу. Дату выезда диспетчер назначает в карточке заявки.`,
      "Сформировать");
    if (!ok) return null;
    try {
      const r = await API.post("/maintenance/auto-generate", { tasks: task ? [task] : null });
      const n = task && r.by_task && r.by_task[task] ? r.by_task[task].created : (r.created || 0);
      toast(n ? `создано заявок: ${n} — смотрите раздел «Заявки»` : "новых заявок нет: каналы уже под контролем",
        n ? "ok" : "info", { title: "Автоформирование заявок", ms: n ? 6000 : 3500 });
      API.invalidate("/maintenance");
      window.dispatchEvent(new CustomEvent("mc:changed"));
      return r;
    } catch (e) { toast(e.message, "err"); return null; }
  }

  /* --- live-поллинг вьюхи (один активный; пауза в фоне) --- */
  let liveTimer = null;
  function live(fn, ms = 20000) {
    liveStop();
    liveTimer = setInterval(() => { if (!document.hidden) { try { fn(); } catch (e) {} } }, ms);
  }
  function liveStop() { if (liveTimer) { clearInterval(liveTimer); liveTimer = null; } }

  /* --- сборка в offscreen-контейнер и мягкий перенос в DOM ---
     Зачем: рендер раздела больше НЕ чистит живой контейнер до сетевых запросов
     (раньше страница «пропадала» на время загрузки), а постановка отличается
     от замены: replaceChildren — атомарная замена (нет пустого кадра),
     merge — обход дерева с обновлением ТОЛЬКО изменившихся узлов (тик, фильтр). */
  const stage = () => document.createDocumentFragment();

  const shapeKey = (n) => {
    if (!n || n.nodeType !== 1) return "t" + (n ? n.nodeType : "?");
    const k = n.getAttribute("data-key");
    return n.nodeName + "|" + (k !== null ? "k:" + k : "c:" + (n.getAttribute("class") || ""));
  };
  const syncAttrs = (a, b) => {
    const ba = b.attributes;
    for (let i = a.attributes.length - 1; i >= 0; i--) {
      const n = a.attributes[i].name;
      if (!b.hasAttribute(n)) a.removeAttribute(n);
    }
    for (let i = 0; i < ba.length; i++) {
      const n = ba[i].name, v = ba[i].value;
      if (a.getAttribute(n) === v) continue;
      if (n === "value" && a === document.activeElement) continue;   // не мешаем вводу
      a.setAttribute(n, v);
    }
  };
  let flashTimer = null;
  const flash = (nodes) => {
    if (!nodes.size || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    nodes.forEach(n => { if (n && n.classList) n.classList.add("lv-flash"); });
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => nodes.forEach(n => {
      if (n && n.classList) n.classList.remove("lv-flash");
    }), 900);
  };
  function morph(a, b, touched) {
    if (a.nodeType === 3 || a.nodeType === 8) {
      if (a.nodeValue !== b.nodeValue) { a.nodeValue = b.nodeValue; touched.add(a.parentNode); }
      return;
    }
    if (shapeKey(a) !== shapeKey(b)) { a.replaceWith(b); return; }
    /* data-keep — узел, которым управляет код карточки/механизм индикаторов
       (график тренда, график обслуживания, лента действий, .seg-ind): не трогаем вообще,
       иначе морфинг сбросит inline-стили (позиция ползунка) и содержимое исчезнет */
    if (a.nodeType === 1 && a.hasAttribute("data-keep")) return;
    if (a.nodeType === 1) syncAttrs(a, b);
    const ac = [...a.childNodes], bc = [...b.childNodes];
    const n = Math.max(ac.length, bc.length);
    for (let i = 0; i < n; i++) {
      const x = ac[i], y = bc[i];
      if (x && y) morph(x, y, touched);
      else if (y) a.appendChild(y);
      else if (x) { if (!(x.nodeType === 1 && x.hasAttribute("data-keep"))) a.removeChild(x); }
    }
  }
  /* mount(host, staged): переносит собранный раздел в живой контейнер.
     merge=true — обновить только изменившиеся узлы (без пересоздания DOM),
     merge=false — атомарная замена детей (без «пустого» кадра). */
  /* индикаторы сегментов/чипов/навигации позиционируются по фактической ширине кнопок,
     поэтому пересчитываем их ПОСЛЕ вставки в DOM (иначе получим width:0) */
  function scheduleSliders(host) {
    requestAnimationFrame(() => {
      if (!window.FX || !FX.refreshSliders) return;
      if (host && !host.isConnected) return;    // ещё не в DOM: роутер вызовет после вставки
      try { FX.refreshSliders(); } catch (e) {}
    });
  }
  function mount(host, stagedN, { merge = false, quiet: q = false } = {}) {
    if (!host || !stagedN) return 0;
    if (q) quiet(host, true);
    const incoming = [...stagedN.childNodes];
    if (!merge || !host.childNodes.length) {
      host.replaceChildren(...incoming);
      scheduleSliders(host);
      return incoming.length;
    }
    const touched = new Set(), hc = [...host.childNodes];
    const n = Math.max(hc.length, incoming.length);
    for (let i = 0; i < n; i++) {
      const x = hc[i], y = incoming[i];
      if (x && y) morph(x, y, touched);
      else if (y) host.appendChild(y);
      else if (x && !(x.nodeType === 1 && x.hasAttribute("data-keep"))) host.removeChild(x);
    }
    /* вспышка только для «листовых» значений (числа/статусы), не для контейнеров */
    [...touched].forEach(p => { if (p && p.children && p.children.length > 1) touched.delete(p); });
    flash(touched);
    scheduleSliders(host);
    return touched.size;
  }

  const skeleton = (rows = 3, h = 120) => el(`<div class="skel-grid">${
    Array.from({ length: rows }, () => `<div class="skel" style="height:${h}px"></div>`).join("")}</div>`);
  /* quiet=true — перерисовка без анимаций появления (live-обновление, смена фильтра) */
  const quiet = (node, on) => { if (node) node.classList.toggle("quiet", !!on); return node; };
  const emptyState = (msg, icon = "info", cls = "") =>
    `<div class="empty ${cls}">${ic(icon)}<div>${esc(msg)}</div></div>`;
  const debounce = (fn, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const stagger = (root, sel = ".rv") => root.querySelectorAll(sel).forEach((n, i) => n.style.setProperty("--i", i));

  applyTheme(theme());
  return { THEMES, THEME_NAMES, THEME_SWATCH, theme, setTheme, el, esc, ic, fmt, fmtPct, fmtInt, dt, dtFull, ago,
    isNum, riskOf, riskLevel, riskColor, riskHex, css, toast, countUp, live, liveStop, skeleton, emptyState,
    debounce, stagger, quiet, stage, mount, autoGenerate };
})();

