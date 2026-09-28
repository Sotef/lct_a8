/* bgfx.js — живой фон «сеть коллекторов»: узлы-колодцы, трубы, бегущие импульсы данных.
   Скорость/выключение регулируются пользователем: BGFX.setSpeed(0|0.35|1|2), BGFX.setPulses(bool).
   Настройки лежат в localStorage (mc_bg_speed, mc_bg_pulses) и применяются на лету. */
window.BGFX = (() => {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const mobile = matchMedia("(max-width: 760px)");     // на телефоне фон-канвас выключен
  const SPEEDS = [0, 0.35, 1, 2];
  const SPEED_RU = { 0: "выключен", 0.35: "медленный", 1: "обычный", 2: "быстрый" };
  let speed = parseFloat(localStorage.getItem("mc_bg_speed"));
  if (isNaN(speed) || !SPEEDS.includes(speed)) speed = 1;
  let pulsesOn = localStorage.getItem("mc_bg_pulses") !== "0";
  let raf = 0, booted = false, W = 0, H = 0, ctx = null, cv = null,
      nodes = [], edges = [], pulses = [], col = {};
  const mouse = { x: -1e4, y: -1e4 };
  const running = () => booted && speed > 0 && !reduced && !mobile.matches;
  mobile.addEventListener("change", () => { if (mobile.matches) stop(); else if (running()) start(); });

  function applyBody() {
    document.body.classList.toggle("bg-off", speed === 0);
    document.body.classList.toggle("bg-slow", speed > 0 && speed < 1);
  }
  function setSpeed(v) {
    v = +v;
    if (!SPEEDS.includes(v)) v = 1;
    speed = v;
    localStorage.setItem("mc_bg_speed", String(v));
    applyBody();
    if (running()) start(); else stop();
    window.dispatchEvent(new CustomEvent("bgchange", { detail: { speed, pulses: pulsesOn } }));
  }
  function setPulses(on) {
    pulsesOn = !!on;
    localStorage.setItem("mc_bg_pulses", on ? "1" : "0");
    if (!pulsesOn) pulses = [];
    window.dispatchEvent(new CustomEvent("bgchange", { detail: { speed, pulses: pulsesOn } }));
  }

  function start() {
    if (mobile.matches) { applyBody(); return; }     // телефон: фон не создаём вовсе
    if (document.getElementById("bgfx")) { booted = true; }
    if (!booted) boot();
    if (!running()) { stop(); return; }
    if (!raf) raf = requestAnimationFrame(frame);
  }
  function stop() {
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    if (ctx && cv) ctx.clearRect(0, 0, W, H);
  }
  function boot() {
    booted = true;
    const orbs = document.createElement("div");
    orbs.className = "bg-orbs"; orbs.innerHTML = "<i></i><i></i><i></i>";
    document.body.prepend(orbs);
    cv = document.createElement("canvas");
    cv.id = "bgfx"; document.body.prepend(cv);
    ctx = cv.getContext("2d");
    readCol(); build();
    addEventListener("resize", UI.debounce(build, 200));
    addEventListener("mousemove", e => { mouse.x = e.clientX; mouse.y = e.clientY; }, { passive: true });
    addEventListener("themechange", () => setTimeout(readCol, 30));
  }
  const readCol = () => {
    const s = getComputedStyle(document.body);
    col = { line: s.getPropertyValue("--net-line").trim() || "139,92,246",
            dot: s.getPropertyValue("--net-dot").trim() || "34,211,238" };
  };
  function build() {
    if (!ctx) return;
    const dpr = Math.min(2, devicePixelRatio || 1);
    W = innerWidth; H = innerHeight;
    cv.width = W * dpr; cv.height = H * dpr; cv.style.width = W + "px"; cv.style.height = H + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = Math.round(Math.min(70, (W * H) / 26000));
    nodes = Array.from({ length: n }, () => ({ x: Math.random() * W, y: Math.random() * H,
      vx: (Math.random() - .5) * .12, vy: (Math.random() - .5) * .12, r: 1 + Math.random() * 1.6 }));
    edges = [];
    nodes.forEach((a, i) => {
      nodes.map((b, j) => [j, (a.x - b.x) ** 2 + (a.y - b.y) ** 2])
        .filter(([j]) => j !== i).sort((p, q) => p[1] - q[1]).slice(0, 2)
        .forEach(([j]) => { if (!edges.some(e => e[0] === j && e[1] === i)) edges.push([i, j]); });
    });
    pulses = [];
  }
  function frame() {
    raf = 0;
    if (!running()) return;
    if (document.hidden) { setTimeout(() => { if (running()) raf = requestAnimationFrame(frame); }, 500); return; }
    const k = speed;                       // множитель скорости (0.35 — медленно, 2 — быстро)
    ctx.clearRect(0, 0, W, H);
    nodes.forEach(p => {
      p.x += p.vx * k; p.y += p.vy * k;
      if (p.x < -20 || p.x > W + 20) p.vx *= -1;
      if (p.y < -20 || p.y > H + 20) p.vy *= -1;
    });
    ctx.lineWidth = 1;
    edges.forEach(([i, j]) => {
      const a = nodes[i], b = nodes[j];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (d > 260) return;
      const m = Math.hypot((a.x + b.x) / 2 - mouse.x, (a.y + b.y) / 2 - mouse.y);
      const alpha = (1 - d / 260) * .16 + (m < 180 ? (1 - m / 180) * .35 : 0);
      ctx.strokeStyle = `rgba(${col.line},${alpha})`;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    });
    if (pulsesOn && pulses.length < 14 && Math.random() < .08 * k && edges.length) {
      pulses.push({ e: edges[(Math.random() * edges.length) | 0], t: 0,
        sp: .004 + Math.random() * .01, rev: Math.random() < .5 });
    }
    pulses = pulses.filter(p => p.t <= 1);
    pulses.forEach(p => {
      p.t += p.sp * k;
      const a = nodes[p.e[p.rev ? 1 : 0]], b = nodes[p.e[p.rev ? 0 : 1]];
      const x = a.x + (b.x - a.x) * p.t, y = a.y + (b.y - a.y) * p.t;
      const g = ctx.createRadialGradient(x, y, 0, x, y, 8);
      g.addColorStop(0, `rgba(${col.dot},.9)`); g.addColorStop(1, `rgba(${col.dot},0)`);
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, 8, 0, 6.3); ctx.fill();
    });
    nodes.forEach(p => {
      const m = Math.hypot(p.x - mouse.x, p.y - mouse.y), near = m < 160 ? 1 - m / 160 : 0;
      ctx.fillStyle = `rgba(${col.dot},${.35 + near * .6})`;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r + near * 1.4, 0, 6.3); ctx.fill();
    });
    raf = requestAnimationFrame(frame);
  }
  const state = () => ({ speed, pulses: pulsesOn, running: running(), speed_ru: SPEED_RU[speed] });
  applyBody();
  return { start, stop, setSpeed, setPulses, state, SPEEDS, SPEED_RU,
    get speed() { return speed; }, get pulses() { return pulsesOn; } };
})();
