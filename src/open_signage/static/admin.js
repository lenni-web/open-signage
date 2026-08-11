const playlist = document.querySelector("#playlist");
const empty = document.querySelector("#empty");
const message = document.querySelector("#message");
const uploadWarning = document.querySelector("#upload-warning");
const textForm = document.querySelector("#text-form");
const textPreviewDialog = document.querySelector("#text-preview-dialog");
let editingTextItem = null;
let previewObjectUrl = null;
let libraryItems = [];
let applicationUpdateInProgress = false;
let applicationReloadScheduled = false;
let schedulingItem = null;
let schedulingPlaylist = null;
let playlists = [];
let editingLibraryImage = null;
let displayControlDirty = false;
let currentDeviceMode = "standalone";
const selectedMediaIds = new Set();

function updateAdminClock() {
  const clock = document.querySelector("#admin-clock");
  const now = new Date();
  clock.dateTime = now.toISOString();
  clock.textContent = now.toLocaleTimeString("de-DE", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  clock.title = now.toLocaleDateString("de-DE", {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
  });
}

updateAdminClock();
window.setInterval(updateAdminClock, 1000);

function notify(text, isError = false, duration = 3000) {
  message.textContent = text;
  message.className = isError ? "show error" : "show";
  window.setTimeout(() => { message.className = ""; }, duration);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && path !== "/api/system/login") showLogin();
    throw new Error(body.detail || `Fehler ${response.status}`);
  }
  return response.status === 204 ? null : response.json();
}

function uploadWithProgress(path, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", path);
    request.upload.addEventListener("progress", event => {
      if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100));
    });
    request.addEventListener("load", () => {
      const body = (() => { try { return JSON.parse(request.responseText); } catch (_) { return {}; } })();
      if (request.status >= 200 && request.status < 300) resolve(body);
      else reject(new Error(body.detail || `Fehler ${request.status}`));
    });
    request.addEventListener("error", () => reject(new Error("Upload-Verbindung fehlgeschlagen")));
    request.send(formData);
  });
}

function uploadProgress(form) {
  let progress = form.querySelector("progress");
  if (!progress) { progress = document.createElement("progress"); progress.max = 100; form.append(progress); }
  progress.hidden = false; progress.value = 0;
  return { update: value => { progress.value = value; }, finish: () => { progress.hidden = true; } };
}

function showLogin() {
  document.querySelector("#login-screen").hidden = false;
  document.querySelector("#admin-app").hidden = true;
}

function showApplication(settings) {
  document.querySelector("#login-screen").hidden = true;
  document.querySelector("#admin-app").hidden = false;
  document.querySelector('#screen-settings-form [name="screen_name"]').value = settings.screen_name;
  document.querySelector("#content-heading").textContent = `Inhalte – ${settings.screen_name}`;
  applyDeviceMode(settings.device_mode || "standalone");
  if (settings.password_change_required) {
    notify("Bitte ändere jetzt das Initialpasswort unter Einstellungen.", true, 10000);
    document.querySelector('[data-page="settings-page"]')?.click();
  }
}

function applyDeviceMode(mode) {
  const wasDisplay = currentDeviceMode === "display";
  currentDeviceMode = mode;
  document.body.dataset.mode = mode;
  const displayMode = mode === "display";
  document.querySelectorAll('.nav-button[data-page="content-page"], .nav-button[data-page="library-page"]').forEach(item => { item.hidden = displayMode; });
  ["#screen-settings-form", "#storage-cleanup", "#storage-orphan-cleanup", "#backup-create", "#backup-restore-form", "#display-control-form"]
    .forEach(selector => { const item = document.querySelector(selector); if (item) item.hidden = displayMode; });
  if (displayMode && !wasDisplay) {
    document.querySelectorAll(".nav-button").forEach(item => item.classList.remove("active"));
    document.querySelectorAll(".page").forEach(page => { page.hidden = true; });
    const systemButton = document.querySelector('.nav-button[data-page="system-page"]');
    systemButton.classList.add("active"); systemButton.hidden = false;
    document.querySelector("#system-page").hidden = false;
    openSystemPage();
  } else if (wasDisplay) {
    document.querySelectorAll(".nav-button").forEach(item => item.classList.remove("active"));
    document.querySelectorAll(".page").forEach(page => { page.hidden = true; });
    const contentButton = document.querySelector('.nav-button[data-page="content-page"]');
    contentButton.classList.add("active"); document.querySelector("#content-page").hidden = false;
  }
}

async function loadSettings() {
  try {
    const settings = await api("/api/settings");
    document.querySelector("#content-heading").textContent = `Inhalte – ${settings.screen_name}`;
  } catch (error) { notify(error.message, true); }
}

async function openSystemPage() {
  await Promise.all([loadSystemInfo(), loadMonitoring(), loadUpdateStatus(), loadApplicationUpdateStatus(), loadStorage(), loadSecurityStatus()]);
}

function organizeAdministrationPages() {
  const settingsContent = document.querySelector("#settings-content");
  if (!settingsContent || settingsContent.childElementCount) return;
  [
    "#password-form",
    "#backup-create",
    "#device-form",
    "#display-control-form",
    "[data-system-action='restart_service']",
  ].forEach((selector) => {
    const card = document.querySelector(selector)?.closest("section.card, details.card");
    if (card) settingsContent.append(card);
  });
}

async function openSettingsPage() {
  await Promise.all([loadBackups(), loadDevice(), loadDisplayControl()]);
}

organizeAdministrationPages();

async function boot() {
  try {
    const session = await api("/api/system/session");
    if (!session.authenticated) {
      showLogin();
      return;
    }
    showApplication(session);
    const loaders = [loadVersion()];
    if (session.device_mode !== "display") loaders.push(load(), loadLibrary(), loadPlaylists());
    await Promise.all(loaders);
  } catch (_) {
    showLogin();
  }
}

function kindLabel(kind) {
  return { image: "Bild", video: "Video", pdf: "PDF", website: "Webseite", stream: "Livestream", text: "Freitext" }[kind] || kind;
}

function hasSchedule(item) {
  return Boolean(item.schedule_start || item.schedule_end || item.schedule_daily_start ||
    item.schedule_daily_end || item.schedule_weekdays?.length);
}

