// Gemeinsamer Zustand, Uhr, Meldungen, API- und Upload-Hilfen.

const playlist = document.querySelector("#playlist");
const empty = document.querySelector("#empty");
const message = document.querySelector("#message");
const uploadWarning = document.querySelector("#upload-warning");
const textForm = document.querySelector("#text-form");
const textPreviewDialog = document.querySelector("#text-preview-dialog");
let editingTextItem = null;
let previewObjectUrl = null;
let libraryItems = [];
let applicationUpdateInProgress = false;
let applicationReloadScheduled = false;
let schedulingItem = null;
let schedulingPlaylist = null;
let playlists = [];
let editingLibraryImage = null;
let displayControlDirty = false;
let currentDeviceMode = "standalone";
const selectedMediaIds = new Set();

function updateAdminClock() {
  const clock = document.querySelector("#admin-clock");
  const now = new Date();
  clock.dateTime = now.toISOString();
  clock.textContent = now.toLocaleTimeString("de-DE", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  clock.title = now.toLocaleDateString("de-DE", {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
  });
}

updateAdminClock();
window.setInterval(updateAdminClock, 1000);

function notify(text, isError = false, duration = 3000) {
  message.textContent = text;
  message.className = isError ? "show error" : "show";
  window.setTimeout(() => { message.className = ""; }, duration);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && path !== "/api/system/login") showLogin();
    throw new Error(body.detail || `Fehler ${response.status}`);
  }
  return response.status === 204 ? null : response.json();
}

function uploadWithProgress(path, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", path);
    request.upload.addEventListener("progress", event => {
      if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100));
    });
    request.addEventListener("load", () => {
      const body = (() => { try { return JSON.parse(request.responseText); } catch (_) { return {}; } })();
      if (request.status >= 200 && request.status < 300) resolve(body);
      else reject(new Error(body.detail || `Fehler ${request.status}`));
    });
    request.addEventListener("error", () => reject(new Error("Upload-Verbindung fehlgeschlagen")));
    request.send(formData);
  });
}

function uploadProgress(form) {
  let progress = form.querySelector("progress");
  if (!progress) { progress = document.createElement("progress"); progress.max = 100; form.append(progress); }
  progress.hidden = false; progress.value = 0;
  return { update: value => { progress.value = value; }, finish: () => { progress.hidden = true; } };
}

function localDateTimeValue(value) {
  if (!value) return "";
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index > 2 ? 1 : 0)} ${units[index]}`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "–";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return [days ? `${days} T` : "", hours ? `${hours} Std` : "", `${minutes} Min`]
    .filter(Boolean).join(" ");
}
