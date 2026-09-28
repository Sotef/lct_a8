/* shell.js — мобильная оболочка (MOBILE_PLAN §4.2, §4.7, §4.8).
   Профиль устройства, нижняя навигация (4 таба), bottom-sheet «Ещё»,
   плашка офлайна/синхронизации, установка PWA, регистрация service worker.

   window.MOBILE = { is, enhance, onView, openMore, closeMore, promptInstall, registerSW } */
window.MOBILE = (() => {
  const { el, esc, ic, toast } = UI;
  const mq = matchMedia("(max-width: 760px)");
  const is = () => mq.matches;

  function applyProfile() {
    document.documentElement.dataset.mode = is() ? "mobile" : "desktop";
  }
  applyProfile();
  try { mq.addEventListener("change", applyProfile); } catch (e) {}

  let nav = null, api = null, installEvt = null, sheet = null;

  const VIEW_ICON = { dashboard: "dashboard", objects: "map", graph: "graph", forecasts: "list",
    plan: "calendar", tickets: "wrench", audit: "shield", sys: "server", users: "users", alerts: "bell" };

  const NAV_ROLE = {
    tech: [
      { v: "tickets", name: "Мои заявки", icon: "wrench" },
      { v: "alerts", name: "Алерты", icon: "bell" },
      { v: "objects", name: "Объекты", icon: "map" },
      { more: true, name: "Ещё", icon: "menu" },
    ],
    dispatcher: [
      { v: "alerts", name: "Алерты", icon: "bell" },
      { v: "tickets", name: "Заявки", icon: "wrench" },
      { v: "objects", name: "Объекты", icon: "map" },
      { more: true, name: "Ещё", icon: "menu" },
    ],
    central: [
      { v: "alerts", name: "Алерты", icon: "bell" },
      { v: "tickets", name: "Заявки", icon: "wrench" },
      { v: "objects", name: "Объекты", icon: "map" },
      { more: true, name: "Ещё", icon: "menu" },
    ],
  };

  /* ---------- верхняя панель: компактный бренд + иконочный поиск ---------- */
  function enhanceTopbar(root) {
    const top = root.querySelector(".topbar");
    if (!top || !is()) return;
    const burger = top.querySelector("#burger");
    if (burger) burger.remove();
    if (!top.querySelector(".m-brand")) {
      const brand = el(`<div class="m-brand">${ic("logo", "l")}<span>ОДС</span></div>`);
      top.insertBefore(brand, top.firstChild);
    }
    const sb = top.querySelector("#search");
    if (sb) {
      sb.classList.add("m-searchbtn");
      sb.innerHTML = ic("search");
      sb.setAttribute("aria-label", "Поиск и команды");
      sb.onclick = () => Cmdk.open(window.App && App._cmdItems ? App._cmdItems() : (() => []));
    }
  }

  /* ---------- нижняя навигация ---------- */
  function buildNav(root) {
    document.querySelectorAll(".mnav").forEach(n => n.remove());
    nav = null;
    if (!is()) return;
    const role = (API.store.user && API.store.user.role) || "central";
    const items = NAV_ROLE[role] || NAV_ROLE.central;
    nav = el(`<nav class="mnav" id="mnav" aria-label="Основная навигация"></nav>`);
    items.forEach(it => {
      const b = el(`<button class="mnav-item" data-v="${it.v || "more"}" aria-label="${esc(it.name)}">
        ${ic(it.icon)}<span class="mnav-label">${esc(it.name)}</span>
        ${it.v === "tickets" ? '<span class="mnav-badge" id="mnavbadge"></span>' : ""}</button>`);
      b.onclick = () => it.more ? openMore() : (api && api.navigate(it.v));
      nav.appendChild(b);
    });
    root.appendChild(nav);
    syncNavBadge();
  }

  function syncNavBadge() {
    const b = document.getElementById("mnavbadge");
    if (!b) return;
    const cnt = (App && App.state && App.state.ticketCount) || 0;
    b.textContent = cnt > 99 ? "99+" : (cnt || "");
  }

  function onView(v) {
    if (!nav && is()) buildNav(document.getElementById("app") || document.body);
    if (!nav) return;
    nav.querySelectorAll(".mnav-item").forEach(b =>
      b.classList.toggle("on", b.dataset.v === v));
    syncNavBadge();
  }

  /* ---------- bottom-sheet «Ещё» ---------- */
  function closeMore() {
    if (!sheet) return;
    const s = sheet, veil = s._veil;
    sheet = null;
    document.removeEventListener("keydown", s._esc);
    if (veil) { veil.classList.add("out"); setTimeout(() => veil.remove(), 260); }
    s.classList.add("out");
    setTimeout(() => s.remove(), 260);
  }

  function mkItem(icon, label, fn) {
    const it = el(`<button class="sheet-item">${ic(icon)}<span>${esc(label)}</span><span class="si-r">${ic("chevron", "s")}</span></button>`);
    it.onclick = () => { closeMore(); try { fn(); } catch (e) {} };
    return it;
  }
  function section(title, node) {
    const sec = el(`<div style="margin-bottom:14px"><div class="side-sec" style="padding:8px 6px 6px">${esc(title)}</div></div>`);
    sec.appendChild(node);
    return sec;
  }

  function openMore() {
    if (sheet) { closeMore(); return; }
    const veil = el(`<div class="sheet-veil"></div>`);
    veil.onclick = closeMore;
    const sh = el(`<div class="m-sheet" role="dialog" aria-modal="true" aria-label="Ещё">
      <div class="sheet-grab"><i></i></div>
      <div class="sheet-head">${ic("menu")} Ещё</div>
      <div class="sheet-body"></div></div>`);
    const body = sh.querySelector(".sheet-body");
    sh._veil = veil;

    /* разделы (из сайдбара — уже отфильтрованы по роли) */
    const secs = [...document.querySelectorAll("#navs .nav-item")]
      .map(b => ({ v: b.dataset.v, name: ((b.querySelector("span") || {}).textContent) || b.title }))
      .filter(x => x.v);
    const list = el(`<div class="sheet-list"></div>`);
    secs.forEach(s => {
      const it = el(`<button class="sheet-item ${App.state.view === s.v ? "on" : ""}" data-v="${s.v}">
        ${ic(VIEW_ICON[s.v] || "info")}<span>${esc(s.name)}</span><span class="si-r">${ic("chevron", "s")}</span></button>`);
      it.onclick = () => { closeMore(); api.navigate(s.v); };
      list.appendChild(it);
    });
    body.appendChild(section("Разделы", list));

    /* направление прогноза */
    const dirs = el(`<div class="sheet-list"></div>`);
    API.TASKS.forEach(t => {
      const m = API.TASK_META[t];
      const it = el(`<button class="sheet-item ${App.state.task === t ? "on" : ""}" data-t="${t}">
        ${ic(m.icon)}<span>${esc(m.label)}</span><span class="si-r">${App.state.task === t ? ic("check", "s") : ""}</span></button>`);
      it.onclick = () => { closeMore(); if (api && api.pickTask) api.pickTask(t); };
      dirs.appendChild(it);
    });
    body.appendChild(section("Направление прогноза", dirs));

    /* профиль / сервис */
    const prof = el(`<div class="sheet-list"></div>`);
    const u = API.store.user || {};
    prof.appendChild(el(`<div class="sheet-item"><span>${ic("user")}</span>
      <span>${esc(u.full_name || u.username || "—")} <span class="faint">· ${esc(API.ROLE_RU[u.role] || u.role || "")}</span></span></div>`));
    prof.appendChild(mkItem("refresh", "Обновить данные", async () => {
      API.invalidate(); if (api) await api.navigate(App.state.view); toast("данные обновлены", "ok");
    }));
    prof.appendChild(mkItem("download", "Синхронизировать сейчас", async () => {
      const r = await Offline.flush();
      toast(`синхронизация: отправлено ${r.synced}, в очереди ${r.left}`, "ok");
    }));
    if (installEvt) prof.appendChild(mkItem("plus", "Установить приложение", promptInstall));
    if (window.PushX && PushX.supported) {
      const st = PushX.state();
      if (st === "granted") {
        prof.appendChild(mkItem("bell", "Тест уведомления", async () => {
          const r = await PushX.test().catch(e => ({ ok: false, detail: e.message }));
          toast(r.sent ? "уведомление отправлено" : (r.detail || "push не настроен"), r.sent ? "ok" : "warn");
        }));
      } else {
        prof.appendChild(mkItem("bell", "Включить уведомления", async () => {
          const r = await PushX.enable().catch(e => ({ ok: false, detail: e.message }));
          toast(r.detail || (r.ok ? "включено" : "не удалось"), r.ok ? "ok" : "warn");
        }));
      }
    }
    prof.appendChild(mkItem("logout", "Выйти", async () => {
      const ok = await Overlay.confirm("Выйти из системы?",
        "Несинхронизированные действия будут потеряны. Сессия завершится, действие попадёт в аудит.",
        "Выйти", "dang");
      if (!ok) return;
      if (window.Offline) await Offline.clearAll();
      API.post("/auth/logout").catch(() => {});
      API.store.clear(); location.reload();
    }));
    body.appendChild(section("Профиль", prof));

    document.body.append(veil, sh);
    sh._esc = e => { if (e.key === "Escape") closeMore(); };
    document.addEventListener("keydown", sh._esc);
    sheet = sh;
  }

  /* ---------- плашка офлайн / очередь ---------- */
  let bar = null, cachedAt = null;
  function banner() {
    const off = navigator.onLine === false;
    const cnt = (banner._n = banner._n || 0);
    if (!off && !cnt) { if (bar) { bar.remove(); bar = null; document.body.classList.remove("offline-active"); } return; }
    const txt = off
      ? `офлайн${cachedAt ? " · данные от " + new Date(cachedAt).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : ""}`
      : `${cnt} ${cnt === 1 ? "действие ждёт" : "действий ждут"} отправки`;
    const cls = off ? "offline-bar" : "offline-bar sync";
    if (!bar) {
      bar = el(`<div class="offline-bar"><span class="offline-dot"></span><span class="ob-text"></span></div>`);
      document.body.appendChild(bar);
      document.body.classList.add("offline-active");
    }
    bar.className = cls;
    bar.querySelector(".ob-text").textContent = txt;
  }

  function setCachedAt(ts) { cachedAt = ts; if (navigator.onLine === false) banner(); }

  /* ---------- установка PWA ---------- */
  function promptInstall() {
    if (!installEvt) return;
    installEvt.prompt();
    installEvt.userChoice.then(c => {
      if (c.outcome === "accepted") toast("приложение установлено", "ok");
      installEvt = null;
    }).catch(() => {});
  }

  /* ---------- service worker + push ---------- */
  function registerSW() {
    if (!("serviceWorker" in navigator)) return;
    if (location.protocol !== "https:" && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
      console.info("[PWA] service worker/push требуют HTTPS или localhost");
      return;
    }
    navigator.serviceWorker.register("/sw.js").then(reg => {
      reg.addEventListener("updatefound", () => {
        const w = reg.installing;
        if (!w) return;
        w.addEventListener("statechange", () => {
          if (w.state === "installed" && navigator.serviceWorker.controller) {
            toast("Доступна новая версия", "info", { title: "Обновление приложения", ms: 12000 });
          }
        });
      });
      window.addEventListener("focus", () => reg.update().catch(() => {}));
    }).catch(e => console.warn("[PWA] sw register failed:", e));
  }

  /* ---------- точка входа ---------- */
  function enhance(root, callbacks) {
    api = callbacks || {};
    enhanceTopbar(root);
    buildNav(root);
    try {
      if (window.Offline) {
        Offline.start();
        Offline.on(n => { banner._n = n; banner(); });
      }
    } catch (e) {}
    window.addEventListener("online", banner);
    window.addEventListener("offline", () => { banner(); });
    window.addEventListener("mc:cached", e => setCachedAt(e.detail));
    banner();
    registerSW();
    if (window.PushX) PushX.init();
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.addEventListener("message", e => {
        const d = e.data || {};
        if (d.type === "flush-outbox" && window.Offline) Offline.flush();
        if (d.type === "navigate" && d.url) {
          const mv = String(d.url).match(/#\/?([a-z]+)/);
          const mid = String(d.url).match(/[?&]id=(\d+)/);
          if (window.App) App.navigate(mv ? mv[1] : "alerts");
          if (mid) setTimeout(() => { try { Cards.forecast.open(+mid[1]); } catch (err) {} }, 400);
        }
      });
    }
    return { syncNavBadge, onView };
  }

  window.addEventListener("beforeinstallprompt", e => {
    e.preventDefault();
    installEvt = e;
  });
  window.addEventListener("appinstalled", () => { installEvt = null; });

  return { is, enhance, onView, openMore, closeMore, promptInstall, registerSW, setCachedAt, syncNavBadge };
})();