function localDateTimeValue(value) {
  if (!value) return "";
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function openSchedule(item) {
  schedulingItem = item;
  const form = document.querySelector("#schedule-form");
  document.querySelector("#schedule-item-name").textContent = item.name;
  form.elements.schedule_start.value = localDateTimeValue(item.schedule_start);
  form.elements.schedule_end.value = localDateTimeValue(item.schedule_end);
  form.elements.schedule_daily_start.value = item.schedule_daily_start || "";
  form.elements.schedule_daily_end.value = item.schedule_daily_end || "";
  form.querySelectorAll('[name="weekday"]').forEach((checkbox) => {
    checkbox.checked = item.schedule_weekdays?.includes(Number(checkbox.value));
  });
  document.querySelector("#schedule-clear").disabled = !hasSchedule(item);
  document.querySelector("#schedule-dialog").showModal();
}

function renderTextSlide(target, source, config) {
  target.replaceChildren();
  const previewError = document.querySelector("#text-preview-error");
  previewError.hidden = true;
  previewError.textContent = "";
  target.style.backgroundImage = source && config.background_kind !== "video" ? `url("${source.replaceAll('"', '%22')}")` : "none";
  if (source && config.background_kind === "video") {
    const video = document.createElement("video");
    video.className = "text-background-video";
    video.src = source; video.autoplay = true; video.muted = true; video.loop = true; video.playsInline = true;
    video.addEventListener("loadeddata", () => { previewError.hidden = true; }, { once: true });
    video.addEventListener("error", () => {
      previewError.textContent = "Das Video kann in diesem Browser nicht abgespielt werden. Bitte das Video in der Mediathek mit „Optimal konvertieren“ in MP4/H.264 umwandeln und anschließend erneut auswählen.";
      previewError.hidden = false;
    }, { once: true });
    target.append(video);
  }
  const align = config.text_align || "left";
  const vertical = config.vertical_position || "center";
  const font = config.font_family || "sans";
  const size = config.font_size || "medium";
  const template = config.template_style || "standard";
  target.className = `text-slide preview-slide align-${align} position-${vertical} font-${font} size-${size} template-${template}`;
  target.style.backgroundPosition = `${config.focus_x ?? 50}% ${config.focus_y ?? 50}%`;
  target.style.setProperty("--background-dim", `${config.background_dim || 0}%`);
  target.style.setProperty("--slide-text", config.text_color || "#ffffff");
  target.style.setProperty("--slide-accent", config.accent_color || "#39d98a");
  const overlay = document.createElement("div");
  const intensity = ["light", "medium", "dark"].includes(config.shadow_intensity)
    ? config.shadow_intensity : "medium";
  overlay.className = `text-overlay${config.shadow_box ? ` shadow-box shadow-box-${intensity}` : ""}`;
  [["h2", "text-headline", config.headline], ["h3", "text-subheadline", config.subheadline], ["p", "text-body", config.body]]
    .forEach(([tag, className, value]) => {
      if (!value) return;
      const element = document.createElement(tag);
      element.className = className;
      element.textContent = value;
      overlay.append(element);
    });
  target.append(overlay);
  if (config.logo_source) {
    const logo = document.createElement("img");
    logo.className = "text-logo";
    logo.src = config.logo_source;
    logo.alt = "Logo";
    target.append(logo);
  }
}

function resetTextForm() {
  editingTextItem = null;
  textForm.reset();
  textForm.elements.duration_seconds.value = "12";
  textForm.elements.shadow_box.checked = true;
  textForm.elements.shadow_intensity.value = "medium";
  textForm.elements.template_style.value = "standard";
  textForm.elements.text_align.value = "left";
  textForm.elements.vertical_position.value = "center";
  textForm.elements.font_size.value = "medium";
  textForm.elements.font_family.value = "sans";
  textForm.elements.text_color.value = "#ffffff";
  textForm.elements.accent_color.value = "#39d98a";
  textForm.elements.background_dim.value = "0";
  textForm.elements.focus_x.value = "50";
  textForm.elements.focus_y.value = "50";
  document.querySelector("#background-dim-output").value = "0 %";
  document.querySelector("#remove-logo-label").hidden = true;
  document.querySelector("#shadow-intensity-label").hidden = false;
  textForm.elements.background.required = false;
  document.querySelector("#text-form-title").textContent = "Freitext hinzufügen";
  document.querySelector("#text-background-note").textContent = "JPG, PNG, WebP, MP4 oder WebM";
  document.querySelector("#text-save-button").textContent = "Speichern und zur Playlist hinzufügen";
  document.querySelector("#text-cancel-edit").hidden = true;
}

function editTextItem(item) {
  showAddContent("text");
  editingTextItem = item;
  textForm.elements.content_id.value = item.id;
  textForm.elements.name.value = item.name;
  textForm.elements.headline.value = item.text_config?.headline || "";
  textForm.elements.subheadline.value = item.text_config?.subheadline || "";
  textForm.elements.body.value = item.text_config?.body || "";
  textForm.elements.duration_seconds.value = item.duration_seconds;
  textForm.elements.shadow_box.checked = Boolean(item.text_config?.shadow_box);
  textForm.elements.shadow_intensity.value = item.text_config?.shadow_intensity || "medium";
  ["template_style", "text_align", "vertical_position", "font_size", "font_family", "text_color", "accent_color", "background_dim", "focus_x", "focus_y"].forEach((field) => {
    const defaults = { template_style: "standard", text_align: "left", vertical_position: "center", font_size: "medium", font_family: "sans", text_color: "#ffffff", accent_color: "#39d98a", background_dim: 0, focus_x: 50, focus_y: 50 };
    textForm.elements[field].value = item.text_config?.[field] ?? defaults[field];
  });
  document.querySelector("#background-dim-output").value = `${textForm.elements.background_dim.value} %`;
  document.querySelector("#remove-logo-label").hidden = !item.text_config?.logo_source;
  document.querySelector("#shadow-intensity-label").hidden = !textForm.elements.shadow_box.checked;
  textForm.elements.library_media_id.value = item.media_id || "";
  textForm.elements.background.required = false;
  document.querySelector("#text-form-title").textContent = "Freitext bearbeiten";
  document.querySelector("#text-background-note").textContent = "Optional: neues Bild oder Video auswählen, sonst bleibt der bisherige Hintergrund erhalten.";
  document.querySelector("#text-save-button").textContent = "Änderungen speichern";
  document.querySelector("#text-cancel-edit").hidden = false;
  textForm.scrollIntoView({ behavior: "smooth", block: "start" });
}

function populateLibraryImageSelect() {
  const select = document.querySelector("#text-library-image");
  const selected = select.value;
  select.replaceChildren(new Option("Kein Mediathek-Medium ausgewählt", ""));
  libraryItems.filter(item => ["image", "video"].includes(item.kind)).forEach((item) => {
    select.append(new Option(`${item.kind === "video" ? "Video" : "Bild"}: ${item.name}`, item.id));
  });
  if ([...select.options].some(option => option.value === selected)) select.value = selected;
}

function showAddContent(type) {
  document.querySelector("#add-content-type").value = type;
  document.querySelectorAll(".add-content-card").forEach(card => { card.hidden = card.dataset.addType !== type; });
  if (type) document.querySelector(`.add-content-card[data-add-type="${type}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderLibrary(items) {
  const target = document.querySelector("#media-library");
  target.replaceChildren();
  document.querySelector("#library-empty").hidden = items.length > 0;
  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = `media-card${selectedMediaIds.has(item.id) ? " selected" : ""}`;
    const selector = document.createElement("input");
    selector.type = "checkbox";
    selector.className = "media-select";
    selector.checked = selectedMediaIds.has(item.id);
    selector.addEventListener("change", () => {
      selector.checked ? selectedMediaIds.add(item.id) : selectedMediaIds.delete(item.id);
      updateBulkActions();
      card.classList.toggle("selected", selector.checked);
    });
    const preview = document.createElement(item.kind === "image" ? "img" : "video");
    if (item.file_exists === false) {
      preview.hidden = true;
    } else if (item.kind === "video") {
      preview.src = item.source;
      if (item.thumbnail_source) preview.poster = item.thumbnail_source;
      preview.muted = true;
      preview.controls = true;
      preview.preload = "metadata";
    } else {
      preview.src = item.thumbnail_source || item.source;
    }
    const body = document.createElement("div");
    body.className = "media-card-body";
    body.innerHTML = `
      <input class="media-name" value="" aria-label="Medienname">
      <input class="media-category" value="" placeholder="Kategorie" aria-label="Kategorie">
      <span class="media-card-meta">${kindLabel(item.kind)} · ${formatBytes(item.storage_bytes ?? item.size_bytes)} Speicher${item.width ? ` · ${item.width}×${item.height}` : ""}${item.metadata?.duration_seconds ? ` · ${item.metadata.duration_seconds}s` : ""} · ${item.usage_count || 0}× verwendet</span>
      <div class="media-card-actions">
        <input class="library-duration" type="number" min="1" max="86400" value="10" title="Anzeigedauer in Sekunden">
        ${item.kind === "video" ? `
          <select class="library-muted" aria-label="Videoton">
            <option value="true">Ohne Ton</option>
            <option value="false">Mit Ton</option>
          </select>
          <label class="inline-check"><input class="library-play-to-end" type="checkbox"><span>Bis Ende</span></label>
        ` : ""}
        <button class="add-library">Zur Playlist</button>
        ${item.kind === "image" ? '<button class="secondary edit-library-image">Bearbeiten</button>' : ""}
        ${item.kind === "video" ? '<button class="secondary transcode-library-video">Optimal konvertieren</button><span class="transcode-status" hidden></span>' : ""}
        ${item.file_exists === false ? '<button class="secondary repair-library-file">Datei ersetzen</button>' : ""}
        <button class="secondary save-library-meta">Speichern</button>
        <button class="danger delete-library">Löschen</button>
      </div>`;
    body.querySelector(".media-name").value = item.name;
    body.querySelector(".media-category").value = item.category || "";
    body.querySelector(".repair-library-file")?.addEventListener("click", () => {
      const input = document.createElement("input"); input.type = "file";
      input.accept = item.kind === "image" ? "image/*" : "video/mp4,video/webm";
      input.addEventListener("change", async () => {
        if (!input.files[0]) return;
        const form = new FormData(); form.append("file", input.files[0]);
        try { await uploadWithProgress(`/api/media-library/${item.id}/replace`, form, () => {}); await loadLibrary(); notify("Mediendatei ersetzt"); }
        catch (error) { notify(error.message, true); }
      });
      input.click();
    });
    const previewError = document.createElement("p");
    previewError.className = "media-preview-error";
    previewError.hidden = item.file_exists !== false;
    if (item.file_exists === false) previewError.textContent = "Datei fehlt im Medienspeicher.";
    if (item.kind === "video") {
      preview.addEventListener("error", () => {
        previewError.textContent = "Vorschau nicht abspielbar – bitte „Optimal konvertieren“ verwenden.";
        previewError.hidden = false;
      });
      preview.addEventListener("loadeddata", () => { previewError.hidden = true; });
    }
    body.querySelector(".add-library").addEventListener("click", async () => {
      try {
        const duration = Number(body.querySelector(".library-duration").value);
        await api(`/api/media-library/${item.id}/playlist`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            duration_seconds: duration,
            muted: item.kind === "video" ? body.querySelector(".library-muted").value === "true" : true,
            play_to_end: item.kind === "video" ? body.querySelector(".library-play-to-end").checked : false,
          }),
        });
        notify("Medium zur Playlist hinzugefügt");
      } catch (error) { notify(error.message, true); }
    });
    body.querySelector(".delete-library").addEventListener("click", async () => {
      if (!window.confirm(`„${item.name}“ aus der Mediathek löschen?`)) return;
      try {
        await api(`/api/media-library/${item.id}`, { method: "DELETE" });
        await loadLibrary();
        notify("Medium gelöscht");
      } catch (error) { notify(error.message, true); }
    });
    body.querySelector(".edit-library-image")?.addEventListener("click", () => {
      editingLibraryImage = item;
      const form = document.querySelector("#image-editor-form");
      form.reset();
      document.querySelector("#image-editor-preview").src = item.source;
      document.querySelector("#image-editor-dialog").showModal();
    });
    body.querySelector(".save-library-meta").addEventListener("click", async () => {
      try {
        await api(`/api/media-library/${item.id}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: body.querySelector(".media-name").value, category: body.querySelector(".media-category").value }),
        });
        await loadLibrary();
        notify("Mediendaten gespeichert");
      } catch (error) { notify(error.message, true); }
    });
    body.querySelector(".transcode-library-video")?.addEventListener("click", async () => {
      if (!window.confirm("Video jetzt für zuverlässige Wiedergabe nach MP4 mit H.264/AAC optimieren?")) return;
      const button = body.querySelector(".transcode-library-video");
      const status = body.querySelector(".transcode-status");
      button.disabled = true;
      button.textContent = "Konvertierung läuft …";
      status.hidden = false;
      status.textContent = "Das kann je nach Videolänge mehrere Minuten dauern.";
      notify("Optimale Videokonvertierung wurde gestartet", false, 6000);
      try {
        const queued = await api(`/api/media-library/${item.id}/transcode`, { method: "POST" });
        status.textContent = queued.message;
        let job = queued;
        while (["queued", "running"].includes(job.status)) {
          await new Promise(resolve => window.setTimeout(resolve, 1500));
          job = await api(`/api/conversions/${queued.job_id}`);
          status.textContent = job.status === "running" ? "Video wird optimal konvertiert …" : "Konvertierung wartet …";
        }
        if (job.status === "failed") throw new Error(job.message);
        status.textContent = job.message;
        await loadLibrary();
        notify("Video wurde erfolgreich optimal konvertiert und die Vorschau aktualisiert", false, 8000);
      } catch (error) {
        button.disabled = false;
        button.textContent = "Erneut optimal konvertieren";
        status.textContent = `Fehler: ${error.message}`;
        notify(error.message, true, 8000);
      }
    });
    card.append(selector, preview, previewError, body);
    target.append(card);
  });
}

