/* offline.js — офлайн-хранилище PWA (MOBILE_PLAN §4.5).
   IndexedDB без внешних библиотек: кэш данных (cache_data) + очередь действий
   (outbox) + идемпотентная синхронизация по X-Client-Id.

   window.Offline = { ready, putCache, getCache, enqueue, sync, count, items,
                      clearAll, clientId, on(cb), isOnline } */
window.Offline = (() => {
  const DB_NAME = "mc_pwa", DB_VER = 1;
  const ST_CACHE = "cache_data", ST_OUT = "outbox", ST_META = "meta";
  const KEY_CLIENT = "mc_client_id";
  let dbp = null, syncing = false;
  const listeners = [];

  function open() {
    if (dbp) return dbp;
    dbp = new Promise((res, rej) => {
      if (!window.indexedDB) { rej(new Error("IndexedDB недоступен")); return; }
      const r = indexedDB.open(DB_NAME, DB_VER);
      r.onupgradeneeded = e => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains(ST_CACHE)) db.createObjectStore(ST_CACHE, { keyPath: "key" });
        if (!db.objectStoreNames.contains(ST_OUT)) db.createObjectStore(ST_OUT, { keyPath: "cid" });
        if (!db.objectStoreNames.contains(ST_META)) db.createObjectStore(ST_META, { keyPath: "key" });
      };
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
    return dbp;
  }

  function run(store, mode, fn) {
    return open().then(db => new Promise((res, rej) => {
      const t = db.transaction(store, mode);
      const s = t.objectStore(store);
      let out;
      try { out = fn(s); } catch (e) { rej(e); return; }
      t.oncomplete = () => res(out && out.result !== undefined ? out.result : out);
      t.onerror = () => rej(t.error);
    }));
  }
  const idbGet = (store, key) => run(store, "readonly", s => s.get(key));
  const idbPut = (store, val) => run(store, "readwrite", s => s.put(val));
  const idbDel = (store, key) => run(store, "readwrite", s => s.delete(key));
  const idbAll = (store) => run(store, "readonly", s => s.getAll());

  const uuid = () => (crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : "c-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);

  function clientId() {
    let v = "";
    try { v = localStorage.getItem(KEY_CLIENT) || ""; } catch (e) {}
    if (!v) { v = uuid(); try { localStorage.setItem(KEY_CLIENT, v); } catch (e) {} }
    return v;
  }

  /* --- кэш данных (последние успешные GET) --- */
  async function putCache(key, data) {
    try { await idbPut(ST_CACHE, { key, data, fetched_at: Date.now() }); } catch (e) {}
  }
  async function getCache(key) {
    try {
      const r = await idbGet(ST_CACHE, key);
      return r ? { data: r.data, fetched_at: r.fetched_at } : null;
    } catch (e) { return null; }
  }

  /* --- очередь действий --- */
  async function enqueue(op) {
    const item = {
      cid: op.cid || uuid(), ts: Date.now(), method: op.method || "PATCH",
      path: op.path, body: op.body || null,
      base_status: op.base_status || null, offline_ts: op.offline_ts || new Date().toISOString(),
      files: op.files || [], attempts: 0, last_error: null, conflict: null,
    };
    try { await idbPut(ST_OUT, item); notify(); } catch (e) {}
    return item;
  }
  async function items() { try { return (await idbAll(ST_OUT)).sort((a, b) => a.ts - b.ts); } catch (e) { return []; } }
  async function count() { return (await items()).length; }
  async function remove(cid) { try { await idbDel(ST_OUT, cid); notify(); } catch (e) {} }
  async function update(cid, patch) {
    const it = await idbGet(ST_OUT, cid);
    if (!it) return;
    Object.assign(it, patch);
    try { await idbPut(ST_OUT, it); notify(); } catch (e) {}
  }

  function notify() { count().then(n => listeners.forEach(cb => { try { cb(n); } catch (e) {} })); }
  function on(cb) { listeners.push(cb); notify(); return () => { const i = listeners.indexOf(cb); if (i >= 0) listeners.splice(i, 1); }; }
  const isOnline = () => navigator.onLine !== false;

  /* --- синхронизация outbox --- */
  async function refreshToken() {
    if (!API.store.refresh) return false;
    try {
      const r = await fetch(API.BASE + "/auth/refresh", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: API.store.refresh }),
      });
      if (!r.ok) return false;
      const j = await r.json();
      if (j && j.access_token) { API.store.token = j.access_token; return true; }
    } catch (e) {}
    return false;
  }

  function authHeaders(extra) {
    const h = Object.assign({ "X-Client": "pwa" }, extra || {});
    if (API.store.token) h["Authorization"] = "Bearer " + API.store.token;
    return h;
  }

  async function sendItem(it) {
    const body = Object.assign({}, it.body || {});
    if (it.base_status) body.base_status = it.base_status;
    if (it.offline_ts) body.offline_ts = it.offline_ts;
    const headers = authHeaders({ "Content-Type": "application/json", "X-Client-Id": it.cid });
    return fetch(API.BASE + it.path, { method: it.method, headers, body: JSON.stringify(body) });
  }

  async function sendFiles(it) {
    for (const f of (it.files || [])) {
      const fd = new FormData();
      fd.append("file", f.blob, f.name || "photo.jpg");
      const headers = authHeaders({ "X-Client-Id": it.cid });
      const r = await fetch(API.BASE + it.path, { method: "POST", headers, body: fd });
      if (!r.ok && r.status !== 409) throw Object.assign(new Error("attachment " + r.status), { status: r.status });
    }
  }

  async function flush() {
    if (syncing || !isOnline() || !API.store.token) return { synced: 0, left: await count() };
    syncing = true;
    let synced = 0;
    try { await refreshToken(); } catch (e) {}
    try {
      for (const it of await items()) {
        if (it.conflict) continue;                       // конфликт решает человек
        try {
          if (it.files && it.files.length && it.method === "POST" && !it.body) {
            await sendFiles(it);                             // фото: multipart, бросит при ошибке
            await remove(it.cid);
            synced++;
            continue;
          }
          const r = await sendItem(it);
          if (r && r.status === 409) {
            let det = null;
            try { det = (await r.json()).detail; } catch (e) {}
            await update(it.cid, { conflict: (det && det.current) || det || { code: "conflict" } });
            continue;
          }
          if (r && r.status === 401) {                       // сессия: одна попытка refresh
            if (await refreshToken()) continue;
          }
          if (r && r.ok) {
            if (it.files && it.files.length) await sendFiles(it);
            await remove(it.cid);
            synced++;
          } else if (r && r.status && r.status < 500 && r.status !== 0) {
            await update(it.cid, { attempts: (it.attempts || 0) + 1, last_error: "HTTP " + r.status });
          } else {
            await update(it.cid, { attempts: (it.attempts || 0) + 1, last_error: "network" });
            break;                                          // сеть пропала — прекратить
          }
        } catch (e) {
          await update(it.cid, { attempts: (it.attempts || 0) + 1, last_error: String(e.message || e) });
          break;
        }
      }
    } finally { syncing = false; notify(); }
    return { synced, left: await count() };
  }

  async function resolveConflict(cid, overwrite) {
    const it = await idbGet(ST_OUT, cid);
    if (!it) return;
    if (overwrite) { await update(cid, { base_status: null, conflict: null }); return flush(); }
    await remove(cid);
  }

  async function clearAll() {
    try {
      await run(ST_CACHE, "readwrite", s => s.clear());
      await run(ST_OUT, "readwrite", s => s.clear());
      await run(ST_META, "readwrite", s => s.clear());
    } catch (e) {}
    notify();
  }

  /* --- триггеры синхронизации --- */
  let started = false;
  function start() {
    if (started) return;
    started = true;
    const kick = () => { if (isOnline()) flush(); };
    window.addEventListener("online", kick);
    window.addEventListener("focus", kick);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) kick(); });
    setInterval(kick, 45000);
    if ("serviceWorker" in navigator && "SyncManager" in window) {
      navigator.serviceWorker.ready.then(reg => { try { reg.sync.register("mc-outbox"); } catch (e) {} }).catch(() => {});
    }
    kick();
  }

  const ready = open().catch(() => null);
  try { ready.then(() => notify()); } catch (e) {}

  return { ready, putCache, getCache, enqueue, items, count, remove, update,
    sync: flush, flush, resolveConflict, clearAll, clientId, on, isOnline, start };
})();

