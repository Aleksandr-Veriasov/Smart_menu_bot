(() => {
  const tg = window.Telegram?.WebApp;

  const qs = new URLSearchParams(location.search);
  const recipeId = Number(qs.get("recipe_id") || 0);

  const $text = document.getElementById("desc_text");
  const $save = document.getElementById("save");
  const $back = document.getElementById("back");
  const $err = document.getElementById("err");
  const $ok = document.getElementById("ok");

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

  function autoGrow(textarea) {
    if (!textarea) return;
    const maxPx = Math.floor(window.innerHeight * 0.70);
    textarea.style.height = "auto";
    const next = Math.min(textarea.scrollHeight, maxPx);
    textarea.style.height = `${next}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxPx ? "auto" : "hidden";
  }

  async function api(path, opts = {}) {
    const initData = tg?.initData || "";
    const headers = Object.assign(
      { "Content-Type": "application/json" },
      opts.headers || {},
      { "ngrok-skip-browser-warning": "1" },
      initData ? { "X-TG-INIT-DATA": initData } : {}
    );
    const res = await fetch(`/api/webapp${path}`, Object.assign({}, opts, { headers }));
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    const text = await res.text();
    let json;
    try { json = text ? JSON.parse(text) : null; } catch {
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

  function goBackTo(targetRecipeId) {
    try { tg?.BackButton?.hide(); } catch {}
    // history.back() is unreliable in some Telegram WebViews (form state can be lost).
    // Force a fresh load of the main page.
    const rid = targetRecipeId || recipeId;
    const url = `/webapp/edit-recipe.html?recipe_id=${encodeURIComponent(String(rid))}&from=desc&t=${Date.now()}`;
    location.replace(url);
  }

  async function load() {
    if (!recipeId) throw new Error("Нет recipe_id в URL");
    if (!tg || !tg.initData) throw new Error("Откройте это окно из Telegram (WebApp initData отсутствует)");

    tg.ready();
    tg.expand();
    applyThemeParams(tg.themeParams);

    try {
      tg.BackButton.show();
      tg.BackButton.onClick(() => goBackTo(recipeId));
    } catch {}

    setBusy(true);
    const recipe = await api(`/recipes/${recipeId}`, { method: "GET" });
    $text.value = recipe.description || "";
    autoGrow($text);
    setBusy(false);
    setTimeout(() => $text.focus(), 0);
  }

  async function save() {
    setErr("");
    setOk("");
    setBusy(true);

    const description = ($text.value || "");
    const updated = await api(`/recipes/${recipeId}`, {
      method: "PATCH",
      body: JSON.stringify({ description }),
    });

    try {
      tg?.sendData?.(JSON.stringify({ type: "recipe_updated", recipe_id: recipeId }));
    } catch {}

    setOk("Сохранено");
    const nextId = Number(updated?.id || recipeId) || recipeId;
    setTimeout(() => goBackTo(nextId), 250);
  }

  $save.addEventListener("click", () => {
    save()
      .catch((e) => setErr(String(e?.message || e)))
      .finally(() => setBusy(false));
  });

  $back.addEventListener("click", () => goBackTo(recipeId));
  $text.addEventListener("input", () => autoGrow($text));
  window.addEventListener("resize", () => autoGrow($text));

  load()
    .catch((e) => setErr(String(e?.message || e)))
    .finally(() => setBusy(false));
})();