function filteredLibraryItems() {
  const query = document.querySelector("#library-search").value.trim().toLowerCase();
  const type = document.querySelector("#library-type-filter").value;
  const usage = document.querySelector("#library-usage-filter").value;
  const category = document.querySelector("#library-category-filter").value.trim().toLowerCase();
  return libraryItems.filter(item =>
    (!query || item.name.toLowerCase().includes(query)) && (!type || item.kind === type) &&
    (!category || (item.category || "").toLowerCase().includes(category)) &&
    (!usage || (usage === "unused" ? !item.usage_count : Boolean(item.usage_count)))
  );
}

function updateBulkActions() {
  document.querySelector("#library-selection-count").textContent = `${selectedMediaIds.size} ausgewählt`;
  document.querySelector("#library-bulk-add").disabled = selectedMediaIds.size === 0;
}

function applyLibraryFilters() { renderLibrary(filteredLibraryItems()); }

async function loadLibrary() {
  try {
    libraryItems = await api("/api/media-library");
    renderLibrary(libraryItems);
    populateLibraryImageSelect();
  } catch (error) { notify(error.message, true); }
}

async function updateItem(id, changes) {
  await api(`/api/content/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
}

function render(items) {
  playlist.replaceChildren();
  empty.hidden = items.length > 0;
  items.forEach((item, index) => {
    const row = document.createElement("article");
    row.className = `playlist-item${item.enabled ? "" : " disabled"}`;
    row.innerHTML = `
      <div class="order-controls">
        <button class="icon secondary up" title="Nach oben" ${index === 0 ? "disabled" : ""}>↑</button>
        <button class="icon secondary down" title="Nach unten" ${index === items.length - 1 ? "disabled" : ""}>↓</button>
      </div>
      <div class="item-main">
        <span class="badge">${kindLabel(item.kind)}</span>
        <strong></strong>
        <small></small>
      </div>
      <label class="duration">Dauer
        <input type="number" min="1" max="86400" value="${item.duration_seconds}">
        <span>s</span>
      </label>
      <label class="toggle">
        <input type="checkbox" ${item.enabled ? "checked" : ""}>
        <span>Aktiv</span>
      </label>
      ${["stream", "video"].includes(item.kind) ? `
        <label class="toggle sound-toggle">
          <input type="checkbox" ${item.muted ? "" : "checked"}>
          <span>Ton</span>
        </label>
      ` : ""}
      ${item.kind === "video" ? `
        <label class="toggle end-toggle">
          <input type="checkbox" ${item.play_to_end ? "checked" : ""}>
          <span>Bis Ende</span>
        </label>
      ` : ""}
      ${item.kind === "text" ? '<button class="secondary edit-text">Bearbeiten</button>' : ""}
      <button class="secondary schedule">${hasSchedule(item) ? "Zeitplan ✓" : "Zeitplan"}</button>
      <button class="danger delete">Löschen</button>
    `;
    row.querySelector("strong").textContent = item.name;
    row.querySelector("small").textContent = item.source;
    row.querySelector(".duration input").addEventListener("change", async (event) => {
      try {
        await updateItem(item.id, { duration_seconds: Number(event.target.value) });
        notify("Anzeigedauer gespeichert");
      } catch (error) { notify(error.message, true); }
    });
    row.querySelector(".toggle input").addEventListener("change", async (event) => {
      try {
        await updateItem(item.id, { enabled: event.target.checked });
        await load();
      } catch (error) { notify(error.message, true); }
    });
    row.querySelector(".sound-toggle input")?.addEventListener("change", async (event) => {
      try {
        await updateItem(item.id, { muted: !event.target.checked });
        notify("Toneinstellung gespeichert");
      } catch (error) { notify(error.message, true); }
    });
    row.querySelector(".end-toggle input")?.addEventListener("change", async (event) => {
      try {
        await updateItem(item.id, { play_to_end: event.target.checked });
        notify("Abspielverhalten gespeichert");
      } catch (error) { notify(error.message, true); }
    });
    row.querySelector(".delete").addEventListener("click", async () => {
      if (!window.confirm(`„${item.name}“ wirklich löschen?`)) return;
      try {
        await api(`/api/content/${item.id}`, { method: "DELETE" });
        await load();
        notify("Inhalt gelöscht");
      } catch (error) { notify(error.message, true); }
    });
    row.querySelector(".edit-text")?.addEventListener("click", () => editTextItem(item));
    row.querySelector(".schedule").addEventListener("click", () => openSchedule(item));
    row.querySelector(".up").addEventListener("click", () => move(items, index, -1));
    row.querySelector(".down").addEventListener("click", () => move(items, index, 1));
    playlist.append(row);
  });
}

async function move(items, index, direction) {
  const otherIndex = index + direction;
  if (otherIndex < 0 || otherIndex >= items.length) return;
  try {
    await Promise.all([
      updateItem(items[index].id, { position: items[otherIndex].position }),
      updateItem(items[otherIndex].id, { position: items[index].position }),
    ]);
    await load();
  } catch (error) { notify(error.message, true); }
}

async function load() {
  try {
    render(await api("/api/content"));
  } catch (error) { notify(error.message, true); }
}

function renderPlaylists() {
  const select = document.querySelector("#playlist-select");
  select.replaceChildren();
  playlists.forEach((playlist) => {
    const option = new Option(`${playlist.name} (${playlist.content_count})`, playlist.id);
    option.selected = playlist.active;
    select.append(option);
  });
  const list = document.querySelector("#playlist-list");
  list.replaceChildren();
  playlists.forEach((playlist) => {
    const row = document.createElement("article");
    const label = document.createElement("span");
    label.textContent = `${playlist.name} · ${playlist.content_count} Inhalte${playlist.active ? " · manuell aktiv" : ""}${playlist.effective ? " · aktuell angezeigt" : ""}${playlist.schedule_enabled ? " · geplant" : ""}`;
    const schedule = document.createElement("button");
    schedule.className = "secondary";
    schedule.textContent = playlist.schedule_enabled ? "Zeitplan ✓" : "Zeitplan";
    schedule.addEventListener("click", () => openPlaylistSchedule(playlist));
    const button = document.createElement("button");
    button.className = "danger";
    button.textContent = "Löschen";
    button.disabled = playlist.active || playlists.length <= 1;
    button.addEventListener("click", async () => {
      if (!window.confirm(`Playlist „${playlist.name}“ einschließlich ihrer Inhalte löschen?`)) return;
      try {
        await api(`/api/playlists/${playlist.id}`, { method: "DELETE" });
        await loadPlaylists();
        notify("Playlist gelöscht");
      } catch (error) { notify(error.message, true); }
    });
    const actions = document.createElement("div");
    actions.className = "playlist-actions";
    actions.append(schedule, button);
    row.append(label, actions);
    list.append(row);
  });
}

async function loadPlaylists() {
  try {
    playlists = await api("/api/playlists");
    renderPlaylists();
  } catch (error) { notify(error.message, true); }
}

async function loadVersion() {
  try {
    const health = await api("/api/health");
    document.querySelector("#app-version").textContent = `v${health.version}`;
  } catch (_) {
    document.querySelector("#app-version").textContent = "Version unbekannt";
  }
}

async function loadStorage() {
  const status = await api("/api/system/storage");
  document.querySelector("#storage-media").textContent = `${status.media_count} Medien`;
  document.querySelector("#storage-files").textContent = `${status.file_count} Dateien`;
  document.querySelector("#storage-unused").textContent = `${status.unused_media_count} Medien`;
  document.querySelector("#storage-size").textContent = formatBytes(status.media_bytes);
  document.querySelector("#storage-cleanup").disabled = status.unused_media_count === 0;
  document.querySelector("#storage-orphan-cleanup").disabled = status.orphan_file_count === 0;
  document.querySelector("#storage-audit").textContent = `${status.missing_media_ids.length} fehlende Medien · ${status.orphan_file_count} verwaiste Dateien (${formatBytes(status.orphan_bytes)}) · ${status.duplicate_groups.length} Dublettengruppen`;
}

async function loadBackups() {
  const backups = await api("/api/system/backups");
  const target = document.querySelector("#backup-list");
  target.replaceChildren(...backups.map(backup => {
    const row = document.createElement("article");
    const label = document.createElement("span");
    label.textContent = `${new Date(backup.created_at).toLocaleString("de-DE")} · ${formatBytes(backup.size_bytes)}`;
    const link = document.createElement("a"); link.className = "button secondary";
    link.href = `/api/system/backups/${encodeURIComponent(backup.name)}`; link.textContent = "Herunterladen";
    row.append(label, link); return row;
  }));
  if (!backups.length) target.innerHTML = '<p class="empty">Noch kein Backup vorhanden.</p>';
}

async function loadSecurityStatus() {
  const status = await api("/api/system/security-status");
  const labels = { initial_password_changed: "Initialpasswort geändert", player_token_available: "Player-Schlüssel vorhanden", database_integrity_ok: "SQLite-Integrität", backup_available: "Backup vorhanden", storage_healthy: "Speicherreserve", https: "HTTPS-Verbindung" };
  const target = document.querySelector("#security-status");
  target.replaceChildren(...Object.entries(status.checks).map(([key, ok]) => {
    const row = document.createElement("p"); row.className = ok ? "security-ok" : "security-warning";
    row.textContent = `${ok ? "✓" : "!"} ${labels[key] || key}`; return row;
  }));
  const details = document.createElement("small");
  details.textContent = `Integritätsprüfung: ${status.integrity_checked_at ? new Date(status.integrity_checked_at).toLocaleString("de-DE") : "nie"} · Backup: ${status.last_backup_at ? new Date(status.last_backup_at).toLocaleString("de-DE") : "nie"}`;
  target.append(details);
}

async function loadDevice() {
  const device = await api("/api/system/device");
  const form = document.querySelector("#device-form");
  form.elements.device_id.value = device.device_id;
  form.elements.role.value = device.role;
  form.elements.controller_url.value = device.controller_url;
  form.elements.controller_pairing_code.value = device.pairing_code || "";
  form.elements.pairing_code.value = "";
  form.elements.controller_pairing_code.closest("label").hidden = device.role !== "controller";
  form.elements.pairing_code.closest("label").hidden = device.role !== "display";
  form.elements.controller_url.closest("label").hidden = device.role !== "display";
  document.querySelector("#sync-now").hidden = device.role !== "display";
  applyDeviceMode(device.role);
  document.querySelector("#sync-status").textContent = `Synchronisationsstatus: ${device.sync_status}`;
  const registered = document.querySelector("#registered-devices");
  registered.replaceChildren(...(device.registered_devices || []).map(item => {
    const row = document.createElement("article");
    row.textContent = `${item.name} · zuletzt ${item.last_seen ? new Date(item.last_seen).toLocaleString("de-DE") : "nie"}`;
    return row;
  }));
}

function renderDisplayControl(data, updateForm = !displayControlDirty) {
  const config = data?.config || {};
  const status = data?.status || {};
  const scheduleEntries = Array.isArray(config.schedule_entries) ? config.schedule_entries : [];
  const form = document.querySelector("#display-control-form");
  if (updateForm) {
    form.elements.cec_address.value = config.cec_address;
    form.elements.activate_source.checked = config.activate_source;
    form.elements.fallback_hdmi_signal.checked = config.fallback_hdmi_signal;
    form.elements.resolution_mode.value = config.resolution_mode || "1080p60";
    form.elements.transition_ms.value = config.transition_ms || 4000;
    document.querySelector("#transition-ms-output").value = `${form.elements.transition_ms.value} ms`;
    form.elements.schedule_enabled.checked = config.schedule_enabled;
    const target = document.querySelector("#display-schedule-entries");
    target.replaceChildren(...scheduleEntries.map((entry, index) => {
      const row = createDisplayScheduleRow(entry);
      if (index === 0 || scheduleEntries[index - 1].weekday !== entry.weekday) row.classList.add("day-group-start");
      if ((data.schedule?.conflicts || []).some(conflict => conflict.first === index || conflict.second === index)) row.classList.add("schedule-conflict");
      return row;
    }));
  }
  const next = data.schedule?.next_action;
  document.querySelector("#display-schedule-next").textContent = next
    ? `Nächster Schaltvorgang: ${next.action === "on" ? "Einschalten" : "Ausschalten"} · ${new Date(next.at).toLocaleString("de-DE")}`
    : "Nächster Schaltvorgang: keiner geplant";
  const conflict = document.querySelector("#display-schedule-conflicts");
  const conflictCount = data.schedule?.conflicts?.length || 0;
  conflict.hidden = conflictCount === 0;
  conflict.textContent = conflictCount ? `${conflictCount} überlappende Zeitfenster erkannt. Sie werden gemeinsam als Einschaltzeit behandelt.` : "";
  document.querySelector("#display-cec-status").textContent = status.cec_available == null ? "Noch unbekannt" : status.cec_available ? "Verfügbar" : "Nicht verfügbar";
  document.querySelector("#display-fallback-status").textContent = status.hdmi_fallback_available == null ? "Noch unbekannt" : status.hdmi_fallback_available ? "Verfügbar" : "Nicht verfügbar";
  const powerLabels = status.method === "wayland_dpms"
    ? { on: "HDMI-Signal an", off: "HDMI-Signal aus", unknown: "Unbekannt" }
    : { on: "Eingeschaltet", off: "Ausgeschaltet", unknown: "Unbekannt" };
  document.querySelector("#display-power-status").textContent = powerLabels[status.power_status] || "Unbekannt";
  document.querySelector("#display-control-method").textContent = { cec: "HDMI-CEC", wayland_dpms: "Wayland-DPMS" }[status.method] || "Noch nicht erkannt";
  document.querySelector("#display-output-name").textContent = status.method === "cec"
    ? status.cec_adapter || "Standardadapter"
    : status.output_name || "–";
  document.querySelector("#display-updated-at").textContent = status.updated_at ? new Date(status.updated_at).toLocaleString("de-DE") : "Noch nie";
  document.querySelector("#display-status-message").textContent = status.message || "";
  document.querySelector("#display-resolution-status").textContent = status.current_resolution
    ? `Auflösung: ${status.current_resolution} · ${status.resolution_message || ""}`
    : `Auflösung: ${status.resolution_message || "noch nicht geprüft"}`;
}

const displayWeekdays = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];

function createDisplayScheduleRow(entry = { weekday: 0, on: "08:00", off: "22:00" }) {
  const row = document.createElement("div");
  row.className = "display-schedule-row";
  const weekday = document.createElement("select");
  weekday.className = "schedule-weekday";
  weekday.setAttribute("aria-label", "Wochentag");
  displayWeekdays.forEach((name, index) => weekday.append(new Option(name, index)));
  weekday.value = String(entry.weekday);
  const on = document.createElement("input");
  on.className = "day-on"; on.type = "time"; on.required = true; on.value = entry.on || "08:00";
  on.setAttribute("aria-label", "Einschaltzeit");
  const off = document.createElement("input");
  off.className = "day-off"; off.type = "time"; off.required = true; off.value = entry.off || "22:00";
  off.setAttribute("aria-label", "Ausschaltzeit");
  const remove = document.createElement("button");
  remove.type = "button"; remove.className = "danger display-schedule-remove"; remove.textContent = "Entfernen";
  const duplicate = document.createElement("button");
  duplicate.type = "button"; duplicate.className = "secondary display-schedule-duplicate"; duplicate.textContent = "Duplizieren";
  const actions = document.createElement("span"); actions.className = "schedule-row-actions"; actions.append(duplicate, remove);
  row.append(weekday, on, off, actions);
  return row;
}

async function loadDisplayControl() {
  try { renderDisplayControl(await api("/api/system/display-control")); }
  catch (error) { notify(error.message, true); }
}

function openPlaylistSchedule(item) {
  schedulingPlaylist = item;
  const form = document.querySelector("#playlist-schedule-form");
  document.querySelector("#playlist-schedule-name").textContent = item.name;
  form.elements.schedule_enabled.checked = item.schedule_enabled;
  form.elements.schedule_start.value = localDateTimeValue(item.schedule_start);
  form.elements.schedule_end.value = localDateTimeValue(item.schedule_end);
  form.elements.schedule_daily_start.value = item.schedule_daily_start || "";
  form.elements.schedule_daily_end.value = item.schedule_daily_end || "";
  form.querySelectorAll('[name="weekday"]').forEach(box => { box.checked = item.schedule_weekdays?.includes(Number(box.value)); });
  document.querySelector("#playlist-schedule-dialog").showModal();
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index > 2 ? 1 : 0)} ${units[index]}`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "–";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return [days ? `${days} T` : "", hours ? `${hours} Std` : "", `${minutes} Min`]
    .filter(Boolean).join(" ");
}

function setSystemValue(name, value) {
  document.querySelector(`[data-system="${name}"]`).textContent = value ?? "–";
}

function renderNetworks(targetId, interfaces, wireless = false) {
  const target = document.querySelector(`#${targetId}`);
  target.replaceChildren();
  if (!interfaces.length) {
    target.innerHTML = '<p class="empty">Keine Schnittstelle erkannt.</p>';
    return;
  }
  interfaces.forEach((network) => {
    const item = document.createElement("article");
    item.className = "network-item";
    const address = network.addresses.length ? network.addresses.join(", ") : "Keine IP-Adresse";
    item.innerHTML = `
      <div class="network-heading">
        <strong></strong>
        <span class="connection ${network.connected ? "online" : "offline"}">
          ${network.connected ? "Verbunden" : "Getrennt"}
        </span>
      </div>
      ${wireless ? '<div><span>SSID</span><b class="ssid"></b></div>' : ""}
      <div><span>IP-Adresse</span><b class="address"></b></div>
      <div><span>Gateway</span><b class="gateway"></b></div>
      <div><span>MAC-Adresse</span><b class="mac"></b></div>
    `;
    item.querySelector("strong").textContent = network.name;
    item.querySelector(".address").textContent = address;
    item.querySelector(".gateway").textContent = network.gateway || "–";
    item.querySelector(".mac").textContent = network.mac || "–";
    if (wireless) item.querySelector(".ssid").textContent = network.ssid || "–";
    target.append(item);
  });
}

async function loadSystemInfo() {
  const button = document.querySelector("#system-refresh");
  button.disabled = true;
  try {
    const info = await api("/api/system/info");
    setSystemValue("hostname", info.hostname);
    setSystemValue("model", info.model);
    setSystemValue("operating_system", info.operating_system);
    setSystemValue("kernel", info.kernel);
    setSystemValue("uptime", formatDuration(info.uptime_seconds));
    setSystemValue("temperature", info.temperature_celsius == null ? "–" : `${info.temperature_celsius} °C`);
    setSystemValue("load", info.load_average?.map(value => value.toFixed(2)).join(" / ") || "–");
    setSystemValue("memory", `${formatBytes(info.memory.used_bytes)} von ${formatBytes(info.memory.total_bytes)}`);
    setSystemValue("disk", `${formatBytes(info.disk.used_bytes)} von ${formatBytes(info.disk.total_bytes)}`);
    renderNetworks("wlan-info", info.network.wlan, true);
    renderNetworks("ethernet-info", info.network.ethernet);
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function loadMonitoring() {
  try {
    const status = await api("/api/system/monitoring");
    const set = (name, value) => { document.querySelector(`[data-monitoring="${name}"]`).textContent = value; };
    const player = status.player;
    set("player", player.online ? `Online · ${player.state}` : "Offline");
    set("content", player.content_name || "–");
    set("last_seen", player.last_seen ? new Date(player.last_seen).toLocaleString("de-DE") : "Noch kein Kontakt");
    const free = status.disk.total_bytes - status.disk.used_bytes;
    set("disk", `${formatBytes(free)} frei`);
    set("temperature", status.temperature_celsius == null ? "–" : `${status.temperature_celsius} °C`);
    set("application_update", status.application_update.status);
    set("system_update", status.system_update.status);
    const warnings = document.querySelector("#monitoring-warnings");
    warnings.hidden = !status.warnings.length;
    warnings.textContent = status.warnings.join(" ");
    const error = document.querySelector("#player-error");
    error.hidden = !player.error;
    error.textContent = player.error ? `Letzter Playerfehler: ${player.error}` : "";
    const events = document.querySelector("#player-events");
    events.hidden = !status.events.length;
    events.querySelector("div").replaceChildren(...status.events.map(item => {
      const row = document.createElement("p");
      row.textContent = `${new Date(item.created_at).toLocaleString("de-DE")} · ${item.content_name || "Player"}: ${item.message}`;
      return row;
    }));
  } catch (error) { notify(error.message, true); }
}

function renderUpdateStatus(status) {
  const state = document.querySelector("#update-state");
  state.className = `update-state ${status.status}`;
  state.querySelector("strong").textContent = status.message;
  const times = [status.started_at ? `Start: ${status.started_at}` : "", status.finished_at ? `Ende: ${status.finished_at}` : ""];
  state.querySelector("span").textContent = times.filter(Boolean).join(" · ");
  const updateButton = document.querySelector("#system-update");
  updateButton.disabled = !status.available || ["queued", "running"].includes(status.status);
  if (!status.available) {
    state.querySelector("strong").textContent = "Systemupdate auf diesem Gerät nicht verfügbar.";
  }
  const details = document.querySelector("#update-log");
  details.hidden = !status.log?.length;
  details.querySelector("pre").textContent = status.log?.join("\n") || "";
}

function renderApplicationUpdateStatus(status) {
  const wasUpdating = applicationUpdateInProgress;
  applicationUpdateInProgress = ["queued", "running"].includes(status.status);
  const state = document.querySelector("#application-update-state");
  state.className = `update-state ${status.status}`;
  state.querySelector("strong").textContent = status.message;
  const times = [status.started_at ? `Start: ${status.started_at}` : "", status.finished_at ? `Ende: ${status.finished_at}` : ""];
  state.querySelector("span").textContent = times.filter(Boolean).join(" · ");
  const button = document.querySelector("#application-update");
  button.disabled = !status.available || ["queued", "running"].includes(status.status);
  if (!status.available) {
    state.querySelector("strong").textContent = "Anwendungsupdate auf diesem Gerät nicht verfügbar.";
  }
  const details = document.querySelector("#application-update-log");
  details.hidden = !status.log?.length;
  details.querySelector("pre").textContent = status.log?.join("\n") || "";
  if (wasUpdating && status.status === "success" && !applicationReloadScheduled) {
    applicationReloadScheduled = true;
    state.querySelector("strong").textContent = "Update erfolgreich – Oberfläche wird neu geladen …";
    window.setTimeout(() => window.location.reload(), 1200);
  }
}

async function loadUpdateStatus() {
  try {
    renderUpdateStatus(await api("/api/system/update"));
  } catch (error) {
    if (!applicationUpdateInProgress) notify(error.message, true);
  }
}

async function loadApplicationUpdateStatus() {
  try {
    renderApplicationUpdateStatus(await api("/api/system/application-update"));
  } catch (error) {
    if (applicationUpdateInProgress) {
      const state = document.querySelector("#application-update-state");
      state.className = "update-state running";
      state.querySelector("strong").textContent = "Server wird aktualisiert und neu gestartet …";
      state.querySelector("span").textContent = "Verbindung wird automatisch wiederhergestellt.";
    } else {
      notify(error.message, true);
    }
  }
}

document.querySelectorAll(".nav-button").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll(".nav-button").forEach(item => item.classList.remove("active"));
    document.querySelectorAll(".page").forEach(page => { page.hidden = true; });
    button.classList.add("active");
    document.querySelector(`#${button.dataset.page}`).hidden = false;
    if (button.dataset.page === "system-page") {
      await openSystemPage();
    } else if (button.dataset.page === "settings-page") {
      await openSettingsPage();
    } else if (button.dataset.page === "library-page") {
      await loadLibrary();
    } else if (button.dataset.page === "content-page") {
      await load();
    }
  });
});

