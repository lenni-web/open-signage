// Stream-Weiterleitung an RTMP-Ziele (z. B. Owncast), übernommen aus dem Projekt „Stream-Verteiler“.

const FORWARDING_STATES = {
  running: ["Läuft", "on"], starting: ["Startet …", "warn"], waiting: ["Wartet auf OBS", ""],
  retry: ["Fehler – neuer Versuch", "off"], disabled: ["Deaktiviert", ""],
};
const FORWARDING_AUDIO_MODES = {
  standard: ["Standard", "Ton wird unverändert von Opus nach AAC umgewandelt."],
  gaps: ["Lücken mit Stille füllen", "Fehlende Tonpakete werden mit Stille ersetzt, damit der Ton ohne Zeitsprünge durchläuft. Die Tonhöhe bleibt unverändert."],
  regular: ["Gleichmäßige Zeitstempel", "Der Ton bekommt neu berechnete, gleichmäßige Zeitstempel. Hilft bei unregelmäßig eintreffenden Paketen; nach Paketverlusten kann der Ton leicht gegen das Bild versetzt sein."],
  hq: ["Höhere AAC-Bitrate", "Wandelt den Ton mit 256 statt 160 kbit/s um."],
};
const forwardingCards = new Map();  // Ziel-ID -> Karte; bleibt beim Aktualisieren bestehen
const forwardingTests = {};         // Testergebnisse je Ziel-ID bzw. „dialog“
let forwardingEditing = null;

