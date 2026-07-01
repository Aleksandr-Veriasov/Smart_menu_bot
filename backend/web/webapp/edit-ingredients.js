(() => {
  const tg = window.Telegram?.WebApp;

  const qs = new URLSearchParams(location.search);
  const recipeId = Number(qs.get("recipe_id") || 0);

  const $list = document.getElementById("ing_list");
  const $add  = document.getElementById("btn_add");
  const $save = document.getElementById("save");
  const $back = document.getElementById("back");
  const $err  = document.getElementById("err");
  const $ok   = document.getElementById("ok");

  const UNITS = ["", "г", "кг", "мл", "л", "ст.л.", "ч.л.", "стакан", "шт", "пучок", "щепотка", "по вкусу"];

  // Форматирует количество без незначащих нулей: "2.000" → "2", "1.500" → "1.5".
  function fmtQty(q) {
    if (q == null || q === "") return "";
    const n = Number(q);
    return Number.isFinite(n) ? String(n) : String(q);
  }

  // ── тема ────────────────────────────────────────────────────────────────────

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
    return (rgb.r * 299 + rgb.g * 587 + rgb.b * 114) / 1000 < 110;
  }

  function applyThemeParams(params) {
    if (!params) return;
    const root = document.documentElement;
    if (params.bg_color)           root.style.setProperty("--bg", params.bg_color);
    if (params.text_color)         root.style.setProperty("--text", params.text_color);
    if (params.text_color)         root.style.setProperty("--fieldText", params.text_color);
    if (params.hint_color)         root.style.setProperty("--muted", params.hint_color);
    if (params.secondary_bg_color) root.style.setProperty("--card", params.secondary_bg_color);
    if (params.button_color)       root.style.setProperty("--accent", params.button_color);
    if (params.button_text_color) {
      root.style.setProperty("--accentText", params.button_text_color);
      root.style.setProperty("--accent-text", params.button_text_color);
    }
    const dark = isDarkHex(params.bg_color) || isDarkHex(params.secondary_bg_color);
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

  // ── утилиты UI ──────────────────────────────────────────────────────────────

  function setErr(msg) { $err.textContent = msg || ""; $ok.textContent = ""; }
  function setOk(msg)  { $ok.textContent  = msg || ""; $err.textContent = ""; }
  function setBusy(v)  { $save.disabled = !!v; $save.textContent = v ? "Сохраняю..." : "💾 Сохранить"; }

  // ── строки ингредиентов ─────────────────────────────────────────────────────

  function buildUnitSelect(selected) {
    const sel = document.createElement("select");
    UNITS.forEach((u) => {
      const opt = document.createElement("option");
      opt.value = u;
      opt.textContent = u || "—";
      if (u === selected) opt.selected = true;
      sel.appendChild(opt);
    });
    return sel;
  }

  function addRow({ name = "", quantity = "", unit = "" } = {}) {
    const row = document.createElement("div");
    row.className = "ing-row";

    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.placeholder = "Название";
    nameInput.value = name;

    const qtyInput = document.createElement("input");
    qtyInput.type = "number";
    qtyInput.placeholder = "Кол-во";
    qtyInput.min = "0";
    qtyInput.step = "any";
    qtyInput.value = fmtQty(quantity);

    const unitSel = buildUnitSelect(unit || "");

    const removeBtn = document.createElement("button");
    removeBtn.className = "btn-remove";
    removeBtn.type = "button";
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => row.remove());

    row.append(nameInput, qtyInput, unitSel, removeBtn);
    $list.appendChild(row);
    return row;
  }

  function getRows() {
    return [...$list.querySelectorAll(".ing-row")].map((row) => {
      const [nameInput, qtyInput, unitSel] = row.querySelectorAll("input, select");
      const name = (nameInput.value || "").trim();
      const qtyRaw = (qtyInput.value || "").trim();
      const unit = unitSel.value || null;
      const quantity = qtyRaw !== "" ? parseFloat(qtyRaw) : null;
      return { name, quantity, unit };
    }).filter((r) => r.name);
  }

  // ── API ──────────────────────────────────────────────────────────────────────

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
      throw new Error(`Non-JSON response (${res.status}, ${ct || "no-ct"}): ${(text || "").slice(0, 400)}`);
    }
    if (!res.ok) throw new Error(json?.detail || text || `HTTP ${res.status}`);
    if (json == null) throw new Error(`Empty JSON response (HTTP ${res.status})`);
    return json;
  }

  function goBackTo(targetRecipeId) {
    try { tg?.BackButton?.hide(); } catch {}
    const rid = targetRecipeId || recipeId;
    location.replace(`/webapp/edit-recipe.html?recipe_id=${encodeURIComponent(String(rid))}&from=ing&t=${Date.now()}`);
  }

  // ── загрузка ─────────────────────────────────────────────────────────────────

  async function load() {
    if (!recipeId) throw new Error("Нет recipe_id в URL");
    if (!tg || !tg.initData) throw new Error("Откройте это окно из Telegram (WebApp initData отсутствует)");

    tg.ready();
    tg.expand();
    try { tg.requestFullscreen?.(); } catch {}
    applyThemeParams(tg.themeParams);

    try { tg.BackButton.show(); tg.BackButton.onClick(() => goBackTo(recipeId)); } catch {}

    setBusy(true);
    const recipe = await api(`/recipes/${recipeId}`, { method: "GET" });

    const details = Array.isArray(recipe.ingredient_details) ? recipe.ingredient_details : [];
    if (details.length > 0) {
      details.forEach((d) => addRow({ name: d.name, quantity: d.quantity, unit: d.unit || "" }));
    } else {
      // фолбэк на легаси список имён
      (recipe.ingredients || []).forEach((name) => addRow({ name }));
    }

    setBusy(false);
  }

  // ── сохранение ───────────────────────────────────────────────────────────────

  async function save() {
    setErr(""); setOk("");
    setBusy(true);

    const ingredients = getRows();
    if (ingredients.length === 0) {
      setErr("Добавьте хотя бы один ингредиент");
      return;
    }

    const updated = await api(`/recipes/${recipeId}`, {
      method: "PATCH",
      body: JSON.stringify({ ingredients }),
    });

    try { tg?.sendData?.(JSON.stringify({ type: "recipe_updated", recipe_id: recipeId })); } catch {}

    setOk("Сохранено");
    setTimeout(() => goBackTo(Number(updated?.id || recipeId) || recipeId), 250);
  }

  // ── события ──────────────────────────────────────────────────────────────────

  $add.addEventListener("click", () => { addRow(); $list.lastElementChild?.querySelector("input")?.focus(); });
  $save.addEventListener("click", () => save().catch((e) => setErr(String(e?.message || e))).finally(() => setBusy(false)));
  $back.addEventListener("click", () => goBackTo(recipeId));

  load().catch((e) => setErr(String(e?.message || e))).finally(() => setBusy(false));
})();