document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = new FormData(event.target).get("password");
  try {
    const session = await api("/api/system/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    event.target.reset();
    showApplication(session);
    await Promise.all([loadVersion(), load(), loadLibrary(), loadPlaylists()]);
    notify("Anmeldung erfolgreich");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#logout").addEventListener("click", async () => {
  await api("/api/system/logout", { method: "POST" });
  showLogin();
});

document.querySelector("#screen-settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const screenName = new FormData(event.target).get("screen_name");
  try {
    await api("/api/system/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ screen_name: screenName }),
    });
    await loadSettings();
    notify("Bildschirmname gespeichert");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  if (form.get("new_password") !== form.get("confirm_password")) {
    notify("Die neuen Passwörter stimmen nicht überein", true);
    return;
  }
  try {
    await api("/api/system/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: form.get("current_password"),
        new_password: form.get("new_password"),
      }),
    });
    event.target.reset();
    notify("Passwort geändert");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#system-refresh").addEventListener("click", () => {
  loadSystemInfo();
  loadUpdateStatus();
  loadApplicationUpdateStatus();
  loadMonitoring();
});
document.querySelector("#monitoring-refresh").addEventListener("click", loadMonitoring);

document.querySelector("#application-update").addEventListener("click", async () => {
  const confirmed = window.confirm(
    "Jetzt den neuesten veröffentlichten Open-Signage-Release installieren?"
  );
  if (!confirmed) return;
  applicationUpdateInProgress = true;
  try {
    renderApplicationUpdateStatus(await api("/api/system/application-update", { method: "POST" }));
    notify("Anwendungsupdate wurde im Hintergrund gestartet");
  } catch (error) {
    const state = document.querySelector("#application-update-state");
    state.className = "update-state running";
    state.querySelector("strong").textContent = "Server wird aktualisiert und neu gestartet …";
    state.querySelector("span").textContent = "Verbindung wird automatisch wiederhergestellt.";
  }
});