function forwardingElement(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function renderForwardingChecks(result) {
  if (!result) return [];
  if (result === "busy") return [forwardingElement("p", "schedule-note", "Teste …")];
  const list = forwardingElement("ul", "forwarding-checks");
  for (const check of result.checks) {
    const state = check.ok === true ? "ok" : check.ok === false ? "fail" : "info";
    const item = forwardingElement("li");
    item.append(forwardingElement("strong", state, check.ok === true ? "✓" : check.ok === false ? "✗" : "i"),
      forwardingElement("span", "", `${check.label}: `), forwardingElement("span", "detail", check.detail));
    list.append(item);
  }
  return [list];
}

async function runForwardingTest(body, key, done) {
  forwardingTests[key] = "busy";
  done();
  try {
    forwardingTests[key] = await api("/api/forwarding/test", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  } catch (error) {
    forwardingTests[key] = { ok: false, checks: [{ label: "Test", ok: false, detail: error.message }] };
  }
  done();
}

function describeForwardingTarget(target) {
  const mode = target.audio_aac === false ? " · Ton unverändert"
    : target.audio_mode !== "standard" ? ` · Ton: ${FORWARDING_AUDIO_MODES[target.audio_mode][0]}` : "";
  return `${target.url}/${target.has_secret ? "•••" : ""}${mode}`;
}

async function loadForwardingLog(card) {
  const { lines } = await api(`/api/forwarding/targets/${card.id}/log`);
  const signature = `${lines.length}:${lines.length ? lines[lines.length - 1].t : 0}`;
  if (signature === card.logSignature) return;
  card.logSignature = signature;
  const box = card.log;
  const stickToBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  box.replaceChildren(...(lines.length ? lines.map(line => {
    const row = forwardingElement("div", line.level === "error" ? "error" : "");
    row.append(forwardingElement("span", "time", new Date(line.t * 1000).toLocaleTimeString("de-DE")), line.msg);
    return row;
  }) : [forwardingElement("div", "", "Noch keine Einträge.")]));
  if (stickToBottom) box.scrollTop = box.scrollHeight;
}

function buildForwardingCard(id) {
  const card = { id, target: null, logOpen: false, logSignature: "", shownTest: null };
  card.root = forwardingElement("article", "card forwarding-target");
  const header = forwardingElement("header");
  const titles = forwardingElement("div");
  card.name = forwardingElement("strong");
  card.description = forwardingElement("small");
  card.error = forwardingElement("p", "forwarding-error");
  titles.append(card.name, card.description);
  card.pill = forwardingElement("span", "live-signal");
  header.append(titles, card.pill);
  const actions = forwardingElement("div", "forwarding-actions");
  const button = (label, className = "secondary") => {
    const item = forwardingElement("button", className, label);
    item.type = "button";
    actions.append(item);
    return item;
  };
  card.test = button("Testen");
  card.logButton = button("Protokoll");
  const edit = button("Bearbeiten");
  card.restart = button("Neu starten");
  const remove = button("Löschen", "danger");
  card.checks = forwardingElement("div");
  card.log = forwardingElement("div", "forwarding-log");
  card.log.hidden = true;
  card.root.append(header, card.error, actions, card.checks, card.log);

  card.test.addEventListener("click", () => runForwardingTest({ id }, id, () => updateForwardingChecks(card)));
  edit.addEventListener("click", () => openForwardingDialog(card.target));
  card.restart.addEventListener("click", async () => {
    try { await api(`/api/forwarding/targets/${id}/restart`, { method: "POST" }); await loadForwarding(); }
    catch (error) { notify(error.message, true); }
  });
  remove.addEventListener("click", async () => {
    if (!window.confirm(`„${card.target.name}“ löschen?`)) return;
    try { await api(`/api/forwarding/targets/${id}`, { method: "DELETE" }); await loadForwarding(); notify("Ziel gelöscht"); }
    catch (error) { notify(error.message, true); }
  });
  card.logButton.addEventListener("click", () => {
    card.logOpen = !card.logOpen;
    card.log.hidden = !card.logOpen;
    card.logButton.textContent = card.logOpen ? "Protokoll ausblenden" : "Protokoll";
    card.logSignature = "";
    if (card.logOpen) loadForwardingLog(card).catch(() => {});
  });
  return card;
}

function updateForwardingChecks(card) {
  const result = forwardingTests[card.id];
  card.test.disabled = result === "busy";
  if (result === card.shownTest && result !== "busy") return;
  card.shownTest = result;
  card.checks.replaceChildren(...renderForwardingChecks(result));
}

function updateForwardingCard(card, target) {
  card.target = target;
  card.name.textContent = target.name;
  card.description.textContent = describeForwardingTarget(target);
  card.error.textContent = target.status.error;
  card.error.hidden = !target.status.error;
  const [label, state] = FORWARDING_STATES[target.status.state] || [target.status.state, ""];
  const rate = target.status.state === "running" && target.status.bitrate_kbps
    ? ` · ${(target.status.bitrate_kbps / 1000).toFixed(1)} Mbit/s` : "";
  card.pill.textContent = label + rate;
  card.pill.className = `live-signal ${state}`;
  card.restart.disabled = !target.enabled;
  updateForwardingChecks(card);
}

async function loadForwarding() {
  const state = await api("/api/forwarding");
  const signal = document.querySelector("#forwarding-signal");
  signal.textContent = !state.ingest.server_running ? "Live-Server aus" : state.ingest.available ? "OBS sendet" : "Kein Signal";
  signal.className = `live-signal ${state.ingest.available ? "on" : ""}`;
  document.querySelector("#forwarding-empty").hidden = state.targets.length > 0;
  const list = document.querySelector("#forwarding-targets");
  const ids = new Set(state.targets.map(target => target.id));
  for (const [id, card] of forwardingCards) {
    if (!ids.has(id)) { card.root.remove(); forwardingCards.delete(id); }
  }
  state.targets.forEach((target, index) => {
    let card = forwardingCards.get(target.id);
    if (!card) { card = buildForwardingCard(target.id); forwardingCards.set(target.id, card); }
    updateForwardingCard(card, target);
    if (list.children[index] !== card.root) list.insertBefore(card.root, list.children[index] || null);
  });
  await Promise.all([...forwardingCards.values()].filter(card => card.logOpen)
    .map(card => loadForwardingLog(card).catch(() => {})));
}

function forwardingForm() {
  return document.querySelector("#forwarding-form");
}

function syncForwardingAudio() {
  const form = forwardingForm();
  form.elements.audio_mode.disabled = !form.elements.audio_aac.checked;
  document.querySelector("#forwarding-audio-hint").textContent = form.elements.audio_aac.checked
    ? FORWARDING_AUDIO_MODES[form.elements.audio_mode.value][1] +
      (forwardingEditing ? " Eine Änderung startet das Ziel kurz neu." : "")
    : "Der Ton wird unverändert weitergegeben (Opus); viele RTMP-Server akzeptieren das nicht.";
}

function showForwardingDialogChecks() {
  const result = forwardingTests.dialog;
  document.querySelector("#forwarding-dialog-checks").replaceChildren(...renderForwardingChecks(result));
  document.querySelector("#forwarding-dialog-test").disabled = result === "busy";
}

function openForwardingDialog(target) {
  forwardingEditing = target || null;
  const form = forwardingForm();
  form.reset();
  document.querySelector("#forwarding-dialog-title").textContent = target ? "Ziel bearbeiten" : "Ziel hinzufügen";
  form.elements.name.value = target?.name || "";
  form.elements.url.value = target?.url || "";
  form.elements.secret.value = "";
  form.elements.secret.placeholder = target?.has_secret ? "unverändert (leer lassen)" : "";
  form.elements.audio_aac.checked = target ? target.audio_aac !== false : true;
  form.elements.audio_mode.value = target?.audio_mode || "standard";
  form.elements.enabled.checked = target ? target.enabled : true;
  document.querySelector("#forwarding-dialog-error").hidden = true;
  delete forwardingTests.dialog;
  showForwardingDialogChecks();
  syncForwardingAudio();
  document.querySelector("#forwarding-dialog").showModal();
}

function forwardingFormBody() {
  const form = forwardingForm();
  return {
    name: form.elements.name.value, url: form.elements.url.value, secret: form.elements.secret.value,
    audio_aac: form.elements.audio_aac.checked, audio_mode: form.elements.audio_mode.value,
    enabled: form.elements.enabled.checked,
  };
}

document.querySelector("#forwarding-add").addEventListener("click", () => openForwardingDialog(null));
document.querySelector("#forwarding-dialog-cancel").addEventListener("click", () => document.querySelector("#forwarding-dialog").close());
forwardingForm().elements.audio_aac.addEventListener("change", syncForwardingAudio);
forwardingForm().elements.audio_mode.addEventListener("change", syncForwardingAudio);
document.querySelector("#forwarding-dialog-test").addEventListener("click", () => {
  const body = forwardingFormBody();
  if (forwardingEditing) body.id = forwardingEditing.id;
  runForwardingTest(body, "dialog", showForwardingDialogChecks);
});
forwardingForm().addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = document.querySelector("#forwarding-dialog-error");
  try {
    await api(forwardingEditing ? `/api/forwarding/targets/${forwardingEditing.id}` : "/api/forwarding/targets", {
      method: forwardingEditing ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(forwardingFormBody()),
    });
    document.querySelector("#forwarding-dialog").close();
    notify(forwardingEditing ? "Ziel gespeichert" : "Ziel hinzugefügt");
    await loadForwarding();
  } catch (failure) {
    error.textContent = failure.message;
    error.hidden = false;
  }
});

window.setInterval(() => {
  if (!document.querySelector("#forwarding-page").hidden && !document.querySelector("#admin-app").hidden) {
    loadForwarding().catch(() => {});
  }
}, 2000);
