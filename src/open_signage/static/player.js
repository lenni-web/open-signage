const stage = document.querySelector("#stage");
let items = [];
let currentIndex = -1;
let timer;
let playlistSignature = "";
let activeHls;
let reconnectTimer;

function signature(value) {
  return JSON.stringify(value.map(({ id, source, duration_seconds, position, muted }) =>
    [id, source, duration_seconds, position, muted]));
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

function showPlaceholder() {
  clearStage();
  const placeholder = document.createElement("div");
  placeholder.className = "placeholder";
  placeholder.innerHTML = "<strong>Open Signage</strong><span>Warte auf Inhalte …</span>";
  stage.append(placeholder);
}

function advance() {
  if (!items.length) return showPlaceholder();
  currentIndex = (currentIndex + 1) % items.length;
  show(items[currentIndex]);
}

function show(item) {
  clearStage();
  let element;
  if (item.kind === "image") {
    element = document.createElement("img");
    element.src = item.source;
    element.alt = item.name;
  } else if (item.kind === "video") {
    element = document.createElement("video");
    element.src = item.source;
    element.autoplay = true;
    element.muted = true;
    element.playsInline = true;
    element.addEventListener("ended", advance, { once: true });
  } else if (item.kind === "website") {
    element = document.createElement("iframe");
    element.src = item.source;
    element.title = item.name;
    element.allow = "autoplay; fullscreen";
  } else if (item.kind === "stream") {
    showStream(item);
    return;
  }
  element.className = "content";
  stage.append(element);
  timer = window.setTimeout(advance, item.duration_seconds * 1000);
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

  video.addEventListener("playing", () => setStatus("", false));
  video.addEventListener("waiting", () => setStatus("Livestream wird gepuffert …"));
  video.addEventListener("error", reconnect);

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
    const response = await fetch("/api/content?enabled_only=true", { cache: "no-store" });
    if (!response.ok) return;
    const nextItems = await response.json();
    const nextSignature = signature(nextItems);
    if (nextSignature !== playlistSignature) {
      const currentId = items[currentIndex]?.id;
      items = nextItems;
      playlistSignature = nextSignature;
      const preservedIndex = items.findIndex(item => item.id === currentId);
      currentIndex = preservedIndex >= 0 ? preservedIndex - 1 : -1;
      advance();
    }
  } catch (_) {
    // Keep the current content visible during temporary server/network errors.
  }
}

refreshPlaylist();
window.setInterval(refreshPlaylist, 5000);