document.querySelector("#system-update").addEventListener("click", async () => {
  const confirmed = window.confirm(
    "Jetzt alle verfügbaren Betriebssystempakete aktualisieren? Der Vorgang kann mehrere Minuten dauern."
  );
  if (!confirmed) return;
  try {
    renderUpdateStatus(await api("/api/system/update", { method: "POST" }));
    notify("Systemupdate wurde im Hintergrund gestartet");
  } catch (error) {
    notify(error.message, true);
  }
});

window.setInterval(() => {
  if (!document.querySelector("#system-page").hidden) {
    loadUpdateStatus();
    loadApplicationUpdateStatus();
    loadMonitoring();
  }
  if (!document.querySelector("#settings-page").hidden) {
    loadDisplayControl();
  }
}, 5000);

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button");
  button.disabled = true;
  uploadWarning.hidden = true;
  try {
    const progress = uploadProgress(event.target);
    const item = await uploadWithProgress("/api/content/upload", new FormData(event.target), progress.update);
    progress.finish();
    event.target.reset();
    await load();
    if (item.compatibility?.warnings?.length) {
      const list = uploadWarning.querySelector("ul");
      list.replaceChildren();
      item.compatibility.warnings.forEach((warning) => {
        const entry = document.createElement("li");
        entry.textContent = warning;
        list.append(entry);
      });
      uploadWarning.querySelector("p").textContent = item.compatibility.recommendation;
      uploadWarning.hidden = false;
      notify("Medium hochgeladen – bitte Formatwarnung beachten", true);
    } else {
      notify("Medium hochgeladen und Videoformat geprüft");
    }
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#website-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api("/api/content/website", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: form.get("name"),
        url: form.get("url"),
        duration_seconds: Number(form.get("duration_seconds")),
      }),
    });
    event.target.reset();
    await load();
    notify("Webseite hinzugefügt");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#stream-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api("/api/content/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: form.get("name"),
        url: form.get("url"),
        duration_seconds: Number(form.get("duration_seconds")),
        muted: form.get("muted") === "on",
      }),
    });
    event.target.reset();
    event.target.elements.muted.checked = true;
    await load();
    notify("Livestream hinzugefügt");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#text-preview-button").addEventListener("click", () => {
  const form = new FormData(textForm);
  const selected = textForm.elements.background.files[0];
  const libraryMedium = libraryItems.find(item => String(item.id) === String(form.get("library_media_id")));
  const source = selected ? URL.createObjectURL(selected) : libraryMedium?.source || editingTextItem?.source;
  if (!source) {
    notify("Bitte zuerst ein Hintergrundbild oder -video auswählen", true);
    return;
  }
  if (!form.get("headline")?.trim() && !form.get("subheadline")?.trim() && !form.get("body")?.trim()) {
    notify("Bitte mindestens ein Textfeld ausfüllen", true);
    if (selected) URL.revokeObjectURL(source);
    return;
  }
  if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
  previewObjectUrl = selected ? source : null;
  const selectedLogo = textForm.elements.logo.files[0];
  const logoSource = selectedLogo ? URL.createObjectURL(selectedLogo) :
    (form.get("remove_logo") === "on" ? null : editingTextItem?.text_config?.logo_source);
  renderTextSlide(document.querySelector("#text-preview-stage"), source, {
    headline: form.get("headline").trim(),
    subheadline: form.get("subheadline").trim(),
    body: form.get("body").trim(),
    shadow_box: form.get("shadow_box") === "on",
    shadow_intensity: form.get("shadow_intensity"),
    text_align: form.get("text_align"), vertical_position: form.get("vertical_position"),
    text_color: form.get("text_color"), accent_color: form.get("accent_color"),
    font_size: form.get("font_size"), font_family: form.get("font_family"),
    background_dim: Number(form.get("background_dim")), focus_x: Number(form.get("focus_x")),
    focus_y: Number(form.get("focus_y")), template_style: form.get("template_style"),
    logo_source: logoSource,
    background_kind: selected ? (selected.type.startsWith("video/") ? "video" : "image") :
      libraryMedium?.kind || editingTextItem?.text_config?.background_kind || "image",
  });
  textPreviewDialog.showModal();
  const previewVideo = document.querySelector("#text-preview-stage .text-background-video");
  previewVideo?.play().catch(() => {
    const error = document.querySelector("#text-preview-error");
    error.textContent = "Die Videovorschau konnte nicht gestartet werden. Bitte das Video in der Mediathek mit „Optimal konvertieren“ optimieren.";
    error.hidden = false;
  });
});

