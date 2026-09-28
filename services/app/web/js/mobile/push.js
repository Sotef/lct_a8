/* push.js — Web Push (MOBILE_PLAN §4.6): разрешение, подписка, тест.
   window.PushX = { supported, state, enable, disable, test, init } */
window.PushX = (() => {
  const SUPPORTED = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

  function b64ToU8(base64) {
    const pad = "=".repeat((4 - (base64.length % 4)) % 4);
    const b = (base64 + pad).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(b);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  function state() {
    if (!SUPPORTED) return "unsupported";
    if (Notification.permission === "denied") return "denied";
    return Notification.permission;      // default | granted
  }

  async function reg() {
    if (!("serviceWorker" in navigator)) return null;
    try { return await navigator.serviceWorker.ready; } catch (e) { return null; }
  }

  async function enable() {
    if (!SUPPORTED) return { ok: false, detail: "браузер не поддерживает push" };
    const perm = await Notification.requestPermission();
    if (perm !== "granted") return { ok: false, detail: "разрешение не выдано" };
    const cfg = await API.get("/push/vapid-public-key").catch(() => null);
    if (!cfg || !cfg.key) {
      return { ok: false, detail: "push не настроен на сервере (нет VAPID-ключа) — работает фолбэк-поллинг" };
    }
    const r = await reg();
    if (!r) return { ok: false, detail: "service worker недоступен (нужен HTTPS/localhost)" };
    let sub = await r.pushManager.getSubscription();
    if (!sub) {
      sub = await r.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToU8(cfg.key) });
    }
    const j = sub.toJSON();
    await API.post("/push/subscribe", { endpoint: j.endpoint, keys: j.keys });
    return { ok: true, detail: "уведомления включены" };
  }

  async function disable() {
    const r = await reg();
    if (!r) return { ok: false };
    const sub = await r.pushManager.getSubscription();
    const endpoint = sub ? sub.endpoint : null;
    if (sub) { try { await sub.unsubscribe(); } catch (e) {} }
    await API.req("/push/subscribe", { method: "DELETE", json: { endpoint } }).catch(() => {});
    return { ok: true };
  }

  async function testPush() { return API.post("/push/test"); }

  async function init() {
    if (!SUPPORTED || Notification.permission !== "granted") return;
    try {
      const r = await reg();
      if (!r) return;
      const sub = await r.pushManager.getSubscription();
      if (sub) await API.post("/push/subscribe", sub.toJSON()).catch(() => {});
    } catch (e) {}
  }

  return { supported: SUPPORTED, state, enable, disable, test: testPush, init };
})();
