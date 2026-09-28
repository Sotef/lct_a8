/* notify.js — центр уведомлений: высокий недельный риск (P≤7д > порога) с 12ч-тишиной по датчику */
window.Notify = (() => {
  const { el, esc, ic, fmt, riskLevel } = UI;
  const LS = "mc_notify_log";        // {key: ts} — когда последний раз уведомляли по датчику
  const MIN_P7D = 0.2;               // порог недельного риска для уведомления
  const SILENCE_MS = 12 * 3600 * 1000;   // не чаще одного уведомления на датчик в 12 часов
  let items = [], panel = null, unread = 0, log = {};
  try { log = JSON.parse(localStorage.getItem(LS) || "{}") || {}; } catch (e) { log = {}; }
  const save = () => { try { localStorage.setItem(LS, JSON.stringify(log)); } catch (e) {} };
  const keyOf = (t, it) => `${t}|${it["ид_канала_данных"] || it.channel_id}`;

  function push(t, it, silent) {
    const p7 = it.p7d !== undefined && it.p7d !== null ? it.p7d : null;
    const lv = riskLevel(p7 === null ? UI.riskOf(it) : p7);
    const nm = it.object_name || it["название_объекта"] || ("объект " + it.object_id);
    items.unshift({ id: it.id, oid: it.object_id, task: t, title: nm,
      desc: `${API.TASK_META[t].label} · ${it.sensor_type || it["тип_датчика"] || it.channel_id || it["ид_канала_данных"]}`,
      risk: p7, cls: lv.cls, ts: Date.now(), kind: "p7d" });
    if (items.length > 60) items.pop();
    unread++;
    if (!silent) {
      UI.toast(`${nm} · P(≤7 дней) = ${fmt(p7, 2)}`, "warn",
        { title: `Внимание: ${API.TASK_META[t].short}`, ms: 8000 });
      badge();
    }
  }
  function badge() {
    const b = document.getElementById("nbadge");
    if (b) b.textContent = unread > 9 ? "9+" : (unread || "");
  }
  /* опрос: серверный журнал алертов (правило и «тишина» живут на сервере,
     MOBILE_PLAN §4.6). Клиентская отметка времени — вторичная страховка от дублей;
     первый проход только расставляет отметки, чтобы не заваливать пользователя. */
  let first = true, polling = false;
  async function poll() {
    if (polling || document.hidden || !API.store.token) return;
    polling = true;
    try {
      const r = await API.get("/alerts?limit=25").catch(() => ({ items: [] }));
      const now = Date.now();
      let fresh = 0, touched = false;
      (r.items || []).forEach(it => {
        const t = it.task, p7 = it.p7d;
        if (p7 === null || p7 === undefined || p7 < MIN_P7D) return;
        const k = keyOf(t, it);
        const last = log[k] || 0;
        if (now - last < SILENCE_MS) return;         // тишина 12 ч по этому датчику
        log[k] = now; touched = true;
        if (first) return;                            // первый проход — без всплывающих
        if (fresh < 3) { push(t, it); fresh++; }
        else push(t, it, true);
      });
      if (touched || !first) save();
      first = false;
    } catch (e) {} finally { polling = false; }
  }

  function toggle() {
    if (panel) { close(); return; }
    unread = 0; badge();
    panel = el(`<div class="npanel"><div class="nh">${ic("bell")} Уведомления риска
      <span class="grow"></span><button class="icbtn" data-x>${ic("x")}</button></div>
      <div class="nl"></div></div>`);
    const list = panel.querySelector(".nl");
    const draw = () => {
      list.innerHTML = items.length ? items.map(it => `<div class="nitem ${it.cls}" data-id="${it.id}" data-oid="${esc(it.oid || "")}" data-t="${it.task}">
        <span class="ni">${ic(it.cls === "high" ? "alert" : "info")}</span>
        <div style="min-width:0"><div class="nt">${esc(it.title)} · P(≤7д) ${fmt(it.risk, 2)}</div>
          <div class="nd">${esc(it.desc)}</div>
          <div class="faint" style="font-size:10.5px">${UI.ago(new Date(it.ts).toISOString())} · открыть объект</div></div></div>`).join("")
        : UI.emptyState("высокого недельного риска (P≤7д > 0.2) не выявлено", "check");
      list.querySelectorAll(".nitem").forEach(n => n.onclick = () => {
        close();
        /* уведомление ведёт на САМ ОБЪЕКТ: его риски по всем направлениям, датчики, заявки */
        const oid = n.dataset.oid;
        if (oid) Cards.object.open(oid, { state: App.state, task: n.dataset.t });
        else Cards.forecast.open(+n.dataset.id);
      });
    };
    draw();
    panel.querySelector("[data-x]").onclick = close;
    document.body.appendChild(panel);
    const out = e => { if (panel && !panel.contains(e.target) && !e.target.closest("#nbell")) close(); };
    setTimeout(() => document.addEventListener("click", out), 50);
    panel._out = out;
  }
  function close() {
    if (!panel) return;
    document.removeEventListener("click", panel._out);
    panel.remove(); panel = null;
  }
  /* демонстрация уведомлений (приёмка/демо): показать n карточек по актуальным топ-рискам */
  async function demo(n = 2) {
    const res = await Promise.all(API.TASKS.map(t =>
      API.get(`/top-risks?task=${t}&k=25&horizon=30d`).catch(() => ({ items: [] }))));
    let shown = 0;
    res.forEach((r, i) => {
      const t = API.TASKS[i];
      (r.items || []).forEach(it => {
        if (shown >= n) return;
        const p7 = it.p7d !== undefined && it.p7d !== null ? it.p7d : UI.riskOf(it);
        if (p7 === null || p7 < MIN_P7D) return;
        log[keyOf(t, it)] = Date.now();
        push(t, it, true);
        shown++;
      });
    });
    save();
    return shown;
  }
  function start() { first = true; poll(); setInterval(poll, 25000); }
  function clear() { items = []; unread = 0; badge(); }

  return { start, poll, toggle, close, clear, badge, demo, get items() { return items; },
    /* для отладки/тестов: сбросить 12ч-тишину по всем датчикам */
    resetSilence() { log = {}; save(); } };
})();
