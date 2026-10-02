// Inhalte der Playlist: Liste, Uploads, Webseiten, Livestreams, Freitext und Zeitpläne.

function kindLabel(kind) {
  return { image: "Bild", video: "Video", pdf: "PDF", website: "Webseite", stream: "Livestream", text: "Freitext", live: "Live (OBS)" }[kind] || kind;
}

function hasSchedule(item) {
  return Boolean(item.schedule_start || item.schedule_end || item.schedule_daily_start ||
    item.schedule_daily_end || item.schedule_weekdays?.length);
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
  const previewError = document.querySelector("#text-preview-error");
  previewError.hidden = true;
  previewError.textContent = "";
  target.style.backgroundImage = source && config.background_kind !== "video" ? `url("${source.replaceAll('"', '%22')}")` : "none";
  if (source && config.background_kind === "video") {
    const video = document.createElement("video");
    video.className = "text-background-video";
    video.src = source; video.autoplay = true; video.muted = true; video.loop = true; video.playsInline = true;
    video.addEventListener("loadeddata", () => { previewError.hidden = true; }, { once: true });
    video.addEventListener("error", () => {
      previewError.textContent = "Das Video kann in diesem Browser nicht abgespielt werden. Bitte das Video in der Mediathek mit „Optimal konvertieren“ in MP4/H.264 umwandeln und anschließend erneut auswählen.";
      previewError.hidden = false;
    }, { once: true });
    target.append(video);
  }
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
  document.querySelector("#text-background-note").textContent = "JPG, PNG, WebP, MP4 oder WebM";
  document.querySelector("#text-save-button").textContent = "Speichern und zur Playlist hinzufügen";
  document.querySelector("#text-cancel-edit").hidden = true;
}

function editTextItem(item) {
  showAddContent("text");
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
  document.querySelector("#text-background-note").textContent = "Optional: neues Bild oder Video auswählen, sonst bleibt der bisherige Hintergrund erhalten.";
  document.querySelector("#text-save-button").textContent = "Änderungen speichern";
  document.querySelector("#text-cancel-edit").hidden = false;
  textForm.scrollIntoView({ behavior: "smooth", block: "start" });
}

function showAddContent(type) {
  document.querySelector("#add-content-type").value = type;
  document.querySelectorAll(".add-content-card").forEach(card => { card.hidden = card.dataset.addType !== type; });
  if (type) document.querySelector(`.add-content-card[data-add-type="${type}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
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
      ${["stream", "video", "live"].includes(item.kind) ? `
        <label class="toggle sound-toggle">
          <input type="checkbox" ${item.muted ? "" : "checked"}>
          <span>Ton</span>
        </label>
      ` : ""}
      ${item.kind === "video" ? `
        <label class="toggle end-toggle">
          <input type="checkbox" ${item.play_to_end ? "checked" : ""}>
          <span>Bis Ende</span>
        </label>
      ` : ""}
      ${item.kind === "text" ? '<button class="secondary edit-text">Bearbeiten</button>' : ""}
      <button class="secondary schedule">${hasSchedule(item) ? "Zeitplan ✓" : "Zeitplan"}</button>
      <button class="danger delete">Löschen</button>
    `;
    row.querySelector("strong").textContent = item.name;
    row.querySelector("small").textContent = item.kind === "live" ? "OBS über WebRTC" : item.source;
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
    row.querySelector(".end-toggle input")?.addEventListener("change", async (event) => {
      try {
        await updateItem(item.id, { play_to_end: event.target.checked });
        notify("Abspielverhalten gespeichert");
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

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button");
  button.disabled = true;
  uploadWarning.hidden = true;
  try {
    const progress = uploadProgress(event.target);
    const item = await uploadWithProgress("/api/content/upload", new FormData(event.target), progress.update);
    progress.finish();
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
  const libraryMedium = libraryItems.find(item => String(item.id) === String(form.get("library_media_id")));
  const source = selected ? URL.createObjectURL(selected) : libraryMedium?.source || editingTextItem?.source;
  if (!source) {
    notify("Bitte zuerst ein Hintergrundbild oder -video auswählen", true);
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
    background_kind: selected ? (selected.type.startsWith("video/") ? "video" : "image") :
      libraryMedium?.kind || editingTextItem?.text_config?.background_kind || "image",
  });
  textPreviewDialog.showModal();
  const previewVideo = document.querySelector("#text-preview-stage .text-background-video");
  previewVideo?.play().catch(() => {
    const error = document.querySelector("#text-preview-error");
    error.textContent = "Die Videovorschau konnte nicht gestartet werden. Bitte das Video in der Mediathek mit „Optimal konvertieren“ optimieren.";
    error.hidden = false;
  });
});

document.querySelector("#text-preview-close").addEventListener("click", () => textPreviewDialog.close());
textPreviewDialog.addEventListener("close", () => {
  if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
  previewObjectUrl = null;
});

document.querySelector("#text-cancel-edit").addEventListener("click", () => { resetTextForm(); showAddContent(""); });

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
      throw new Error("Bitte ein Hintergrundbild oder -video hochladen oder aus der Mediathek auswählen");
    }
    await api(id ? `/api/content/${id}/text` : "/api/content/text", {
      method: "POST",
      body: form,
    });
    resetTextForm();
    showAddContent("");
    await load();
    notify(id ? "Freitext aktualisiert" : "Freitext zur Playlist hinzugefügt");
  } catch (error) { notify(error.message, true); }
  finally { button.disabled = false; }
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
document.querySelector("#add-content-type").addEventListener("change", event => showAddContent(event.target.value));

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
