/* overlays.js — drawer (карточки), modal / confirm */
window.Overlay = (() => {
  const { el, esc, ic } = UI;
  let drawerNode = null, veilNode = null, onCloseCb = null;

  function closeDrawer(instant) {
    if (!drawerNode) return;
    const d = drawerNode, v = veilNode;
    drawerNode = veilNode = null;
    document.removeEventListener("keydown", escKey);
    if (onCloseCb) { const cb = onCloseCb; onCloseCb = null; try { cb(); } catch (e) {} }
    if (instant) { d.remove(); v.remove(); return; }
    d.classList.add("out"); v.classList.add("out");
    setTimeout(() => { d.remove(); v.remove(); }, 340);
  }
  const escKey = e => { if (e.key === "Escape" && !document.querySelector(".modal-wrap, .cmdk")) closeDrawer(); };
  /* открывает drawer со скелетоном; возвращает {root, body, foot, setTitle, isOpen} */
  function drawer(title, onClose) {
    closeDrawer(true);
    veilNode = el(`<div class="veil"></div>`);
    drawerNode = el(`<aside class="drawer" role="dialog" aria-modal="true">
      <div class="dx"><div class="t">${esc(title || "")}</div>
        <button class="icbtn" data-x aria-label="закрыть">${ic("x")}</button></div>
      <div class="dbody"><div class="skel" style="height:140px;margin-bottom:14px"></div>
        <div class="skel" style="height:220px;margin-bottom:14px"></div><div class="skel" style="height:160px"></div></div>
      <div class="dfoot" hidden></div></aside>`);
    veilNode.onclick = () => closeDrawer();
    drawerNode.querySelector("[data-x]").onclick = () => closeDrawer();
    document.body.append(veilNode, drawerNode);
    document.addEventListener("keydown", escKey);
    onCloseCb = onClose || null;
    const root = drawerNode;
    return { root, body: root.querySelector(".dbody"), foot: root.querySelector(".dfoot"),
      setTitle: t => { root.querySelector(".dx .t").innerHTML = t; }, isOpen: () => drawerNode === root };
  }

  const fieldHtml = f => {
    if (f.type === "select") return `<select name="${f.name}">${f.options.map(o =>
      `<option value="${esc(o.value)}" ${o.value === f.value ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select>`;
    if (f.type === "textarea") return `<textarea name="${f.name}" placeholder="${esc(f.placeholder || "")}">${esc(f.value || "")}</textarea>`;
    return `<input name="${f.name}" type="${f.type || "text"}" value="${esc(f.value || "")}" placeholder="${esc(f.placeholder || "")}">`;
  };
  /* modal -> Promise<объект полей | {} | null(отмена)> */
  function modal({ title, text = "", fields = [], ok = "OK", cancel = "Отмена", kind = "" }) {
    return new Promise(resolve => {
      const wrap = el(`<div class="modal-wrap"><div class="veil" style="position:absolute;inset:0;z-index:0"></div>
        <div class="modal" style="position:relative;z-index:1" role="dialog" aria-modal="true">
          <h3>${esc(title)}</h3>${text ? `<div class="muted" style="font-size:13px">${text}</div>` : ""}
          <form style="margin-top:14px">${fields.map(f =>
            `<div class="fld"><label>${esc(f.label)}</label>${fieldHtml(f)}</div>`).join("")}
          <div class="acts"><button type="button" class="btn ghost" data-c>${esc(cancel)}</button>
            <button type="submit" class="btn ${kind}">${esc(ok)}</button></div></form></div></div>`);
      const done = v => { wrap.remove(); document.removeEventListener("keydown", k); resolve(v); };
      const k = e => { if (e.key === "Escape") done(null); };
      wrap.querySelector("[data-c]").onclick = () => done(null);
      wrap.querySelector(".veil").onclick = () => done(null);
      wrap.querySelector("form").onsubmit = e => {
        e.preventDefault();
        const out = {};
        new FormData(e.target).forEach((v, key) => { out[key] = v; });
        done(out);
      };
      document.addEventListener("keydown", k);
      document.body.appendChild(wrap);
      const first = wrap.querySelector("input, textarea, select, button[type=submit]");
      setTimeout(() => first && first.focus(), 60);
    });
  }
  const confirm = (title, text, ok = "Подтвердить", kind = "") =>
    modal({ title, text, ok, kind }).then(v => v !== null);
  return { drawer, closeDrawer, modal, confirm };
})();