document.querySelector("#text-preview-close").addEventListener("click", () => textPreviewDialog.close());
textPreviewDialog.addEventListener("close", () => {
  if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
  previewObjectUrl = null;
});

document.querySelector("#text-cancel-edit").addEventListener("click", () => { resetTextForm(); showAddContent(""); });

textForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#text-save-button");
  button.disabled = true;
  try {
    const form = new FormData(textForm);
    const id = form.get("content_id");
    form.delete("content_id");
    if (!form.get("background")?.size) form.delete("background");
    if (!form.get("background") && !form.get("library_media_id") && !editingTextItem) {
      throw new Error("Bitte ein Hintergrundbild oder -video hochladen oder aus der Mediathek auswählen");
    }
    await api(id ? `/api/content/${id}/text` : "/api/content/text", {
      method: "POST",
      body: form,
    });
    resetTextForm();
    showAddContent("");
    await load();
    notify(id ? "Freitext aktualisiert" : "Freitext zur Playlist hinzugefügt");
  } catch (error) { notify(error.message, true); }
  finally { button.disabled = false; }
});

document.querySelector("#library-upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button");
  const warning = document.querySelector("#library-upload-warning");
  button.disabled = true;
  warning.hidden = true;
  try {
    const progress = uploadProgress(event.target);
    const item = await uploadWithProgress("/api/media-library", new FormData(event.target), progress.update);
    progress.finish();
    event.target.reset();
    await loadLibrary();
    if (item.compatibility?.warnings?.length) {
      const list = warning.querySelector("ul");
      list.replaceChildren(...item.compatibility.warnings.map(text => {
        const entry = document.createElement("li");
        entry.textContent = text;
        return entry;
      }));
      warning.querySelector("p").textContent = item.compatibility.recommendation;
      warning.hidden = false;
    }
    notify("Medium in der Mediathek gespeichert");
  } catch (error) { notify(error.message, true); }
  finally { button.disabled = false; }
});

