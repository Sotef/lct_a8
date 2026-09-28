/* view_users.js — управление пользователями и ролями (только central) */
window.Views = window.Views || {};
Views.users = (() => {
  const { el, esc, ic, toast, dt } = UI;

  async function render(main, state) {
    let data;
    try { data = await API.get("/auth/admin/users"); }
    catch (e) { main.innerHTML = UI.emptyState(e.message, "lock", "err-state"); return; }
    const users = data.users || [];

    const head = el(`<div class="page-head">
      <div><div class="h1">Пользователи и доступ</div>
        <div class="sub">${users.length} учётных записей · RBAC: техник видит только свой район, диспетчер — все объекты
          (или поддерево района), центральный диспетчер — весь сервис</div></div>
      <div class="grow"></div>
      <button class="btn sm" id="nu">${ic("plus", "s")} Новый пользователь</button></div>`);

    const roleCard = el(`<div class="grid2e"><div class="card"><div class="ct">${ic("shield", "s")} Матрица ролей</div>
      <table class="tbl"><thead><tr><th>действие</th><th>техник</th><th>диспетчер</th><th>центральный</th></tr></thead><tbody>
      ${[["Пульт рисков и карта", "свой район", "да", "да"],
         ["Карточка прогноза", "просмотр", "решения", "решения"],
         ["Заявки (взять/закрыть)", "назначенные", "все", "все"],
         ["План ТО и автоформирование", "—", "да", "да"],
         ["Журнал аудита", "свои действия", "свои действия", "все действия"],
         ["Администрирование, лог, модели", "—", "—", "да"]].map(r => `<tr>
        <td>${esc(r[0])}</td><td class="muted">${esc(r[1])}</td><td class="muted">${esc(r[2])}</td>
        <td class="muted">${esc(r[3])}</td></tr>`).join("")}</tbody></table></div>
      <div class="card"><div class="ct">${ic("user", "s")} Все пользователи</div>
        <div class="stack" id="ulist"></div></div></div>`);
    const ulist = roleCard.querySelector("#ulist");
    users.forEach(u => {
      const row = el(`<div class="ritem" data-id="${u.id}">
        <div class="userchip" style="border:0;padding:0;flex:0 0 auto"><div class="ava">${esc((u.username || "?")[0].toUpperCase())}</div></div>
        <div class="mid"><div class="obj"><span class="nm">${esc(u.full_name || u.username)}</span>
            <span class="badge ${u.active ? "low" : "high"}">${u.active ? "активен" : "отключён"}</span></div>
          <div class="sen">${esc(u.username)} · ${esc(API.ROLE_RU[u.role] || u.role)}
            ${u.district ? ` · район ${esc(u.district)}` : ""}</div></div>
        <button class="btn xs ${u.active ? "dang" : "good"}" data-act="${u.active ? "off" : "on"}" data-id="${u.id}"
          data-name="${esc(u.username)}">${ic(u.active ? "ban" : "check", "s")} ${u.active ? "отключить" : "включить"}</button></div>`);
      row.querySelector("[data-act]").onclick = async e => {
        e.stopPropagation();
        const b = e.currentTarget, on = b.dataset.act === "on";
        const ok = await Overlay.confirm(on ? "Включить пользователя?" : "Отключить пользователя?",
          `${b.dataset.name}: ${on ? "доступ будет восстановлен" : "вход в систему станет недоступен"}`, on ? "Включить" : "Отключить");
        if (!ok) return;
        b.classList.add("loading");
        try {
          await API.post(`/auth/admin/users/${b.dataset.id}/active`, { active: on });
          toast(`пользователь ${b.dataset.name} ${on ? "включён" : "отключён"}`, "ok");
          API.invalidate("/audit");
          render(main, state);
        } catch (err) { toast(err.message, "err"); b.classList.remove("loading"); }
      };
      ulist.appendChild(row);
    });

    head.querySelector("#nu").onclick = () => openCreate(main, state);

    const F = UI.stage();
    F.appendChild(head); F.appendChild(roleCard);
    F.appendChild(el(`<div class="note">${ic("info", "s")} Все действия администратора (создание, блокировка)
      попадают в журнал аудита: раздел «Аудит» → администрирование.</div>`));
    UI.mount(main, F, { merge: false });
    return true;
  }

  async function openCreate(main, state) {
    const r = await Overlay.modal({
      title: "Новый пользователь", text: "Пароль ≥ 4 символов; район (object_id) ограничивает видимость объектов.",
      ok: "Создать", kind: "",
      fields: [
        { name: "username", label: "Логин", placeholder: "ivanov.od" },
        { name: "password", label: "Пароль", type: "password" },
        { name: "full_name", label: "ФИО", placeholder: "Иванов О. Д." },
        { name: "role", label: "Роль", type: "select", value: "dispatcher",
          options: [{ value: "dispatcher", label: "диспетчер" }, { value: "central", label: "центральный диспетчер" },
                    { value: "tech", label: "техник" }] },
        { name: "district", label: "Район (object_id), необязательно", placeholder: "например 5122" },
      ],
    });
    if (!r) return;
    if (!r.username || (r.password || "").length < 4) { toast("логин и пароль ≥ 4 символов обязательны", "warn"); return; }
    try {
      await API.post("/auth/admin/create-user", {
        username: r.username.trim(), password: r.password, role: r.role,
        full_name: r.full_name ? r.full_name.trim() : null,
        district: r.district ? r.district.trim() : null,
      });
      toast("пользователь создан", "ok", { title: r.username });
      API.invalidate("/audit");
      render(main, state);
    } catch (e) { toast(e.message, "err"); }
  }
  return { render, name: "Пользователи", icon: "users" };
})();
