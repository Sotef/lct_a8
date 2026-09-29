/* card_object.js — карточка объекта (drawer): риски L2 по задачам, датчики, заявки, прогнозы */
Cards.object = (() => {
  const { el, esc, ic, fmt, riskColor } = UI;

  async function open(objectId, opts = {}) {
    const d = Overlay.drawer("Объект " + objectId);
    let obj, risks, tickets = [];
    try {
      [obj, risks] = await Promise.all([
        API.get(`/objects/${objectId}`),
        API.get(`/objects/${objectId}/risks`),
      ]);
    } catch (e) { d.body.innerHTML = UI.emptyState(e.message, "alert", "err-state"); return; }
    try {
      tickets = (await API.get(`/maintenance/tickets?object_id=${encodeURIComponent(objectId)}`
        + `&order=due&limit=200`)).items || [];
    } catch (e) { tickets = []; }
    /* маршрут движения нарушителя: сработки охранных каналов объекта (ответ заказчика №2) */
    let route = null;
    const oidEnc = encodeURIComponent(objectId);
    try { route = await API.get(`/objects/${oidEnc}/security-route?hours=72`); }
    catch (e) { route = null; }
    if (!d.isOpen()) return;

    const o = obj.object || {}, riskMap = {};
    (risks.risks || []).forEach(r => riskMap[r.task] = r);
    const maxR = Math.max(0, ...["fire", "access", "sensor", "wear"].map(t => (riskMap[t] || {}).risk30_max || 0));
    d.setTitle(`${ic("pin")} ${esc(o.name || objectId)}`);
    const b = d.body;
    b.innerHTML = "";

    b.appendChild(el(`<div class="rv row wrap" style="gap:8px">
      <span class="badge ${maxR >= .5 ? "high" : maxR >= .2 ? "mid" : "low"}">макс. риск ${fmt(maxR, 2)}</span>
      <span class="badge">${esc(o.type || "—")}</span>
      <span class="badge">район ${esc(o.district || "—")}</span>
      <span class="badge">${(obj.channels || []).length} каналов</span>
      ${o.parent_id ? `<span class="badge faint">родитель ${esc(o.parent_id)}</span>` : ""}</div>`));

    const rg = el(`<div class="dsec rv"><h4>${ic("target", "s")} Риски L2 по направлениям</h4>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px"></div></div>`);
    const rbox = rg.querySelector("div");
    API.TASKS.forEach(t => {
      const r = riskMap[t], m = API.TASK_META[t], v = r ? (r.risk30_max || 0) : 0;
      const cell = el(`<div class="pbox" style="text-align:center">
        <div class="l" style="color:${r ? "var(--text-dim)" : "var(--text-faint)"}">${ic(m.icon, "s")} ${esc(m.short)}</div>
        <div class="v" style="color:${r ? riskColor(v) : "var(--text-faint)"}" data-v="${v}">—</div>
        <div class="faint" style="font-size:10.5px">${r ? r.channel_count + " кан." : "нет данных"}</div>
        <div class="rbar"><i data-w="${Math.min(100, v * 100)}" style="background:${riskColor(v)}"></i></div></div>`);
      cell.onclick = () => goJournal(t, objectId);
      cell.style.cursor = "pointer";
      rbox.appendChild(cell);
    });
    b.appendChild(rg);
    rbox.querySelectorAll("[data-v]").forEach(n => UI.countUp(n, +n.dataset.v, { d: 2 }));
    FX.bars(rg);
    b.appendChild(el(`<div class="note">риски L2 — максимум risk30 по активным каналам направления (материализация L2).
      клик по направлению — журнал прогнозов по объекту</div>`));

    /* маршрут движения нарушителя (охранные сработки: люк, аварийный выход, дверь, движение, стекло) */
    const rp = (route && route.points) || [];
    if (rp.length) {
      b.appendChild(el(`<div class="dsec rv" id="secroute"><h4>${ic("shield", "s")}
        Маршрут движения нарушителя — охранные сработки (${rp.length})</h4>
        <div class="card flat" style="padding:10px 14px"><div class="stack">
          ${rp.slice(0, 40).map((p, i) => `<div class="row" style="gap:10px;align-items:center">
            <span class="badge">${i + 1}</span>
            <span class="num faint" style="min-width:74px">${esc(p.время)}</span>
            <span>${esc(p.тип_датчика || "—")}${p.название_датчика ? ` · ${esc(p.название_датчика)}` : ""}</span>
            ${p.тег_пикета ? `<span class="faint" style="font-size:11px">пикет ${esc(p.тег_пикета)}</span>` : ""}
            <span class="grow"></span>
            <span class="badge high">${esc(p.группа_события || "террор")}</span></div>`).join("")}
        </div></div>
        <div class="note">${esc((route && route.note) || "")} · точек: ${rp.length}, бакетов: ${(route && route.buckets) || 0}</div></div>`));
    }

    /* датчики */
    const ch = obj.channels || [];
    const sec = el(`<div class="dsec rv"><h4>${ic("cpu", "s")} Датчики и каналы (${ch.length})</h4>
      <input class="inp" type="search" id="chq" placeholder="фильтр по типу / названию / тегу…" style="margin-bottom:10px">
      <div class="card flat tscroll" style="max-height:320px"><table class="tbl"><thead><tr>
        <th>Датчик</th><th>Тип</th><th>Система</th><th>Тег</th></tr></thead><tbody id="chb"></tbody></table></div></div>`);
    const tb = sec.querySelector("#chb");
    const drawCh = q => {
      const term = (q || "").toLowerCase();
      const rows = ch.filter(c => !term || [c.name, c.sensor_type, c.system_type, c.tag, c.channel_id]
        .some(v => (v || "").toLowerCase().includes(term)));
      tb.innerHTML = rows.slice(0, 400).map(c => `<tr><td><b>${esc(c.name || c.channel_id)}</b></td>
        <td class="muted">${esc(c.sensor_type || "—")}</td><td class="muted">${esc(c.system_type || "—")}</td>
        <td class="num muted">${esc(c.tag || "—")}</td></tr>`).join("")
        || `<tr><td colspan="4" class="empty">не найдено</td></tr>`;
    };
    sec.querySelector("#chq").oninput = e => drawCh(e.target.value);
    drawCh("");
    b.appendChild(sec);

    /* заявки объекта */
    if (tickets.length) {
      const st = { suggested: "low", assigned: "info", in_progress: "mid", done: "low", cancelled: "" };
      b.appendChild(el(`<div class="dsec rv"><h4>${ic("wrench", "s")} Заявки и график работ по объекту (${tickets.length})</h4>
        <div class="stack">${tickets.slice(0, 14).map(t => `<div class="ritem" data-tid="${t.id}">
          <div class="mid"><div class="obj"><span class="nm">${esc(t.task_desc)} · ${esc(t.sensor_name || t.channel_id)}</span>
            <span class="badge ${st[t.status] || ""}">${esc(t.status_ru)}</span>
            ${t.overdue ? '<span class="badge high">просрочено</span>' : ""}</div>
          <div class="sen">${t.scheduled_at ? `выезд назначен на <b>${UI.dt(t.scheduled_at)}</b> · ` : ""}
            срок до ${UI.dt(t.due_to)} · приоритет ${esc(t.priority)} · источник ${esc(t.source)}
            ${t.assignee ? ` · ${esc(t.assignee)}` : ""}</div></div>
          <span class="go">${ic("chevron")}</span></div>`).join("")}</div></div>`));
      b.querySelectorAll("[data-tid]").forEach(n => n.onclick = () =>
        window.Views.tickets && Views.tickets.openCard(+n.dataset.tid, opts.state));
    }

    b.appendChild(el(`<div class="dsec rv"><h4>${ic("zap", "s")} Действия</h4>
      <div class="row wrap"><button class="btn sm ghost" id="goj">${ic("list", "s")} Открыть в журнале прогнозов</button>
      <button class="btn sm ghost" id="got">${ic("wrench", "s")} Заявки по задачам</button></div></div>`));
    b.querySelector("#goj").onclick = () => { Overlay.closeDrawer(); goJournal(opts.task || "wear", objectId); };
    b.querySelector("#got").onclick = () => { Overlay.closeDrawer(); navigateTo("tickets"); };
    UI.stagger(b);
  }

  function goJournal(task, objectId) {
    Overlay.closeDrawer();
    if (window.App) App.setObjFilter(objectId);
    navigateTo("forecasts", { task, obj: objectId });
  }
  function navigateTo(v, params) {
    if (window.App) return App.navigate(v, params);
    location.hash = "#/" + v;
  }
  return { open };
})();
