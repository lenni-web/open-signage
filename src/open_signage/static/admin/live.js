// Live-Übertragung aus OBS: Signalstatus, Übernahme der Wiedergabe und OBS-Zugangsdaten.

let liveStatus = null;
let livePreviewSession = null;

// Vorschau in der Verwaltung: dieselbe WebRTC-Verbindung wie im Player, aber nur
// in diesem Browser – an den Displays ändert sich nichts.
function stopLivePreview() {
  livePreviewSession?.close();
  livePreviewSession = null;
  const video = document.querySelector("#live-preview-video");
  video.srcObject = null;
  document.querySelector("#live-preview").hidden = true;
  const toggle = document.querySelector("#live-preview-toggle");
  toggle.textContent = "Vorschau";
  toggle.disabled = !liveStatus?.available;
}

function startLivePreview() {
  const status = document.querySelector("#live-preview-status");
  status.textContent = "Verbindung wird hergestellt …";
  status.hidden = false;
  document.querySelector("#live-preview").hidden = false;
  document.querySelector("#live-preview-toggle").textContent = "Vorschau schließen";
  livePreviewSession = connectLive(document.querySelector("#live-preview-video"), {
    onStatus: text => {
      status.textContent = text;
      status.hidden = false;
    },
  });
}
let liveScheduleDirty = false;

function formatLiveTime(value) {
  return new Date(value).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

function formatLiveMoment(value) {
  const moment = new Date(value);
  const weekday = moment.toLocaleDateString("de-DE", { weekday: "long" });
  return `${weekday}, ${formatLiveTime(value)} Uhr`;
}

function createLiveScheduleRow(entry = { weekday: 6, start: "11:00", end: "12:30" }) {
  // displayWeekdays stammt aus display.js (Montag = 0) und steht beim Aufruf bereit.
  const row = document.createElement("div");
  row.className = "live-schedule-row";
  row.innerHTML = `
    <select name="weekday" aria-label="Wochentag">
      ${displayWeekdays.map((day, index) => `<option value="${index}">${day}</option>`).join("")}
    </select>
    <input name="start" type="time" required aria-label="Beginn">
    <span>bis</span>
    <input name="end" type="time" required aria-label="Ende">
    <button class="danger icon remove" type="button" title="Zeitfenster entfernen">×</button>
  `;
  row.querySelector('[name="weekday"]').value = String(entry.weekday);
  row.querySelector('[name="start"]').value = entry.start;
  row.querySelector('[name="end"]').value = entry.end;
  row.querySelector(".remove").addEventListener("click", () => {
    row.remove();
    liveScheduleDirty = true;
  });
  return row;
}

function renderLiveSchedule(status) {
  const form = document.querySelector("#live-schedule-form");
  if (!liveScheduleDirty) {
    form.elements.enabled.checked = status.schedule.enabled;
    form.elements.sound.checked = status.schedule.sound;
    document.querySelector("#live-schedule-entries")
      .replaceChildren(...status.schedule.entries.map(createLiveScheduleRow));
  }
  let text = "Der Zeitplan ist ausgeschaltet.";
  if (status.schedule.enabled && status.schedule_active_until) {
    text = status.schedule_takeover
      ? `Zeitfenster läuft bis ${formatLiveTime(status.schedule_active_until)} Uhr – Live wird gezeigt.`
      : `Zeitfenster läuft bis ${formatLiveTime(status.schedule_active_until)} Uhr – wartet auf Signal aus OBS.`;
  } else if (status.schedule.enabled && status.schedule_next) {
    text = `Nächstes Zeitfenster: ${formatLiveMoment(status.schedule_next)}.`;
  } else if (status.schedule.enabled) {
    text = "Der Zeitplan ist aktiv, enthält aber kein Zeitfenster.";
  }
  document.querySelector("#live-schedule-status").textContent = text;
}

function renderLive(status) {
  liveStatus = status;
  const card = document.querySelector("#live-card");
  const signal = document.querySelector("#live-signal");
  if (!status.server_installed) {
    signal.textContent = "Live-Server fehlt";
    signal.className = "live-signal off";
  } else if (!status.server_running) {
    signal.textContent = "Live-Server startet …";
    signal.className = "live-signal off";
  } else {
    signal.textContent = status.available ? "OBS sendet" : "Kein Signal";
    signal.className = `live-signal ${status.available ? "on" : ""}`;
  }
  card.classList.toggle("active", status.takeover);
  document.querySelector("#live-takeover-start").hidden = status.takeover;
  document.querySelector("#live-takeover-stop").hidden = !status.takeover;
  document.querySelector("#live-setup").hidden = status.server_installed && status.server_running;
  if (!livePreviewSession) document.querySelector("#live-preview-toggle").disabled = !status.available;
  let takeoverText = "Die Playlist läuft normal.";
  if (status.manual_takeover) {
    const started = status.takeover_started_at ? formatLiveTime(status.takeover_started_at) : "";
    takeoverText = `Live hat die Wiedergabe seit ${started} Uhr übernommen${status.available ? "." : " – wartet auf Signal aus OBS."}`;
  } else if (status.schedule_takeover) {
    takeoverText = `Live läuft nach Zeitplan bis ${formatLiveTime(status.schedule_active_until)} Uhr.`;
  }
  document.querySelector("#live-takeover-status").textContent = takeoverText;
  renderLiveSchedule(status);
  if (status.manual_takeover) {
    document.querySelector("#live-sound").checked = status.sound;
    document.querySelector("#live-auto-end").checked = status.auto_end;
  }
  document.querySelector("#live-server-url").textContent =
    `http://${window.location.hostname}:${status.publish_port}${status.publish_path}`;
  document.querySelector("#live-token").textContent = status.publish_token;
}

async function loadLive() {
  try {
    renderLive(await api("/api/live"));
  } catch (error) {
    document.querySelector("#live-signal").textContent = "Status unbekannt";
  }
}

async function setLiveTakeover(active) {
  try {
    const status = await api("/api/live/takeover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        active,
        sound: document.querySelector("#live-sound").checked,
        auto_end: document.querySelector("#live-auto-end").checked,
      }),
    });
    renderLive({ ...liveStatus, ...status });
    notify(active ? "Live hat die Wiedergabe übernommen" : "Zurück zur Playlist");
  } catch (error) { notify(error.message, true); }
}

