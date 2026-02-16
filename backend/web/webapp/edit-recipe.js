(() => {
  const tg = window.Telegram?.WebApp;

  const qs = new URLSearchParams(location.search);
  const recipeId = Number(qs.get("recipe_id") || 0);

  const $title = document.getElementById("title");
  const $category = document.getElementById("category");
  const $save = document.getElementById("save");
  const $err = document.getElementById("err");
  const $ok = document.getElementById("ok");
  const $btnDesc = document.getElementById("btn_desc");
  const $btnIng = document.getElementById("btn_ing");

  function draftKey() {
    return `sm_draft_recipe_${String(recipeId)}`;
  }

  function storageGet(key) {
    try {
      const v = sessionStorage.getItem(key);
      if (v != null) return v;
    } catch {}
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function storageSet(key, val) {
    try { sessionStorage.setItem(key, val); } catch {}
    try { localStorage.setItem(key, val); } catch {}
  }

  function storageRemove(key) {
    try { sessionStorage.removeItem(key); } catch {}
    try { localStorage.removeItem(key); } catch {}
  }

  function readDraft() {
    try {
      const raw = storageGet(draftKey());
      if (!raw) return null;
      const v = JSON.parse(raw);
      if (!v || typeof v !== "object") return null;
      return v;
    } catch {
      return null;
    }
  }

  function restoreDraftIntoForm() {
    const d = readDraft();
    if (!d) return;

    if (typeof d.title === "string" && d.title.trim()) {
      $title.value = d.title;
    }

    const draftCat = Number(d.category_id || 0);
    if (draftCat && $category) {
      // Apply only if option exists; otherwise leave current.
      const has = Array.from($category.options || []).some((o) => String(o.value) === String(draftCat));
      if (has) $category.value = String(draftCat);
    }
  }

  function writeDraft() {
    try {
      if (!recipeId) return;
      const prev = readDraft() || {};
      const titleNow = String($title?.value || "").trim();
      const categoryIdNow = Number($category?.value || 0);

      const title =
        titleNow ? titleNow : (typeof prev.title === "string" && prev.title.trim() ? prev.title : "");

      const category_id =
        Number.isFinite(categoryIdNow) && categoryIdNow
          ? categoryIdNow
          : (Number(prev.category_id || 0) || 0);

      storageSet(
        draftKey(),
        JSON.stringify({
          title,
          category_id,
          ts: Date.now(),
        })
      );
    } catch {}
  }

  function clearDraft() {
    storageRemove(draftKey());
  }

  async function putDraftToRedis() {
    try {
      await api(`/recipes/${recipeId}/draft`, {
        method: "PUT",
        body: JSON.stringify({
          title: ($title?.value || "").trim(),
          category_id: Number($category?.value || 0) || null,
        }),
      });
    } catch {
      // по возможности
    }
  }

  async function getDraftFromRedis() {
    try {
      return await api(`/recipes/${recipeId}/draft`, { method: "GET" });
    } catch {
      return null;
    }
  }

  async function restoreDraftFromRedisIntoForm() {
    const d = await getDraftFromRedis();
    if (!d) return;
    if (typeof d.title === "string" && d.title.trim()) $title.value = d.title;
    const cid = Number(d.category_id || 0);
    if (cid && $category) {
      const has = Array.from($category.options || []).some((o) => String(o.value) === String(cid));
      if (has) $category.value = String(cid);
    }
  }

  function parseHexColor(s) {
    if (!s || typeof s !== "string") return null;
    const v = s.trim();
    if (!v.startsWith("#")) return null;
    const hex = v.slice(1);
    if (hex.length === 3) {
      const r = parseInt(hex[0] + hex[0], 16);
      const g = parseInt(hex[1] + hex[1], 16);
      const b = parseInt(hex[2] + hex[2], 16);
      if ([r, g, b].some((x) => Number.isNaN(x))) return null;
      return { r, g, b };
    }
    if (hex.length === 6) {
      const r = parseInt(hex.slice(0, 2), 16);
      const g = parseInt(hex.slice(2, 4), 16);
      const b = parseInt(hex.slice(4, 6), 16);
      if ([r, g, b].some((x) => Number.isNaN(x))) return null;
      return { r, g, b };
    }
    return null;
  }

  function isDarkHex(hex) {
    const rgb = parseHexColor(hex);
    if (!rgb) return false;
    // Perceived brightness
    const y = (rgb.r * 299 + rgb.g * 587 + rgb.b * 114) / 1000;
    return y < 110;
  }

  function applyThemeParams(params) {
    if (!params) return;
    const root = document.documentElement;
    const bg = params.bg_color;
    const text = params.text_color;
    const hint = params.hint_color;
    const accent = params.button_color;
    const accentText = params.button_text_color;
    const secondary = params.secondary_bg_color;

    if (bg) root.style.setProperty("--bg", bg);
    if (text) root.style.setProperty("--text", text);
    if (text) root.style.setProperty("--fieldText", text);
    if (hint) root.style.setProperty("--muted", hint);
    if (secondary) root.style.setProperty("--card", secondary);
    if (accent) root.style.setProperty("--accent", accent);
    if (accentText) {
      root.style.setProperty("--accentText", accentText);
      root.style.setProperty("--accent-text", accentText);
    }

    // Поля ввода: не ставим field=secondary, иначе оно сливается с карточкой.
    // Подбираем контраст под тёмную/светлую тему.
    const dark = isDarkHex(bg) || isDarkHex(secondary);
    root.dataset.mode = dark ? "dark" : "light";
    root.setAttribute("data-theme", dark ? "dark" : "light");
    if (dark) {
      root.style.setProperty("--field", "rgba(255,255,255,0.10)");
      root.style.setProperty("--fieldBorder", "rgba(255,255,255,0.28)");
      root.style.setProperty("--field-border", "rgba(255,255,255,0.28)");
    } else {
      root.style.setProperty("--field", "rgba(255,255,255,0.92)");
      root.style.setProperty("--fieldBorder", "rgba(0,0,0,0.22)");
      root.style.setProperty("--field-border", "rgba(0,0,0,0.22)");
    }
  }

  function setErr(msg) {
    $err.textContent = msg || "";
    $ok.textContent = "";
  }

  function setOk(msg) {
    $ok.textContent = msg || "";
    $err.textContent = "";
  }

  function setBusy(isBusy) {
    $save.disabled = !!isBusy;
    $save.textContent = isBusy ? "Сохраняю..." : "Сохранить";
  }

  async function api(path, opts = {}) {
    const initData = tg?.initData || "";
    const headers = Object.assign(
      { "Content-Type": "application/json" },
      opts.headers || {},
      // ngrok free иногда возвращает HTML interstitial; этот заголовок его отключает.
      { "ngrok-skip-browser-warning": "1" },
      initData ? { "X-TG-INIT-DATA": initData } : {}
    );
    const res = await fetch(`/api/webapp${path}`, Object.assign({}, opts, { headers }));
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    const text = await res.text();
    let json;
    try { json = text ? JSON.parse(text) : null; } catch (e) {
      // Обычно это значит, что вместо JSON пришла HTML-страница (ngrok warning, 502 от nginx и т.п.).
      const preview = (text || "").slice(0, 400);
      throw new Error(`Non-JSON response (${res.status}, ${ct || "no-ct"}): ${preview}`);
    }
    if (!res.ok) {
      const detail = json?.detail || text || `HTTP ${res.status}`;
      throw new Error(detail);
    }
    if (json == null) throw new Error(`Empty JSON response (HTTP ${res.status})`);
    return json;
  }

  async function load() {
    if (!recipeId) throw new Error("Нет recipe_id в URL");
    if (!tg || !tg.initData) throw new Error("Откройте это окно из Telegram (WebApp initData отсутствует)");

    tg.ready();
    tg.expand();
    applyThemeParams(tg.themeParams);

    setBusy(true);
    const [cats, recipe] = await Promise.all([
      api(`/categories`, { method: "GET" }),
      api(`/recipes/${recipeId}`, { method: "GET" }),
    ]);
    setBusy(false);

    if (!Array.isArray(cats)) throw new Error("categories: expected array");
    $category.innerHTML = "";
    for (const c of cats) {
      const opt = document.createElement("option");
      opt.value = String(c.id);
      opt.textContent = c.name;
      $category.appendChild(opt);
    }

    // Base values from server
    $title.value = recipe.title || "";
    $category.value = String(recipe.category_id);

    // Restore unsaved edits when returning from other pages (or after reload).
    restoreDraftIntoForm();
    await restoreDraftFromRedisIntoForm();

    // Ensure draft exists even if user didn't change anything before navigating away.
    // This avoids "empty title after Back" on some WebViews with odd bfcache behavior.
    if (!readDraft()) writeDraft();
  }

  async function save() {
    setErr("");
    setOk("");
    setBusy(true);

    const title = ($title.value || "").trim();
    const categoryId = Number($category.value || 0);
    if (!title) throw new Error("Название не может быть пустым");
    if (!categoryId) throw new Error("Выберите категорию");

    await api(`/recipes/${recipeId}`, {
      method: "PATCH",
      body: JSON.stringify({
        title,
        category_id: categoryId,
      }),
    });
    clearDraft();

    try {
      tg?.sendData?.(JSON.stringify({ type: "recipe_updated", recipe_id: recipeId }));
    } catch {}

    setOk("Сохранено");
    setTimeout(() => tg?.close(), 350);
  }

  $btnDesc.addEventListener("click", async () => {
    writeDraft();
    await putDraftToRedis();
    location.href = `/webapp/edit-description.html?recipe_id=${encodeURIComponent(String(recipeId))}`;
  });

  $btnIng.addEventListener("click", async () => {
    writeDraft();
    await putDraftToRedis();
    location.href = `/webapp/edit-ingredients.html?recipe_id=${encodeURIComponent(String(recipeId))}`;
  });

  $save.addEventListener("click", () => {
    save()
      .catch((e) => setErr(String(e?.message || e)))
      .finally(() => setBusy(false));
  });

  $title.addEventListener("input", writeDraft);
  $category.addEventListener("change", writeDraft);
  window.addEventListener("pagehide", writeDraft);
  window.addEventListener("pageshow", (e) => {
    restoreDraftIntoForm();
    // Some WebViews restore a "blanked" form from bfcache. If title is empty, refetch.
    if (!($title?.value || "").trim()) {
      restoreDraftFromRedisIntoForm().finally(() => {
        if (!($title?.value || "").trim()) load().catch(() => {});
      });
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    restoreDraftIntoForm();
    if (!($title?.value || "").trim()) {
      restoreDraftFromRedisIntoForm().finally(() => {
        if (!($title?.value || "").trim()) load().catch(() => {});
      });
    }
  });

  load()
    .catch((e) => setErr(String(e?.message || e)))
    .finally(() => setBusy(false));
})();
