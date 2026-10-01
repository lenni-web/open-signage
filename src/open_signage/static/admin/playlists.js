// Playlists auswählen, anlegen und zeitgesteuert aktivieren.

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
