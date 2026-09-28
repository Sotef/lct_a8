/* cmdk.js — палитра команд (Ctrl/⌘+K): разделы, задачи, темы, объекты, действия */
window.Cmdk = (() => {
  const { el, esc, ic } = UI;
  let node = null, veil = null;
  function close() { if (veil) veil.remove(); if (node) node.remove(); node = veil = null; }
  function open(getItems) {
    if (node) { close(); return; }
    veil = el(`<div class="veil" style="z-index:69"></div>`);
    node = el(`<div class="cmdk"><div class="ci">${ic("search")}<input placeholder="Команда, раздел, объект или задача…" autocomplete="off">
      <kbd>esc</kbd></div><div class="cl"></div>
      <div class="cf"><span><kbd>↑↓</kbd> навигация</span><span><kbd>↵</kbd> выбрать</span><span><kbd>Ctrl K</kbd> открыть/закрыть</span></div></div>`);
    const inp = node.querySelector("input"), list = node.querySelector(".cl");
    let sel = 0, shown = [], items = [];
    function draw() {
      const q = inp.value.trim().toLowerCase();
      shown = items.filter(i => !q || (i.title + " " + (i.hint || "") + " " + (i.kw || "")).toLowerCase().includes(q)).slice(0, 50);
      sel = Math.min(sel, Math.max(0, shown.length - 1));
      let html = "", group = null;
      shown.forEach((it, i) => {
        if (it.group !== group) { group = it.group; html += `<div class="cg">${esc(group)}</div>`; }
        html += `<div class="co ${i === sel ? "on" : ""}" data-i="${i}">${ic(it.icon || "chevron")}<span>${esc(it.title)}</span>
          <span class="s">${esc(it.hint || "")}</span></div>`;
      });
      list.innerHTML = html || (items.length ? UI.emptyState("ничего не найдено", "search") : `<div class="skel" style="height:160px"></div>`);
      const on = list.querySelector(".co.on");
      if (on) on.scrollIntoView({ block: "nearest" });
    }
    const pick = i => { const it = shown[i]; if (!it) return; close(); it.run(); };
    inp.oninput = () => { sel = 0; draw(); };
    inp.onkeydown = e => {
      if (e.key === "ArrowDown") { sel = Math.min(shown.length - 1, sel + 1); draw(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); draw(); e.preventDefault(); }
      else if (e.key === "Enter") pick(sel);
      else if (e.key === "Escape") close();
    };
    list.onclick = e => { const c = e.target.closest(".co"); if (c) pick(+c.dataset.i); };
    list.onmousemove = e => {
      const c = e.target.closest(".co");
      if (c && +c.dataset.i !== sel) {
        list.querySelectorAll(".co.on").forEach(x => x.classList.remove("on"));
        c.classList.add("on"); sel = +c.dataset.i;
      }
    };
    veil.onclick = close;
    document.body.append(veil, node);
    inp.focus();
    draw();
    Promise.resolve(getItems()).then(r => { items = r || []; if (node) draw(); }).catch(() => {});
  }
  return { open, close, isOpen: () => !!node };
})();