document.querySelector("#library-refresh").addEventListener("click", loadLibrary);
["#library-search", "#library-type-filter", "#library-usage-filter", "#library-category-filter"].forEach(selector => {
  document.querySelector(selector).addEventListener("input", applyLibraryFilters);
});
document.querySelector("#library-bulk-add").addEventListener("click", async () => {
  try {
    await api("/api/media-library/bulk-playlist", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        media_ids: [...selectedMediaIds],
        duration_seconds: Number(document.querySelector("#library-bulk-duration").value),
        muted: document.querySelector("#library-bulk-muted").value === "true",
        play_to_end: document.querySelector("#library-bulk-play-to-end").checked,
      }),
    });
    selectedMediaIds.clear();
    await Promise.all([loadLibrary(), load()]);
    updateBulkActions();
    notify("Ausgewählte Medien zur Playlist hinzugefügt");
  } catch (error) { notify(error.message, true); }
});
document.querySelector("#image-editor-cancel").addEventListener("click", () => document.querySelector("#image-editor-dialog").close());
document.querySelector("#image-editor-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!editingLibraryImage) return;
  const form = new FormData(event.target);
  try {
    await api(`/api/media-library/${editingLibraryImage.id}/edit-image`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rotate: Number(form.get("rotate")), crop_16_9: form.get("crop_16_9") === "on",
        brightness: Number(form.get("brightness")), contrast: Number(form.get("contrast")),
        focus_x: Number(form.get("focus_x")), focus_y: Number(form.get("focus_y")),
      }),
    });
    document.querySelector("#image-editor-dialog").close();
    await Promise.all([loadLibrary(), load()]);
    notify("Bild optimiert und gespeichert");
  } catch (error) { notify(error.message, true); }
});
textForm.elements.background.addEventListener("change", () => {
  if (textForm.elements.background.files.length) textForm.elements.library_media_id.value = "";
});
textForm.elements.library_media_id.addEventListener("change", () => {
  if (textForm.elements.library_media_id.value) textForm.elements.background.value = "";
});
textForm.elements.shadow_box.addEventListener("change", () => {
  document.querySelector("#shadow-intensity-label").hidden = !textForm.elements.shadow_box.checked;
});
textForm.elements.background_dim.addEventListener("input", (event) => {
  document.querySelector("#background-dim-output").value = `${event.target.value} %`;
});

textForm.elements.template_style.addEventListener("change", (event) => {
  const presets = {
    standard: { text_align: "left", vertical_position: "center", font_family: "sans", accent_color: "#39d98a" },
    elegant: { text_align: "center", vertical_position: "center", font_family: "serif", accent_color: "#f2d49b" },
    alert: { text_align: "left", vertical_position: "center", font_family: "sans", accent_color: "#ffcc00" },
  };
  Object.entries(presets[event.target.value]).forEach(([field, value]) => { textForm.elements[field].value = value; });
});

document.querySelector("#refresh").addEventListener("click", load);
document.querySelector("#add-content-type").addEventListener("change", event => showAddContent(event.target.value));

