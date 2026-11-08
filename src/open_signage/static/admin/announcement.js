// Sofortmeldung, die auf allen Playern über dem laufenden Inhalt erscheint.

function renderAnnouncement(item) {
  const card = document.querySelector("#announcement-card");
  const state = document.querySelector("#announcement-state");
  const current = document.querySelector("#announcement-current");
  card.classList.toggle("active", Boolean(item));
  state.className = `live-signal ${item ? "off" : ""}`;
  state.textContent = item ? "Wird angezeigt" : "Keine Meldung";
  current.hidden = !item;
  if (item) {
    const until = item.until
      ? `bis ${new Date(item.until).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })} Uhr`
      : "bis zum Zurücknehmen";
    current.textContent = `„${item.text}“ – ${item.style === "fullscreen" ? "Vollbild" : "Laufband"}, ${until}`;
  }
  document.querySelector("#announcement-clear").hidden = !item;
}

async function loadAnnouncement() {
  try { renderAnnouncement((await api("/api/announcement")).announcement); }
  catch (error) { notify(error.message, true); }
}

document.querySelector("#announcement-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    const result = await api("/api/announcement", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: form.get("text"), style: form.get("style"),
        minutes: form.get("minutes") ? Number(form.get("minutes")) : null,
      }),
    });
    renderAnnouncement(result.announcement);
    notify("Sofortmeldung wird auf allen Displays angezeigt");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#announcement-clear").addEventListener("click", async () => {
  try {
    renderAnnouncement((await api("/api/announcement", { method: "DELETE" })).announcement);
    notify("Sofortmeldung zurückgenommen");
  } catch (error) { notify(error.message, true); }
});

// Abgelaufene Meldungen verschwinden auch in der Verwaltung von selbst.
window.setInterval(() => {
  if (!document.querySelector("#content-page").hidden && !document.querySelector("#admin-app").hidden &&
      !document.querySelector("#announcement-clear").hidden) loadAnnouncement();
}, 30000);
