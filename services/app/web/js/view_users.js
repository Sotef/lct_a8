/* view_users.js — управление пользователями (только central) */
window.Views = window.Views || {};
Views.users = (() => {
  const { el, esc, toast } = UI;
  const ROLE_RU = API.ROLE_RU;

  async function render(main, state) {
    main.innerHTML = `<div class="spin"></div>`;
    let data;
    try { data = await API.get("/auth/admin/users"); }
    catch (e) { main.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }

    const head = el(`<div class="topbar">
      <div><div class="h1">Пользователи</div>
      <div class="sub">${data.users.length} учётных записей · создание и роли (RBAC)</div></div></div>`);

    /* --- форма создания --- */
    const form = el(`<div class="card" style="margin-bottom:14px">
      <div class="ct">Новый пользователь</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px">
        <div class="fld"><label>Логин</label><input id="fu" placeholder="ivanov.od"></div>
        <div class="fld"><label>Пароль (≥4)</label><input id="fp" type="password"></div>
        <div class="fld"><label>ФИО</label><input id="fn" placeholder="Иванов О. Д."></div>
        <div class="fld"><label>Роль</label><select id="fr">
          <option value="dispatcher">диспетчер</option>
          <option value="central">центральный диспетчер</option>
          <option value="tech">техник</option></select></div>
        <div class="fld"><label>Район (object_id, для tech/dispatcher)</label>
          <input id="fd" placeholder="например 5122"></div>
      </div>
      <div style="display:flex;gap:10px;align-items:center">
        <button class="btn" id="fb">Создать</button>
        <span class="err" id="fe" style="margin:0"></span>
      </div>
      <div class="note">tech видит только объекты своего района; dispatcher с районом — поддерево района;
        central — все объекты. Действие попадает в audit_log.</div>
    </div>`);

    form.querySelector("#fb").onclick = async () => {
      const fe = form.querySelector("#fe");
      fe.textContent = "";
      const payload = {
        username: form.querySelector("#fu").value.trim(),
        password: form.querySelector("#fp").value,
        role: form.querySelector("#fr").value,
        full_name: form.querySelector("#fn").value.trim() || null,
        district: form.querySelector("#fd").value.trim() || null,
      };
      if (!payload.username || payload.password.length < 4) {
        fe.textContent = "логин и пароль ≥ 4 символов обязательны"; return;
      }
      try {
        await API.post("/auth/admin/create-user", payload);
        toast("пользователь создан ✓");
        render(main, state);
      } catch (e) { fe.textContent = e.message; }
    };

    /* --- таблица --- */
    const card = el(`<div class="card" style="padding:6px 0"><table class="tbl"><thead><tr>
      <th>Логин</th><th>ФИО</th><th>Роль</th><th>Район</th><th>Статус</th></tr></thead>
      <tbody></tbody></table></div>`);
    const tbody = card.querySelector("tbody");
    data.users.forEach(u => {
      tbody.appendChild(el(`<tr>
        <td><b>${esc(u.username)}</b></td>
        <td class="muted">${esc(u.full_name || "—")}</td>
        <td>${esc(ROLE_RU[u.role] || u.role)}</td>
        <td class="num muted">${esc(u.district || "—")}</td>
        <td><span class="badge ${u.active ? "low" : "high"}">${u.active ? "активен" : "отключён"}</span></td>
      </tr>`));
    });

    main.innerHTML = "";
    main.appendChild(head); main.appendChild(form); main.appendChild(card);
  }

  return { render, name: "Пользователи", icon: "👥" };
})();
