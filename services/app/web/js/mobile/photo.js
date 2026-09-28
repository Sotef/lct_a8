/* photo.js — фото с объекта: камера/галерея, сжатие на устройстве, вложение
   (MOBILE_PLAN §4.5). window.PhotoX = { pick, compress, attach, capture, url } */
window.PhotoX = (() => {
  const MAX_SIDE = 1280;      // длинная сторона ≤ 1280px
  const QUALITY = 0.72;       // JPEG q≈0.72
  const MAX_BYTES = 300 * 1024;
  const ACCEPT = "image/jpeg,image/png,image/webp";

  function pick() {
    return new Promise(resolve => {
      const inp = document.createElement("input");
      inp.type = "file";
      inp.accept = ACCEPT;
      inp.setAttribute("capture", "environment");
      inp.style.display = "none";
      inp.onchange = () => {
        const f = inp.files && inp.files[0] || null;
        inp.remove();
        resolve(f);
      };
      document.body.appendChild(inp);
      inp.click();
      window.addEventListener("focus", () => setTimeout(() => {
        if (inp.isConnected && (!inp.files || !inp.files.length)) { inp.remove(); resolve(null); }
      }, 1000), { once: true });
    });
  }

  async function compress(file) {
    if (!file) return null;
    let blob = file;
    try {
      const bmp = await createImageBitmap(file);
      const scale = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
      const w = Math.max(1, Math.round(bmp.width * scale));
      const h = Math.max(1, Math.round(bmp.height * scale));
      const cv = document.createElement("canvas");
      cv.width = w; cv.height = h;
      cv.getContext("2d").drawImage(bmp, 0, 0, w, h);
      if (bmp.close) bmp.close();
      const out = await new Promise(r => cv.toBlob(r, "image/jpeg", QUALITY));
      if (out && out.size) blob = out;
    } catch (e) { /* нет createImageBitmap/canvas — отдаём оригинал */ }
    return blob;
  }

  async function attach(ticketId, blob, name) {
    const path = `/maintenance/tickets/${ticketId}/attachments`;
    const fileName = name || `photo-${Date.now()}.jpg`;
    if (!blob) return { ok: false, detail: "нет файла" };
    if (blob.size > MAX_BYTES * 3) return { ok: false, detail: "файл слишком большой" };
    if (!Offline.isOnline()) {
      await Offline.enqueue({ method: "POST", path, files: [{ blob, name: fileName }] });
      return { ok: true, queued: true };
    }
    try {
      const fd = new FormData();
      fd.append("file", blob, fileName);
      const r = await fetch(API.BASE + path, {
        method: "POST",
        headers: Object.assign({ "X-Client": "pwa" },
          API.store.token ? { Authorization: "Bearer " + API.store.token } : {}),
        body: fd,
      });
      if (!r.ok) {
        let d = r.statusText;
        try { d = (await r.json()).detail || d; } catch (e) {}
        throw Object.assign(new Error(typeof d === "string" ? d : "ошибка загрузки"), { status: r.status });
      }
      return { ok: true, attachment: (await r.json()).attachment };
    } catch (e) {
      if (e.status === 0 || e.status === undefined) {   // сеть пропала в процессе
        await Offline.enqueue({ method: "POST", path, files: [{ blob, name: fileName }] });
        return { ok: true, queued: true };
      }
      throw e;
    }
  }

  /* полный сценарий: выбрать фото → сжать → приложить (онлайн или в очередь) */
  async function capture(ticketId) {
    const f = await pick();
    if (!f) return { ok: false, detail: "отменено" };
    const blob = await compress(f);
    return attach(ticketId, blob, f.name);
  }

  const url = id => `/api/v1/maintenance/attachments/${id}`;
  return { pick, compress, attach, capture, url, MAX_BYTES };
})();
