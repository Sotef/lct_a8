/* view_tickets.js — канбан превентивных заявок: drag&drop со сменой статуса, карточка, комментарии */
window.Views = window.Views || {};
Views.tickets = (() => {
  const { el, esc, ic, fmt, dt } = UI;
  const COLS = [
    { k: "suggested", t: "Предложена", c: "var(--accent-2)", hint: "модель предложила ТО" },
    { k: "assigned", t: "Назначена", c: "var(--info)", hint: "ответственный определён" },
    { k: "in_progress", t: "В работе", c: "var(--warn)", hint: "бригада на объекте" },
    { k: "done", t: "Выполнена", c: "var(--ok)", hint: "закрыта с комментарием" },
    { k: "cancelled", t: "Отменена", c: "var(--text-faint)", hint: "ложное срабатывание / дубль" },
  ];
  const NEXT = {
    suggested: ["assigned", "in_progress", "cancelled"],
    assigned: ["in_progress", "done", "cancelled", "suggested"],
    in_progress: ["done", "assigned", "cancelled"],
    done: ["in_progress"],
    cancelled: ["suggested"],
  };
  let filterTask = "", q = "", showCancelled = true, items = [], canEdit = true, curState = null;
  let mineOnly = null;                       // «только мои» (на телефоне у техника включено)

  async function render(main, state, silent) {
    curState = state;
    const F = UI.stage();               // сборка offscreen — живой канбан не «пропадает»
    UI.quiet(main, silent);
    const role = API.store.user && API.store.user.role;
    canEdit = ["dispatcher", "central", "tech"].includes(role);
    /* направление для доски берём ТОЛЬКО из собственного фильтра раздела:
       ползунок в шапке не должен «прятать» заявки (казалось, что они пропали) */
    const task = filterTask;
    const mobile = !!(window.MOBILE && MOBILE.is());
    if (mineOnly === null) mineOnly = role === "tech";
    const qp = new URLSearchParams({ limit: 800 });
    if (task) qp.set("task", task);
    if (q) qp.set("q", q);
    if (mobile) { qp.set("order", "due"); qp.set("scope", "active"); }
    if (mineOnly) qp.set("mine", "1");
    const data = await API.get(`/maintenance/tickets?${qp}`).catch(() => ({ items: [] }));
    items = data.items || [];

    const head = el(`<div class="page-head">
      <div><div class="h1">Заявки на обслуживание</div>
        <div class="sub">${items.length} заявок · перетаскивайте карточки между колонками (проверяются допустимые переходы) ·
          ${esc(API.ROLE_RU[role] || role)}</div></div>
      <div class="grow"></div>
      <div class="row wrap">
        ${["dispatcher", "central"].includes(role) ? `<button class="btn sm" id="auto">${ic("sparkles", "s")} Автоформирование</button>` : ""}
        <button class="btn ghost sm" id="rf">${ic("refresh", "s")}</button></div></div>`);
    const tools = el(`<div class="toolrow">
      <input type="search" id="q" placeholder="поиск: объект, датчик, канал…" value="${esc(q)}">
      <select id="ft"><option value="">все направления</option>${API.TASKS.map(t =>
        `<option value="${t}" ${filterTask === t ? "selected" : ""}>${esc(API.TASK_META[t].label)}</option>`).join("")}</select>
      <label class="chk"><input type="checkbox" id="sc" ${showCancelled ? "checked" : ""}> показывать отменённые</label>
      <label class="chk"><input type="checkbox" id="mo" ${mineOnly ? "checked" : ""}> только мои</label>
      <span class="grow"></span><span class="faint">${items.length} записей</span></div>`);
    tools.querySelector("#q").oninput = UI.debounce(e => { q = e.target.value.trim(); render(main, state, true); }, 350);
    tools.querySelector("#ft").onchange = e => { filterTask = e.target.value; render(main, state, true); };
    tools.querySelector("#sc").onchange = e => { showCancelled = e.target.checked; render(main, state, true); };
    tools.querySelector("#mo").onchange = e => { mineOnly = e.target.checked; render(main, state, true); };
    head.querySelector("#rf").onclick = () => { API.invalidate("/maintenance"); render(main, state, true); };
    const autoB = head.querySelector("#auto");
    if (autoB) autoB.onclick = async e => {
      const b = e.currentTarget; b.classList.add("loading");
      try {
        const r = await API.post("/maintenance/auto-generate", { tasks: task ? [task] : null });
        UI.toast(r.created ? `создано заявок: ${r.created}` : "новых заявок нет", r.created ? "ok" : "info");
        API.invalidate("/maintenance");
        render(main, state, true);
      } catch (err) { UI.toast(err.message, "err"); b.classList.remove("loading"); }
    };

    if (mobile) {
      F.appendChild(head); F.appendChild(tools);
      F.appendChild(mobileBoard(main, state));
      F.appendChild(el(`<div class="note">${ic("info", "s")} Модель только <b>предлагает</b> заявку: назначение,
        перевод в работу и закрытие делает человек. Техник берёт в работу и закрывает назначенные ему заявки;
        для закрытия обязателен комментарий о выполненных работах. Фото с объекта прикладывается в карточке.</div>`));
      UI.mount(main, F, { merge: !!main.dataset.mounted, quiet: silent });
      main.dataset.mounted = "1";
      UI.stagger(main, ".m-item");
      return true;
    }

    const board = el(`<div class="kanban"></div>`);
    const colsShown = COLS.filter(c => !(c.k === "cancelled" && !showCancelled));
    board.style.setProperty("--cols", colsShown.length);   // оставшиеся колонки делят ширину
    colsShown.forEach(col => {
      const cards = items.filter(t => t.status === col.k);
      const node = el(`<div class="kcol" data-k="${col.k}">
        <div class="kh"><i style="background:${col.c}"></i> ${esc(col.t)}<span class="n">${cards.length}</span></div>
        <div class="kl"></div></div>`);
      const list = node.querySelector(".kl");
      if (!cards.length) list.appendChild(el(`<div class="faint" style="text-align:center;font-size:11.5px;padding:14px 6px">пусто · ${esc(col.hint)}</div>`));
      cards.forEach((t, i) => list.appendChild(ticketCard(t, col, i, main)));
      bindDrop(node, col.k, main, state);
      board.appendChild(node);
    });
    F.appendChild(head); F.appendChild(tools); F.appendChild(board);
    F.appendChild(el(`<div class="note">${ic("info", "s")} Модель только <b>предлагает</b> заявку: назначение, перевод
      в работу, закрытие и отмена — решения человека, каждое пишется в журнал аудита. Техник может брать в работу и
      закрывать назначенные ему заявки. Дату выезда диспетчер назначает в карточке заявки.</div>`));
    UI.mount(main, F, { merge: !!main.dataset.mounted, quiet: silent });
    main.dataset.mounted = "1";
    UI.stagger(main, ".rv-row");
    return true;
  }

  /* ---------- мобильный режим: табы по статусу + карточки ---------- */
  let mobileStatus = "";
  function mobileBoard(main, state) {
    const wrap = el(`<div></div>`);
    const tabs = el(`<div class="m-tabs"></div>`);
    const counts = {};
    items.forEach(t => { counts[t.status] = (counts[t.status] || 0) + 1; });
    const defs = [
      { k: "", t: "Все" },
      { k: "assigned", t: "Назначены" },
      { k: "in_progress", t: "В работе" },
      { k: "suggested", t: "Предложены" },
      { k: "done", t: "Выполнены" },
    ];
    defs.forEach(d => {
      const n = d.k ? (counts[d.k] || 0) : items.length;
      const b = el(`<button class="m-tab ${mobileStatus === d.k ? "on" : ""}" data-k="${d.k}">
        ${esc(d.t)}<span class="n">${n}</span></button>`);
      b.onclick = () => { mobileStatus = d.k; render(main, state, true); };
      tabs.appendChild(b);
    });
    wrap.appendChild(tabs);
    const shown = mobileStatus ? items.filter(t => t.status === mobileStatus) : items;
    if (!shown.length) { wrap.appendChild(el(UI.emptyState("заявок нет — измените фильтр", "check"))); return wrap; }
    const list = el(`<div class="m-list"></div>`);
    shown.forEach((t, i) => list.appendChild(ticketMobile(t, main, state, i)));
    wrap.appendChild(list);
    return wrap;
  }

  function ticketMobile(t, main, state, i) {
    const risk = t.risk || 0;
    const card = el(`<div class="m-item" data-id="${t.id}" style="--i:${Math.min(i, 20)}">
      <div class="m-item-top">
        <div style="min-width:0">
          <div class="m-item-title">${esc(t.object_name || t.object_id)}</div>
          <div class="m-item-sub">${esc(t.sensor_name || t.channel_id)} · ${esc(t.task_desc)}</div>
        </div>
        <div class="m-item-side">
          <span class="badge ${risk >= .5 ? "high" : risk >= .2 ? "mid" : "low"}">${fmt(risk, 2)}</span>
          <div class="faint" style="font-size:10.5px;margin-top:4px">${t.overdue ? "просрочено" : "до " + dt(t.due_to)}</div>
        </div>
      </div>
      <div class="row wrap" style="gap:6px">
        <span class="status-pill">${esc(t.status_ru)}</span>
        ${t.assignee ? `<span class="badge">${esc(t.assignee)}</span>` : ""}
        <span class="badge faint">#${t.id}</span></div>
      <div class="m-item-actions"></div></div>`);
    const acts = card.querySelector(".m-item-actions");
    (NEXT[t.status] || []).forEach(s => {
      const c = COLS.find(x => x.k === s) || { t: s };
      const cls = s === "done" ? "good" : s === "cancelled" ? "dang" : s === "in_progress" ? "warn" : "ghost";
      const b = el(`<button class="btn ${cls} sm">${esc(c.t)}</button>`);
      b.onclick = async ev => { ev.stopPropagation(); await quickMove(t, s, main, state); };
      acts.appendChild(b);
    });
    card.onclick = () => openCard(+t.id, state || curState, main);
    return card;
  }

  async function quickMove(t, status, main, state) {
    if (status === "done") {
      const m = await Overlay.modal({
        title: `Закрыть заявку #${t.id}`, text: "Опишите выполненные работы — комментарий обязателен.",
        fields: [{ name: "comment", type: "textarea", label: "Комментарий", placeholder: "что сделано" }],
        ok: "Закрыть", kind: "good",
      });
      if (!m) return;
      const cm = (m.comment || "").trim();
      if (!cm) { UI.toast("для закрытия нужен комментарий", "warn"); return; }
      return move(t, status, main, state, cm);
    }
    return move(t, status, main, state);
  }

  /* ---------- фото с объекта (вложение заявки) ---------- */
  function appendPhotos(body, t, main, state) {
    const sec = el(`<div class="dsec rv"><h4>${ic("eye", "s")} Фото с объекта</h4>
      <div class="photo-grid"></div>
      <button class="btn ghost sm" id="addph">${ic("plus", "s")} Добавить фото</button>
      <div class="faint" style="font-size:11px;margin-top:6px">фото сжимается на устройстве;
        в офлайне уходит в очередь и отправляется при появлении связи</div></div>`);
    const grid = sec.querySelector(".photo-grid");
    const load = async () => {
      const r = await API.get(`/maintenance/tickets/${t.id}/attachments`).catch(() => ({ items: [] }));
      grid.innerHTML = "";
      const its = r.items || [];
      if (!its.length) {
        grid.appendChild(el(`<div class="faint" style="grid-column:1/-1;font-size:12px">фото не приложены</div>`));
        return;
      }
      its.forEach(a => {
        const img = el(`<img src="${PhotoX.url(a.id)}" alt="${esc(a.filename)}" loading="lazy">`);
        img.onclick = () => window.open(PhotoX.url(a.id), "_blank");
        grid.appendChild(img);
      });
    };
    load();
    sec.querySelector("#addph").onclick = async ev => {
      if (!window.PhotoX) { UI.toast("модуль фото недоступен", "err"); return; }
      const b = ev.currentTarget;
      b.classList.add("loading");
      try {
        const r = await PhotoX.capture(t.id);
        if (r && r.queued) UI.toast("фото поставлено в очередь (офлайн)", "warn");
        else if (r && r.ok) UI.toast("фото приложено", "ok");
        await load();
      } catch (e) { UI.toast(e.message, "err"); }
      b.classList.remove("loading");
    };
    body.appendChild(sec);
    UI.stagger(sec);
  }

  function ticketCard(t, col, i, main) {
    const node = el(`<div class="tk ${esc(t.priority)} rv-row" draggable="true" style="--i:${Math.min(i, 16)}" data-id="${t.id}">
      <div class="tt">${esc(t.object_name || t.object_id)}</div>
      <div class="td">${esc(t.sensor_name || t.channel_id)}${t.sensor_type ? " · " + esc(t.sensor_type) : ""}</div>
      <div class="tf">
        <span class="badge ${t.task === "fire" ? "high" : t.task === "wear" ? "mid" : "acc"}">${esc(t.task_desc)}</span>
        ${t.risk !== null && t.risk !== undefined ? `<span class="badge ${t.risk >= .5 ? "high" : "mid"}">риск ${fmt(t.risk, 2)}</span>` : ""}
        ${t.exp_days ? `<span class="badge">≈${fmt(t.exp_days, 0)} дн</span>` : ""}
        ${t.overdue ? '<span class="badge high">просрочено</span>' : ""}
        <span class="badge faint">#${t.id}</span></div>
      <div class="faint" style="font-size:11px;margin-top:7px">срок до ${dt(t.due_to)}
        ${t.assignee ? ` · ${esc(t.assignee)}` : ""} · ${esc(t.source)}</div></div>`);
    node.addEventListener("dragstart", e => {
      if (!canEdit) { e.preventDefault(); return; }
      e.dataTransfer.setData("text/plain", node.dataset.id);
      node.classList.add("dragging");
    });
    node.addEventListener("dragend", () => node.classList.remove("dragging"));
    node.onclick = () => openCard(+node.dataset.id, curState, main);
    return node;
  }

  function bindDrop(node, status, main, state) {
    node.addEventListener("dragover", e => { e.preventDefault(); node.classList.add("over"); });
    node.addEventListener("dragleave", () => node.classList.remove("over"));
    node.addEventListener("drop", async e => {
      e.preventDefault(); node.classList.remove("over");
      const id = +e.dataTransfer.getData("text/plain");
      const t = items.find(x => x.id === id);
      if (!t || t.status === status) return;
      if (!(NEXT[t.status] || []).includes(status)) {
        const from = (COLS.find(c => c.k === t.status) || {}).t, to = (COLS.find(c => c.k === status) || {}).t;
        UI.toast(`«${from}» → «${to}» недопустимо для этой роли/статуса`, "warn", { title: "Правило перехода статусов" });
        return;
      }
      await move(t, status, main, state);
    });
  }

  async function move(t, status, main, state, comment, lock = true) {
    const payload = { status, comment: comment || null, assign_to_me: false };
    if (lock) payload.base_status = t.status;
    if (navigator.onLine === false) payload.offline_ts = new Date().toISOString();
    try {
      const r = await API.patch(`/maintenance/tickets/${t.id}`, payload);
      const label = (COLS.find(c => c.k === status) || {}).t;
      if (API.queued(r)) UI.toast(`заявка #${t.id}: «${label}» — ждёт отправки (офлайн)`, "warn",
        { title: "Действие в очереди" });
      else UI.toast(`заявка #${t.id}: ${label}`, "ok");
      API.invalidate("/maintenance"); API.invalidate("/audit");
      window.dispatchEvent(new CustomEvent("mc:changed", { detail: { kind: "ticket", id: t.id } }));
      if (main) render(main, state || curState);
    } catch (e) {
      if (e.status === 409) {
        const cur = (e.body && e.body.detail && e.body.detail.current) || {};
        const ok = await Overlay.confirm("Заявку изменили в другом месте",
          `Сейчас на сервере статус «${cur.status_ru || cur.status || "—"}», ваше устройство ждало «${t.status_ru}». ` +
          `Применить действие к новому состоянию?`,
          "Применить", "warn");
        if (ok) return move(t, status, main, state, comment, false);
        if (main) render(main, state || curState);
        return;
      }
      UI.toast(e.message, "err");
    }
  }
  /* карточка заявки: оценка модели, журнал, допустимые переходы */
  async function openCard(id, state, main) {
    let t = items.find(x => x.id === id);
    if (!t) {
      /* карточку можно открыть из другого раздела (объект, прогноз) — список заявок
         тогда ещё не загружен: подтягиваем заявку по id, а не просим «обновить список» */
      try {
        t = await API.get(`/maintenance/tickets/${id}`);
      } catch (e) {
        UI.toast(e.message === "заявка не найдена" ? `заявка #${id} не найдена` : e.message, "err");
        return;
      }
      if (t && t.id && !items.some(x => x.id === t.id)) items.push(t);
    }
    if (!t || !t.id) { UI.toast(`заявка #${id} недоступна`, "err"); return; }
    const d = Overlay.drawer(`Заявка #${t.id}`);
    d.setTitle(`${ic("wrench")} Заявка #${t.id} · <span class="faint" style="font-size:13px">${esc(t.status_ru)}</span>`);
    d.body.innerHTML = `<div class="rv">
      <div class="row wrap" style="gap:6px;margin-bottom:10px">
        <span class="badge ${t.priority === "high" ? "high" : t.priority === "medium" ? "mid" : "low"}">приоритет ${esc(t.priority)}</span>
        <span class="badge">${esc(t.task_desc)}</span><span class="badge">источник ${esc(t.source)}</span>
        ${t.overdue ? '<span class="badge high pulse">просрочено</span>' : ""}</div>
      <div style="font-size:18px;font-weight:800">${esc(t.object_name || t.object_id)}</div>
      <div class="muted" style="margin-top:6px">${ic("cpu", "s")} ${esc(t.sensor_name || t.channel_id)}
        ${t.sensor_type ? ` · ${esc(t.sensor_type)}` : ""} · район ${esc(t.district || "—")}</div>
      <div class="muted" style="margin-top:4px">${ic("clock", "s")} срок до ${dt(t.due_to)}
        ${t.scheduled_at ? ` · <b>назначено на ${dt(t.scheduled_at)}</b>` : " · дата выезда не назначена"}
        ${t.assignee ? ` · исполнитель ${esc(t.assignee)}` : " · исполнитель не назначен"}</div>
      <div class="muted" style="margin-top:4px">${ic("activity", "s")} план ТО:
        возраст ${t.age_years != null ? fmt(t.age_years, 1) + " лет" : "—"} ·
        норматив ${t.norm_due ? dt(t.norm_due) : "—"}
        ${t.campaign ? ' · <span class="badge faint">кампания/ППР</span>' : ""}</div></div>
      <div class="dsec rv"><h4>${ic("target", "s")} Оценка модели</h4><div class="pgrid">
        <div class="pbox"><div class="l">риск 30 дней</div><div class="v" data-c="${t.risk || 0}">—</div>
          <div class="rbar"><i data-w="${Math.min(100, (t.risk || 0) * 100)}" style="background:${UI.riskColor(t.risk || 0)}"></i></div></div>
        <div class="pbox"><div class="l">p24</div><div class="v" data-p="${t.p24 || 0}">—</div></div>
        <div class="pbox"><div class="l">ожидание, дней</div><div class="v" data-e="${t.exp_days || 0}">—</div></div>
        <div class="pbox"><div class="l">score</div><div class="v" data-s="${t.score || 0}">—</div></div></div>
        ${t.rationale ? `<div class="faint" style="margin-top:8px;font-size:11px">почему такая дата:
          прогноз ${t.rationale["прогноз_дней"] != null ? fmt(t.rationale["прогноз_дней"], 1) + " дн" : "—"} ·
          норматив ${t.rationale["норматив"] ? String(t.rationale["норматив"]).slice(0, 10) : "—"} ·
          возраст ${t.rationale["возраст_лет"] != null ? fmt(t.rationale["возраст_лет"], 1) + " лет" : "—"} ·
          severity ${t.rationale["severity"] != null ? fmt(t.rationale["severity"], 2) : "—"} ·
          эффективный порог ${t.rationale["min_risk_эффективный"] != null ? fmt(t.rationale["min_risk_эффективный"], 2) : "—"}
          ${t.rationale["кампания"] ? " · <b>кампанийная неделя</b>" : ""}</div>` : ""}</div></div>
      <div class="dsec rv"><h4>${ic("info", "s")} Журнал заявки</h4>
        <div class="timeline"><div class="tl-i"><b>создана</b> · <span class="faint">${dt(t.created_at)}</span>
          <div class="muted">источник: ${esc(t.source === "auto" ? "автоформирование по прогнозу"
            : t.source === "decision" ? "решение диспетчера «профилактика»" : "создана вручную")}</div></div>
        ${t.updated_at ? `<div class="tl-i"><b>обновлена</b> · <span class="faint">${dt(t.updated_at)}</span></div>` : ""}
        ${(t.comment || "").split("\n").filter(Boolean).map(c => `<div class="tl-i"><span class="muted">${esc(c)}</span></div>`).join("")}
        </div></div>
      ${t.prediction_id ? `<div class="dsec rv"><h4>${ic("zap", "s")} Связи</h4>
        <button class="btn ghost sm" id="gp">${ic("target", "s")} Открыть исходный прогноз #${t.prediction_id}</button></div>` : ""}`;
    d.body.querySelector("[data-c]") && UI.countUp(d.body.querySelector("[data-c]"), (t.risk || 0) * 100, { d: 1, suffix: "%" });
    d.body.querySelector("[data-p]") && UI.countUp(d.body.querySelector("[data-p]"), (t.p24 || 0) * 100, { d: 1, suffix: "%" });
    d.body.querySelector("[data-e]") && UI.countUp(d.body.querySelector("[data-e]"), t.exp_days || 0, { d: 1 });
    d.body.querySelector("[data-s]") && UI.countUp(d.body.querySelector("[data-s]"), t.score || 0, { d: 2 });
    FX.bars(d.body); UI.stagger(d.body);
    const gp = d.body.querySelector("#gp");
    if (gp) gp.onclick = () => Cards.forecast.open(t.prediction_id,
      { onDecided: () => { Overlay.closeDrawer(); if (main) render(main, state || curState); } });
    appendPhotos(d.body, t, main, state);

    if (!canEdit) return;
    const f = d.foot;
    f.hidden = false;
    const opts = NEXT[t.status] || [];
    f.innerHTML = `<div class="row wrap" style="gap:10px;margin-bottom:8px">
        <label class="chk" style="gap:6px">дата выезда
          <input type="date" id="tsched" value="${(t.scheduled_at || "").slice(0, 10)}"
            style="padding:4px 8px;border-radius:8px;border:1px solid var(--border);background:var(--bg-2)"></label>
        <button class="btn ghost xs" id="tsave">${ic("check", "s")} сохранить дату</button>
        <span class="faint" style="font-size:11px">${t.scheduled_at ? "назначено " + dt(t.scheduled_at) : "дата не назначена"}</span>
      </div>
      <div class="row wrap" style="gap:8px;margin-bottom:6px;align-items:center">
        <label class="chk" style="gap:6px">что устранено (по «Неисправен»)
          <select id="trs" style="padding:4px 8px;border-radius:8px;border:1px solid var(--border);background:var(--bg-2)">
            <option value="">— не указано</option>
            ${["автомат", "кабель", "контактор", "модуль связи", "питание шкафа", "прочее"]
              .map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join("")}
          </select></label>
        <span class="faint" style="font-size:11px">перечень согласован с заказчиком (ремонт: автомат, кабель,
          контактор, модуль связи, питание шкафа; причина может быть и вне коллектора — РСО, повреждение в земле)</span>
      </div>
      <textarea class="inp" id="cm" rows="2" placeholder="комментарий к действию (попадёт в журнал заявки и аудит)"></textarea>
      <div class="row wrap">${opts.map(s => {
        const c = COLS.find(x => x.k === s) || { t: s };
        const cls = s === "done" ? "good" : s === "cancelled" ? "dang" : s === "in_progress" ? "warn" : "ghost";
        const icn = s === "done" ? "check" : s === "cancelled" ? "ban" : "chevron";
        return `<button class="btn sm ${cls}" data-s="${s}">${ic(icn, "s")} ${esc(c.t)}</button>`;
      }).join("")}</div><div class="err" id="te"></div>`;
    const saveDate = async () => {
      const v = f.querySelector("#tsched").value;
      try {
        await API.patch(`/maintenance/tickets/${t.id}`,
          { status: t.status, scheduled_at: v ? v + "T09:00:00" : null, base_status: t.status });
        UI.toast(v ? `выезд назначен на ${v}` : "дата снята", "ok");
        API.invalidate("/maintenance"); API.invalidate("/audit");
        Overlay.closeDrawer();
        if (main) await render(main, state || curState);
      } catch (e) { UI.toast(e.message, "err"); }
    };
    f.querySelector("#tsave").onclick = saveDate;
    f.querySelector("#tsched").onchange = saveDate;
    f.querySelectorAll("[data-s]").forEach(b => b.onclick = async () => {
      const status = b.dataset.s, cm0 = f.querySelector("#cm").value.trim();
      const rs = ((f.querySelector("#trs") || {}).value || "").trim();
      const cm = cm0 + (rs ? `${cm0 ? " · " : ""}устранено: ${rs}` : "");
      if (status === "done" && !cm0) {
        f.querySelector("#te").textContent = "для закрытия заявки нужен комментарий о выполненных работах";
        return;
      }
      b.classList.add("loading");
      Overlay.closeDrawer();
      await move(t, status, main, state || curState, cm);
    });
  }

  return { render, openCard, name: "Заявки", icon: "wrench" };
})();
