/* sw.js — service worker PWA (MOBILE_PLAN §4.4).
   - оболочка (html/css/js/иконки): stale-while-revalidate;
   - GET /api/v1: network-first с откатом на рантайм-кэш (данные также кэширует
     IndexedDB в js/mobile/offline.js — SW-кэш нужен для перезагрузки в офлайне);
   - push: показ уведомления; клик — открытие нужного экрана;
   - background sync «mc-outbox»: просьба странице отправить очередь действий. */
const VER = "mc-v2";
const SHELL = `mc-shell-${VER}`;
const RUNTIME = `mc-runtime-${VER}`;
const SHELL_ASSETS = [
  "/", "/index.html", "/manifest.webmanifest",
  "/css/core.css", "/css/shell.css", "/css/topbar.css", "/css/components.css",
  "/css/buttons.css", "/css/widgets.css", "/css/overlays.css", "/css/overlays2.css",
  "/css/pages.css", "/css/pages2.css", "/css/themes.css", "/css/anim.css", "/css/mobile.css",
  "/js/api.js", "/js/app.js", "/js/ui.js", "/js/fx.js", "/js/icons.js", "/js/overlays.js",
  "/js/view_alerts.js", "/js/view_tickets.js", "/js/view_objects.js", "/js/mobile/offline.js",
  "/js/mobile/shell.js", "/js/mobile/push.js", "/js/mobile/photo.js",
  "/icons/icon-192.svg", "/icons/icon-512.svg", "/icons/maskable-512.svg",
];

self.addEventListener("install", e => {
  e.waitUntil((async () => {
    const c = await caches.open(SHELL);
    await Promise.allSettled(SHELL_ASSETS.map(u => c.add(new Request(u, { cache: "reload" }))));
    self.skipWaiting();
  })());
});

self.addEventListener("activate", e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== SHELL && k !== RUNTIME).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener("message", e => {
  if (e.data && e.data.type === "SKIP_WAITING") self.skipWaiting();
});

function isApi(url) { return url.pathname.startsWith("/api/v1/"); }
function isAuth(url) { return url.pathname.startsWith("/api/v1/auth/"); }

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  if (isApi(url)) {                       // данные: сеть → кэш
    if (isAuth(url)) return;              // токены не кэшируем
    e.respondWith((async () => {
      try {
        const r = await fetch(req);
        if (r && r.ok) {
          const c = await caches.open(RUNTIME);
          c.put(req, r.clone());
        }
        return r;
      } catch (err) {
        const hit = await caches.match(req);
        if (hit) return hit;
        return new Response(JSON.stringify({ detail: "офлайн: нет данных" }),
          { status: 503, headers: { "Content-Type": "application/json" } });
      }
    })());
    return;
  }

  if (req.mode === "navigate") {          // SPA-оболочка
    e.respondWith((async () => {
      try { return await fetch(req); }
      catch (err) { return (await caches.match("/index.html")) || Response.error(); }
    })());
    return;
  }

  e.respondWith((async () => {            // статика: stale-while-revalidate
    const hit = await caches.match(req);
    const net = fetch(req).then(r => {
      if (r && r.ok) caches.open(SHELL).then(c => c.put(req, r.clone()));
      return r;
    }).catch(() => null);
    return hit || (await net) || Response.error();
  })());
});

/* --- push --- */
self.addEventListener("push", e => {
  let d = { title: "Москоллектор ОДС", body: "Новый сигнал риска", url: "/#/alerts" };
  try { if (e.data) d = Object.assign(d, e.data.json()); } catch (err) {
    try { if (e.data) d.body = e.data.text(); } catch (e2) {}
  }
  e.waitUntil(self.registration.showNotification(d.title, {
    body: d.body,
    tag: d.tag || undefined,
    renotify: !!d.tag,
    icon: "/icons/icon-192.svg",
    badge: "/icons/icon-192.svg",
    data: { url: d.url || "/#/alerts" },
    vibrate: [80, 40, 80],
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/#/alerts";
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) {
      if ("focus" in c) { c.postMessage({ type: "navigate", url }); return c.focus(); }
    }
    return self.clients.openWindow(url);
  })());
});

/* --- background sync очереди офлайн-действий --- */
self.addEventListener("sync", e => {
  if (e.tag !== "mc-outbox") return;
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    all.forEach(c => c.postMessage({ type: "flush-outbox" }));
  })());
});