document.querySelector("#live-preview-video").addEventListener("playing", () => {
  document.querySelector("#live-preview-status").hidden = true;
});

document.querySelector("#live-preview-toggle").addEventListener("click", () => {
  if (livePreviewSession) stopLivePreview();
  else startLivePreview();
});

document.querySelector("#live-takeover-start").addEventListener("click", () => setLiveTakeover(true));
document.querySelector("#live-takeover-stop").addEventListener("click", () => setLiveTakeover(false));

document.querySelector("#live-schedule-add").addEventListener("click", () => {
  document.querySelector("#live-schedule-entries").append(createLiveScheduleRow());
  liveScheduleDirty = true;
});

document.querySelector("#live-schedule-form").addEventListener("input", () => { liveScheduleDirty = true; });

document.querySelector("#live-schedule-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const entries = [...document.querySelectorAll("#live-schedule-entries .live-schedule-row")].map(row => ({
    weekday: Number(row.querySelector('[name="weekday"]').value),
    start: row.querySelector('[name="start"]').value,
    end: row.querySelector('[name="end"]').value,
  }));
  try {
    const status = await api("/api/live/schedule", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: form.elements.enabled.checked, sound: form.elements.sound.checked, entries }),
    });
    liveScheduleDirty = false;
    renderLive({ ...liveStatus, ...status });
    notify("Zeitplan gespeichert");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#live-setup").addEventListener("click", async () => {
  try {
    await api("/api/live/setup", { method: "POST" });
    notify("Live-Server wird eingerichtet. Das dauert etwa eine Minute.", false, 6000);
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#live-password").addEventListener("click", async () => {
  if (!window.confirm("Neues Token erzeugen? OBS muss danach mit dem neuen Token verbunden werden.")) return;
  try {
    const result = await api("/api/live/password", { method: "POST" });
    document.querySelector("#live-token").textContent = result.publish_token;
    notify("Neues OBS-Token erzeugt");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#live-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api("/api/content/live", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: form.get("name"),
        duration_seconds: Number(form.get("duration_seconds")),
        muted: form.get("sound") !== "on",
      }),
    });
    event.target.reset();
    await load();
    notify("Live-Inhalt hinzugefügt");
  } catch (error) { notify(error.message, true); }
});

window.setInterval(() => {
  const visible = !document.querySelector("#content-page").hidden && currentDeviceMode !== "display" &&
    !document.querySelector("#admin-app").hidden;
  if (visible) loadLive();
  // Vorschau beim Verlassen der Inhalte-Seite beenden, damit keine Verbindung offen bleibt.
  else if (livePreviewSession) stopLivePreview();
}, 5000);

window.addEventListener("pagehide", () => livePreviewSession?.close());
