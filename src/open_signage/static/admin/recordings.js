// Aufnahmen der Live-Übertragungen: Liste, Download (auch mit AAC-Ton) und Löschen.

let recordingsSignature = "";
const recordingDownloads = new Set();  // Aufnahmen, die nach dem Umwandeln automatisch herunterladen

function formatDuration(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  return hours ? `${hours}:${String(minutes).padStart(2, "0")} h` : `${Math.max(1, minutes)} min`;
}

function recordingUrl(name, audio = "original") {
  return `/api/recordings/${encodeURIComponent(name)}/download${audio === "aac" ? "?audio=aac" : ""}`;
}

function startDownload(url) {
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  document.body.append(link);
  link.click();
  link.remove();
}

function renderRecording(item) {
  const row = document.createElement("article");
  row.className = `recording-row${item.active ? " active" : ""}`;
  const info = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = new Date(item.started_at).toLocaleString("de-DE", {
    weekday: "short", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  }) + " Uhr";
  const details = document.createElement("small");
  details.textContent = item.active
    ? `Aufnahme läuft · ${formatDuration(item.duration_seconds)} · ${formatBytes(item.size_bytes)}`
    : `${formatDuration(item.duration_seconds)} · ${formatBytes(item.size_bytes)}`;
  info.append(title, details);

  const actions = document.createElement("div");
  actions.className = "forwarding-actions";
  if (!item.active) {
    const download = document.createElement("a");
    download.className = "button secondary";
    download.href = recordingUrl(item.name);
    download.download = "";
    download.textContent = "Herunterladen";
    download.title = "Original: Bild H.264, Ton Opus – spielt z. B. in VLC und im Browser";
    const converted = document.createElement("button");
    converted.type = "button";
    converted.className = "secondary";
    const state = item.conversion?.status;
    converted.textContent = state === "running" ? "Ton wird umgewandelt …" : "Download mit AAC-Ton";
    converted.disabled = state === "running";
    converted.title = "Ton nach AAC umgewandelt, für Programme ohne Opus-Unterstützung (z. B. Windows-Mediaplayer, Schnittprogramme)";
    converted.addEventListener("click", async () => {
      if (state === "done") return startDownload(recordingUrl(item.name, "aac"));
      try {
        const result = await api(`/api/recordings/${encodeURIComponent(item.name)}/convert`, { method: "POST" });
        if (result.status === "done") return startDownload(recordingUrl(item.name, "aac"));
        recordingDownloads.add(item.name);
        notify("Der Ton wird umgewandelt – der Download startet danach automatisch.", false, 6000);
        await loadRecordings();
      } catch (error) { notify(error.message, true); }
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Löschen";
    remove.addEventListener("click", async () => {
      if (!window.confirm("Diese Aufnahme endgültig löschen?")) return;
      try {
        await api(`/api/recordings/${encodeURIComponent(item.name)}`, { method: "DELETE" });
        notify("Aufnahme gelöscht");
        await loadRecordings();
      } catch (error) { notify(error.message, true); }
    });
    actions.append(download, converted, remove);
    if (state === "failed") {
      const failure = document.createElement("small");
      failure.className = "forwarding-error";
      failure.textContent = `Umwandlung fehlgeschlagen: ${item.conversion.message || "unbekannter Fehler"}`;
      info.append(failure);
    }
  }
  row.append(info, actions);
  return row;
}

async function loadRecordings() {
  const state = await api("/api/recordings");
  document.querySelector("#recordings-card").hidden = !state.available;
  if (!state.available) return;
  document.querySelector("#recordings-enabled").checked = state.enabled;
  const total = state.recordings.reduce((sum, item) => sum + item.size_bytes, 0);
  document.querySelector("#recordings-note").textContent = state.enabled
    ? `Jede Übertragung aus OBS wird unverändert aufgenommen. Behalten werden die letzten ${state.keep} Aufnahmen` +
      (state.recordings.length ? ` – belegt: ${formatBytes(total)}.` : ".")
    : "Die automatische Aufnahme ist ausgeschaltet. Vorhandene Aufnahmen bleiben erhalten.";
  // Fertige Umwandlungen, die der Nutzer angestoßen hat, gleich herunterladen.
  for (const item of state.recordings) {
    if (recordingDownloads.has(item.name) && item.conversion?.status !== "running") {
      recordingDownloads.delete(item.name);
      if (item.conversion?.status === "done") startDownload(recordingUrl(item.name, "aac"));
      else notify(`Umwandlung fehlgeschlagen: ${item.conversion?.message || "unbekannter Fehler"}`, true, 8000);
    }
  }
  const signature = JSON.stringify(state.recordings.map(item =>
    [item.name, item.active, item.active || item.size_bytes, item.conversion?.status]));
  if (signature === recordingsSignature) {
    // Laufende Aufnahme: nur Dauer und Größe nachführen, ohne die Liste neu aufzubauen.
    const active = state.recordings.find(item => item.active);
    const row = document.querySelector("#recordings-list .recording-row.active small");
    if (active && row) row.textContent = `Aufnahme läuft · ${formatDuration(active.duration_seconds)} · ${formatBytes(active.size_bytes)}`;
    return;
  }
  recordingsSignature = signature;
  document.querySelector("#recordings-empty").hidden = state.recordings.length > 0;
  document.querySelector("#recordings-list").replaceChildren(...state.recordings.map(renderRecording));
}

document.querySelector("#recordings-enabled").addEventListener("change", async (event) => {
  try {
    const result = await api("/api/recordings/settings", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: event.target.checked }),
    });
    notify(result.enabled ? "Übertragungen werden wieder aufgenommen" : "Automatische Aufnahme ausgeschaltet");
    await loadRecordings();
  } catch (error) {
    event.target.checked = !event.target.checked;
    notify(error.message, true);
  }
});

window.setInterval(() => {
  if (!document.querySelector("#forwarding-page").hidden && !document.querySelector("#admin-app").hidden) {
    loadRecordings().catch(() => {});
  }
}, 3000);
