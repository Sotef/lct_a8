/* app.js — логин, оболочка, роутер */
(() => {
  const { el, esc, THEMES, THEME_NAMES, THEME_SWATCH, theme, setTheme } = UI;

  /* ---------- экран входа ---------- */
  function loginScreen() {
    document.getElementById("app").innerHTML = "";
    const cur = theme();
    const wrap = el(`<div class="login-wrap"><div class="login">
      <div class="lg">Москоллектор<span>Предиктивная аналитика ОДС · СМВУ</span></div>
      <div class="ct" style="font-size:11px;font-weight:800;color:var(--text-dim);
        text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px">Оформление</div>
      <div class="tprev"></div>
      <div class="fld"><label>Логин</label><input id="lu" autocomplete="username"></div>
      <div class="fld"><label>Пароль</label><input id="lp" type="password" autocomplete="current-password"></div>
      <button class="btn full" id="lb">Войти</button>
      <div class="err" id="le"></div>
      <div class="demo">Демо-доступы:
        <div class="drow">
          <button data-u="central.operator" data-p="central123">central.operator</button>
          <button data-u="dispatcher.alpha" data-p="alpha123">dispatcher.alpha</button>
          <button data-u="dispatcher.beta" data-p="beta123">dispatcher.beta</button>
          <button data-u="tech.alpha" data-p="tech123">tech.alpha</button>
        </div></div>
    </div></div>`);

    const tp = wrap.querySelector(".tprev");
    THEMES.forEach(t => {
      const b = el(`<button data-t="${t}" class="${t === cur ? "on" : ""}">
        <div class="p" style="background:${THEME_SWATCH[t]}"></div>
        <div class="pn">${THEME_NAMES[t]}</div></button>`);
      b.onclick = () => setTheme(t);
      tp.appendChild(b);
    });

    const doLogin = async () => {
      const u = wrap.querySelector("#lu").value.trim();
      const p = wrap.querySelector("#lp").value;
      const err = wrap.querySelector("#le");
      err.textContent = "";
      if (!u || !p) { err.textContent = "введите логин и пароль"; return; }
      const btn = wrap.querySelector("#lb");
      btn.disabled = true; btn.textContent = "вход…";
      try {
        const r = await API.post("/auth/login", { username: u, password: p });
        API.store.token = r.access_token;
        API.store.user = r.user;
        UI.toast("добро пожаловать, " + r.user.username);
        start();
      } catch (e) {
        err.textContent = e.message;
        btn.disabled = false; btn.textContent = "Войти";
      }
    };
    wrap.querySelector("#lb").onclick = doLogin;
    wrap.addEventListener("keydown", e => { if (e.key === "Enter") doLogin(); });
    wrap.querySelectorAll(".demo button").forEach(b => {
      b.onclick = () => {
        wrap.querySelector("#lu").value = b.dataset.u;
        wrap.querySelector("#lp").value = b.dataset.p;
        doLogin();
      };
    });
    document.getElementById("app").appendChild(wrap);
  }

  /* ---------- оболочка + роутер ---------- */
  const VIEWS = ["dashboard", "objects", "graph", "forecasts", "plan"];
  const state = { task: localStorage.getItem("mc_task") || "wear", view: "dashboard",
                  navigate: null, viewObject: null,
                  setTask: (t) => { state.task = t; localStorage.setItem("mc_task", t); } };

  function shell() {
    const u = API.store.user || {};
    const app = document.getElementById("app");
    app.innerHTML = "";
    const root = el(`<div class="shell">
      <aside class="sidebar">
        <div class="logo">Москоллектор<span>предиктивная аналитика ОДС</span></div>
        <div class="navs" style="display:flex;flex-direction:column;gap:4px"></div>
        <div class="spacer"></div>
        <div class="userchip">
          <div class="ava">${esc((u.username || "?")[0].toUpperCase())}</div>
          <div><div class="nm">${esc(u.username || "—")}</div>
          <div class="rl">${esc(API.ROLE_RU[u.role] || u.role || "")}</div></div>
          <button id="lo" title="выйти">⎋</button>
        </div>
      </aside>
      <section class="main" id="main">
        <div id="page"></div>
      </section>
    </div>`);
    app.appendChild(root);

    /* навигация (tech: дашборд, объекты и план ТО своего района; users — только central) */
    const navs = root.querySelector(".navs");
    let items = u.role === "tech" ? ["dashboard", "objects", "plan"] : VIEWS;
    if (u.role === "central") items = [...items, "users"];
    items.forEach(v => {
      const V = Views[v];
      const b = el(`<button class="nav-item" data-v="${v}">${V.icon} ${esc(V.name)}</button>`);
      b.onclick = () => navigate(v);
      navs.appendChild(b);
    });
    root.querySelector("#lo").onclick = () => {
      API.store.token = ""; API.store.user = null; location.reload();
    };

    /* верхняя панель: задачи + сим-часы + переключатель дизайна */
    const topbar = el(`<div class="topbar" style="margin-bottom:0">
      <div class="chips" id="tasks"></div><div class="grow"></div>
      <div class="sub clockchip" id="clockchip" title="Симулируемое время сервиса (реплей данных 2026)"></div>
      <div class="sub">модель v0-2026-09-20</div>
      <div class="themeswitch" title="Выбор дизайна"></div></div>`);
    const tasks = topbar.querySelector("#tasks");
    API.TASKS.forEach(t => {
      const m = API.TASK_META[t];
      const c = el(`<button class="chip ${t === state.task ? "on" : ""}" data-t="${t}">${m.icon} ${esc(m.label)}</button>`);
      c.onclick = () => {
        state.setTask(t);
        tasks.querySelectorAll(".chip").forEach(x => x.classList.toggle("on", x.dataset.t === t));
        const box = document.getElementById("pagebox");
        if (box) Views[state.view].render(box, state).catch(e => UI.toast(e.message));
      };
      tasks.appendChild(c);
    });
    const ts = topbar.querySelector(".themeswitch");
    THEMES.forEach(t => {
      const b = el(`<button data-t="${t}" class="${t === theme() ? "on" : ""}" title="${THEME_NAMES[t]}"><i></i></button>`);
      b.onclick = () => setTheme(t);
      ts.appendChild(b);
    });
    const page = root.querySelector("#page");
    page.appendChild(topbar);
    const box = el(`<div id="pagebox"></div>`);
    page.appendChild(box);
    state.navigate = (v) => navigate(v);

    /* сим-часы: поллинг /meta/clock; новый бакет -> перерисовать активную вьюху */
    let lastBucket = null;
    const chip = topbar.querySelector("#clockchip");
    const pollClock = async () => {
      let c;
      try { c = await API.get("/meta/clock"); } catch (e) { return; }
      if (!c.sim_now) return;
      chip.innerHTML = `<span class="live-dot"></span>⏱ ${esc(c.sim_now.slice(0, 16).replace("T", " "))}` +
        (c.computing ? " · расчёт…" : "");
      if (lastBucket !== null && c.bucket !== lastBucket) {
        chip.classList.remove("pulse-ok"); void chip.offsetWidth; chip.classList.add("pulse-ok");
        const LIVE = ["dashboard", "forecasts", "plan", "objects"];
        if (LIVE.includes(state.view)) {
          const b = document.getElementById("pagebox");
          if (b && Views[state.view]) Views[state.view].render(b, state).catch(() => {});
        }
      }
      lastBucket = c.bucket;
    };
    pollClock();
    setInterval(pollClock, 10000);
    return box;
  }

  function navigate(v) {
    state.view = v;
    UI.liveStop();
    document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("on", b.dataset.v === v));
    const box = document.getElementById("pagebox");
    if (!box) { start(); return; }
    Views.objects.destroy();
    Views.forecasts.closeDrawer && Views.forecasts.closeDrawer();
    box.innerHTML = "";
    Views[v].render(box, state).catch(e => {
      box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    });
  }

  function start() {
    if (!API.store.token || !API.store.user) { loginScreen(); return; }
    shell();
    navigate("dashboard");
  }

  document.addEventListener("DOMContentLoaded", start);
})();
