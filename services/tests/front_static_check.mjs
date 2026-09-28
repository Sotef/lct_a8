/* front_static_check.mjs — статическая проверка фронтенда без браузера.
   Запуск: node services/tests/front_static_check.mjs (из папки services)
   Проверяет: иконки, классы CSS, вызовы API против маршрутов FastAPI, ссылки на модули. */
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve("app/web");
const JS = path.join(WEB, "js");
const CSS = path.join(WEB, "css");
let fails = 0, checks = 0;
function chk(name, cond, extra = "") {
  checks++;
  if (!cond) { fails++; console.log("  FAIL " + name + (extra ? " :: " + extra : "")); }
  else console.log("  ok   " + name);
}
const read = f => fs.readFileSync(f, "utf8");
const jsFiles = fs.readdirSync(JS).filter(f => f.endsWith(".js"));
const cssFiles = fs.readdirSync(CSS).filter(f => f.endsWith(".css"));
const js = Object.fromEntries(jsFiles.map(f => [f, read(path.join(JS, f))]));
const allJs = Object.values(js).join("\n");
const allCss = cssFiles.map(f => read(path.join(CSS, f))).join("\n");

/* 1. иконки */
const definedIcons = new Set([...js["icons.js"].matchAll(/(?:^|[,{]\s*)([a-z_]+):\s*'/gm)].map(m => m[1]));
const usedIcons = new Set();
for (const src of Object.values(js)) {
  for (const m of src.matchAll(/\bic\(\s*"([a-z_]+)"/g)) usedIcons.add(m[1]);
  for (const m of src.matchAll(/\bIcons\.svg\(\s*"([a-z_]+)"/g)) usedIcons.add(m[1]);
  for (const m of src.matchAll(/\bicon:\s*"([a-z_]+)"/g)) usedIcons.add(m[1]);
}
const missingIcons = [...usedIcons].filter(n => !definedIcons.has(n));
chk(`иконки: используется ${usedIcons.size}, определено ${definedIcons.size}, пропущено ${missingIcons.length}`,
  missingIcons.length === 0, missingIcons.join(", "));

/* 2. классы CSS */
const usedClasses = new Set();
for (const src of Object.values(js)) {
  for (const m of src.matchAll(/class="([^"$`]+)"/g))
    m[1].split(/\s+/).filter(c => /^[a-z][a-z0-9-]*$/.test(c)).forEach(c => usedClasses.add(c));
  for (const m of src.matchAll(/classList\.(?:add|toggle|remove)\(([^)]*)\)/g))
    for (const mm of m[1].matchAll(/"([a-z][a-z0-9-]*)"/g)) usedClasses.add(mm[1]);
}
const definedClasses = new Set([...allCss.matchAll(/\.([a-z][a-z0-9-]*)/g)].map(m => m[1]));
const ignore = new Set(["ico", "s", "l", "on", "rv", "out", "new", "hl", "dim", "over", "dragging",
  "loading", "done", "busy", "err", "live", "spin", "hide"]);
const missingClasses = [...usedClasses].filter(c => !definedClasses.has(c) && !ignore.has(c));
chk(`классы CSS: используется ${usedClasses.size}, не найдено ${missingClasses.length}`,
  missingClasses.length === 0, missingClasses.join(", "));

/* 3. API-пути против маршрутов FastAPI */
const routesFile = path.resolve("tests/_routes.json");
if (fs.existsSync(routesFile)) {
  const have = new Set(JSON.parse(read(routesFile)));
  const norm = p => p.replace(/\$?\{[^}]*\}/g, "{id}").replace(/\/$/, "");
  const haveNorm = new Set([...have].map(norm));
  const used = new Set();
  for (const src of Object.values(js)) {
    for (const m of src.matchAll(/API\.(?:get|post|patch|req)\(\s*[`"'](\/[\w\-${}./]*)/g)) used.add(m[1]);
  }
  const unknown = [...used].map(p => "/api/v1" + norm(p).replace(/^\//, "/"))
    .filter(p => ![...haveNorm].some(h => norm(h) === p));
  chk(`API: используется ${used.size} путей, неизвестных ${new Set(unknown).size}`,
    unknown.length === 0, [...new Set(unknown)].join(", "));
} else {
  console.log("  skip  API-пути (нет tests/_routes.json)");
}
/* 4. ссылки на разделы */
const viewModules = jsFiles.filter(f => f.startsWith("view_")).map(f => f.replace(/^view_|\.js$/g, ""));
const usedViews = new Set([...allJs.matchAll(/Views\.([a-z]+)\./g)].map(m => m[1]));
const missingViews = [...usedViews].filter(v => !viewModules.includes(v));
chk(`разделы: определено ${viewModules.length} [${viewModules.join(", ")}], неизвестных ссылок ${missingViews.length}`,
  missingViews.length === 0, missingViews.join(", "));
for (const v of viewModules) {
  const src = js[`view_${v}.js`];
  chk(`view_${v}: render + name + icon`, /function render/.test(src) && /name:\s*"/.test(src) && /icon:\s*"/.test(src));
}

/* 5. публичные методы модулей */
const apiOf = {
  UI: ["el", "esc", "ic", "fmt", "fmtInt", "fmtPct", "countUp", "toast", "stagger",
       "riskOf", "riskLevel", "riskColor", "emptyState", "live", "liveStop", "debounce",
       "ago", "dt", "dtFull", "theme", "setTheme", "skeleton", "css", "riskHex"],
  Charts: ["trend", "spark", "gauge", "survival", "eta", "factors", "donut", "tip", "smooth", "drawLines"],
  Cards: ["forecast", "object"],
  Overlay: ["drawer", "closeDrawer", "modal", "confirm"],
  FX: ["seg", "slider", "bars", "bindGlobal", "reduced"],
  Notify: ["start", "poll", "toggle", "close", "badge"],
  Cmdk: ["open", "close"],
  BGFX: ["start"],
  Icons: ["svg"],
};
for (const [mod, keys] of Object.entries(apiOf)) {
  const src = Object.entries(js).filter(([f]) => f.includes(mod.toLowerCase()) ||
    (mod === "UI" && f === "ui.js") || (mod === "Charts" && f.startsWith("charts"))
    || (mod === "Cards" && f.startsWith("card_")) || (mod === "Overlay" && f === "overlays.js")
    || (mod === "FX" && f === "fx.js") || (mod === "Notify" && f === "notify.js")
    || (mod === "Cmdk" && f === "cmdk.js") || (mod === "BGFX" && f === "bgfx.js")
    || (mod === "Icons" && f === "icons.js")).map(([, s]) => s).join("\n");
  const miss = keys.filter(k => !new RegExp(`(^|[\\s{,.])${k}\\s*[:(,=}]`).test(src));
  chk(`модуль ${mod}: экспорты на месте (${keys.length})`, miss.length === 0, miss.join(", "));
}

/* 6. index.html */
const html = read(path.join(WEB, "index.html"));
const notLinkedJs = jsFiles.filter(f => !html.includes(`/js/${f}`));
const notLinkedCss = cssFiles.filter(f => !html.includes(`/css/${f}`));
chk("index.html подключает все JS", notLinkedJs.length === 0, notLinkedJs.join(", "));
chk("index.html подключает все CSS", notLinkedCss.length === 0, notLinkedCss.join(", "));
chk("внешние CDN не используются (офлайн-контур)", !/unpkg\.com|googleapis\.com|cdn\.jsdelivr/.test(html));

/* 7. ключевые сценарии и UX */
chk("палитра команд по Ctrl+K", /key\.toLowerCase\(\) === "k"/.test(js["app.js"]));
chk("уведомления риска запускаются", /Notify\.start\(\)/.test(js["app.js"]));
chk("view transitions", /startViewTransition/.test(js["app.js"] + js["ui.js"]));
chk("канбан: drag&drop смены статуса", /dragstart/.test(js["view_tickets.js"]) && /ondrop|addEventListener\("drop"/.test(js["view_tickets.js"]));
chk("live-лог по after_id", /after_id/.test(js["view_sys.js"]));
chk("ошибки UI уходят в /logs/client", /logs\/client/.test(js["api.js"]));
chk("авто-refresh JWT при 401", /auth\/refresh/.test(js["api.js"]) && /tryRefresh/.test(js["api.js"]));
chk("карточка прогноза: 3 решения диспетчера", /confirm/.test(js["card_forecast.js"]) && /preventive/.test(js["card_forecast.js"]));
chk("count-up и tilt-эффекты", /countUp/.test(allJs) && /data-tilt/.test(allJs));
chk("учитывается prefers-reduced-motion", /prefers-reduced-motion/.test(js["fx.js"] + js["bgfx.js"] + allCss));
chk("экран входа с демо-ролями", /central.operator/.test(js["login.js"]) && /dispatcher.alpha/.test(js["login.js"]));
chk("риски: единая логика risk30_cal/risk_used", /risk30_cal/.test(js["ui.js"]));

console.log(`\n=== FRONT STATIC: ${fails === 0 ? "ALL OK" : fails + " FAIL"} (${checks} проверок) ===`);
process.exit(fails === 0 ? 0 : 1);

