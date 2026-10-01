// Bildschirmsteuerung per HDMI-CEC/DPMS mit Zeitplan.

function renderDisplayControl(data, updateForm = !displayControlDirty) {
  const config = data?.config || {};
  const status = data?.status || {};
  const scheduleEntries = Array.isArray(config.schedule_entries) ? config.schedule_entries : [];
  const form = document.querySelector("#display-control-form");
  if (updateForm) {
    form.elements.cec_address.value = config.cec_address;
    form.elements.activate_source.checked = config.activate_source;
    form.elements.fallback_hdmi_signal.checked = config.fallback_hdmi_signal;
    form.elements.resolution_mode.value = config.resolution_mode || "1080p60";
    form.elements.transition_ms.value = config.transition_ms || 4000;
    document.querySelector("#transition-ms-output").value = `${form.elements.transition_ms.value} ms`;
    form.elements.schedule_enabled.checked = config.schedule_enabled;
    const target = document.querySelector("#display-schedule-entries");
    target.replaceChildren(...scheduleEntries.map((entry, index) => {
      const row = createDisplayScheduleRow(entry);
      if (index === 0 || scheduleEntries[index - 1].weekday !== entry.weekday) row.classList.add("day-group-start");
      if ((data.schedule?.conflicts || []).some(conflict => conflict.first === index || conflict.second === index)) row.classList.add("schedule-conflict");
      return row;
    }));
  }
  const next = data.schedule?.next_action;
  document.querySelector("#display-schedule-next").textContent = next
    ? `Nächster Schaltvorgang: ${next.action === "on" ? "Einschalten" : "Ausschalten"} · ${new Date(next.at).toLocaleString("de-DE")}`
    : "Nächster Schaltvorgang: keiner geplant";
  const conflict = document.querySelector("#display-schedule-conflicts");
  const conflictCount = data.schedule?.conflicts?.length || 0;
  conflict.hidden = conflictCount === 0;
  conflict.textContent = conflictCount ? `${conflictCount} überlappende Zeitfenster erkannt. Sie werden gemeinsam als Einschaltzeit behandelt.` : "";
  document.querySelector("#display-cec-status").textContent = status.cec_available == null ? "Noch unbekannt" : status.cec_available ? "Verfügbar" : "Nicht verfügbar";
  document.querySelector("#display-fallback-status").textContent = status.hdmi_fallback_available == null ? "Noch unbekannt" : status.hdmi_fallback_available ? "Verfügbar" : "Nicht verfügbar";
  const powerLabels = status.method === "wayland_dpms"
    ? { on: "HDMI-Signal an", off: "HDMI-Signal aus", unknown: "Unbekannt" }
    : { on: "Eingeschaltet", off: "Ausgeschaltet", unknown: "Unbekannt" };
  document.querySelector("#display-power-status").textContent = powerLabels[status.power_status] || "Unbekannt";
  document.querySelector("#display-control-method").textContent = { cec: "HDMI-CEC", wayland_dpms: "Wayland-DPMS" }[status.method] || "Noch nicht erkannt";
  document.querySelector("#display-output-name").textContent = status.method === "cec"
    ? status.cec_adapter || "Standardadapter"
    : status.output_name || "–";
  document.querySelector("#display-updated-at").textContent = status.updated_at ? new Date(status.updated_at).toLocaleString("de-DE") : "Noch nie";
  document.querySelector("#display-status-message").textContent = status.message || "";
  document.querySelector("#display-resolution-status").textContent = status.current_resolution
    ? `Auflösung: ${status.current_resolution} · ${status.resolution_message || ""}`
    : `Auflösung: ${status.resolution_message || "noch nicht geprüft"}`;
}

const displayWeekdays = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];

function createDisplayScheduleRow(entry = { weekday: 0, on: "08:00", off: "22:00" }) {
  const row = document.createElement("div");
  row.className = "display-schedule-row";
  const weekday = document.createElement("select");
  weekday.className = "schedule-weekday";
  weekday.setAttribute("aria-label", "Wochentag");
  displayWeekdays.forEach((name, index) => weekday.append(new Option(name, index)));
  weekday.value = String(entry.weekday);
  const on = document.createElement("input");
  on.className = "day-on"; on.type = "time"; on.required = true; on.value = entry.on || "08:00";
  on.setAttribute("aria-label", "Einschaltzeit");
  const off = document.createElement("input");
  off.className = "day-off"; off.type = "time"; off.required = true; off.value = entry.off || "22:00";
  off.setAttribute("aria-label", "Ausschaltzeit");
  const remove = document.createElement("button");
  remove.type = "button"; remove.className = "danger display-schedule-remove"; remove.textContent = "Entfernen";
  const duplicate = document.createElement("button");
  duplicate.type = "button"; duplicate.className = "secondary display-schedule-duplicate"; duplicate.textContent = "Duplizieren";
  const actions = document.createElement("span"); actions.className = "schedule-row-actions"; actions.append(duplicate, remove);
  row.append(weekday, on, off, actions);
  return row;
}

