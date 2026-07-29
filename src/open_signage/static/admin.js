const playlist = document.querySelector("#playlist");
const empty = document.querySelector("#empty");
const message = document.querySelector("#message");

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

function kindLabel(kind) {
  return { image: "Bild", video: "Video", website: "Webseite", stream: "Livestream" }[kind] || kind;
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

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button");
  button.disabled = true;
  try {
    await api("/api/content/upload", { method: "POST", body: new FormData(event.target) });
    event.target.reset();
    await load();
    notify("Medium hochgeladen");
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
load();
