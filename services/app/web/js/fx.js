/* fx.js — микро-взаимодействия: spotlight, tilt, ripple, скользящие индикаторы */
window.FX = (() => {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const coarse = matchMedia("(pointer: coarse)").matches;   // телефон/планшет: без tilt/ripple

  function bindGlobal() {
    document.addEventListener("pointermove", e => {
      const s = e.target.closest && e.target.closest(".spot, .kpi");
      if (s) {
        const r = s.getBoundingClientRect();
        s.style.setProperty("--mx", (e.clientX - r.left) + "px");
        s.style.setProperty("--my", (e.clientY - r.top) + "px");
      }
      const t = e.target.closest && e.target.closest("[data-tilt]");
      if (t && !reduced && !coarse) {
        const r = t.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width - .5, py = (e.clientY - r.top) / r.height - .5;
        t.style.transform = `perspective(900px) rotateX(${(-py * 7).toFixed(2)}deg) rotateY(${(px * 9).toFixed(2)}deg)`;
      }
    }, { passive: true });
    document.addEventListener("pointerout", e => {
      const t = e.target.closest && e.target.closest("[data-tilt]");
      if (t && !t.contains(e.relatedTarget)) t.style.transform = "";
    });
    document.addEventListener("pointerdown", e => {
      const b = e.target.closest && e.target.closest(".btn, .chip, .seg button, .nav-item");
      if (!b || reduced || coarse) return;
      const r = b.getBoundingClientRect(), s = Math.max(r.width, r.height);
      const rp = document.createElement("span");
      rp.className = "ripple";
      rp.style.cssText = `width:${s}px;height:${s}px;left:${e.clientX - r.left - s / 2}px;top:${e.clientY - r.top - s / 2}px`;
      if (getComputedStyle(b).position === "static") b.style.position = "relative";
      b.style.overflow = "hidden";
      b.appendChild(rp); setTimeout(() => rp.remove(), 700);
    });
  }

  /* скользящий индикатор под активным элементом (сегменты, чипы, навигация) */
  function slider(container, indSel, activeSel) {
    const ind = container.querySelector(indSel), on = container.querySelector(activeSel);
    if (!ind) return;
    ind.setAttribute("data-keep", "");          // индикатор принадлежит механизму, а не разметке
    if (!on) { ind.style.opacity = 0; return; }
    ind.style.opacity = 1;
    /* первая установка — без анимации: иначе индикатор «проезжает» от левого края до выбранной кнопки */
    const first = !ind.dataset.placed;
    if (first) ind.style.transition = "none";
    /* offsetLeft/Top считаются от padding-box контейнера (position:relative) — как и left:0 у индикатора */
    if (ind.classList.contains("nav-ind")) {
      ind.style.transform = `translateY(${on.offsetTop}px)`; ind.style.height = on.offsetHeight + "px";
    } else {
      ind.style.width = on.offsetWidth + "px"; ind.style.transform = `translateX(${on.offsetLeft}px)`;
    }
    ind.dataset.placed = "1";
    if (first) { void ind.offsetWidth; ind.style.transition = ""; }
  }
  /* сегментный переключатель: .seg > button[data-*]; onPick(button) */
  function seg(node, onPick) {
    if (!node.querySelector(".seg-ind")) {
      const ind = document.createElement("i");
      ind.className = "seg-ind";
      ind.setAttribute("data-keep", "");      // позицию задаёт механизм, разметка её не трогает
      node.prepend(ind);
    }
    const upd = () => slider(node, ".seg-ind", "button.on");
    node.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
      if (b.classList.contains("on")) return;
      node.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
      upd(); onPick && onPick(b);
    }));
    /* ширина кнопок известна только когда раздел уже в DOM: пересчитываем по первому
       же изменению размера контейнера (ResizeObserver), плюс подстраховка через rAF/таймер */
    if (window.ResizeObserver && !node._ro) {
      node._ro = new ResizeObserver(() => upd());
      node._ro.observe(node);
    }
    upd();
    requestAnimationFrame(upd);
    setTimeout(upd, 80);
    return upd;
  }
  /* пересчёт всех индикаторов (после мягкого обновления раздела: ширина кнопок могла измениться) */
  function refreshSliders(root) {
    (root || document).querySelectorAll(".seg").forEach(n => slider(n, ".seg-ind", "button.on"));
    document.querySelectorAll(".chip-ind").forEach(i => i.setAttribute("data-keep", ""));
    document.querySelectorAll(".nav-ind").forEach(i => i.setAttribute("data-keep", ""));
    const chips = document.querySelector(".chips");
    if (chips) slider(chips, ".chip-ind", ".chip.on");
    const navs = document.getElementById("navs");
    if (navs) slider(navs, ".nav-ind", ".nav-item.on");
  }
  /* анимированная полоска ширины (после вставки в DOM) */
  function bars(root) {
    requestAnimationFrame(() => requestAnimationFrame(() =>
      root.querySelectorAll("[data-w]").forEach(i => { i.style.width = i.dataset.w + "%"; })));
  }
  return { bindGlobal, slider, seg, bars, refreshSliders, reduced };
})();
