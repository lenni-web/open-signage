// Live-Übertragung aus OBS: Signalstatus, Übernahme der Wiedergabe und OBS-Zugangsdaten.

let liveStatus = null;

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
  const started = status.takeover_started_at
    ? new Date(status.takeover_started_at).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) : "";
  document.querySelector("#live-takeover-status").textContent = status.takeover
    ? `Live hat die Wiedergabe seit ${started} Uhr übernommen${status.available ? "." : " – wartet auf Signal aus OBS."}`
    : "Die Playlist läuft normal.";
  if (status.takeover) {
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

document.querySelector("#live-takeover-start").addEventListener("click", () => setLiveTakeover(true));
document.querySelector("#live-takeover-stop").addEventListener("click", () => setLiveTakeover(false));

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
  if (!document.querySelector("#content-page").hidden && currentDeviceMode !== "display" &&
      !document.querySelector("#admin-app").hidden) {
    loadLive();
  }
}, 5000);
