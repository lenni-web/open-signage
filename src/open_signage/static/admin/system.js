// Systemseite und Einstellungen: Monitoring, Updates, Speicher, Backups, Gerät.

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

document.querySelectorAll("[data-system-action]").forEach(button => button.addEventListener("click", async () => {
  const action = button.dataset.systemAction;
  const labels = { restart_service: "Open Signage neu starten", reboot: "den Raspberry Pi neu starten", poweroff: "den Raspberry Pi herunterfahren" };
  if (!window.confirm(`${labels[action]}?`)) return;
  try {
    await api("/api/system/action", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) });
    notify("Systemaktion wurde angefordert");
  } catch (error) { notify(error.message, true); }
}));
