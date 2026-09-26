/* ui.js — DOM-хелперы, темы, тосты, drawer-каркас */
window.UI = (() => {
  const THEMES = ["obsidian", "editorial", "terminal"];
  const THEME_NAMES = { obsidian: "Obsidian", editorial: "Editorial", terminal: "Terminal" };

  function theme() { return document.body.dataset.theme || localStorage.getItem("mc_theme") || "obsidian"; }
  function setTheme(t) {
    if (!THEMES.includes(t)) t = "obsidian";
    document.body.dataset.theme = t;
    localStorage.setItem("mc_theme", t);
    document.querySelectorAll(".themeswitch button, .tprev button")
      .forEach(b => b.classList.toggle("on", b.dataset.t === t));
    if (window.__map && window.__map.refreshStyle) window.__map.refreshStyle();
  }

  const el = (html) => {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  };
  const esc = (s) => String((s === undefined || s === null) ? "" : s).replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (v, d = 3) => (v === null || v === undefined || isNaN(v)) ? "—" :
    (+v).toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmtPct = (v, d = 1) => (v === null || v === undefined || isNaN(v)) ? "—" :
    `${fmt(v * 100, d)}%`;
  const dt = (iso) => iso ? new Date(iso).toLocaleString("ru-RU",
    { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";

  function riskLevel(p) {
    const r = (p.risk30_cal !== null && p.risk30_cal !== undefined) ? p.risk30_cal : p.risk30;
    if (r === null || r === undefined) return { cls: "low", text: "—" };
    if (r >= 0.5) return { cls: "high", text: "высокий" };
    if (r >= 0.2) return { cls: "mid", text: "средний" };
    return { cls: "low", text: "низкий" };
  }
  const riskColor = (r) => r >= 0.5 ? "var(--bad)" : r >= 0.2 ? "var(--warn)" : "var(--ok)";
  const riskHex = (r) => r >= 0.5 ? "#f87171" : r >= 0.2 ? "#fbbf24" : "#34d399";

  function toast(msg, ms = 2600) {
    document.querySelectorAll(".toast").forEach(t => t.remove());
    const t = el(`<div class="toast">${esc(msg)}</div>`);
    document.body.appendChild(t);
    setTimeout(() => t.remove(), ms);
  }

  /* --- live-обновления: один активный поллинг на вьюху --- */
  let __liveTimer = null;
  function live(fn, ms = 20000) {
    liveStop();
    __liveTimer = setInterval(() => { try { fn(); } catch (e) {} }, ms);
  }
  function liveStop() { if (__liveTimer) { clearInterval(__liveTimer); __liveTimer = null; } }

  /* Темы: превью-градиенты для карточек выбора */
  const THEME_SWATCH = {
    obsidian: "linear-gradient(135deg,#0a0b10 30%,#8b5cf6 70%,#22d3ee 100%)",
    editorial: "linear-gradient(135deg,#faf8f4 40%,#e3ddd1 60%,#b91c1c 100%)",
    terminal: "linear-gradient(135deg,#050807 45%,#0d9d63 80%,#16ff8a 100%)",
  };

  /* авто-применение сохранённой темы при загрузке страницы */
  setTheme(theme());

  return { THEMES, THEME_NAMES, THEME_SWATCH, theme, setTheme, el, esc, fmt, fmtPct, dt,
           riskLevel, riskColor, riskHex, toast, live, liveStop };
})();
