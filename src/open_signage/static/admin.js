const playlist = document.querySelector("#playlist");
const empty = document.querySelector("#empty");
const message = document.querySelector("#message");
const uploadWarning = document.querySelector("#upload-warning");

function notify(text, isError = false) {
  message.textContent = text;
  message.className = isError ? "show error" : "show";
  window.setTimeout(() => { message.className = ""; }, 3000);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Fehler ${response.status}`);
  }
  return response.status === 204 ? null : response.json();
}

function showSystemLogin() {
  document.querySelector("#system-login").hidden = false;
  document.querySelector("#system-content").hidden = true;
}

function showSystemContent(settings) {
  document.querySelector("#system-login").hidden = true;
  document.querySelector("#system-content").hidden = false;
  document.querySelector('#screen-settings-form [name="screen_name"]').value = settings.screen_name;
}

async function loadSettings() {
  try {
    const settings = await api("/api/settings");
    document.querySelector("#content-heading").textContent = `Inhalte – ${settings.screen_name}`;
  } catch (error) { notify(error.message, true); }
}

async function openSystemPage() {
  try {
    const session = await api("/api/system/session");
    showSystemContent(session);
    await Promise.all([loadSystemInfo(), loadUpdateStatus(), loadApplicationUpdateStatus()]);
  } catch (error) {
    showSystemLogin();
    if (error.message !== "Anmeldung erforderlich") notify(error.message, true);
  }
}

function kindLabel(kind) {
  return { image: "Bild", video: "Video", pdf: "PDF", website: "Webseite", stream: "Livestream" }[kind] || kind;
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
}

async function loadUpdateStatus() {
  try {
    renderUpdateStatus(await api("/api/system/update"));
  } catch (error) {
    notify(error.message, true);
  }
}

async function loadApplicationUpdateStatus() {
  try {
    renderApplicationUpdateStatus(await api("/api/system/application-update"));
  } catch (error) {
    notify(error.message, true);
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
    showSystemContent(session);
    await Promise.all([loadSystemInfo(), loadUpdateStatus(), loadApplicationUpdateStatus()]);
    notify("Anmeldung erfolgreich");
  } catch (error) { notify(error.message, true); }
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
});

document.querySelector("#application-update").addEventListener("click", async () => {
  const confirmed = window.confirm(
    "Jetzt den neuesten veröffentlichten Open-Signage-Release installieren?"
  );
  if (!confirmed) return;
  try {
    renderApplicationUpdateStatus(await api("/api/system/application-update", { method: "POST" }));
    notify("Anwendungsupdate wurde im Hintergrund gestartet");
  } catch (error) {
    notify(error.message, true);
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

document.querySelector("#refresh").addEventListener("click", load);
loadVersion();
loadSettings();
load();
