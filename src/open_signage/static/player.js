const stage = document.querySelector("#stage");
let items = [];
let currentIndex = -1;
let timer;
let playlistSignature = "";
let activeHls;
let reconnectTimer;
const imagePreloads = new Map();
let currentItem = null;
let playerState = "idle";
let playerError = null;
const CACHE_KEY = "open-signage-playlist-v1";
const CURRENT_KEY = "open-signage-current-content";

function sendHeartbeat(state = playerState, error = playerError) {
  playerState = state;
  playerError = error;
  fetch("/api/player/heartbeat", {
    method: "POST", headers: { "Content-Type": "application/json" }, keepalive: true,
    body: JSON.stringify({
      state, content_id: currentItem?.id || null, content_name: currentItem?.name || null, error,
    }),
  }).catch(() => {});
}

function signature(value) {
  return JSON.stringify(value.map(({ id, name, kind, source, duration_seconds, position, muted, play_to_end, text_config }) =>
    [id, name, kind, source, duration_seconds, position, muted, play_to_end, text_config]));
}

function clearStage() {
  window.clearTimeout(timer);
  window.clearTimeout(reconnectTimer);
  if (activeHls) {
    activeHls.destroy();
    activeHls = null;
  }
  stage.replaceChildren();
}

function preloadImage(source, highPriority = false) {
  if (!source) return Promise.resolve();
  if (imagePreloads.has(source)) return imagePreloads.get(source);
  const promise = new Promise((resolve) => {
    const image = new Image();
    image.decoding = "async";
    image.fetchPriority = highPriority ? "high" : "low";
    image.onload = () => image.decode?.().catch(() => {}).finally(resolve);
    image.onerror = resolve;
    image.src = source;
  });
  imagePreloads.set(source, promise);
  return promise;
}

function imageSource(item) {
  return ["image", "text"].includes(item?.kind) ? item.source : null;
}

function preloadPlaylist(playlist, firstIndex = 0) {
  const activeSources = new Set(playlist.map(imageSource).filter(Boolean));
  for (const source of imagePreloads.keys()) {
    if (!activeSources.has(source)) imagePreloads.delete(source);
  }
  const firstPromise = preloadImage(imageSource(playlist[firstIndex]), true);
  playlist.forEach((item, index) => {
    if (index !== firstIndex) preloadImage(imageSource(item));
  });
  return firstPromise;
}

function showPlaceholder() {
  clearStage();
  const placeholder = document.createElement("div");
  placeholder.className = "placeholder";
  placeholder.innerHTML = "<strong>Open Signage</strong><span>Warte auf Inhalte …</span>";
  stage.append(placeholder);
  currentItem = null;
  sendHeartbeat("idle", null);
}

function advance() {
  if (!items.length) return showPlaceholder();
  currentIndex = (currentIndex + 1) % items.length;
  show(items[currentIndex]);
}

function show(item) {
  clearStage();
  currentItem = item;
  try { localStorage.setItem(CURRENT_KEY, String(item.id)); } catch (_) {}
  sendHeartbeat("playing", null);
  let element;
  if (item.kind === "image") {
    element = document.createElement("img");
    element.src = item.source;
    element.alt = item.name;
    element.fetchPriority = "high";
    element.decoding = "async";
    element.addEventListener("error", () => {
      sendHeartbeat("error", "Bild konnte nicht geladen werden.");
      advance();
    }, { once: true });
  } else if (item.kind === "video") {
    element = document.createElement("video");
    element.src = item.source;
    element.autoplay = true;
    element.muted = item.muted;
    element.playsInline = true;
    element.addEventListener("ended", advance, { once: true });
    element.addEventListener("error", () => {
      sendHeartbeat("error", "Video konnte nicht abgespielt werden.");
      advance();
    }, { once: true });
  } else if (item.kind === "website") {
    element = document.createElement("iframe");
    element.src = item.source;
    element.title = item.name;
    element.allow = "autoplay; fullscreen";
  } else if (item.kind === "pdf") {
    element = document.createElement("iframe");
    element.src = `${item.source}#toolbar=0&navpanes=0&scrollbar=0&view=FitH`;
    element.title = item.name;
  } else if (item.kind === "text") {
    element = document.createElement("div");
    element.style.backgroundImage = `url("${item.source.replaceAll('"', '%22')}")`;
    const config = item.text_config || {};
    const align = config.text_align || "left";
    const vertical = config.vertical_position || "center";
    const font = config.font_family || "sans";
    const size = config.font_size || "medium";
    const template = config.template_style || "standard";
    element.style.backgroundPosition = `${config.focus_x ?? 50}% ${config.focus_y ?? 50}%`;
    element.style.setProperty("--background-dim", `${config.background_dim || 0}%`);
    element.style.setProperty("--slide-text", config.text_color || "#ffffff");
    element.style.setProperty("--slide-accent", config.accent_color || "#39d98a");
    const overlay = document.createElement("div");
    const intensity = ["light", "medium", "dark"].includes(config.shadow_intensity)
      ? config.shadow_intensity : "medium";
    overlay.className = `text-overlay${config.shadow_box ? ` shadow-box shadow-box-${intensity}` : ""}`;
    [["h2", "text-headline", config.headline], ["h3", "text-subheadline", config.subheadline], ["p", "text-body", config.body]]
      .forEach(([tag, className, value]) => {
        if (!value) return;
        const text = document.createElement(tag);
        text.className = className;
        text.textContent = value;
        overlay.append(text);
      });
    element.append(overlay);
    if (config.logo_source) {
      const logo = document.createElement("img");
      logo.className = "text-logo";
      logo.src = config.logo_source;
      logo.alt = "Logo";
      element.append(logo);
    }
    element.dataset.slideClasses = `align-${align} position-${vertical} font-${font} size-${size} template-${template}`;
  } else if (item.kind === "stream") {
    showStream(item);
    return;
  }
  element.className = item.kind === "text" ? `content text-slide ${element.dataset.slideClasses}` : "content";
  stage.append(element);
  if (!(item.kind === "video" && item.play_to_end)) {
    timer = window.setTimeout(advance, item.duration_seconds * 1000);
  }
}

