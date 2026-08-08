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
let playlists = [];
let editingLibraryImage = null;
const selectedMediaIds = new Set();

function notify(text, isError = false) {
  message.textContent = text;
  message.className = isError ? "show error" : "show";
  window.setTimeout(() => { message.className = ""; }, 3000);
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

function showLogin() {
  document.querySelector("#login-screen").hidden = false;
  document.querySelector("#admin-app").hidden = true;
}

function showApplication(settings) {
  document.querySelector("#login-screen").hidden = true;
  document.querySelector("#admin-app").hidden = false;
  document.querySelector('#screen-settings-form [name="screen_name"]').value = settings.screen_name;
  document.querySelector("#content-heading").textContent = `Inhalte – ${settings.screen_name}`;
}

async function loadSettings() {
  try {
    const settings = await api("/api/settings");
    document.querySelector("#content-heading").textContent = `Inhalte – ${settings.screen_name}`;
  } catch (error) { notify(error.message, true); }
}

async function openSystemPage() {
  await Promise.all([loadSystemInfo(), loadMonitoring(), loadUpdateStatus(), loadApplicationUpdateStatus()]);
}

async function boot() {
  try {
    const session = await api("/api/system/session");
    showApplication(session);
    await Promise.all([loadVersion(), load(), loadLibrary(), loadPlaylists()]);
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
  target.style.backgroundImage = source ? `url("${source.replaceAll('"', '%22')}")` : "none";
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
  document.querySelector("#text-background-note").textContent = "JPG, PNG oder WebP";
  document.querySelector("#text-save-button").textContent = "Speichern und zur Playlist hinzufügen";
  document.querySelector("#text-cancel-edit").hidden = true;
}

function editTextItem(item) {
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
  document.querySelector("#text-background-note").textContent = "Optional: neues Bild auswählen, sonst bleibt das bisherige erhalten.";
  document.querySelector("#text-save-button").textContent = "Änderungen speichern";
  document.querySelector("#text-cancel-edit").hidden = false;
  textForm.scrollIntoView({ behavior: "smooth", block: "start" });
}

function populateLibraryImageSelect() {
  const select = document.querySelector("#text-library-image");
  const selected = select.value;
  select.replaceChildren(new Option("Kein Mediathek-Bild ausgewählt", ""));
  libraryItems.filter(item => item.kind === "image").forEach((item) => {
    select.append(new Option(item.name, item.id));
  });
  if ([...select.options].some(option => option.value === selected)) select.value = selected;
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
    preview.src = item.thumbnail_source || item.source;
    if (item.kind === "video") {
      preview.muted = true;
      preview.controls = true;
      preview.preload = "metadata";
    }
    const body = document.createElement("div");
    body.className = "media-card-body";
    body.innerHTML = `
      <input class="media-name" value="" aria-label="Medienname">
      <input class="media-category" value="" placeholder="Kategorie" aria-label="Kategorie">
      <span class="media-card-meta">${kindLabel(item.kind)} · ${formatBytes(item.size_bytes)}${item.width ? ` · ${item.width}×${item.height}` : ""}${item.metadata?.duration_seconds ? ` · ${item.metadata.duration_seconds}s` : ""} · ${item.usage_count || 0}× verwendet</span>
      <div class="media-card-actions">
        <input class="library-duration" type="number" min="1" max="86400" value="10" title="Anzeigedauer in Sekunden">
        <button class="add-library">Zur Playlist</button>
        ${item.kind === "image" ? '<button class="secondary edit-library-image">Bearbeiten</button>' : ""}
        ${item.kind === "video" ? '<button class="secondary transcode-library-video">In MP4 konvertieren</button>' : ""}
        <button class="secondary save-library-meta">Speichern</button>
        <button class="danger delete-library">Löschen</button>
      </div>`;
    body.querySelector(".media-name").value = item.name;
    body.querySelector(".media-category").value = item.category || "";
    body.querySelector(".add-library").addEventListener("click", async () => {
      try {
        const duration = Number(body.querySelector(".library-duration").value);
        await api(`/api/media-library/${item.id}/playlist`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ duration_seconds: duration }),
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
      if (!window.confirm("Video jetzt nach MP4/H.264/AAC konvertieren?")) return;
      try {
        await api(`/api/media-library/${item.id}/transcode`, { method: "POST" });
        await loadLibrary();
        notify("Video erfolgreich konvertiert");
      } catch (error) { notify(error.message, true); }
    });
    card.append(selector, preview, body);
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
      ${item.kind === "stream" ? `
        <label class="toggle sound-toggle">
          <input type="checkbox" ${item.muted ? "" : "checked"}>
          <span>Ton</span>
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
    label.textContent = `${playlist.name} · ${playlist.content_count} Inhalte${playlist.active ? " · aktiv" : ""}`;
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
    row.append(label, button);
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
}, 5000);

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button");
  button.disabled = true;
  uploadWarning.hidden = true;
  try {
    const item = await api("/api/content/upload", {
      method: "POST",
      body: new FormData(event.target),
    });
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
  const libraryImage = libraryItems.find(item => String(item.id) === String(form.get("library_media_id")));
  const source = selected ? URL.createObjectURL(selected) : libraryImage?.source || editingTextItem?.source;
  if (!source) {
    notify("Bitte zuerst ein Hintergrundbild auswählen", true);
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
  });
  textPreviewDialog.showModal();
});

document.querySelector("#text-preview-close").addEventListener("click", () => textPreviewDialog.close());
textPreviewDialog.addEventListener("close", () => {
  if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
  previewObjectUrl = null;
});

document.querySelector("#text-cancel-edit").addEventListener("click", resetTextForm);

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
      throw new Error("Bitte ein Hintergrundbild hochladen oder aus der Mediathek auswählen");
    }
    await api(id ? `/api/content/${id}/text` : "/api/content/text", {
      method: "POST",
      body: form,
    });
    resetTextForm();
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
    const item = await api("/api/media-library", { method: "POST", body: new FormData(event.target) });
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
      body: JSON.stringify({ media_ids: [...selectedMediaIds], duration_seconds: Number(document.querySelector("#library-bulk-duration").value) }),
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
boot();
