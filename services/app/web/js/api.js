/* api.js — HTTP-клиент + auth-стор */
window.API = (() => {
  const BASE = "/api/v1";
  const store = {
    get token() { return localStorage.getItem("mc_token") || ""; },
    set token(v) { v ? localStorage.setItem("mc_token", v) : localStorage.removeItem("mc_token"); },
    get user() { try { return JSON.parse(localStorage.getItem("mc_user") || "null"); } catch (e) { return null; } },
    set user(v) { v ? localStorage.setItem("mc_user", JSON.stringify(v)) : localStorage.removeItem("mc_user"); },
  };

  async function req(path, opts = {}) {
    const headers = Object.assign({}, opts.headers || {});
    if (store.token) headers["Authorization"] = "Bearer " + store.token;
    if (opts.json !== undefined) {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
    }
    let r;
    try {
      r = await fetch(BASE + path, { ...opts, headers });
    } catch (e) {
      throw new Error("нет связи с сервером");
    }
    if (r.status === 401 && !path.startsWith("/auth/")) {
      store.token = ""; store.user = null;
      location.reload();
      throw new Error("сессия истекла");
    }
    if (!r.ok) {
      let detail = r.statusText;
      try { const j = await r.json(); detail = j.detail || detail; } catch (e) {}
      const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      err.status = r.status;
      throw err;
    }
    return r.json();
  }
  const get = (p) => req(p);
  const post = (p, json) => req(p, { method: "POST", json });

  const TASK_META = {
    fire:    { label: "Пожарный риск",        short: "Пожар",  icon: "🔥" },
    access:  { label: "Несанкц. доступ",      short: "Доступ", icon: "🔓" },
    sensor:  { label: "Отказ датчика",        short: "Датчик", icon: "📟" },
    wear:    { label: "Износ инфраструктуры", short: "Износ",  icon: "⚙️" },
  };
  const TASKS = ["fire", "access", "sensor", "wear"];
  const ROLE_RU = { tech: "техник", dispatcher: "диспетчер", central: "центр. диспетчер" };

  return { BASE, store, req, get, post, TASK_META, TASKS, ROLE_RU };
})();