function showStream(item) {
  const video = document.createElement("video");
  video.className = "content";
  video.autoplay = true;
  video.muted = item.muted;
  video.playsInline = true;
  video.controls = false;

  const status = document.createElement("div");
  status.className = "stream-status";
  status.innerHTML = "<strong>Live-Übertragung</strong><span>Verbindung wird hergestellt …</span>";
  stage.append(video, status);

  const setStatus = (text, visible = true) => {
    status.querySelector("span").textContent = text;
    status.classList.toggle("hidden", !visible);
  };
  const tryPlay = () => {
    video.play()
      .then(() => setStatus("", false))
      .catch(() => setStatus(item.muted
        ? "Stream konnte nicht automatisch gestartet werden."
        : "Autoplay mit Ton wurde vom Browser blockiert."));
  };
  const reconnect = () => {
    setStatus("Stream ist offline – neuer Versuch …");
    window.clearTimeout(reconnectTimer);
    reconnectTimer = window.setTimeout(() => {
      if (activeHls) {
        activeHls.stopLoad();
        activeHls.startLoad(-1);
      } else {
        video.load();
      }
    }, 5000);
  };

  video.addEventListener("playing", () => { setStatus("", false); sendHeartbeat("playing", null); });
  video.addEventListener("waiting", () => { setStatus("Livestream wird gepuffert …"); sendHeartbeat("buffering", null); });
  video.addEventListener("error", () => { sendHeartbeat("error", "Livestream-Verbindung unterbrochen."); reconnect(); });

  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = item.source;
    video.addEventListener("loadedmetadata", tryPlay, { once: true });
  } else if (window.Hls?.isSupported()) {
    activeHls = new Hls({
      enableWorker: true,
      lowLatencyMode: true,
      backBufferLength: 30,
    });
    activeHls.loadSource(item.source);
    activeHls.attachMedia(video);
    activeHls.on(Hls.Events.MANIFEST_PARSED, tryPlay);
    activeHls.on(Hls.Events.ERROR, (_, data) => {
      if (!data.fatal) return;
      if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
        setStatus("Wiedergabefehler – Wiederherstellung läuft …");
        activeHls.recoverMediaError();
      } else {
        reconnect();
      }
    });
  } else {
    setStatus("Dieser Browser unterstützt keine HLS-Wiedergabe.");
  }

  timer = window.setTimeout(advance, item.duration_seconds * 1000);
}

async function refreshPlaylist() {
  try {
    const response = await fetch("/api/player/content", { cache: "no-store" });
    if (!response.ok) return;
    const nextItems = await response.json();
    const nextSignature = signature(nextItems);
    if (nextSignature !== playlistSignature) {
      const currentId = items[currentIndex]?.id;
      items = nextItems;
      try { localStorage.setItem(CACHE_KEY, JSON.stringify(nextItems)); } catch (_) {}
      playlistSignature = nextSignature;
      const preservedIndex = items.findIndex(item => item.id === currentId);
      currentIndex = preservedIndex >= 0 ? preservedIndex - 1 : -1;
      const nextIndex = preservedIndex >= 0 ? preservedIndex : 0;
      await preloadPlaylist(items, nextIndex);
      advance();
    }
  } catch (_) {
    // Keep the current content visible during temporary server/network errors.
  }
}

try {
  const cached = JSON.parse(localStorage.getItem(CACHE_KEY) || "[]");
  if (Array.isArray(cached) && cached.length) {
    items = cached;
    playlistSignature = signature(cached);
    const rememberedId = Number(localStorage.getItem(CURRENT_KEY));
    currentIndex = Math.max(-1, cached.findIndex(item => item.id === rememberedId) - 1);
    preloadPlaylist(items, Math.max(0, currentIndex + 1)).then(advance);
  }
} catch (_) {}
refreshPlaylist();
window.setInterval(refreshPlaylist, 5000);
window.setInterval(() => sendHeartbeat(), 10000);