document.querySelector("#playlist-select").addEventListener("change", async (event) => {
  try {
    await api(`/api/playlists/${event.target.value}/activate`, { method: "POST" });
    await Promise.all([loadPlaylists(), load()]);
    notify("Aktive Playlist gewechselt");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#playlist-create").addEventListener("click", async () => {
  const name = window.prompt("Name der neuen Playlist:");
  if (!name?.trim()) return;
  try {
    const created = await api("/api/playlists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    await api(`/api/playlists/${created.id}/activate`, { method: "POST" });
    await Promise.all([loadPlaylists(), load()]);
    notify("Playlist erstellt und aktiviert");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#schedule-cancel").addEventListener("click", () => {
  document.querySelector("#schedule-dialog").close();
});

document.querySelector("#schedule-clear").addEventListener("click", async () => {
  if (!schedulingItem) return;
  try {
    await updateItem(schedulingItem.id, { clear_schedule: true });
    document.querySelector("#schedule-dialog").close();
    await load();
    notify("Zeitplan entfernt");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#schedule-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!schedulingItem) return;
  const form = new FormData(event.target);
  const payload = {
    schedule_start: form.get("schedule_start") ? new Date(form.get("schedule_start")).toISOString() : null,
    schedule_end: form.get("schedule_end") ? new Date(form.get("schedule_end")).toISOString() : null,
    schedule_weekdays: form.getAll("weekday").map(Number),
    schedule_daily_start: form.get("schedule_daily_start") || null,
    schedule_daily_end: form.get("schedule_daily_end") || null,
  };
  try {
    await updateItem(schedulingItem.id, payload);
    document.querySelector("#schedule-dialog").close();
    await load();
    notify("Zeitplan gespeichert");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#playlist-schedule-cancel").addEventListener("click", () => document.querySelector("#playlist-schedule-dialog").close());
document.querySelector("#playlist-schedule-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!schedulingPlaylist) return;
  const form = new FormData(event.target);
  try {
    await api(`/api/playlists/${schedulingPlaylist.id}/schedule`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        schedule_enabled: form.get("schedule_enabled") === "on",
        schedule_start: form.get("schedule_start") ? new Date(form.get("schedule_start")).toISOString() : null,
        schedule_end: form.get("schedule_end") ? new Date(form.get("schedule_end")).toISOString() : null,
        schedule_weekdays: form.getAll("weekday").map(Number),
        schedule_daily_start: form.get("schedule_daily_start") || null,
        schedule_daily_end: form.get("schedule_daily_end") || null,
      }),
    });
    document.querySelector("#playlist-schedule-dialog").close();
    await Promise.all([loadPlaylists(), load()]);
    notify("Playlist-Zeitplan gespeichert");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#storage-cleanup").addEventListener("click", async () => {
  if (!window.confirm("Alle ungenutzten Mediathek-Einträge und deren Dateien dauerhaft löschen?")) return;
  try {
    const result = await api("/api/system/storage/cleanup", { method: "POST" });
    await Promise.all([loadStorage(), loadLibrary()]);
    notify(`${result.removed_media} ungenutzte Medien gelöscht`);
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#storage-orphan-cleanup").addEventListener("click", async () => {
  if (!window.confirm("Alle Dateien löschen, die keinem Mediathek-Eintrag zugeordnet sind?")) return;
  try {
    const result = await api("/api/system/storage/orphans/cleanup", { method: "POST" });
    await loadStorage(); notify(`${result.removed_files} verwaiste Dateien gelöscht`);
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#backup-create").addEventListener("click", async () => {
  const button = document.querySelector("#backup-create"); button.disabled = true;
  try {
    await api("/api/system/backups", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ include_media: document.querySelector("#backup-include-media").checked }) });
    await Promise.all([loadBackups(), loadSecurityStatus()]); notify("Backup erfolgreich erstellt");
  } catch (error) { notify(error.message, true); }
  finally { button.disabled = false; }
});

document.querySelector("#backup-restore-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!window.confirm("Das Backup ersetzt Playlists, Einstellungen und gegebenenfalls Medien. Fortfahren?")) return;
  try {
    const result = await api("/api/system/backups/restore", { method: "POST", body: new FormData(event.target) });
    notify(result.message, false, 10000); event.target.reset();
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#device-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    const updated = await api("/api/system/device", { method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: form.get("role"), controller_url: form.get("controller_url"), pairing_code: form.get("pairing_code"), current_password: form.get("current_password") }) });
    event.target.elements.current_password.value = "";
    await loadDevice();
    if (updated.role !== "display") await Promise.all([load(), loadLibrary(), loadPlaylists()]);
    notify("Gerätekonfiguration gespeichert");
  } catch (error) { notify(error.message, true); }
});

document.querySelector('#device-form [name="role"]').addEventListener("change", event => {
  const form = event.target.form; const mode = event.target.value;
  form.elements.controller_url.closest("label").hidden = mode !== "display";
  form.elements.pairing_code.closest("label").hidden = mode !== "display";
  form.elements.controller_pairing_code.closest("label").hidden = mode !== "controller";
});

document.querySelector("#sync-now").addEventListener("click", async () => {
  const button = document.querySelector("#sync-now"); button.disabled = true;
  try { await api("/api/system/device/sync", { method: "POST" }); await Promise.all([loadDevice(), load(), loadLibrary(), loadPlaylists()]); notify("Synchronisierung abgeschlossen"); }
  catch (error) { notify(error.message, true); }
  finally { button.disabled = false; }
});

document.querySelector("#display-control-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    const result = await api("/api/system/display-control", {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cec_address: form.get("cec_address"),
        activate_source: form.get("activate_source") === "on",
        fallback_hdmi_signal: form.get("fallback_hdmi_signal") === "on",
        resolution_mode: form.get("resolution_mode"),
        transition_ms: Number(form.get("transition_ms")),
        schedule_enabled: form.get("schedule_enabled") === "on",
        schedule_entries: [...event.target.querySelectorAll(".display-schedule-row")]
          .map(row => ({ weekday: Number(row.querySelector(".schedule-weekday").value), on: row.querySelector(".day-on").value, off: row.querySelector(".day-off").value })),
      }),
    });
    displayControlDirty = false;
    renderDisplayControl(result, true);
    notify("Bildschirmsteuerung und Zeitplan gespeichert");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#display-control-form").addEventListener("input", event => {
  if (event.target.name === "transition_ms") {
    document.querySelector("#transition-ms-output").value = `${event.target.value} ms`;
  }
  displayControlDirty = true;
});

document.querySelector("#display-schedule-add").addEventListener("click", () => {
  document.querySelector("#display-schedule-entries").append(createDisplayScheduleRow());
  displayControlDirty = true;
});

document.querySelector("#display-schedule-entries").addEventListener("click", event => {
  const row = event.target.closest(".display-schedule-row");
  if (event.target.closest(".display-schedule-remove")) row.remove();
  else if (event.target.closest(".display-schedule-duplicate")) {
    row.after(createDisplayScheduleRow({ weekday: Number(row.querySelector(".schedule-weekday").value), on: row.querySelector(".day-on").value, off: row.querySelector(".day-off").value }));
  } else return;
  displayControlDirty = true;
});

["display-schedule-copy-source", "display-schedule-copy-target"].forEach((id, selectIndex) => {
  const select = document.querySelector(`#${id}`);
  displayWeekdays.forEach((name, index) => select.append(new Option(`${selectIndex ? "Nach" : "Von"}: ${name}`, index)));
  if (selectIndex) select.value = "1";
});

document.querySelector("#display-schedule-copy").addEventListener("click", () => {
  const source = Number(document.querySelector("#display-schedule-copy-source").value);
  const targetDay = Number(document.querySelector("#display-schedule-copy-target").value);
  if (source === targetDay) { notify("Bitte zwei unterschiedliche Wochentage auswählen", true); return; }
  const target = document.querySelector("#display-schedule-entries");
  target.querySelectorAll(".display-schedule-row").forEach(row => {
    if (Number(row.querySelector(".schedule-weekday").value) === targetDay) row.remove();
  });
  [...target.querySelectorAll(".display-schedule-row")]
    .filter(row => Number(row.querySelector(".schedule-weekday").value) === source)
    .forEach(row => target.append(createDisplayScheduleRow({ weekday: targetDay, on: row.querySelector(".day-on").value, off: row.querySelector(".day-off").value })));
  displayControlDirty = true;
});

document.querySelectorAll("[data-display-action]").forEach(button => button.addEventListener("click", async () => {
  const action = button.dataset.displayAction;
  if (action === "off" && !window.confirm("Den angeschlossenen Bildschirm jetzt ausschalten?")) return;
  button.disabled = true;
  try {
    await api("/api/system/display-control/action", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }),
    });
    notify(action === "on" ? "Einschalten angefordert" : action === "off" ? "Ausschalten angefordert" : "Statusabfrage gestartet");
    window.setTimeout(loadDisplayControl, 2000);
  } catch (error) { notify(error.message, true); }
  finally { window.setTimeout(() => { button.disabled = false; }, 2000); }
}));

document.querySelectorAll("[data-system-action]").forEach(button => button.addEventListener("click", async () => {
  const action = button.dataset.systemAction;
  const labels = { restart_service: "Open Signage neu starten", reboot: "den Raspberry Pi neu starten", poweroff: "den Raspberry Pi herunterfahren" };
  if (!window.confirm(`${labels[action]}?`)) return;
  try {
    await api("/api/system/action", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) });
    notify("Systemaktion wurde angefordert");
  } catch (error) { notify(error.message, true); }
}));
boot();
