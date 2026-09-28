/* app.js — оболочка сервиса: сайдбар, верхняя панель, сим-часы, роутер, палитра команд */
window.App = (() => {
  const { el, esc, ic, toast, THEMES, THEME_NAMES, theme, setTheme } = UI;

  const VIEWS = [
    { v: "alerts", name: "Алерты", icon: "bell", roles: ["tech", "dispatcher", "central"] },
    { v: "dashboard", name: "Пульт", icon: "dashboard", roles: ["tech", "dispatcher", "central"] },
    { v: "objects", name: "Объекты", icon: "map", roles: ["tech", "dispatcher", "central"] },
    { v: "graph", name: "Граф систем", icon: "graph", roles: ["dispatcher", "central"] },
    { v: "forecasts", name: "Журнал прогнозов", icon: "list", roles: ["tech", "dispatcher", "central"] },
    { v: "plan", name: "План ТО", icon: "calendar", roles: ["tech", "dispatcher", "central"] },
    { v: "tickets", name: "Заявки", icon: "wrench", roles: ["tech", "dispatcher", "central"] },
    { v: "audit", name: "Аудит", icon: "shield", roles: ["dispatcher", "central"] },
    { v: "sys", name: "Система", icon: "server", roles: ["central"] },
    { v: "users", name: "Пользователи", icon: "users", roles: ["central"] },
  ];
  const state = {
    task: localStorage.getItem("mc_task") || "wear",
    view: "dashboard", objFilter: "", clock: null, ticketCount: 0, box: null,
    setTask(t) { this.task = t; localStorage.setItem("mc_task", t); },
    setObjFilter(v) { this.objFilter = v || ""; },
    navigate(v, params) { return navigate(v, params); },
  };
  const curBox = () => state.box || document.getElementById("pagebox");
  let chipsHost = null;

  function shell() {
    const u = API.store.user || {};
    const role = u.role;
    const items = VIEWS.filter(x => x.roles.includes(role));
    const app = document.getElementById("app");
    app.innerHTML = "";
    const root = el(`<div class="shell" id="shell">
      <aside class="sidebar">
        <div class="brand"><span class="mark">${ic("logo")}</span>
          <div class="nm">Москоллектор<span>предиктивная аналитика ОДС</span></div></div>
        <div class="side-sec">рабочие места</div>
        <nav class="navs" id="navs"><i class="nav-ind"></i></nav>
        <div class="spacer"></div>
        <div class="side-sec" style="padding-bottom:2px">сервис</div>
        <button class="nav-item" id="collapse" title="свернуть меню">${ic("sidebar")}<span>Свернуть меню</span></button>
        <div class="userchip">
          <div class="ava">${esc((u.username || "?")[0].toUpperCase())}</div>
          <div class="who"><div class="nm">${esc(u.full_name || u.username || "—")}</div>
            <div class="rl">${esc(API.ROLE_RU[u.role] || u.role || "")}${u.district ? " · " + esc(u.district) : ""}</div></div>
          <button class="icbtn" id="lo" title="выйти" style="width:30px;height:30px;flex:0 0 30px">${ic("logout", "s")}</button>
        </div>
      </aside>
      <main class="main">
        <div class="topbar" id="topbar"></div>
        <div id="pagebox"></div>
      </main>
    </div>`);
    app.appendChild(root);
    const navs = root.querySelector("#navs");
    items.forEach(it => {
      const b = el(`<button class="nav-item" data-v="${it.v}" title="${esc(it.name)}">
        ${ic(it.icon)}<span>${esc(it.name)}</span>
        ${it.v === "tickets" ? '<span class="cnt" id="tkbadge"></span>' : ""}</button>`);
      b.onclick = () => navigate(it.v);
      navs.appendChild(b);
    });

    const top = root.querySelector("#topbar");
    top.appendChild(el(`<button class="icbtn burger" id="burger">${ic("menu")}</button>`));
    chipsHost = el(`<div class="chips" id="chips"><i class="chip-ind"></i></div>`);
    API.TASKS.forEach(t => {
      const m = API.TASK_META[t];
      const c = el(`<button class="chip ${t === state.task ? "on" : ""}" data-t="${t}" title="${esc(m.label)}">
        ${ic(m.icon, "s")} ${esc(m.label)}</button>`);
      c.onclick = () => pickTask(t);
      chipsHost.appendChild(c);
    });
    top.appendChild(chipsHost);
    top.appendChild(el(`<div class="grow"></div>`));
    const sb = el(`<button class="searchbtn" id="search">${ic("search", "s")}<span>Поиск и команды</span><kbd>Ctrl K</kbd></button>`);
    sb.onclick = () => Cmdk.open(cmdItems);
    const bell = el(`<button class="icbtn" id="nbell" title="Уведомления риска">${ic("bell")}<span class="dot" id="nbadge"></span></button>`);
    bell.onclick = () => Notify.toggle();
    const clock = el(`<div class="clockchip" id="clockchip" title="Симулируемое время сервиса (реплей данных 2026)">
      <i class="live-dot"></i><span id="cl">—</span><i class="prog" id="clp" style="width:0%"></i></div>`);
    const tsw = el(`<div class="themeswitch" title="Оформление"></div>`);
    THEMES.forEach(t => {
      const b = el(`<button data-t="${t}" class="${t === theme() ? "on" : ""}" title="${esc(THEME_NAMES[t])}"><i></i></button>`);
      b.onclick = e => setTheme(t, e);
      tsw.appendChild(b);
    });
    top.append(sb, bell, clock, tsw);

    root.querySelector("#collapse").onclick = () => root.classList.toggle("collapsed");
    root.querySelector("#burger").onclick = () => root.classList.toggle("mobile-open");
    root.querySelector("#lo").onclick = async () => {
      const ok = await Overlay.confirm("Выйти из системы?",
        "Сессия будет завершена, действие попадёт в журнал аудита.", "Выйти", "dang");
      if (!ok) return;
      await API.post("/auth/logout").catch(() => {});
      API.store.clear(); location.reload();
    };
    requestAnimationFrame(() => {
      FX.slider(navs, ".nav-ind", ".nav-item.on");
      FX.slider(chipsHost, ".chip-ind", ".chip.on");
    });
    startClock(clock);
    return root;
  }

  function pickTask(t) {
    state.setTask(t);
    if (chipsHost) {
      chipsHost.querySelectorAll(".chip").forEach(x => x.classList.toggle("on", x.dataset.t === t));
      FX.slider(chipsHost, ".chip-ind", ".chip.on");
    }
    if (navBusy) return;                 // раздел сейчас переключается — не мешаем
    /* ползунок направления влияет только на разделы, которые от него зависят:
       иначе не перерисовываем их зря (без мигания на «Аудите», «Пользователях», «Системе») */
    if (!["dashboard", "forecasts", "plan", "tickets", "graph"].includes(state.view)) return;
    const box = curBox();
    if (box && Views[state.view]) Views[state.view].render(box, state, true).catch(e => toast(e.message, "err"));
  }
  /* ---------- сим-часы: поллинг /meta/clock + локальный обратный отсчёт ---------- */
  function startClock(chip) {
    const label = chip.querySelector("#cl"), prog = chip.querySelector("#clp"), dot = chip.querySelector(".live-dot");
    let lastBucket = null, local = 0;
    const paint = () => {
      const c = state.clock;
      if (!c || !c.sim_now) { label.textContent = "нет данных"; dot.className = "live-dot err"; return; }
      label.textContent = c.sim_now.slice(0, 16).replace("T", " ") + (c.paused ? " ⏸" : "")
        + (c.speed && c.speed !== 1 ? ` ${c.speed}×` : "");
      dot.className = "live-dot" + (c.error ? " err" : c.paused ? " busy" : c.computing ? " busy" : "");
      chip.title = `сим-время ${c.sim_now} · бакет ${c.bucket} (пройдено ${Math.round((c.progress || 0) * 100)}%)`
        + ` · данных до ${c.panel_max_ts || "—"}${c.loop ? " · цикл включён" : ""}`
        + (c.paused ? " · ПАУЗА" : "")
        + (c.next_tick_in_sec !== null && c.next_tick_in_sec !== undefined ? ` · следующий тик ~${c.next_tick_in_sec} с` : "");
      const total = c.tick_sec || 75;
      if (!c.paused) local = Math.max(0, local - 1);
      prog.style.width = `${Math.min(100, (1 - local / total) * 100)}%`;
    };
    const poll = async () => {
      const c = await API.get("/meta/clock").catch(() => null);
      if (!c) return;
      const same = c.bucket === lastBucket;
      if (lastBucket !== null && !same) {
        local = c.tick_sec || 75;
        toast(`прогнозы пересчитаны на бакет ${c.sim_now.slice(0, 16).replace("T", " ")}`, "info",
          { title: "Новый тик сим-времени" });
        API.invalidate();
        const box = curBox();
        const LIVE = ["dashboard", "forecasts", "plan", "tickets", "objects", "alerts"];
        if (!navBusy && box && LIVE.includes(state.view) && Views[state.view])
          Views[state.view].render(box, state, true).catch(() => {});
        refreshBadge();
      }
      if (!same && c.next_tick_in_sec) local = c.next_tick_in_sec;
      lastBucket = c.bucket;
      state.clock = c;
      paint();
    };
    poll();
    setInterval(poll, 8000);
    setInterval(paint, 1000);
  }

  async function refreshBadge() {
    const s = await API.get("/maintenance/summary").catch(() => null);
    if (!s) return;
    state.ticketCount = s.open || 0;
    const b = document.getElementById("tkbadge");
    if (b) b.textContent = state.ticketCount > 99 ? "99+" : (state.ticketCount || "");
    if (window.MOBILE && MOBILE.syncNavBadge) MOBILE.syncNavBadge();
  }
  /* ---------- роутер: hash-адреса, View Transitions, каскадное появление ---------- */
  let navSeq = 0;                       // устаревшие навигации отбрасываются после await
  let navBusy = false;                  // идёт переключение раздела (тик/ползунок ждут)

  /* deep-link: #/forecasts?id=123&task=wear (push-уведомления, ярлыки PWA) */
  function parseHash() {
    const h = (location.hash || "").replace(/^#\/?/, "");
    const [v, qs] = h.split("?");
    let p = new URLSearchParams();
    try { p = new URLSearchParams(qs || ""); } catch (e) {}
    return { view: Views[v] ? v : "dashboard", id: p.get("id"), task: p.get("task") };
  }

  async function navigate(v, params) {
    if (!Views[v]) v = "dashboard";
    navBusy = true;
    if (params && params.obj !== undefined) state.setObjFilter(params.obj);
    state.view = v;
    if (params && params.task) { state.setTask(params.task); pickTaskChips(params.task); }
    location.hash = "#/" + v;
    document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("on", b.dataset.v === v));
    const navs = document.getElementById("navs");
    if (navs) FX.slider(navs, ".nav-ind", ".nav-item.on");
    if (window.MOBILE) MOBILE.onView(v);
    if (Views.sys && Views.sys.destroy) Views.sys.destroy();
    Overlay.closeDrawer();
    UI.liveStop();

    /* Рендер идёт в БУДУЩИЙ #pagebox (ещё не в DOM): на экране остаётся предыдущий
       раздел, пока грузятся данные, а затем один атомарный переход. Так обработчики
       разделов привязываются сразу к живому контейнеру (не к временному). */
    const old = document.getElementById("pagebox");
    const seq = ++navSeq;
    if (old) old.classList.add("page-busy");
    else {                              // первый раздел после входа: показать скелетон
      const ph = el(`<div id="pagebox" class="page-enter"></div>`);
      ph.innerHTML = `<div class="skel" style="height:120px;margin-bottom:16px"></div>
        <div class="skel" style="height:340px"></div>`;
      const m = document.querySelector(".main");
      if (m) m.appendChild(ph);
    }
    const box = el(`<div id="pagebox" class="page-enter"></div>`);
    try { await Views[v].render(box, state); }
    catch (e) {
      box.innerHTML = UI.emptyState(e.message || "не удалось загрузить раздел", "alert", "err-state");
    }
    if (old) old.classList.remove("page-busy");
    if (seq === navSeq) navBusy = false;   // этот переход — актуальный, снимаем «занято»
    else return;                           // пришёл ответ от прошлой навигации — не переключаем
    box.dataset.mounted = "1";          // раздел собран полностью: дальше только мягкие обновления
    const swap = () => {
      /* защита от отложенного callback перехода ПРОШЛОЙ навигации: он мог вернуть старый
         контейнер поверх текущего (внешне — «раздел не переключился») */
      if (seq !== navSeq) return;
      document.querySelectorAll("#pagebox").forEach(n => { if (n !== box) n.remove(); });
      if (old && old.isConnected) old.replaceWith(box);
      else {
        const m = document.querySelector(".main");
        if (m) m.appendChild(box);
      }
    };
    if (document.startViewTransition && !FX.reduced) {
      try { document.startViewTransition(swap).ready.catch(() => {}); } catch (e) { /* ignore */ }
    }
    swap();
    state.box = box;                    // внешние триггеры (ползунок задач, часы) обновляют этот контейнер
    /* раздел вставлен: пересчитываем индикаторы ползунков (ширина кнопок известна только в DOM) */
    requestAnimationFrame(() => { try { FX.refreshSliders(); } catch (e) {} });
    if (v === "tickets" || v === "dashboard") refreshBadge();
  }
  function pickTaskChips(t) {
    if (!chipsHost) return;
    chipsHost.querySelectorAll(".chip").forEach(x => x.classList.toggle("on", x.dataset.t === t));
    FX.slider(chipsHost, ".chip-ind", ".chip.on");
  }

  /* ---------- палитра команд ---------- */
  async function cmdItems() {
    const role = API.store.user && API.store.user.role;
    const out = [];
    VIEWS.filter(x => x.roles.includes(role)).forEach(x =>
      out.push({ group: "Разделы", title: x.name, icon: x.icon, run: () => navigate(x.v) }));
    API.TASKS.forEach(t => out.push({ group: "Направления прогноза",
      title: API.TASK_META[t].label, hint: "переключить", icon: API.TASK_META[t].icon,
      run: () => { pickTask(t); } }));
    THEMES.forEach(t => out.push({ group: "Оформление", title: "Тема: " + THEME_NAMES[t],
      icon: "sparkles", run: () => setTheme(t) }));
    /* фон: скорость частиц и выключение */
    BGFX.SPEEDS.forEach(v => out.push({ group: "Фон", title: "Фон: " + BGFX.SPEED_RU[v],
      hint: BGFX.speed === v ? "текущий" : "", icon: "sparkles",
      run: () => { BGFX.setSpeed(v); toast("фон: " + BGFX.SPEED_RU[v], "ok"); } }));
    out.push({ group: "Фон", title: BGFX.pulses ? "Фон: выключить бегущие импульсы" : "Фон: включить бегущие импульсы",
      icon: "sparkles", run: () => {
        BGFX.setPulses(!BGFX.pulses);
        toast(BGFX.pulses ? "импульсы включены" : "импульсы выключены", "ok");
      } });
    out.push({ group: "Действия", title: "Обновить данные раздела", icon: "refresh",
      kw: "refresh reload", run: async () => { API.invalidate(); await navigate(state.view); toast("данные обновлены", "ok"); } });
    out.push({ group: "Действия", title: "Открыть справку по API (Swagger)", icon: "terminal",
      run: () => window.open("/docs", "_blank") });
    if (["dispatcher", "central"].includes(role)) {
      out.push({ group: "Действия", title: "Сформировать заявки по всем направлениям", icon: "wrench",
        hint: "превентивно, дубли не создаются",
        run: async () => {
          const r = await UI.autoGenerate({ task: null });
          if (r) { refreshBadge(); navigate("tickets"); }
        } });
    }
    /* поиск объектов и заявок (живые данные) */
    try {
      const q = (Cmdk._q || "").trim();
      const [tree, tk] = await Promise.all([
        API.get("/objects", 15000).catch(() => ({ tree: [] })),
        API.get("/maintenance/tickets?limit=400", 15000).catch(() => ({ items: [] })),
      ]);
      const objs = (tree.tree || []).filter(o => o.level >= 2);
      objs.forEach(o => out.push({ group: "Объекты", title: o.name || o.object_id, hint: o.district || o.type || "",
        icon: "pin", kw: o.object_id, run: () => Cards.object.open(o.object_id, { state, task: state.task }) }));
      (tk.items || []).slice(0, 200).forEach(t => out.push({ group: "Заявки",
        title: `#${t.id} ${t.object_name || t.object_id}`, hint: `${t.status_ru} · ${t.channel_id}`, icon: "wrench",
        kw: t.channel_id, run: () => navigate("tickets").then(() => Views.tickets.openCard(t.id, state)) }));
    } catch (e) {}
    return out;
  }

  /* ---------- инициализация ---------- */
  function boot() {
    BGFX.start();
    FX.bindGlobal();
    API.on("unauthorized", () => {
      toast("сессия истекла — войдите заново", "warn", { title: "Требуется вход" });
      setTimeout(() => { API.store.clear(); location.reload(); }, 900);
    });
    const finish = () => {
      shell();
      const boot = parseHash();
      navigate(boot.view);
      if (boot.id) setTimeout(() => { try { Cards.forecast.open(+boot.id); } catch (e) {} }, 450);
      refreshBadge();
      Notify.start();
      if (window.MOBILE) MOBILE.enhance(document.getElementById("shell") || document.body,
        { navigate, pickTask, refreshBadge });
      window.addEventListener("mc:changed", () => { refreshBadge(); Notify.poll(); });
      document.addEventListener("keydown", e => {
        if (e.key === "Escape") {
          Cmdk.close(); Notify.close();
          if (window.MOBILE && MOBILE.closeMore) MOBILE.closeMore();
          return;
        }
        if (window.MOBILE && MOBILE.is()) return;     // клавиатурные шорткаты — только десктоп
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
          e.preventDefault(); Cmdk.open(cmdItems); return;
        }
        const tag = (e.target.tagName || "").toLowerCase();
        if (tag === "input" || tag === "textarea" || tag === "select" || e.ctrlKey || e.metaKey || e.altKey) return;
        const idx = ["1", "2", "3", "4"].indexOf(e.key);
        if (idx >= 0) { pickTask(API.TASKS[idx]); return; }
        if (e.key === "[") { const s = document.getElementById("shell"); if (s) s.classList.toggle("collapsed"); }
      });
      const bootEl = document.getElementById("boot");
      if (bootEl) { bootEl.classList.add("done"); setTimeout(() => bootEl.remove(), 700); }
    };
    const hasAuth = API.store.token && API.store.user;
    if (hasAuth) {
      API.get("/auth/me").then(u => { API.store.user = u; finish(); })
        .catch(() => { API.store.clear(); Login.show(finish); });
    } else {
      const boot = document.getElementById("boot");
      if (boot) { boot.classList.add("done"); setTimeout(() => boot.remove(), 700); }
      Login.show(finish);
    }
  }
  document.addEventListener("DOMContentLoaded", boot);
  return { navigate, state, shell, refreshBadge, pickTask, _cmdItems: cmdItems };
})();
