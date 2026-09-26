/* view_plan.js — план превентивного обслуживания (план × тип канала) */
window.Views = window.Views || {};
Views.plan = (() => {
  const { el, esc, fmt } = UI;
  const TASK_META = API.TASK_META;
  let task = "wear";

  async function render(main, state) {
    main.innerHTML = `<div class="spin"></div>`;
    task = state.task || "wear";
    const data = await API.get(`/maintenance-plan?task=${task}`);

    const head = el(`<div class="topbar">
      <div><div class="h1">План ТО</div>
      <div class="sub">агрегат «горизонт обслуживания × тип канала» · границы по exp_days
      (&lt;7 д — текущий квартал, &lt;21 д — следующий, иначе плановый год)</div></div></div>`);

    const card = el(`<div class="card" style="padding:6px 0">
      <table class="tbl"><thead><tr>
        <th>План</th><th>Тип канала</th><th>Каналов</th><th>Ср. риск</th>
        <th>Σ score</th><th>Медиана exp, дн</th><th></th>
      </tr></thead><tbody></tbody></table></div>`);
    const tbody = card.querySelector("tbody");
    const rows = data.rows || [];
    if (!rows.length) tbody.appendChild(el(`<tr><td colspan="7" class="empty">нет данных — запустите прогнозный цикл</td></tr>`));
    const maxScore = Math.max(1, ...rows.map(r => r.score_сумма || 0));
    rows.forEach(r => {
      const tr = el(`<tr>
        <td><span class="badge ${r.plan === "текущий квартал" ? "high" : r.plan === "следующий квартал" ? "mid" : "low"}">${esc(r.plan)}</span></td>
        <td><b>${esc(r["тип_датчика"])}</b></td>
        <td class="num">${r["каналов"]}</td>
        <td class="num">${fmt(r["риск_средний"], 3)}</td>
        <td class="num">${fmt(r.score_сумма, 2)}</td>
        <td class="num">${fmt(r.exp_days_медиана, 1)}</td>
        <td><div class="rbar" style="width:120px;margin:0"><i style="width:${(r.score_сумма || 0) / maxScore * 100}%"></i></div></td>
      </tr>`);
      tbody.appendChild(tr);
    });

    const noteWrap = el(`<div><div class="note">Заявки формируются из топ-K по score = risk30 × severity(тип) ×
      scale(объект). Кнопка «в журнал» открывает прогнозы задачи для разбора.</div>
      <div style="margin-top:10px"><button class="btn ghost sm" id="jf">в журнал прогнозов →</button></div></div>`);
    noteWrap.querySelector("#jf").onclick = () => state.navigate && state.navigate("forecasts");

    main.innerHTML = "";
    main.appendChild(head); main.appendChild(card); main.appendChild(noteWrap);
  }

  return { render, name: "План ТО", icon: "▦" };
})();
