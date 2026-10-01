// Mediathek mit Filtern, Mehrfachauswahl und Bildeditor.

function populateLibraryImageSelect() {
  const select = document.querySelector("#text-library-image");
  const selected = select.value;
  select.replaceChildren(new Option("Kein Mediathek-Medium ausgewählt", ""));
  libraryItems.filter(item => ["image", "video"].includes(item.kind)).forEach((item) => {
    select.append(new Option(`${item.kind === "video" ? "Video" : "Bild"}: ${item.name}`, item.id));
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
