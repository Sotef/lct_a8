/* api.js — HTTP-клиент: JWT + авто-refresh, кэш GET, логирование ошибок на сервер */
window.API = (() => {
  const BASE = "/api/v1";
  const ls = (k, v) => v === undefined ? localStorage.getItem(k)
    : (v ? localStorage.setItem(k, v) : localStorage.removeItem(k));
  const store = {
    get token() { return ls("mc_token") || ""; }, set token(v) { ls("mc_token", v || ""); },
    get refresh() { return ls("mc_refresh") || ""; }, set refresh(v) { ls("mc_refresh", v || ""); },
    get user() { try { return JSON.parse(ls("mc_user") || "null"); } catch (e) { return null; } },
    set user(v) { ls("mc_user", v ? JSON.stringify(v) : ""); },
    clear() { this.token = ""; this.refresh = ""; this.user = null; },
  };
  const listeners = { unauthorized: [], net: [] };
  const on = (ev, fn) => listeners[ev].push(fn);
  const emit = (ev, ...a) => listeners[ev].forEach(f => { try { f(...a); } catch (e) {} });

  let refreshing = null;
  let _cachedAt = null;
  function tryRefresh() {
    if (!store.refresh) return Promise.resolve(false);
    if (!refreshing) {
      refreshing = fetch(BASE + "/auth/refresh", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: store.refresh }),
      }).then(r => r.ok ? r.json() : null).then(j => {
        if (j && j.access_token) { store.token = j.access_token; return true; }
        return false;
      }).catch(() => false).finally(() => setTimeout(() => { refreshing = null; }, 0));
    }
    return refreshing;
  }

  /* --- PWA: клиентский id, офлайн-кэш GET и очередь изменений (MOBILE_PLAN §4.5) --- */
  const uuid = () => (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID() : "c-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  const QUEUE_RX = [/^\/maintenance\/tickets\/\d+$/, /^\/forecasts\/\d+\/decision$/];
  const isQueueable = (path, method) => method !== "GET" && QUEUE_RX.some(rx => rx.test(path));
  const CACHE_RX = [/^\/objects$/, /^\/meta\/tasks$/, /^\/maintenance\/tickets(\?|$)/,
    /^\/maintenance\/summary$/, /^\/meta\/summary$/, /^\/alerts(\?|$)/,
    /^\/forecasts\/\d+/, /^\/objects\/\d+\/risks/];
  const cacheable = path => CACHE_RX.some(rx => rx.test(path));

  async function req(path, opts = {}, retried = false) {
    const method = opts.method || "GET";
    const headers = Object.assign({ "X-Client": "pwa" }, opts.headers || {});
    if (store.token) headers["Authorization"] = "Bearer " + store.token;
    if (method !== "GET") headers["X-Client-Id"] = opts.__cid || (opts.__cid = uuid());
    const o = { method, headers };
    if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; o.body = JSON.stringify(opts.json); }
    let r;
    const t0 = performance.now();
    try { r = await fetch(BASE + path, o); }
    catch (e) {
      emit("net", false);
      if (window.Offline) {
        if (method === "GET") {                       // офлайн: отдать ранее загруженные данные
          const c = await Offline.getCache(path);
          if (c) {
            _cachedAt = c.fetched_at;
            window.dispatchEvent(new CustomEvent("mc:cached", { detail: c.fetched_at }));
            return c.data;
          }
        } else if (isQueueable(path, method)) {        // офлайн: поставить действие в очередь
          const it = await Offline.enqueue({ method, path, body: opts.json || null, cid: opts.__cid });
          return { queued: true, offline: true, cid: it.cid };
        }
      }
      throw Object.assign(new Error("нет связи с сервером"), { status: 0 });
    }
    emit("net", true);
    if (r.status === 401 && !path.startsWith("/auth/login")) {
      if (!retried && await tryRefresh()) return req(path, opts, true);
      store.clear(); emit("unauthorized");
      throw Object.assign(new Error("сессия истекла — войдите снова"), { status: 401 });
    }
    if (!r.ok) {
      let detail = r.statusText, body = null;
      try { body = await r.json(); detail = body.detail || detail; } catch (e) {}
      if (Array.isArray(detail)) detail = detail.map(d => (d.loc || []).slice(-1)[0] + ": " + d.msg).join("; ");
      const err = new Error(typeof detail === "string" ? detail
        : (detail && detail.message) || JSON.stringify(detail));
      err.status = r.status; err.body = body; err.requestId = r.headers.get("x-request-id");
      if (r.status >= 500) clientLog("error", `API ${method} ${path} -> ${r.status}: ${err.message}`,
        { request_id: err.requestId, ms: Math.round(performance.now() - t0) });
      throw err;
    }
    const ct = r.headers.get("content-type") || "";
    if (!ct.includes("json")) return r.text();
    const data = await r.json();
    if (method === "GET" && cacheable(path) && window.Offline) Offline.putCache(path, data);
    return data;
  }

  const cache = new Map();   // короткий кэш GET (дедуп параллельных запросов)
  function get(p, ttl = 0) {
    if (!ttl) return req(p);
    const c = cache.get(p);
    if (c && performance.now() - c.t < ttl) return c.p;
    const pr = req(p).catch(e => { cache.delete(p); throw e; });
    cache.set(p, { t: performance.now(), p: pr });
    return pr;
  }
  const post = (p, json) => req(p, { method: "POST", json: json === undefined ? {} : json });
  const patch = (p, json) => req(p, { method: "PATCH", json });
  const invalidate = (prefix) => { for (const k of [...cache.keys()]) if (!prefix || k.startsWith(prefix)) cache.delete(k); };

  /* клиентский лог -> POST /logs/client (с защитой от флуда: ≤20/мин) */
  let sent = 0, windowStart = Date.now();
  function clientLog(level, message, context) {
    if (!store.token) return;
    if (Date.now() - windowStart > 60000) { sent = 0; windowStart = Date.now(); }
    if (++sent > 20) return;
    fetch(BASE + "/logs/client", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + store.token },
      body: JSON.stringify({ level, message: String(message).slice(0, 1900),
        url: (location.hash || location.pathname).slice(0, 400),
        stack: context && context.stack ? String(context.stack).slice(0, 5000) : null,
        context: context || null }),
    }).catch(() => {});
  }
  window.addEventListener("error", e => clientLog("error", e.message || "window.error",
    { stack: e.error && e.error.stack, src: e.filename, line: e.lineno }));
  window.addEventListener("unhandledrejection", e => {
    const r = e.reason || {};
    if (r.status !== undefined && r.status < 500) return;   // бизнес-ошибки API уже показаны
    clientLog("error", "unhandledrejection: " + (r.message || r), { stack: r.stack });
  });

  const TASK_META = {
    fire:   { label: "Пожарный риск",        short: "Пожар",  icon: "flame", color: "#f97316" },
    access: { label: "Несанкц. доступ",      short: "Доступ", icon: "lock",  color: "#a78bfa" },
    sensor: { label: "Отказ датчика",        short: "Датчик", icon: "cpu",   color: "#22d3ee" },
    wear:   { label: "Износ инфраструктуры", short: "Износ",  icon: "cog",   color: "#facc15" },
  };
  const TASKS = ["fire", "access", "sensor", "wear"];
  const ROLE_RU = { tech: "техник", dispatcher: "диспетчер", central: "центр. диспетчер" };

  const isQueued = r => !!(r && r.queued);
  return { BASE, store, req, get, post, patch, invalidate, on, clientLog, TASK_META, TASKS, ROLE_RU,
    queued: isQueued, get cachedAt() { return _cachedAt; }, cacheable, isQueueable };
})();
