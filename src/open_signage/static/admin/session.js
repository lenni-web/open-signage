// Anmeldung, Navigation, Gerätemodus und Start der Verwaltung. Wird zuletzt geladen.

function showLogin() {
  document.querySelector("#login-screen").hidden = false;
  document.querySelector("#admin-app").hidden = true;
}

function showApplication(settings) {
  document.querySelector("#login-screen").hidden = true;
  document.querySelector("#admin-app").hidden = false;
  document.querySelector('#screen-settings-form [name="screen_name"]').value = settings.screen_name;
  document.querySelector("#content-heading").textContent = `Inhalte – ${settings.screen_name}`;
  document.body.dataset.profile = settings.headless ? "server" : "kiosk";
  document.querySelector("#monitoring-title").textContent = settings.headless ? "Server-Monitoring" : "Player-Monitoring";
  applyDeviceMode(settings.device_mode || "standalone");
  if (settings.password_change_required) {
    notify("Bitte ändere jetzt das Initialpasswort unter Einstellungen.", true, 10000);
    document.querySelector('[data-page="settings-page"]')?.click();
  }
}

function applyDeviceMode(mode) {
  const wasDisplay = currentDeviceMode === "display";
  currentDeviceMode = mode;
  document.body.dataset.mode = mode;
  const displayMode = mode === "display";
  document.querySelectorAll('.nav-button[data-page="content-page"], .nav-button[data-page="library-page"]').forEach(item => { item.hidden = displayMode; });
  ["#screen-settings-form", "#storage-cleanup", "#storage-orphan-cleanup", "#backup-create", "#backup-restore-form", "#display-control-form"]
    .forEach(selector => { const item = document.querySelector(selector); if (item) item.hidden = displayMode; });
  if (displayMode && !wasDisplay) {
    document.querySelectorAll(".nav-button").forEach(item => item.classList.remove("active"));
    document.querySelectorAll(".page").forEach(page => { page.hidden = true; });
    const systemButton = document.querySelector('.nav-button[data-page="system-page"]');
    systemButton.classList.add("active"); systemButton.hidden = false;
    document.querySelector("#system-page").hidden = false;
    openSystemPage();
  } else if (wasDisplay) {
    document.querySelectorAll(".nav-button").forEach(item => item.classList.remove("active"));
    document.querySelectorAll(".page").forEach(page => { page.hidden = true; });
    const contentButton = document.querySelector('.nav-button[data-page="content-page"]');
    contentButton.classList.add("active"); document.querySelector("#content-page").hidden = false;
  }
}

async function loadSettings() {
  try {
    const settings = await api("/api/settings");
    document.querySelector("#content-heading").textContent = `Inhalte – ${settings.screen_name}`;
  } catch (error) { notify(error.message, true); }
}

async function openSystemPage() {
  await Promise.all([loadSystemInfo(), loadMonitoring(), loadUpdateStatus(), loadApplicationUpdateStatus(), loadStorage(), loadSecurityStatus(), loadDisplayOverview()]);
}

function organizeAdministrationPages() {
  const settingsContent = document.querySelector("#settings-content");
  if (!settingsContent || settingsContent.childElementCount) return;
  [
    "#password-form",
    "#backup-create",
    "#device-form",
    "#display-control-form",
    "[data-system-action='restart_service']",
  ].forEach((selector) => {
    const card = document.querySelector(selector)?.closest("section.card, details.card");
    if (card) settingsContent.append(card);
  });
}

async function openSettingsPage() {
  await Promise.all([loadBackups(), loadDevice(), loadDisplayControl(), loadPlayerAccess()]);
}

organizeAdministrationPages();

async function boot() {
  try {
    const session = await api("/api/system/session");
    if (!session.authenticated) {
      showLogin();
      return;
    }
    showApplication(session);
    const loaders = [loadVersion()];
    if (session.device_mode !== "display") loaders.push(load(), loadLibrary(), loadPlaylists(), loadLive());
    await Promise.all(loaders);
  } catch (_) {
    showLogin();
  }
}

document.querySelectorAll(".nav-button").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll(".nav-button").forEach(item => item.classList.remove("active"));
    document.querySelectorAll(".page").forEach(page => { page.hidden = true; });
    button.classList.add("active");
    document.querySelector(`#${button.dataset.page}`).hidden = false;
    if (button.dataset.page === "system-page") {
      await openSystemPage();
    } else if (button.dataset.page === "settings-page") {
      await openSettingsPage();
    } else if (button.dataset.page === "library-page") {
      await loadLibrary();
    } else if (button.dataset.page === "content-page") {
      await Promise.all([load(), loadLive()]);
    }
  });
});

document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = new FormData(event.target).get("password");
  try {
    const session = await api("/api/system/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    event.target.reset();
    showApplication(session);
    await Promise.all([loadVersion(), load(), loadLibrary(), loadPlaylists(), loadLive()]);
    notify("Anmeldung erfolgreich");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#logout").addEventListener("click", async () => {
  await api("/api/system/logout", { method: "POST" });
  showLogin();
});

boot();