async function loadDisplayControl() {
  try { renderDisplayControl(await api("/api/system/display-control")); }
  catch (error) { notify(error.message, true); }
}

document.querySelector("#display-control-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    const result = await api("/api/system/display-control", {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cec_address: form.get("cec_address"),
        activate_source: form.get("activate_source") === "on",
        fallback_hdmi_signal: form.get("fallback_hdmi_signal") === "on",
        resolution_mode: form.get("resolution_mode"),
        transition_ms: Number(form.get("transition_ms")),
        schedule_enabled: form.get("schedule_enabled") === "on",
        schedule_entries: [...event.target.querySelectorAll(".display-schedule-row")]
          .map(row => ({ weekday: Number(row.querySelector(".schedule-weekday").value), on: row.querySelector(".day-on").value, off: row.querySelector(".day-off").value })),
      }),
    });
    displayControlDirty = false;
    renderDisplayControl(result, true);
    notify("Bildschirmsteuerung und Zeitplan gespeichert");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#display-control-form").addEventListener("input", event => {
  if (event.target.name === "transition_ms") {
    document.querySelector("#transition-ms-output").value = `${event.target.value} ms`;
  }
  displayControlDirty = true;
});

document.querySelector("#display-schedule-add").addEventListener("click", () => {
  document.querySelector("#display-schedule-entries").append(createDisplayScheduleRow());
  displayControlDirty = true;
});

document.querySelector("#display-schedule-entries").addEventListener("click", event => {
  const row = event.target.closest(".display-schedule-row");
  if (event.target.closest(".display-schedule-remove")) row.remove();
  else if (event.target.closest(".display-schedule-duplicate")) {
    row.after(createDisplayScheduleRow({ weekday: Number(row.querySelector(".schedule-weekday").value), on: row.querySelector(".day-on").value, off: row.querySelector(".day-off").value }));
  } else return;
  displayControlDirty = true;
});

["display-schedule-copy-source", "display-schedule-copy-target"].forEach((id, selectIndex) => {
  const select = document.querySelector(`#${id}`);
  displayWeekdays.forEach((name, index) => select.append(new Option(`${selectIndex ? "Nach" : "Von"}: ${name}`, index)));
  if (selectIndex) select.value = "1";
});

document.querySelector("#display-schedule-copy").addEventListener("click", () => {
  const source = Number(document.querySelector("#display-schedule-copy-source").value);
  const targetDay = Number(document.querySelector("#display-schedule-copy-target").value);
  if (source === targetDay) { notify("Bitte zwei unterschiedliche Wochentage auswählen", true); return; }
  const target = document.querySelector("#display-schedule-entries");
  target.querySelectorAll(".display-schedule-row").forEach(row => {
    if (Number(row.querySelector(".schedule-weekday").value) === targetDay) row.remove();
  });
  [...target.querySelectorAll(".display-schedule-row")]
    .filter(row => Number(row.querySelector(".schedule-weekday").value) === source)
    .forEach(row => target.append(createDisplayScheduleRow({ weekday: targetDay, on: row.querySelector(".day-on").value, off: row.querySelector(".day-off").value })));
  displayControlDirty = true;
});

document.querySelectorAll("[data-display-action]").forEach(button => button.addEventListener("click", async () => {
  const action = button.dataset.displayAction;
  if (action === "off" && !window.confirm("Den angeschlossenen Bildschirm jetzt ausschalten?")) return;
  button.disabled = true;
  try {
    await api("/api/system/display-control/action", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }),
    });
    notify(action === "on" ? "Einschalten angefordert" : action === "off" ? "Ausschalten angefordert" : "Statusabfrage gestartet");
    window.setTimeout(loadDisplayControl, 2000);
  } catch (error) { notify(error.message, true); }
  finally { window.setTimeout(() => { button.disabled = false; }, 2000); }
}));
