/* login.js — экран входа: hero-панель, форма, демо-роли, выбор оформления */
window.Login = (() => {
  const { el, esc, ic, toast, THEMES, THEME_NAMES, THEME_SWATCH, theme, setTheme } = UI;
  const DEMO = [
    { u: "central.operator", p: "central123", r: "центральный диспетчер" },
    { u: "dispatcher.alpha", p: "alpha123", r: "диспетчер" },
    { u: "dispatcher.beta", p: "beta123", r: "диспетчер" },
    { u: "tech.alpha", p: "tech123", r: "техник (свой район)" },
  ];

  function show(onDone) {
    const app = document.getElementById("app");
    const cur = theme();
    const wrap = el(`<div class="login-wrap">
      <section class="login-hero">
        <div class="big">Предиктивная<br>аналитика <span class="gt">ОДС</span></div>
        <div class="lead">Мониторинг СМВУ, журналы ОДС и реестр оборудования превращаются в прогноз риска
          на 30 дней вперёд: отказ датчика, пожарный риск, несанкционированный доступ и износ инфраструктуры.
          Модель предлагает — диспетчер решает.</div>
        <div class="feats">
          <div class="feat">${ic("target")} горизонт до 30 дней, шаг 6 часов</div>
          <div class="feat">${ic("activity")} SHAP-факторы «почему»</div>
          <div class="feat">${ic("wrench")} автоформирование заявок ТО</div>
          <div class="feat">${ic("shield")} RBAC, аудит, request-id</div>
        </div>
        <div class="note" style="max-width:520px;margin-top:26px">${ic("info", "s")}
          Демонстрационный контур: сервис живёт в режиме реплея данных 2026 года — сим-часы
          продвигают «сейчас» на 6 часов, прогнозы и заявки появляются в реальном времени.</div>
      </section>
      <section class="login-side"><form class="login" autocomplete="on">
        <div class="lg"><span class="mark">${ic("logo")}</span>
          <div><b>Москоллектор</b><span>предиктивная аналитика ОДС</span></div></div>
        <div class="faint" style="font-size:10.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px">Оформление</div>
        <div class="tprev"></div>
        <div class="fld"><label>Логин</label><input id="lu" autocomplete="username" placeholder="central.operator"></div>
        <div class="fld" style="position:relative"><label>Пароль</label>
          <input id="lp" type="password" autocomplete="current-password" placeholder="••••••••">
          <button type="button" class="icbtn" id="eye" style="position:absolute;right:6px;top:26px;width:30px;height:30px;
            flex:0 0 30px" title="показать пароль">${ic("eye", "s")}</button></div>
        <button class="btn full" id="lb">${ic("chevron", "s")} Войти в систему</button>
        <div class="err" id="le"></div>
        <div class="demo">Демо-доступы (нажмите, чтобы войти):
          <div class="drow">${DEMO.map(d => `<button type="button" data-u="${d.u}" data-p="${d.p}">
            <b>${esc(d.u)}</b><small>${esc(d.r)}</small></button>`).join("")}</div></div>
      </form></section></div>`);
    app.innerHTML = "";
    app.appendChild(wrap);

    const tp = wrap.querySelector(".tprev");
    THEMES.forEach(t => {
      const b = el(`<button type="button" data-t="${t}" class="${t === cur ? "on" : ""}">
        <div class="p" style="background:${THEME_SWATCH[t]}"></div><div class="pn">${esc(THEME_NAMES[t])}</div></button>`);
      b.onclick = e => setTheme(t, e);
      tp.appendChild(b);
    });
    const lu = wrap.querySelector("#lu"), lp = wrap.querySelector("#lp"), lb = wrap.querySelector("#lb");
    const er = wrap.querySelector("#le"), form = wrap.querySelector("form");
    wrap.querySelector("#eye").onclick = () => {
      lp.type = lp.type === "password" ? "text" : "password";
    };
    async function doLogin() {
      const u = lu.value.trim(), p = lp.value;
      er.textContent = "";
      if (!u || !p) { er.textContent = "введите логин и пароль"; return; }
      lb.classList.add("loading");
      try {
        const r = await API.post("/auth/login", { username: u, password: p });
        API.store.token = r.access_token;
        API.store.refresh = r.refresh_token;
        API.store.user = r.user;
        toast(`добро пожаловать, ${r.user.username}`, "ok", { title: API.ROLE_RU[r.user.role] || r.user.role });
        onDone();
      } catch (e) {
        er.textContent = e.message;
        lb.classList.remove("loading");
        form.classList.remove("shake"); void form.offsetWidth; form.classList.add("shake");
        lp.select();
      }
    }
    lb.onclick = doLogin;
    form.onsubmit = e => { e.preventDefault(); doLogin(); };
    wrap.querySelectorAll(".demo button").forEach(b => b.onclick = () => {
      lu.value = b.dataset.u; lp.value = b.dataset.p; doLogin();
    });
    lu.focus();
  }
  return { show };
})();
