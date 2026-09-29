/* card_forecast.js — карточка прогноза (drawer): риск, горизонт, факторы, решение, заявка */
window.Cards = window.Cards || {};
Cards.forecast = (() => {
  const { el, esc, ic, fmt, dt, riskLevel, riskColor } = UI;
  const DEC = {
    confirm:    { t: "Подтвердить", s: "инцидент: проверка подтвердила тревожное сообщение", cls: "dang", icon: "alert" },
    reject:     { t: "Отклонить",   s: "ошибка / ложное срабатывание", cls: "good", icon: "x" },
    preventive: { t: "Профилактика", s: "ППР: планово-предупредительные работы", cls: "warn", icon: "wrench" },
  };
  const DEC_RU = { confirm: "подтверждено (инцидент)", reject: "отклонено (ошибка)",
                   preventive: "профилактика (ППР)" };
  /* класс тревожного сообщения по ответам заказчика: авария угрожает жизни,
     инцидент (питание/связь) — «слепая зона», косвенно допускает аварию */
  const CLASS_BADGE = {
    "авария":   { cls: "high", icon: "alert" },
    "инцидент": { cls: "mid", icon: "zap" },
  };

  async function open(id, opts = {}) {
    const role = API.store.user && API.store.user.role;
    const canDecide = ["dispatcher", "central"].includes(role);
    const d = Overlay.drawer("Прогноз #" + id);
    let c;
    try { c = await API.get(`/forecasts/${id}`); }
    catch (e) { d.body.innerHTML = UI.emptyState(e.message, "alert", "err-state"); return; }
    if (!d.isOpen()) return;
    const P = c.probabilities || {}, ru = UI.riskOf(P), lv = riskLevel(ru), tm = API.TASK_META[c.task] || {};
    d.setTitle(`${ic(tm.icon || "info")} ${esc(c.task_desc)} <span class="faint" style="font-weight:500;font-size:13px">· #${c.id}</span>`);
    const b = d.body;
    b.innerHTML = "";

    const hero = el(`<div class="hero rv"><div class="gw"></div><div>
      <div class="row wrap" style="gap:6px;margin-bottom:8px">
        <span class="badge ${lv.cls} ${lv.cls === "high" ? "pulse" : ""}">риск: ${lv.text}</span>
        ${c.rbam && c.rbam.plan ? `<span class="badge acc">${esc(c.rbam.plan)}</span>` : ""}
        ${P.risk30_cal !== null && P.risk30_cal !== undefined ? `<span class="badge info">калиброван</span>` : ""}
        ${c.ticket ? `<span class="badge info">${ic("wrench", "s")} заявка #${c.ticket.id} · ${esc(c.ticket.status)}</span>` : ""}
        ${c.класс_события ? `<span class="badge ${(CLASS_BADGE[c.класс_события] || {}).cls || "info"}">
          ${ic((CLASS_BADGE[c.класс_события] || {}).icon || "info", "s")} ${esc(c.класс_события)}: ${esc(c.группа_события || "—")}
          ${c.косвенно_авария ? '<span class="faint"> · косвенно допускает аварию</span>' : ""}</span>` : ""}
        ${c.охранный ? `<span class="badge">${ic("shield", "s")} охранный канал · маршрут нарушителя</span>` : ""}</div>
      <div style="font-size:19px;font-weight:800;font-family:var(--font-display)">${esc(c.object && c.object.name || c.object_id)}</div>
      <div class="muted" style="margin-top:5px">${ic("pin", "s")} ${esc(c.object && c.object.type || "")} · район ${esc(c.object && c.object.district || "—")}</div>
      <div class="muted" style="margin-top:4px">${ic("cpu", "s")} ${esc(c.sensor_type || "—")} · ${esc(c.channel_name || c.channel_id)}
        ${c.tag ? ` · <span class="num faint">${esc(c.tag)}</span>` : ""}</div>
      ${c.system_type ? `<div class="faint" style="margin-top:4px;font-size:12px">система: ${esc(c.system_type)}</div>` : ""}</div></div>`);
    hero.querySelector(".gw").appendChild(Charts.gauge(ru, "риск 30 дней"));
    b.appendChild(hero);

    const expDays = c.rbam && c.rbam.exp_days !== undefined ? c.rbam.exp_days : (c.horizon && c.horizon.exp_days);
    const pg = el(`<div class="dsec rv"><h4>${ic("target", "s")} Вероятности события</h4><div class="pgrid">
      ${[["≤ 24 ч", P.p24], ["≤ 72 ч", P.p72], ["≤ 30 дней", ru]].map(([l, v]) => `
        <div class="pbox"><div class="l">P ${l}</div><div class="v" style="color:${riskColor(v || 0)}" data-c="${v || 0}">—</div>
        <div class="rbar"><i data-w="${Math.min(100, (v || 0) * 100)}" style="background:${riskColor(v || 0)}"></i></div></div>`).join("")}
      <div class="pbox"><div class="l">ожидание, дней</div><div class="v" data-e="${expDays || 0}">—</div>
        <div class="faint" style="font-size:11px;margin-top:6px">E[время до события]</div></div></div></div>`);
    b.appendChild(pg);
    pg.querySelectorAll("[data-c]").forEach(n => UI.countUp(n, +n.dataset.c * 100, { d: 1, suffix: "%" }));
    pg.querySelectorAll("[data-e]").forEach(n => UI.countUp(n, +n.dataset.e, { d: 1 }));
    FX.bars(pg);

    const labels = (c.horizon && c.horizon.labels) || ["6ч", "12ч", "24ч", "48ч", "3д", "7д", "14д", "30д"];
    const surv = c.horizon && c.horizon.surv_points;
    const g2 = el(`<div class="dsec rv stack"></div>`);
    g2.appendChild(Charts.survival(surv, labels));
    g2.appendChild(Charts.eta(surv, labels));
    b.appendChild(g2);

    const fac = el(`<div class="dsec rv"><h4>${ic("sparkles", "s")} Почему модель так решила</h4>
      <div class="facbox"></div></div>`);
    const facbox = fac.querySelector(".facbox");
    const paintFactors = list => {
      facbox.innerHTML = "";
      facbox.appendChild(Charts.factors(list));
      fxBars(facbox);
    };
    const fxBars = root => requestAnimationFrame(() => requestAnimationFrame(() =>
      root.querySelectorAll("[data-w]").forEach(i => { i.style.width = i.dataset.w + "%"; })));
    if (c.factors && c.factors.length) {
      paintFactors(c.factors);
    } else {
      /* быстрый режим прокрута: факторы не считались массово — считаем по запросу */
      const box = el(`<div class="note">${ic("info", "s")} В быстром режиме прокрута SHAP-факторы
        для всех каналов не считаются. Рассчитаем их для этого прогноза по запросу — это ≈1 с.
        <div style="margin-top:8px"><button class="btn ghost sm" id="fx-go">
        ${ic("sparkles", "s")} Рассчитать факторы</button></div></div>`);
      facbox.appendChild(box);
      box.querySelector("#fx-go").onclick = async e => {
        const b = e.currentTarget;
        b.classList.add("loading");
        try {
          const r = await API.get(`/forecasts/${c.id}/factors?compute=true`);
          if (r.factors && r.factors.length) { paintFactors(r.factors); UI.toast("факторы рассчитаны", "ok"); }
          else { UI.toast("не удалось рассчитать факторы (нет субъектов/панели)", "warn"); }
        } catch (err) { UI.toast(err.message, "err"); }
        finally { b.classList.remove("loading"); }
      };
    }
    b.appendChild(fac);
    UI.stagger(b);
    renderRest(d, c, canDecide, opts, expDays);
  }

  function renderRest(d, c, canDecide, opts, expDays) {
    const { el, esc, ic, fmt, dt, riskColor } = UI;
    const b = d.body;
    b.appendChild(el(`<div class="dsec rv"><h4>${ic("wrench", "s")} Рекомендация</h4>
      <div class="card" style="padding:14px 16px;background:var(--grad-soft)">${esc(c.recommended_action || "—")}</div>
      ${c.preventive_order ? `<div class="note">${esc(c.preventive_order)}</div>` : ""}
      ${c.rbam ? `<div class="note">RBAM: score <b>${fmt(c.rbam.score, 3)}</b> = риск × severity <b>${fmt(c.rbam.severity, 2)}</b>
        × scale <b>${fmt(c.rbam.scale, 2)}</b> · ожидание ≈ ${fmt(expDays, 1)} дн</div>` : ""}</div>`));

    /* предсказано / произошло: факты журнала по этому каналу + ожидание по прогнозу */
    API.get(`/forecasts/${c.id}/facts?n=6`).then(f => {
      if (!d.isOpen() || !f || !f.summary) return;
      const items = f.items || [], s = f.summary;
      b.appendChild(el(`<div class="dsec rv"><h4>${ic("activity", "s")} Предсказано / произошло</h4>
        <div class="row wrap" style="gap:8px;margin-bottom:8px">
          <span class="badge info">прогноз выдан ${esc(f.выдано || "—")} · p24 = ${fmt(f.p24, 4)}</span>
          <span class="badge ${f.ожидается_событие ? "mid" : "low"}">${f.ожидается_событие
            ? `модель ожидает событие до ${esc(f.окно_до || "—")}` : "событие в горизонте 24 ч не ожидается"}</span>
          ${f.событие_в_этом_бакете ? '<span class="badge high">в этом бакете событие уже зафиксировано</span>' : ""}</div>
        ${items.length ? `<div class="card flat"><table class="tbl"><thead><tr>
            <th>произошло</th><th>что именно</th><th>предсказано</th></tr></thead><tbody>
          ${items.map(x => `<tr><td class="num">${esc(x.произошло)}</td>
            <td>${esc(x.тип_датчика || "—")}${x.похоже_на_ППР ? ' <span class="badge faint">ППР</span>' : ""}</td>
            <td>${x.предсказано ? `за ${x.предсказано_за_ч} ч · p24=${x.прогноз_p24}
              <div class="faint" style="font-size:10.5px">прогноз от ${esc(x.прогноз_бакет)}</div>`
              : '<span class="badge high">пропущено моделью</span>'}</td></tr>`).join("")}
        </tbody></table></div>` : '<div class="faint">по каналу в текущем круге происшествий не было</div>'}
        <div class="faint" style="font-size:11px">событий: ${s.events || 0} · предсказано: ${s.predicted || 0}
          (${s.recall === null || s.recall === undefined ? "—" : Math.round(s.recall * 100) + "%"}) ·
          попаданий алертов: ${s.hits || 0} из ${s.alerts || 0} ·
          медианное упреждение: ${s.median_lead_h === null ? "—" : s.median_lead_h + " ч"} ·
          порог p24 ≥ ${f.threshold}</div></div>`));
    }).catch(() => {});

    const ev = c.last_events || [];
    if (ev.length) b.appendChild(el(`<div class="dsec rv"><h4>${ic("activity", "s")} История прогнозов канала</h4>
      <div class="card flat"><table class="tbl"><thead><tr><th>бакет</th><th>risk30</th><th>p24</th><th>score</th></tr></thead>
      <tbody>${ev.map(e => `<tr><td class="num">${dt(e.bucket_ts)}</td>
        <td class="num" style="color:${riskColor(e.risk30 || 0)}">${fmt(e.risk30, 3)}</td>
        <td class="num">${fmt(e.p24, 3)}</td><td class="num">${fmt(e.score, 3)}</td></tr>`).join("")}</tbody></table></div></div>`));

    const hist = c.history || [];
    b.appendChild(el(`<div class="dsec rv"><h4>${ic("clock", "s")} История решений</h4>
      ${hist.length ? `<div class="timeline">${hist.map(h => `<div class="tl-i ${esc(h.decision)}">
        <b>${esc(DEC_RU[h.decision] || h.decision)}</b> · ${esc(h.responsible || "—")} · <span class="faint">${dt(h.created_at)}</span>
        ${h.comment ? `<div class="muted">${esc(h.comment)}</div>` : ""}</div>`).join("")}</div>`
        : `<div class="faint">решений пока нет</div>`}</div>`));
    b.appendChild(el(`<div class="note">модель <b>${esc(c.model_version || "—")}</b> · бакет ${dt(c.bucket_ts)} ·
      финальное решение принимает диспетчер — модель только прогнозирует</div>`));
    if (canDecide) renderDecision(d, c, opts);
  }

  function renderDecision(d, c, opts) {
    const { el, esc, ic } = UI;
    const f = d.foot;
    f.hidden = false;
    f.innerHTML = `<div class="row wrap" style="gap:10px;margin-bottom:8px">
        <label class="chk" style="gap:6px">дата выезда (для «Профилактика»)
          <input type="date" id="dsched" style="padding:4px 8px;border-radius:8px;
            border:1px solid var(--border);background:var(--bg-2)"></label>
        <span class="faint" style="font-size:11px">пусто — заявка без назначенной даты</span></div>
      <textarea class="inp" id="dc" rows="2" placeholder="Комментарий: например, «выявлено задымление, направлена бригада №3»"></textarea>
      <div class="decgrid">${Object.entries(DEC).map(([k, v]) => `<button class="btn ${v.cls}" data-v="${k}">${ic(v.icon)}
        <span>${v.t}</span><small>${v.s}</small></button>`).join("")}</div><div class="err" id="de"></div>`;
    f.querySelectorAll("[data-v]").forEach(btn => btn.onclick = async () => {
      const decision = btn.dataset.v, err = f.querySelector("#de");
      err.textContent = "";
      btn.classList.add("loading");
      try {
        const date = f.querySelector("#dsched").value;
        const r = await API.post(`/forecasts/${c.id}/decision`, {
          decision, responsible: API.store.user && API.store.user.username,
          comment: f.querySelector("#dc").value.trim() || null,
          scheduled_at: decision === "preventive" && date ? date + "T09:00:00" : null });
        UI.toast(decision === "preventive" && r.ticket_id ? `Заявка #${r.ticket_id} назначена` : "Запись добавлена в журнал аудита",
          "ok", { title: "Решение сохранено: " + DEC_RU[decision] });
        API.invalidate("/maintenance");
        API.invalidate("/audit");
        window.dispatchEvent(new CustomEvent("mc:changed", { detail: { kind: "decision", id: c.id } }));
        if (opts.onDecided) opts.onDecided(decision, r);
        open(c.id, opts);
      } catch (e) { err.textContent = e.message; btn.classList.remove("loading"); }
    });
  }
  return { open, DEC_RU };
})();
